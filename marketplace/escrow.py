"""Comprar ↔ ConfioMarketEscrow (BSC).

Every user action is a sponsored 7702 batch, exactly like the invite escrow
(send/invite_bsc_flow.py): the server builds the calls, the client signs the
ConfioBatchDelegate intent, `submit_action` re-validates and hands the batch to
`sponsor_7702.send_sponsored_batch`. The order row is never trusted for money
state: `sync_order` reads `getOrder(orderId)` from the contract and is the only
writer of funded/shipped/disputed/released/refunded.

  deposit  buyer     [ (cUSD+.unwrapToCusd), cUSD.approve(escrow), escrow.deposit(...) ]
  ship     merchant  [ escrow.markShipped(orderId) ]
  confirm  buyer     [ escrow.confirm(orderId) ]
  dispute  buyer     [ escrow.dispute(orderId) ]
  refund   merchant  [ escrow.refund(orderId) ]
  reclaim  buyer     [ escrow.reclaim(orderId) ]

Keeper-only (the sponsor EOA, no user signature): release past releaseAt,
refundExpiredDispute past the timeout, and resolve (the sponsor is the arbiter
until the Safe rotates it).
"""

import logging
import time
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from eth_abi import decode as abi_decode, encode as abi_encode
from eth_utils import keccak, to_checksum_address

logger = logging.getLogger(__name__)

WAD = 10**18


def _sel(sig: str) -> str:
    return keccak(text=sig)[:4].hex()


SEL_DEPOSIT = _sel('deposit(bytes32,address,address,uint256,uint16,uint256,bytes)')
SEL_MARK_SHIPPED = _sel('markShipped(bytes32)')
SEL_CONFIRM = _sel('confirm(bytes32)')
SEL_DISPUTE = _sel('dispute(bytes32)')
SEL_REFUND = _sel('refund(bytes32)')
SEL_RECLAIM = _sel('reclaim(bytes32)')
SEL_RELEASE = _sel('release(bytes32)')
SEL_RESOLVE = _sel('resolve(bytes32,bool)')
SEL_REFUND_EXPIRED = _sel('refundExpiredDispute(bytes32)')
SEL_GET_ORDER = _sel('getOrder(bytes32)')

ORDER_TUPLE = '(address,uint64,uint16,uint8,address,uint64,uint32,address,uint64,uint256)'
CHAIN_STATES = {0: 'none', 1: 'funded', 2: 'shipped', 3: 'disputed', 4: 'released', 5: 'refunded'}

DEPOSIT_TYPEHASH = keccak(text=(
    'Deposit(bytes32 orderId,address buyer,address merchant,address token,'
    'uint256 amount,uint16 feeBps,uint256 deadline)'))
DOMAIN_TYPEHASH = keccak(
    text='EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)')

# action → (sponsored batch kind, who may sign it)
ACTIONS = {
    'deposit': ('market_deposit', 'buyer'),
    'ship': ('market_ship', 'merchant'),
    'confirm': ('market_confirm', 'buyer'),
    'dispute': ('market_dispute', 'buyer'),
    'refund': ('market_refund', 'merchant'),
    'reclaim': ('market_reclaim', 'buyer'),
}
SINGLE_CALL_SELECTORS = {
    'ship': SEL_MARK_SHIPPED,
    'confirm': SEL_CONFIRM,
    'dispute': SEL_DISPUTE,
    'refund': SEL_REFUND,
    'reclaim': SEL_RECLAIM,
}
# Which mirrored states each user action is offered from. The contract is
# the authority; this only keeps the app from offering a button that reverts.
ALLOWED_FROM = {
    'ship': ('funded',),
    'confirm': ('funded', 'shipped', 'disputed'),
    'dispute': ('funded', 'shipped'),
    'refund': ('funded', 'shipped', 'disputed'),
    'reclaim': ('funded',),
}
# How long an un-mined action blocks the next one before it is treated as lost.
PENDING_ACTION_TTL_S = 15 * 60
# After a deposit authorization's deadline, wait this long for finality before
# concluding from a 'none' chain read that it was never spent.
DEADLINE_GRACE_S = 5 * 60
# Depth of the snapshot that may conclude an authorization expired unspent.
RELEASE_CONFIRMATIONS = 15


class EscrowError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── configuration ───────────────────────────────────────────────────────

def escrow_address() -> str:
    return (getattr(settings, 'MARKETPLACE_ESCROW_ADDRESS', '') or '').lower()


def token_address() -> str:
    """Escrow holds universal cUSD only (deposit asserts exact receipt)."""
    return (getattr(settings, 'CUSD_VAULT_ADDRESS', '') or '').lower()


