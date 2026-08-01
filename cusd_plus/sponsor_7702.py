"""
EIP-7702 sponsored batch execution — the successor to BNB gas dusting.

The client never holds BNB: it signs (a) a one-time 7702 authorization
designating ConfioBatchDelegate at its own EOA and (b) a per-action EIP-712
intent over the exact call batch. This module validates both against a
strict policy, simulates, then builds/signs/broadcasts the type-4
transaction FROM THE SPONSOR, which pays all gas
(contracts/cusd_plus/ConfioBatchDelegate.sol is the on-chain half).

Policy posture (sponsor-outflow rules): the sponsor only ever executes
call batches this module has verified are (1) signed by the JWT account's
registered BSC key, (2) composed solely of allowlisted vault-flow calls,
and (3) survive an eth_call simulation. Rate limits, daily caps and a
balance preflight bound the sponsor's spend.
"""
import json
import logging
import time
from typing import Optional

from django.conf import settings
from django.core.cache import cache

from eth_abi import encode as abi_encode
from eth_utils import keccak

logger = logging.getLogger(__name__)

USDT_BSC = '0x55d398326f99059ff775485246999027b3197955'
DELEGATION_PREFIX = '0xef0100'

# Selectors, computed once at import (cusd_plus/vault.py pattern).
def _sel(sig: str) -> str:
    return keccak(text=sig)[:4].hex()


SEL_APPROVE = _sel('approve(address,uint256)')                       # 095ea7b3
SEL_TRANSFER = _sel('transfer(address,uint256)')                     # a9059cbb
SEL_SUBSCRIBE_AND_MINT = _sel('subscribeAndMint(uint256,uint256,address)')
SEL_REDEEM_TO_USDT = _sel('redeemToUsdt(uint256,uint256,address)')   # f4794519
SEL_PRESALE_BUY = _sel('buy(uint256,uint256)')                       # ConfioPresaleVault
SEL_PAY = _sel('pay(bytes32,address,uint256,address,uint256,bytes)')  # ConfioPayContract
SEL_EXECUTE = _sel('execute((address,uint256,bytes)[],uint256,uint256,bytes32,bytes)')

# EIP-712 constants — canonical strings shared with ConfioBatchDelegate.sol
# and apps/src/services/evmWallet.ts. The three-way parity anchor lives in
# test_sharedEip712Vector (forge) / test_shared_eip712_vector (here) /
# validate-evm-signer.mts. Never change one alone.
DOMAIN_TYPEHASH = keccak(
    text='EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)')
CALL_TYPEHASH = keccak(text='Call(address to,uint256 value,bytes data)')
EXECUTE_TYPEHASH = keccak(
    text='Execute(Call[] calls,uint256 nonce,uint256 deadline,bytes32 intentId)Call(address to,uint256 value,bytes data)')
NAME_HASH = keccak(text='ConfioBatchDelegate')
VERSION_HASH = keccak(text='1')

# Gas budgets calibrated on a BSC mainnet fork (ConfioBatchDelegate.fork.t.sol:
# approve+subscribeAndMint batch 664k, redeemToUsdt batch 390k). Fixed and
# deterministic on purpose: eth_estimateGas can't see a not-yet-applied
# delegation, and a griefed estimate could oversize the sponsor's spend.
#
# The fork numbers are a FLOOR, not the truth: they were measured at one
# block, and the vault's redeem cost depends on third-party state we don't
# control (Ondo's InstantManager). A fork test pinned at a cheap block keeps
# passing while production reverts — which is what happened on 2026-08-01.
# So budget for the expensive path here, and rely on simulate() running under
# this same limit to catch the next divergence before it costs sponsor gas.
GAS_BASE = 21_000
GAS_PER_AUTHORIZATION = 25_000  # PER_EMPTY_ACCOUNT_COST
GAS_EXECUTE_OVERHEAD = 30_000
GAS_PER_SELECTOR = {
    SEL_APPROVE: 50_000,
    SEL_TRANSFER: 80_000,  # plain ERC-20 transfer (~35-52k) + headroom
    SEL_SUBSCRIBE_AND_MINT: 620_000,
    # 750k, raised from 400k after prod reverts on 2026-08-01: redeemToUsdt
    # alone estimated 590k, so the 541,200 total budget starved the inner
    # call and it reverted with the outer frame's EIP-150 1/64 left over
    # (518k of 541k burned, zero logs). The cost is not ours to control —
    # _imRedeem's price depends on Ondo's InstantManager taking the cheap
    # path (pay from its USDT balance) or the expensive one (source it),
    # and its balance is routinely 0. Budget for the expensive path.
    SEL_REDEEM_TO_USDT: 750_000,
    SEL_PRESALE_BUY: 200_000,  # curve integral + 2 ledger writes + transferFrom
    SEL_PAY: 240_000,  # 2 transferFroms + invoice write + accrual + ecrecover/EIP712 auth
    _sel('createInvitation(bytes32,address,uint256)'): 140_000,  # transferFrom + struct write
    _sel('reclaimInvitation(bytes32)'): 90_000,                  # transfer + settle
}