def chain_id() -> int:
    return int(getattr(settings, 'BSC_CHAIN_ID', 56))


def enabled() -> bool:
    """Comprar is on wherever the escrow is configured; only builds that have
    the tab ever reach it. Whether a token is accepted is the contract's call
    (token_limits)."""
    return bool(escrow_address() and token_address())


SEL_TOKEN_LIMITS = _sel('tokenLimits(address)')
SEL_OPEN_PRINCIPAL = _sel('openPrincipal(address)')
LIMITS_CACHE_S = 60


def token_limits() -> tuple[int, int, int]:
    """(maxOrder, maxOpen, openPrincipal) for cUSD, straight from the escrow —
    the ONE place these limits live (the Safe sets them). maxOrder 0 = the
    token is not accepted. Fails closed: an unreadable limit refuses checkout."""
    from django.core.cache import cache
    from cusd_plus.sponsor_7702 import _rpc

    key = f'comprar:limits:{escrow_address()}'
    cached = cache.get(key)
    if cached is None:
        try:
            token_word = _addr_word(token_address())
            raw = _rpc('eth_call', [{'to': escrow_address(), 'data': '0x' + SEL_TOKEN_LIMITS + token_word}, 'latest'])
            max_order, max_open = abi_decode(['uint128', 'uint128'], bytes.fromhex(raw[2:]))
            cached = (int(max_order), int(max_open))
            cache.set(key, cached, LIMITS_CACHE_S)
        except Exception as exc:  # noqa: BLE001
            logger.warning('[COMPRAR] escrow limits unreadable: %s', exc)
            raise EscrowError('limits_unavailable') from exc
    try:
        raw = _rpc('eth_call', [{'to': escrow_address(),
                                 'data': '0x' + SEL_OPEN_PRINCIPAL + _addr_word(token_address())}, 'latest'])
        open_principal = int(raw, 16)
    except Exception as exc:  # noqa: BLE001
        raise EscrowError('limits_unavailable') from exc
    return cached[0], cached[1], open_principal


def deposit_step_up(user, *, order_id32: str, buyer: str, merchant: str, amount_wei: int,
                    amount_usd, consume: bool = False) -> str:
    """'' or the message that blocks this payment: an identity hold, or
    Confío Face. Pay's rule: everyone who went through KYC confirms with
    their face; a purchase from someone else's store stays inside Confío, so
    small amounts get the light check.

    Run BEFORE the deposit authorization is signed: the signed batch is
    executable by itself (anyone can broadcast it through the delegate), so
    the approval is consumed — bound to this order's exact terms — before
    any executable authorization exists."""
    from security.face_context import face_client_supported
    from security.face_step_up import require_face_step_up, step_up_applies, withdrawal_action_key
    from security.identity_reuse import outgoing_identity_restriction

    restriction = outgoing_identity_restriction(user)
    if restriction:
        return restriction
    # Unconditional for Comprar: every build with the tab supports Confío
    # Face, so the app-wide rollout switch (flag OR capable client) is forced
    # on here — a request without the capability header cannot skip it.
    token = face_client_supported.set(True)
    try:
        if not step_up_applies(user):
            # Buyers are KYC'd (checkout requires it): never wave one through.
            return 'identity_required'
        action_key = withdrawal_action_key('market_order', order_id32, [
            chain_id(), buyer, str(amount_wei), merchant])
        message = require_face_step_up(user, 'withdrawal', action_key=action_key, consume=consume,
                                       amount_usd=amount_usd, cash_out=False)
        if message or not consume:
            return message
        # Proof, not inference: an approval must now be consumed under THIS
        # order's key. (The helper returns '' without consuming if eligibility
        # flipped mid-call; that must never let an authorization be signed.)
        from security.models import FaceCheck
        if not FaceCheck.objects.filter(user=user, purpose='withdrawal', status='passed',
                                        consumed_by=action_key, consumed_at__isnull=False).exists():
            from security.face_step_up import FACE_STEP_UP_MESSAGE
            return FACE_STEP_UP_MESSAGE
        return ''
    finally:
        face_client_supported.reset(token)


def _word(v: int) -> str:
    return format(int(v), 'x').rjust(64, '0')


def _addr_word(addr: str) -> str:
    return addr.lower().replace('0x', '').rjust(64, '0')


def new_order_id32(public_id) -> str:
    return keccak(text=f'comprar:{public_id}').hex()


# ── deposit authorization (EIP-712, the escrow's orderSigner) ───────────

def deposit_digest(order_id32: str, buyer: str, merchant: str, token: str,
                   amount_wei: int, fee_bps: int, deadline: int, escrow: str | None = None) -> bytes:
    escrow = escrow or escrow_address()
    domain = keccak(abi_encode(
        ['bytes32', 'bytes32', 'bytes32', 'uint256', 'address'],
        [DOMAIN_TYPEHASH, keccak(text='ConfioMarketEscrow'), keccak(text='1'),
         chain_id(), to_checksum_address(escrow)]))
    struct_hash = keccak(abi_encode(
        ['bytes32', 'bytes32', 'address', 'address', 'address', 'uint256', 'uint16', 'uint256'],
        [DEPOSIT_TYPEHASH, bytes.fromhex(order_id32), to_checksum_address(buyer),
         to_checksum_address(merchant), to_checksum_address(token), int(amount_wei),
         int(fee_bps), int(deadline)]))
    return keccak(b'\x19\x01' + domain + struct_hash)


def sign_deposit(digest: bytes) -> tuple[str, str]:
    """(signature_hex, signer_address). The KMS sponsor is the orderSigner,
    the same key that authorizes Pay invoices."""
    from payments.bsc_flow import _sign_pay_authorization
    sig, signer = _sign_pay_authorization(digest)
    return sig, signer.lower()


def recover_signer(digest: bytes, sig_hex: str) -> str:
    from payments.bsc_flow import _recover_pay_signer
    return _recover_pay_signer(digest, sig_hex)


# ── call builders ───────────────────────────────────────────────────────

def deposit_call(order) -> dict:
    sig = bytes.fromhex(order.deposit_signature.replace('0x', ''))
    args = abi_encode(
        ['bytes32', 'address', 'address', 'uint256', 'uint16', 'uint256', 'bytes'],
        [bytes.fromhex(order.order_id32), to_checksum_address(order.merchant_address),
         to_checksum_address(order.token_address), int(order.amount_wei), int(order.fee_bps),
         int(order.deposit_deadline), sig])
    return {'to': escrow_address(), 'value': '0', 'data': '0x' + SEL_DEPOSIT + args.hex()}


def approve_call(order) -> dict:
    from cusd_plus.sponsor_7702 import SEL_APPROVE
    return {'to': order.token_address.lower(), 'value': '0',
            'data': '0x' + SEL_APPROVE + _addr_word(escrow_address()) + _word(int(order.amount_wei))}


def single_call(action: str, order) -> dict:
    return {'to': escrow_address(), 'value': '0',
            'data': '0x' + SINGLE_CALL_SELECTORS[action] + order.order_id32}