class PolicyError(Exception):
    """Rejection with a stable client-facing error code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


# ── config / chain helpers ──────────────────────────────────────────────

def delegate_address() -> str:
    return (getattr(settings, 'CUSD_PLUS_BATCH_DELEGATE_ADDRESS', '') or '').lower()


def _vault_address() -> str:
    return (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()


def _rpc(method, params):
    from .tasks import _rpc as tasks_rpc
    return tasks_rpc(method, params)


def is_delegated(addr: str) -> bool:
    """True when addr's code is the 7702 designation of OUR delegate."""
    code = (_rpc('eth_getCode', [addr, 'latest']) or '0x').lower()
    return code == DELEGATION_PREFIX + delegate_address()[2:]


def _delegate_runtime_code() -> Optional[str]:
    """The delegate's runtime bytecode (for eth_call state overrides),
    fetched from the chain once and cached — no artifact files in prod."""
    cached = cache.get('cusd_plus_7702_runtime_code')
    if cached:
        return cached
    try:
        code = _rpc('eth_getCode', [delegate_address(), 'latest'])
    except Exception:  # noqa: BLE001
        return None
    if not code or code == '0x':
        return None
    cache.set('cusd_plus_7702_runtime_code', code, 24 * 3600)
    return code


# ── EIP-712 intent digest / signature recovery ──────────────────────────

def _addr_bytes(addr: str) -> bytes:
    return bytes.fromhex(addr.lower().replace('0x', '').rjust(40, '0'))


def intent_id_for(kind: str, source_id=None) -> bytes:
    """The bytes32 intentId the user's signature binds to (2026-07-31
    migration audit): the flow PURPOSE and, for domain flows, the exact
    domain row. keccak('<kind>:<source_id>'); the generic savings rail omits
    the id (kind alone). Server-derived so an intent for one flow/row cannot
    be presented as another. The client is handed the hex in prepare (domain
    flows) or derives it identically (generic rail)."""
    tag = f'{kind}:{source_id}' if source_id is not None else f'{kind}:'
    return keccak(text=tag)


def intent_id_hex(kind: str, source_id=None) -> str:
    return '0x' + intent_id_for(kind, source_id).hex()


def intent_digest(calls: list, nonce: int, deadline: int, user_addr: str,
                  chain_id: int, intent_id: bytes) -> bytes:
    """EIP-712 digest of Execute(calls, nonce, deadline, intentId) with
    verifyingContract = the user's own EOA (see ConfioBatchDelegate.sol)."""
    call_hashes = b''
    for c in calls:
        call_hashes += keccak(abi_encode(
            ['bytes32', 'address', 'uint256', 'bytes32'],
            [CALL_TYPEHASH, c['to'], int(c['value']), keccak(bytes.fromhex(c['data'][2:]))],
        ))
    domain_separator = keccak(abi_encode(
        ['bytes32', 'bytes32', 'bytes32', 'uint256', 'address'],
        [DOMAIN_TYPEHASH, NAME_HASH, VERSION_HASH, chain_id, user_addr],
    ))
    struct_hash = keccak(abi_encode(
        ['bytes32', 'bytes32', 'uint256', 'uint256', 'bytes32'],
        [EXECUTE_TYPEHASH, keccak(call_hashes), int(nonce), int(deadline), intent_id],
    ))
    return keccak(b'\x19\x01' + domain_separator + struct_hash)


def _recover(digest: bytes, y_parity: int, r: int, s: int) -> Optional[str]:
    try:
        from eth_keys.datatypes import Signature
        pub = Signature(vrs=(y_parity, r, s)).recover_public_key_from_msg_hash(digest)
        return pub.to_address().lower()
    except Exception:  # noqa: BLE001
        return None