def funding_leg(buyer_addr: str, amount_wei: int):
    """None when the buyer already holds enough cUSD; otherwise the leading
    cUSD+.unwrapToCusd for just the shortfall (inside the perimeter, no
    conversion fee — the same normalization Pay uses). Raises EscrowError."""
    from cusd_plus import vault as cp_vault
    from cusd_plus.sponsor_7702 import SEL_UNWRAP_TO_CUSD
    from payments.bsc_flow import ONDO_MIN_REDEEM_WEI

    vault_addr = (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()
    try:
        cusd_raw = cp_vault.erc20_balance_raw(token_address(), buyer_addr)
        if cusd_raw >= amount_wei:
            return None
        if not vault_addr:
            raise EscrowError('insufficient_balance')
        pps_wad = cp_vault.p_plus_wad()
        shares_raw = cp_vault.erc20_balance_raw(vault_addr, buyer_addr)
        oracle_p_wad = cp_vault.last_oracle_price_wad()
    except EscrowError:
        raise
    except Exception as exc:  # noqa: BLE001 — money reads fail closed
        logger.warning('[COMPRAR] balance rpc failed: %s', exc)
        raise EscrowError('balance_unavailable') from exc

    shortfall = amount_wei - cusd_raw
    if (shares_raw * pps_wad) // WAD + cusd_raw < amount_wei:
        raise EscrowError('insufficient_balance')
    shares_needed = -(-shortfall * WAD // pps_wad)
    for _ in range(8):
        if shares_needed >= shares_raw:
            break
        if cp_vault.redeem_gross_usdt_out(shares_needed, pps_wad, oracle_p_wad) >= shortfall:
            break
        shares_needed += 1
    shares_needed = min(shares_needed, shares_raw)
    predicted = cp_vault.redeem_gross_usdt_out(shares_needed, pps_wad, oracle_p_wad)
    if predicted < shortfall:
        raise EscrowError('insufficient_balance')
    if predicted < ONDO_MIN_REDEEM_WEI:
        raise EscrowError('redeem_below_minimum')
    return {'to': vault_addr, 'value': '0',
            'data': '0x' + SEL_UNWRAP_TO_CUSD + _word(shares_needed) + _word(shortfall)
                    + _addr_word(buyer_addr)}


# ── validation of what the client sends back ────────────────────────────

def validate_deposit_calls(calls: list, order) -> None:
    """[ (unwrap), approve(escrow, amount), deposit(...) ] pinned to the row."""
    from cusd_plus.sponsor_7702 import PolicyError, SEL_UNWRAP_TO_CUSD

    if len(calls) not in (2, 3):
        raise PolicyError('bad_batch_size')
    for call in calls:
        if int(call.get('value') or 0) != 0:
            raise PolicyError('value_not_allowed')
    if len(calls) == 3:
        unwrap = calls[0]
        vault_addr = (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()
        data = (unwrap.get('data') or '').lower()
        if (unwrap.get('to') or '').lower() != vault_addr or len(data) != 2 + 8 + 192 \
                or data[2:10] != SEL_UNWRAP_TO_CUSD:
            raise PolicyError('bad_calldata')
        if data[138:202] != _addr_word(order.buyer_address):
            raise PolicyError('conversion_recipient_not_allowed')
    approve, deposit = calls[-2], calls[-1]
    if approve != approve_call(order):
        raise PolicyError('bad_calldata')
    if deposit != deposit_call(order):
        raise PolicyError('bad_calldata')
    if int(order.deposit_deadline) <= int(time.time()):
        raise PolicyError('authorization_expired')
    digest = deposit_digest(order.order_id32, order.buyer_address, order.merchant_address,
                            order.token_address, int(order.amount_wei), order.fee_bps,
                            int(order.deposit_deadline))
    try:
        recovered = recover_signer(digest, order.deposit_signature)
    except Exception as exc:  # noqa: BLE001
        raise PolicyError('bad_authorization') from exc
    if recovered != order.deposit_signer.lower():
        raise PolicyError('bad_authorization')


def _normalize(calls: list) -> list:
    return [{'to': (c.get('to') or '').lower(), 'value': str(int(c.get('value') or 0)),
             'data': (c.get('data') or '').lower()} for c in calls]


# ── submit (shared by every user action) ────────────────────────────────

def actor_address(order, action: str) -> str:
    role = ACTIONS[action][1]
    return (order.buyer_address if role == 'buyer' else order.merchant_address).lower()


def actor_allowed(user, order, action: str) -> bool:
    """May `user` perform `action` for its side of the order RIGHT NOW?
    Personal side: its user. Business side: the owner, or an active employee
    whose role holds the action's permission (rechecked here, at the moment
    money moves)."""
    from .permissions import ACTION_PERMISSIONS, can_act_for, order_actor_account
    return can_act_for(user, order_actor_account(order, action), ACTION_PERMISSIONS[action])


def action_calls(order, action: str) -> list:
    """The exact calls the actor signs: the deposit batch stored at prepare
    (its funding leg depends on balances read then), or the one escrow call."""
    if action == 'deposit':
        return _normalize(order.deposit_calls or [])
    return [single_call(action, order)]


def submit_action(user, order, action: str, nonce: int, deadline: int,
                  intent_signature: str, authorization=None) -> dict:
    from cusd_plus import sponsor_7702
    from .models import Order

    if action not in ACTIONS:
        return {'success': False, 'error': 'unknown_action'}
    if not enabled():
        return {'success': False, 'error': 'marketplace_disabled'}
    if not actor_allowed(user, order, action):
        return {'success': False, 'error': 'not_your_order'}
    kind = ACTIONS[action][0]
    signer_addr = actor_address(order, action)
    calls = action_calls(order, action)

    now = int(time.time())
    if not (now + 30 <= int(deadline) <= now + 1800):
        return {'success': False, 'error': 'bad_deadline'}

    if action == 'deposit':
        if order.status != 'draft':
            return {'success': False, 'error': 'order_not_payable'}
        # Confío Face was consumed when this authorization was issued
        # (checkout). Identity holds are re-read by send_sponsored_batch.
    else:
        if order.status not in ALLOWED_FROM[action]:
            return {'success': False, 'error': 'action_not_allowed'}
        if order.pending_action and not _pending_expired(order):
            return {'success': False, 'error': 'action_in_progress'}

    # Everything that can reject without side effects happens BEFORE the row
    # is taken (the invite-flow lesson: a first-use 'authorization_required'
    # must leave the row retryable).
    try:
        if action == 'deposit':
            validate_deposit_calls(calls, order)
        intent_id = sponsor_7702.intent_id_for(kind, order.pk)
        digest = sponsor_7702.intent_digest(calls, int(nonce), int(deadline), signer_addr,
                                            chain_id(), intent_id)
        if sponsor_7702.recover_intent_signer(digest, intent_signature) != signer_addr:
            return {'success': False, 'error': 'bad_intent_signature'}
        auth_dict = None
        if not sponsor_7702.is_delegated(signer_addr):
            if authorization is None:
                return {'success': False, 'error': 'authorization_required',
                        'authorization_required': True}
            auth_dict = sponsor_7702.normalize_and_validate_authorization(
                authorization, signer_addr, chain_id())
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}

    # Take the row: exactly one caller moves it, and only that caller broadcasts.
    if action == 'deposit':
        # Stock was reserved when the authorization was issued (checkout);
        # winning the row is all that is left.
        won = Order.objects.filter(pk=order.pk, status='draft').update(
            status='depositing', pending_action='deposit', pending_action_at=timezone.now())
        if not won:
            return {'success': False, 'error': 'order_not_payable'}
    else:
        won = Order.objects.filter(pk=order.pk, status=order.status).filter(
            _pending_free_q()).update(pending_action=action, pending_action_at=timezone.now())
        if not won:
            return {'success': False, 'error': 'action_in_progress'}

    try:
        tx_hash, batch = sponsor_7702.send_sponsored_batch(
            user, signer_addr, calls, int(nonce), int(deadline), intent_signature, auth_dict,
            kind, source_id=order.pk)
    except sponsor_7702.PolicyError as exc:
        _release_action(order, action)
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001
        logger.exception('[COMPRAR] %s failed for order %s', action, order.pk)
        # A durable batch row means the transaction may already be on chain.
        # Reporting failure here is how a buyer retries and pays twice: say
        # "pending" and let the confirm task / reconciler settle it.
        live = _live_batch(order, action)
        if live is not None:
            return {'success': True, 'pending': True, 'transaction_hash': live.tx_hash}
        _release_action(order, action, only_if_no_batch=True)
        return {'success': False, 'error': str(exc)[:200]}

    # Past the broadcast, nothing may turn this into a failure: the batch row
    # is durable and cusd_plus.reconcile_signed_batches re-enqueues the
    # confirm task if scheduling it here fails.
    try:
        updates = {'last_tx_hash': tx_hash}
        if action == 'deposit':
            updates['deposit_tx_hash'] = tx_hash
        Order.objects.filter(pk=order.pk).update(**updates)
        from .tasks import confirm_market_action
        confirm_market_action.apply_async(args=[order.pk, batch.id], countdown=6)
    except Exception:  # noqa: BLE001
        logger.exception('[COMPRAR] post-broadcast bookkeeping failed for order %s (%s)', order.pk, tx_hash)
    return {'success': True, 'transaction_hash': tx_hash}


def _live_batch(order, action: str):
    from blockchain.models import SponsoredBatch
    return SponsoredBatch.objects.filter(
        kind=ACTIONS[action][0], source_id=order.pk, status__in=('signed', 'sent', 'confirmed'),
    ).order_by('-id').first()


def _pending_expired(order) -> bool:
    at = order.pending_action_at
    return at is None or (timezone.now() - at).total_seconds() > PENDING_ACTION_TTL_S


def _pending_free_q():
    from django.db.models import Q
    cutoff = timezone.now() - timedelta(seconds=PENDING_ACTION_TTL_S)
    return Q(pending_action='') | Q(pending_action_at__lt=cutoff) | Q(pending_action_at__isnull=True)


def reserve_stock(product_id: int, quantity: int) -> bool:
    """Taken when the deposit authorization is ISSUED (checkout), because a
    signed authorization is spendable on chain until its deadline whatever
    the row says. Caller runs inside the transaction that creates the order."""
    from .models import Product
    return bool(Product.objects.filter(pk=product_id, stock__gte=quantity).update(
        stock=F('stock') - quantity))


def release_unspent_reservation(order) -> bool:
    """Give the stock back ONLY once the authorization can no longer be spent:
    past its deadline (+ a finality grace) and the chain never saw the order.
    Returns True when released."""
    from .models import Order, Product

    if not order.stock_reserved:
        return False
    if int(time.time()) <= int(order.deposit_deadline) + DEADLINE_GRACE_S:
        return False
    # A CONFIRMED snapshot whose own block time is past the deadline: a
    # lagging node answering from before the deposit mined cannot pass this,
    # and the contract rejects any deposit after its deadline.
    snapshot = read_chain_order(order.order_id32, confirmations=RELEASE_CONFIRMATIONS)
    if snapshot['state'] != 'none':
        return False
    if int(snapshot['block_time']) <= int(order.deposit_deadline):
        return False
    with transaction.atomic():
        row = Order.objects.select_for_update().get(pk=order.pk)
        if (not row.stock_reserved or row.status not in ('draft', 'depositing', 'cancelled')
                or int(row.chain_block or 0) > int(snapshot['block'])):
            return False
        Order.objects.filter(pk=row.pk).update(
            stock_reserved=False, status='cancelled', pending_action='', pending_action_at=None)
        Product.objects.filter(pk=row.product_id).update(stock=F('stock') + row.quantity)
        return True


def _release_action(order, action: str, only_if_no_batch: bool = False) -> None:
    """Hand the row back after an attempt that provably never reached the chain."""
    from blockchain.models import SponsoredBatch
    from .models import Order

    kind = ACTIONS[action][0]
    if only_if_no_batch and SponsoredBatch.objects.filter(
            kind=kind, source_id=order.pk, status__in=('signed', 'sent')).exists():
        logger.warning('[COMPRAR] order %s %s left in flight — a live batch exists', order.pk, action)
        return
    if action == 'deposit':
        # Back to draft; the reservation stays until the authorization expires.
        Order.objects.filter(pk=order.pk, status='depositing').update(
            status='draft', pending_action='', pending_action_at=None)
    else:
        Order.objects.filter(pk=order.pk, pending_action=action).update(
            pending_action='', pending_action_at=None)


# ── reading the chain ───────────────────────────────────────────────────

def read_chain_order(order_id32: str, confirmations: int = 0) -> dict:
    """The contract's order at ONE block (returned as 'block', plus its
    'block_time' when confirmations are asked for), so a slow reader can be
    told its snapshot is older than one already mirrored."""
    from cusd_plus.sponsor_7702 import _rpc
    block = int(_rpc('eth_blockNumber', []), 16) - int(confirmations)
    block_time = None
    if confirmations:
        header = _rpc('eth_getBlockByNumber', [hex(block), False])
        block_time = int(header['timestamp'], 16)
    raw = _rpc('eth_call', [{'to': escrow_address(), 'data': '0x' + SEL_GET_ORDER + order_id32},
                            hex(block)])
    (buyer, ship_by, fee_bps, state, merchant, release_at, release_window, token,
     disputed_at, amount), = abi_decode([ORDER_TUPLE], bytes.fromhex(raw[2:]))
    return {
        'buyer': buyer.lower(), 'ship_by': ship_by, 'fee_bps': fee_bps,
        'state': CHAIN_STATES.get(state, 'unknown'), 'merchant': merchant.lower(),
        'release_at': release_at, 'token': token.lower(), 'disputed_at': disputed_at,
        'amount': amount, 'block': block, 'block_time': block_time,
    }


def _ts(value: int):
    return datetime.fromtimestamp(int(value), tz=dt_timezone.utc) if value else None


def sync_order(order, chain: dict | None = None) -> str:
    """Mirror the contract's view of this order onto the row. The ONLY writer
    of money states. Returns the resulting status.

    Snapshots are block-pinned: one older than the block already mirrored is
    dropped, and released/refunded never move again. A cancelled row (a
    superseded or expired draft) is resurrected if its authorization was in
    fact spent — the chain is the authority, not the row."""
    from .models import Order

    chain = chain or read_chain_order(order.order_id32)
    state = chain['state']
    if state == 'none':
        # Never funded. Expired authorizations hand their stock back through
        # release_unspent_reservation (keeper); nothing to mirror here.
        return order.status
    # Defense in depth: the chain order must be THIS order.
    if (chain['buyer'] != order.buyer_address.lower()
            or chain['merchant'] != order.merchant_address.lower()
            or int(chain['amount']) != int(order.amount_wei)
            or chain['token'] != order.token_address.lower()
            or int(chain['fee_bps']) != int(order.fee_bps)):
        logger.error('[COMPRAR] chain order %s does not match row %s — refusing to sync',
                     order.order_id32, order.pk)
        return order.status

    with transaction.atomic():
        row = Order.objects.select_for_update().get(pk=order.pk)
        previous = row.status
        if int(chain['block']) < int(row.chain_block or 0):
            return previous  # an older snapshot than the one already mirrored
        if previous in ('released', 'refunded') and state != previous:
            logger.error('[COMPRAR] order %s is %s but chain read %s at block %s — ignoring',
                         row.pk, previous, state, chain['block'])
            return previous
        updates = {
            'status': state,
            'chain_block': int(chain['block']),
            'ship_by': _ts(chain['ship_by']),
            'release_at': _ts(chain['release_at']),
            'disputed_at': _ts(chain['disputed_at']),
        }
        if row.funded_at is None:
            updates['funded_at'] = timezone.now()
        if state in ('funded', 'shipped', 'disputed'):
            updates['open_block'] = int(chain['block'])
        if not row.stock_reserved:
            # Defensive: funded although its reservation was handed back (it
            # cannot be, since release waits for the deadline + a 'none' read).
            # The sale is real, so the units are sold.
            from .models import Product
            Product.objects.filter(pk=row.product_id).update(stock=F('stock') - row.quantity)
            updates['stock_reserved'] = True
        if state in ('released', 'refunded') and row.settled_at is None:
            settled_at, scan_block = settlement_time(row, state, int(chain['block']))
            updates['settle_scan_block'] = scan_block
            if settled_at is not None:
                updates['settled_at'] = settled_at
        # An in-flight marker (user action or keeper tx) clears only once the
        # chain moved or the marker expired — never on an unchanged read, or
        # the keeper would send the same release twice.
        if row.pending_action and (previous != state or _pending_expired(row)):
            updates['pending_action'] = ''
            updates['pending_action_at'] = None
        for field, value in updates.items():
            setattr(row, field, value)
        row.save(update_fields=[*updates.keys(), 'updated_at'])
        from .ledger import sync_order_ledger
        sync_order_ledger(row)  # history + Tu mes rows (never raises)
        if state == 'released' and row.settled_at is not None:
            # Only with the exact release time: the partner share depends on
            # which agreement was running then. Deferred reads retry next sync.
            record_fee(row)
    if previous != state:
        from .notifications import order_status_changed
        order_status_changed(row, previous)
    return state


SETTLED_EVENT_TOPICS = {
    'released': '0x' + keccak(text='Released(bytes32,address,uint256,uint256,address)').hex(),
    'refunded': '0x' + keccak(text='Refunded(bytes32,address,uint256,address)').hex(),
}


LOG_CHUNK_BLOCKS = 5_000
MAX_LOG_CHUNKS = 120


# A lower bound on BSC block time, so a block estimated from a timestamp is
# always EARLIER than the real one (the search may start early, never late).
MIN_BLOCK_SECONDS = 0.4


def _search_start_block(order, to_block: int) -> int:
    """A block at or before the settlement event: the last block the order
    was seen open; else the deposit's block (from its hash, recovered from the
    durable batch row if the post-broadcast write was lost); else a block
    safely before the order was created."""
    from blockchain.models import SponsoredBatch
    from cusd_plus.sponsor_7702 import _rpc

    if order.open_block:
        return int(order.open_block)
    batch = SponsoredBatch.objects.filter(
        kind='market_deposit', source_id=order.pk, status='confirmed').order_by('-id').first()
    if batch is not None and batch.block_number:
        return int(batch.block_number)
    tx_hash = order.deposit_tx_hash or (batch.tx_hash if batch is not None else '')
    if tx_hash:
        receipt = _rpc('eth_getTransactionReceipt', [tx_hash])
        if receipt and receipt.get('blockNumber'):
            return int(receipt['blockNumber'], 16)
    age_s = max((timezone.now() - order.created_at).total_seconds(), 0)
    return max(to_block - int(age_s / MIN_BLOCK_SECONDS) - 1_000, 0)


def settlement_time(order, state: str, to_block: int):
    """(settled_at, scan_block): the block time of the escrow's
    Released/Refunded event, searched FORWARD from a stable lower bound in
    chunks, resuming where the last attempt stopped (scan_block). settled_at
    is None when it cannot be established yet — the caller saves the progress
    and the next sync continues; the time is never guessed (it decides the
    partner share)."""
    from cusd_plus.sponsor_7702 import _rpc

    scan = int(order.settle_scan_block or 0)
    try:
        lo = max(_search_start_block(order, to_block), scan)
        for _ in range(MAX_LOG_CHUNKS):
            if lo > to_block:
                break
            hi = min(lo + LOG_CHUNK_BLOCKS - 1, to_block)
            logs = _rpc('eth_getLogs', [{
                'address': escrow_address(), 'fromBlock': hex(lo), 'toBlock': hex(hi),
                'topics': [SETTLED_EVENT_TOPICS[state], '0x' + order.order_id32],
            }])
            if logs:
                header = _rpc('eth_getBlockByNumber', [logs[0]['blockNumber'], False])
                return _ts(int(header['timestamp'], 16)), lo
            lo = hi + 1
            scan = lo
        if lo > to_block:
            logger.warning('[COMPRAR] no %s event found for order %s up to block %s',
                           state, order.pk, to_block)
    except Exception as exc:  # noqa: BLE001
        logger.warning('[COMPRAR] settlement time lookup failed for order %s: %s', order.pk, exc)
    return None, scan


def record_fee(order) -> None:
    """One ledger row per released order; the partner share comes from the
    agreement active for the store's country at release time."""
    from decimal import Decimal
    from .models import MarketplaceFeeLedger, MarketplacePartnerAgreement
    from .pricing import fee_wei

    if MarketplaceFeeLedger.objects.filter(order=order).exists():
        return
    from django.db.models import Q

    released_at = order.settled_at or timezone.now()
    fee = Decimal(fee_wei(int(order.amount_wei), order.fee_bps)) / Decimal(WAD)
    # The agreement whose interval contains the RELEASE time, whatever its
    # active flag says today: ending an agreement after a release must not
    # erase a share the partner had already earned.
    agreement = MarketplacePartnerAgreement.objects.filter(
        Q(ended_at__isnull=True) | Q(ended_at__gt=released_at),
        country_code=order.store.country_code, started_at__lte=released_at,
    ).order_by('-started_at').first()
    if agreement and agreement.ended_at is None and not agreement.active:
        agreement = None  # deactivated without an end date: treat as never running
    partner_share = Decimal('0')
    if agreement:
        partner_share = (fee * agreement.share_bps / Decimal(10_000)).quantize(Decimal('0.000001'))
    MarketplaceFeeLedger.objects.create(
        order=order, country_code=order.store.country_code, gross_usd=order.amount_usd,
        fee_usd=fee, partner_agreement=agreement, partner_share_usd=partner_share,
        confio_share_usd=fee - partner_share, released_at=released_at)


# ── keeper transactions (sponsor EOA) ───────────────────────────────────

def send_keeper_tx(data: str, gas_limit: int = 150_000) -> str:
    """release / refundExpiredDispute / resolve from the sponsor EOA (the
    contract's arbiter). Pre-flights under the real budget; returns tx hash."""
    from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
    from cusd_plus.sponsor_7702 import (_rpc, acquire_sponsor_nonce_lock,
                                        release_sponsor_nonce_lock)

    signer = get_bsc_sponsor_signer_from_settings()
    sender = signer.address
    escrow = to_checksum_address(escrow_address())
    lock = acquire_sponsor_nonce_lock()
    if not lock:
        raise EscrowError('sponsor_nonce_lock_busy')
    try:
        _rpc('eth_call', [{'from': sender, 'to': escrow, 'data': data, 'gas': hex(gas_limit)}, 'latest'])
        nonce = int(_rpc('eth_getTransactionCount', [sender, 'pending']), 16)
        gas_price = max(int(_rpc('eth_gasPrice', []), 16),
                        int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 50_000_000)))
        raw, tx_hash = signer.sign_transaction({
            'chainId': chain_id(), 'nonce': nonce, 'gasPrice': (gas_price * 12) // 10,
            'gas': gas_limit, 'to': escrow, 'value': 0, 'data': data,
        })
        try:
            _rpc('eth_sendRawTransaction', [raw])
        except Exception as exc:  # noqa: BLE001 — the receipt decides
            logger.warning('[COMPRAR] keeper broadcast reported an error for %s: %s', tx_hash, exc)
    finally:
        release_sponsor_nonce_lock(lock)
    return tx_hash