def recover_intent_signer(digest: bytes, signature_hex: str) -> Optional[str]:
    """Recover the signer of a 65-byte r‖s‖v signature (v in {0,1,27,28})."""
    try:
        sig = bytes.fromhex(signature_hex.replace('0x', ''))
        if len(sig) != 65:
            return None
        r = int.from_bytes(sig[0:32], 'big')
        s = int.from_bytes(sig[32:64], 'big')
        v = sig[64]
        if v >= 27:
            v -= 27
        if v not in (0, 1):
            return None
        return _recover(digest, v, r, s)
    except Exception:  # noqa: BLE001
        return None


def recover_authorization_authority(auth: dict) -> Optional[str]:
    """Authority (signer) of a 7702 authorization tuple:
    keccak(0x05 ‖ rlp([chainId, address, nonce]))."""
    try:
        import rlp
        payload = rlp.encode([
            int(auth['chain_id']),
            _addr_bytes(auth['address']),
            int(auth['nonce']),
        ])
        digest = keccak(b'\x05' + payload)
        return _recover(digest, int(auth['y_parity']), int(auth['r'], 16), int(auth['s'], 16))
    except Exception:  # noqa: BLE001
        return None


def normalize_and_validate_authorization(authorization, user_addr: str, chain_id: int) -> dict:
    """Normalize a client 7702 authorization tuple (graphene input or dict)
    and validate it end-to-end: delegate address, chain binding, signature
    authority, and LIVE account nonce. Raises PolicyError with the same
    stable codes SponsorBscBatch returns inline (this helper mirrors that
    proven block for other sponsored rails, e.g. the presale buy).
    Returns the normalized dict send_sponsored_batch expects."""
    def _get(obj, snake, camel=None):
        if isinstance(obj, dict):
            return obj.get(snake)
        return getattr(obj, snake, None) if hasattr(obj, snake) else getattr(obj, camel or snake, None)

    def _hex(x):
        x = (x or '').lower()
        return x if x.startswith('0x') else '0x' + x

    auth_dict = {
        'chain_id': int(_get(authorization, 'chain_id', 'chainId')),
        'address': (_get(authorization, 'address') or '').lower(),
        'nonce': str(int(_get(authorization, 'nonce'))),
        'y_parity': int(_get(authorization, 'y_parity', 'yParity')),
        'r': _hex(_get(authorization, 'r')),
        's': _hex(_get(authorization, 's')),
    }
    # chainId 0 would be a wildcard valid on EVERY chain — refuse it even
    # though the tuple is user-signed.
    if auth_dict['chain_id'] != chain_id:
        raise PolicyError('bad_auth_chain')
    if auth_dict['address'] != delegate_address():
        raise PolicyError('bad_auth_delegate')
    authority = recover_authorization_authority(auth_dict)
    if authority != user_addr.lower():
        raise PolicyError('bad_auth_signature')
    live_nonce = int(_rpc('eth_getTransactionCount', [user_addr, 'pending']), 16)
    if int(auth_dict['nonce']) != live_nonce:
        # Signed against a stale account nonce — applying it would silently
        # no-op. Client refetches and re-signs.
        raise PolicyError('stale_auth_nonce')
    return auth_dict


# ── policy ──────────────────────────────────────────────────────────────

def redeem_recipient_allowed(user, recipient: str, signer: str) -> bool:
    """The redeemToUsdt recipient rule, shared verbatim between the legacy
    raw-tx relay guard and the 7702 batch policy: the signer's own address
    (self-redeem), or the user's LIVE Guardarian sell deposit address —
    re-fetched server-side, never trusted from the client."""
    recipient = recipient.lower()
    if recipient == signer.lower():
        return True
    deposit_address = _guardarian_savings_deposit_address(user)
    return bool(deposit_address) and deposit_address.lower() == recipient