def _claimed_keeper_tx(order, expected_status: str, marker: str, data: str) -> str:
    """Claim the row (pending_action '' → marker) BEFORE sending, so two
    keeper runs or two admins can never broadcast the same settlement. A send
    that fails before broadcast hands the claim back; an uncertain broadcast
    keeps it until the TTL, by which time sync has seen the chain."""
    from .models import Order

    won = Order.objects.filter(pk=order.pk, status=expected_status).filter(
        _pending_free_q()).update(pending_action=marker, pending_action_at=timezone.now())
    if not won:
        raise EscrowError('action_in_progress')
    try:
        tx_hash = send_keeper_tx(data)
    except Exception:
        Order.objects.filter(pk=order.pk, pending_action=marker).update(
            pending_action='', pending_action_at=None)
        raise
    Order.objects.filter(pk=order.pk).update(last_tx_hash=tx_hash)
    return tx_hash


def keeper_release(order) -> str:
    return _claimed_keeper_tx(order, 'shipped', 'keeper_release', '0x' + SEL_RELEASE + order.order_id32)


def keeper_refund_expired_dispute(order) -> str:
    return _claimed_keeper_tx(order, 'disputed', 'keeper_refund',
                              '0x' + SEL_REFUND_EXPIRED + order.order_id32)


def arbiter_resolve(order, to_merchant: bool) -> str:
    return _claimed_keeper_tx(order, 'disputed', 'arbiter',
                              '0x' + SEL_RESOLVE + order.order_id32 + _word(1 if to_merchant else 0))