def _guardarian_savings_deposit_address(user):
    """Deposit address of the user's newest Guardarian USDT sell still
    awaiting funds — fetched live from Guardarian's API, never from the
    client. (Moved from schema.py so both rails share one implementation.)"""
    try:
        from datetime import timedelta

        import requests
        from django.utils import timezone

        from usdc_transactions.models import GuardarianTransaction

        tx = GuardarianTransaction.objects.filter(
            user=user,
            from_currency__in=['USDT'],
            status__in=['new', 'waiting', 'waiting_for_deposit', 'waiting_for_customer'],
            created_at__gte=timezone.now() - timedelta(hours=24),
        ).order_by('-created_at').first()
        if not tx:
            return None
        api_key = getattr(settings, 'GUARDARIAN_API_KEY', None)
        base_url = getattr(settings, 'GUARDARIAN_API_URL', 'https://api-payments.guardarian.com/v1')
        if not api_key:
            return None
        resp = requests.get(
            f'{base_url.rstrip("/")}/transaction/{tx.guardarian_id}',
            headers={'x-api-key': api_key},
            timeout=10,
        )
        if not resp.ok:
            return None
        data = resp.json()
        return data.get('deposit_address') or (data.get('deposit') or {}).get('address')
    except Exception:
        logger.exception('guardarian savings deposit lookup failed')
        return None


def _word(data_hex: str, i: int) -> str:
    """i-th 32-byte static word of calldata (0x + selector stripped)."""
    start = 8 + 64 * i
    return data_hex[start:start + 64]


def validate_policy(calls: list, user, user_addr: str) -> None:
    """Raise PolicyError unless every call is an allowlisted vault-flow
    action for THIS user. calls: [{'to','value','data'}] normalized lower.

    Strictly tighter than the legacy relay: subscribeAndMint's recipient is
    pinned to the user (the raw-tx guard never checked it)."""
    vault = _vault_address()
    if not vault:
        raise PolicyError('vault_not_configured')
    user_word = user_addr.lower().replace('0x', '').rjust(64, '0')

    for c in calls:
        if int(c['value']) != 0:
            raise PolicyError('value_not_allowed')
        data = c['data']
        if not data.startswith('0x') or len(data) > 4_096 or (len(data) - 2) % 2 != 0:
            raise PolicyError('bad_calldata')
        data_hex = data[2:].lower()
        selector = data_hex[:8]

        if c['to'] == USDT_BSC:
            if selector == SEL_APPROVE:
                # approve: ONLY with the vault as spender.
                if len(data_hex) != 8 + 128:
                    raise PolicyError('bad_calldata')
                if _word(data_hex, 0)[-40:] != vault[2:]:
                    raise PolicyError('approve_spender_not_allowed')
            elif selector == SEL_TRANSFER:
                # transfer: the sponsored USDT send (2026-07-30) — the EXIT
                # for raw wallet USDT, so the recipient is deliberately
                # unrestricted (exits are never gated) and no eligibility
                # applies. Cost is bounded by the rail's own rate limits and
                # daily cap; unlike gas dust, sponsored gas can't be
                # extracted — it's consumed by the transfer itself.
                if len(data_hex) != 8 + 128:
                    raise PolicyError('bad_calldata')
            else:
                raise PolicyError('selector_not_allowed')
        elif c['to'] == vault:
            if selector == SEL_SUBSCRIBE_AND_MINT:
                if len(data_hex) != 8 + 192:
                    raise PolicyError('bad_calldata')
                if _word(data_hex, 2) != user_word:
                    raise PolicyError('mint_recipient_not_allowed')
            elif selector == SEL_REDEEM_TO_USDT:
                if len(data_hex) != 8 + 192:
                    raise PolicyError('bad_calldata')
                recipient = '0x' + _word(data_hex, 2)[-40:]
                if not redeem_recipient_allowed(user, recipient, user_addr):
                    logger.warning(
                        '7702 redeem recipient %s rejected for user %s (signer %s)',
                        recipient, user.id, user_addr,
                    )
                    raise PolicyError('redeem_recipient_not_allowed')
            else:
                raise PolicyError('selector_not_allowed')
        else:
            raise PolicyError('destination_not_allowed')


# ── transaction assembly ────────────────────────────────────────────────

def execute_calldata(calls: list, nonce: int, deadline: int, signature_hex: str,
                     intent_id: bytes) -> str:
    """ABI-encode ConfioBatchDelegate.execute(calls, nonce, deadline,
    intentId, sig)."""
    call_tuples = [
        (c['to'], int(c['value']), bytes.fromhex(c['data'][2:])) for c in calls
    ]
    encoded = abi_encode(
        ['(address,uint256,bytes)[]', 'uint256', 'uint256', 'bytes32', 'bytes'],
        [call_tuples, int(nonce), int(deadline), intent_id,
         bytes.fromhex(signature_hex.replace('0x', ''))],
    )
    return '0x' + SEL_EXECUTE + encoded.hex()


def gas_budget(calls: list, num_authorizations: int) -> int:
    total = GAS_BASE + GAS_PER_AUTHORIZATION * num_authorizations + GAS_EXECUTE_OVERHEAD
    for c in calls:
        total += GAS_PER_SELECTOR.get(c['data'][2:10].lower(), 100_000)
    total = (total * 12) // 10
    return min(total, int(getattr(settings, 'CUSD_PLUS_7702_GAS_LIMIT', 1_100_000)))


def simulate(user_addr: str, calldata: str, delegated: bool, sponsor: str,
             gas: int | None = None) -> None:
    """eth_call the execute() before spending sponsor gas. For a first-time
    (undelegated) user, inject the delegate's runtime code via a state
    override; if the node rejects overrides, log and proceed on fixed
    budgets — a revert is a hard reject either way.

    `gas` is the limit the real transaction will carry. Without it the node
    simulates at its own default ceiling, which hides an under-budgeted
    inner call until it burns sponsor gas on-chain."""
    call_obj = {'from': sponsor, 'to': user_addr, 'data': calldata}
    if gas is not None:
        call_obj['gas'] = hex(int(gas))
    try:
        if delegated:
            _rpc('eth_call', [call_obj, 'latest'])
        else:
            code = _delegate_runtime_code()
            if not code:
                logger.warning('7702 simulate skipped: delegate runtime code unavailable')
                return
            _rpc('eth_call', [call_obj, 'latest', {user_addr: {'code': code}}])
    except RuntimeError as exc:
        msg = str(exc).lower()
        # Node lacks state-override support → can't simulate first-timers.
        if not delegated and ('override' in msg or 'too many arguments' in msg or 'invalid argument' in msg):
            logger.warning('7702 simulate skipped (no state-override support): %s', exc)
            return
        logger.warning('7702 simulation reverted for %s: %s', user_addr, exc)
        raise PolicyError('simulation_reverted')


def acquire_sponsor_nonce_lock(attempts: int = 30, ttl_s: int = 15):
    """Serialize sponsor-account nonce-fetch → broadcast across EVERY rail
    that signs from the KMS sponsor (7702 batches, presale, payroll payouts).

    Returns an OWNERSHIP TOKEN string when acquired, else None (audit
    2026-07-31 P2): the token must be passed to release_sponsor_nonce_lock
    so a slow holder whose TTL expired cannot delete a DIFFERENT holder's
    lock and let two requests allocate the same sponsor nonce. Caller MUST
    release in a finally block."""
    import uuid
    token = uuid.uuid4().hex
    for _ in range(attempts):
        if cache.add('bsc_sponsor_nonce_lock', token, ttl_s):
            return token
        time.sleep(0.5)
    return None


def release_sponsor_nonce_lock(token=None) -> None:
    """Release ONLY if we still own the lock (token matches). A None token
    is the legacy unconditional release — avoid it on new call sites."""
    if token is None:
        cache.delete('bsc_sponsor_nonce_lock')
        return
    # Compare-and-delete: never clobber a lock a later holder acquired after
    # our TTL lapsed.
    if cache.get('bsc_sponsor_nonce_lock') == token:
        cache.delete('bsc_sponsor_nonce_lock')


def send_sponsored_batch(user, user_addr: str, calls: list, nonce: int, deadline: int,
                         intent_sig: str, authorization: Optional[dict], kind: str,
                         source_id: Optional[int] = None):
    """Build, sign (KMS) and broadcast the sponsored transaction: type-4
    when an authorization rides along (first use — EIP-7702 requires a
    NON-EMPTY authorization list in a type-4), plain type-2 to the already-
    delegated EOA afterwards. Returns (tx_hash, batch_row). Caller has
    already validated everything.

    Durability (audit 2026-07-31 P1-2): the SponsoredBatch row is written
    with the DETERMINISTIC signed tx hash BEFORE eth_sendRawTransaction, so
    a crash mid-broadcast leaves a 'signed' row the reconciler can resolve
    by hash — never a chain tx attached to no DB state, and never a lost row
    that a retry would double-send."""
    from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
    from .models import SponsoredBatch

    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))
    signer = get_bsc_sponsor_signer_from_settings()
    sponsor = signer.address

    # The intentId is derived from (kind, source_id) — the SAME derivation the
    # submit used for its recover check, so the on-chain execute and the
    # server-verified digest bind identical bytes.
    intent_id = intent_id_for(kind, source_id)
    calldata = execute_calldata(calls, nonce, deadline, intent_sig, intent_id)
    # Simulate UNDER THE REAL BUDGET. An eth_call with no gas field runs at
    # the node's (enormous) default, so an under-budgeted call sails through
    # the pre-flight and then reverts on-chain having spent sponsor gas —
    # exactly how the 2026-08-01 redeem reverts reached the chain. Passing
    # the same limit turns that class of bug into a pre-flight rejection.
    gas = gas_budget(calls, 1 if authorization else 0)
    simulate(user_addr, calldata, authorization is None, sponsor, gas)

    gas_price = max(int(_rpc('eth_gasPrice', []), 16),
                    int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 100_000_000)))
    price_cap = int(getattr(settings, 'CUSD_PLUS_7702_MAX_GAS_PRICE_WEI', 5_000_000_000))
    if gas_price > price_cap:
        # Underpricing below the live market would strand the tx; refusing
        # keeps the sponsor's worst-case spend bounded and honest.
        raise PolicyError('gas_price_too_high')
    fee_per_gas = min((gas_price * 12) // 10, price_cap)

    auth_list = []
    if authorization:
        auth_list.append({
            'chainId': int(authorization['chain_id']),
            'address': authorization['address'],
            'nonce': int(authorization['nonce']),
            'yParity': int(authorization['y_parity']),
            'r': authorization['r'],
            's': authorization['s'],
        })

    # Other sponsor-signed flows share this account: serialize nonce-fetch →
    # broadcast so concurrent sends can't collide on a nonce.
    lock = acquire_sponsor_nonce_lock()
    if not lock:
        raise PolicyError('sponsor_busy')

    from eth_utils import to_checksum_address
    try:
        sponsor_nonce = int(_rpc('eth_getTransactionCount', [sponsor, 'pending']), 16)
        sponsor_balance = int(_rpc('eth_getBalance', [sponsor, 'latest']), 16)
        max_cost = gas * fee_per_gas
        if sponsor_balance < (max_cost * 11) // 10:
            logger.error('sponsor BNB too low for 7702 batch (have %s, need %s) — refill needed',
                         sponsor_balance, max_cost)
            raise PolicyError('sponsor_balance_low')

        tx = {
            'type': 4 if auth_list else 2,
            'chainId': chain_id,
            'nonce': sponsor_nonce,
            'maxPriorityFeePerGas': fee_per_gas,
            'maxFeePerGas': fee_per_gas,
            'gas': gas,
            'to': to_checksum_address(user_addr),
            'value': 0,
            'data': calldata,
            'accessList': [],
        }
        if auth_list:
            tx['authorizationList'] = auth_list
        raw, tx_hash = signer.sign_typed_transaction(tx)

        # DURABLE record BEFORE broadcast. tx_hash is deterministic for the
        # signed bytes, so this is the exact hash that will (or won't) mine.
        batch = SponsoredBatch.objects.create(
            user=user,
            user_bsc_address=user_addr,
            kind=kind,
            source_id=source_id,
            num_calls=len(calls),
            calls_json=json.dumps(calls),
            tx_hash=tx_hash,
            delegate_nonce=int(nonce),
            gas_limit=gas,
            max_fee_wei=str(fee_per_gas),
            status='signed',
        )
        try:
            _rpc('eth_sendRawTransaction', [raw])
        except Exception:  # noqa: BLE001
            # The row survives as 'signed' with the real hash: the reconciler
            # checks the chain and either finds it mined or re-broadcasts.
            # NEVER lose it — a lost row is what enables the double-send.
            logger.exception('7702 broadcast failed (row %s kept as signed): %s', batch.id, tx_hash)
            raise
        batch.status = 'sent'
        batch.save(update_fields=['status', 'updated_at'])
    finally:
        release_sponsor_nonce_lock(lock)

    from .tasks import check_sponsored_batch_receipt
    check_sponsored_batch_receipt.apply_async(args=[batch.id], countdown=6)
    logger.info('7702 sponsored %s batch sent for user %s at %s: %s (gas=%s)',
                kind, user.id, user_addr, tx_hash, gas)
    return tx_hash, batch
