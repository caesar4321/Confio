"""
BSC payroll flow — ConfioPayrollVault (per-business cUSD+ escrow with
delegate-signed payouts). Phase 2 W3 of the cUSD phase-out.

Why this rail is shaped differently from send/pay: under EIP-7702 only the
business key can sign for the business EOA, so an employee-delegate cannot
author a business batch. The delegate model lives ON-CHAIN instead — the
business parks payroll float in ConfioPayrollVault and allowlists delegate
EVM addresses; each payout is an EIP-712 signature by the delegate (their
OWN personal wallet key) which ANY caller may execute. Confío's KMS sponsor
is that caller (plain type-2 tx, not 7702), paying gas.

TWO ESCROW POOLS (v2, 2026-08-02). The vault escrows cUSD+ shares OR raw
USDT, per business, never fungible between them. An Ondo-BLOCKED employer
holds its dollars as raw USDT and can never mint shares, so the shares-only
v1 made Nómina eligible-employers-only: fundableBalance read $0.00 and
funding failed "insufficient balance" on money the business owned. Which
pool a run spends is `funding_token` at creation, pinned on the run.

Three surfaces:

  admin ops (business EOA, 7702 sponsored batches like every other flow):
      fund          [token.approve(payroll, amt), payroll.deposit(asset, amt)]
      withdraw      [payroll.withdraw(asset, amt, business)]  — NEVER blocked
      set_delegate  [payroll.setDelegate(delegateAddr, allowed)]
    No stored batch: submit rebuilds the calls from INTEGER params (asset,
    amount, delegate address), so the batch is byte-exact by construction
    and the server never trusts client calldata.

  payout (two-step, server-authoritative like send/pay):
      prepare  gates + branch choice, stores the exact Payout struct on the
               PayrollItem, returns the EIP-712 digest for the delegate to
               sign with their own key
      submit   recover signer from the STORED struct, double-check the
               on-chain allowlist, broadcast payout() as a plain KMS tx
               under the shared sponsor nonce lock

Recipient rails mirror send/bsc_flow.py, and apply to the cUSD+ pool only:
eligible → shares transfer; ineligible/unknown → vault.redeemToUsdt inside
payout() (atomic USDT delivery — exits never geo-gated). Out of the USDT
pool there is one rail, a plain transfer: the money is already what an
ineligible recipient would be redeemed into, and an eligible one sweeps it
into cUSD+ themselves exactly as they would a ramp deposit.
"""
import json
import logging
import time
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from eth_abi import encode as abi_encode
from eth_utils import keccak

logger = logging.getLogger(__name__)

WAD = 10 ** 18
REDEEM_MIN_OUT_BPS = 9_950  # same drift tolerance as send/bsc_flow.py
PAYOUT_DEADLINE_S = 900

# Ondo's Instant Manager refuses redemptions under $1.
ONDO_MIN_REDEEM_WEI = 10 ** 18

# ── EIP-712 (canonical strings shared with ConfioPayrollVault.sol and the
#    client signer — parity anchored in test_payout_digest_parity + the
#    contract's payoutDigest() view; never change one alone) ──────────────
P_DOMAIN_TYPEHASH = keccak(
    text='EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)')
P_NAME_HASH = keccak(text='ConfioPayrollVault')
# "2": the Payout struct gained `asset` and renamed shares→amount when the
# vault learned to escrow raw USDT (2026-08-02).
P_VERSION_HASH = keccak(text='2')
PAYOUT_TYPEHASH = keccak(
    text='Payout(address business,address recipient,uint8 asset,'
         'uint256 netAmount,uint256 feeAmount,bool redeemToUsdt,'
         'uint256 minUsdtOut,bytes32 itemId,uint256 deadline)')

# ── The two escrow pools ─────────────────────────────────────────────────
# Mirrors ConfioPayrollVault.Asset. An Ondo-BLOCKED employer holds its
# dollars as raw USDT and can never mint shares, so a shares-only escrow
# made Nómina eligible-employers-only; the pools are separate money and a
# run is denominated in exactly one of them, pinned at creation.
ASSET_CUSD_PLUS = 0
ASSET_USDT = 1
#: run/item token_type ↔ on-chain asset selector
TOKEN_ASSET = {'CUSD_PLUS': ASSET_CUSD_PLUS, 'USDT': ASSET_USDT}


def _sel(sig: str) -> str:
    return keccak(text=sig)[:4].hex()


SEL_PAYROLL_DEPOSIT = _sel('deposit(uint8,uint256)')
SEL_PAYROLL_WITHDRAW = _sel('withdraw(uint8,uint256,address)')
SEL_PAYROLL_SET_DELEGATE = _sel('setDelegate(address,bool)')
SEL_PAYOUT = _sel(
    'payout((address,address,uint8,uint256,uint256,bool,uint256,bytes32,uint256),bytes)')
SEL_ESCROW_SHARES = _sel('escrowShares(address)')
SEL_ESCROW_USDT = _sel('escrowUsdt(address)')
SEL_IS_DELEGATE = _sel('isDelegate(address,address)')

# Fork-calibrated (ConfioPayrollVault.fork.t.sol: transfer payout 147k,
# redeem payout 566k) + the sponsor-spend headroom rule.
GAS_PAYOUT_TRANSFER = 350_000
GAS_PAYOUT_REDEEM = 950_000


def _payroll_address() -> str:
    return (getattr(settings, 'BSC_PAYROLL_VAULT_ADDRESS', '') or '').lower()


def _vault_address() -> str:
    return (getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', '') or '').lower()


def _escrow_token_address(asset: int) -> str:
    """The ERC-20 behind a pool: vault shares, or BSC USDT."""
    if asset == ASSET_USDT:
        from cusd_plus import vault as cp_vault
        return (cp_vault.usdt_address() or '').lower()
    return _vault_address()


def _uint_word(v: int) -> str:
    return format(int(v), 'x').rjust(64, '0')


def _addr_word(addr: str) -> str:
    return addr.lower().replace('0x', '').rjust(64, '0')


def _payout_asset(p: dict) -> int:
    """Asset selector for a prepared payout.

    Defaults to cUSD+ so a payout dict written before the USDT pool existed
    still hashes to what it was signed against — the field is inside the
    struct hash, and silently reading a missing key as 0 is only safe
    BECAUSE 0 is exactly what those older payouts meant.
    """
    return int(p.get('asset', ASSET_CUSD_PLUS))


def payout_digest(p: dict, chain_id: int) -> bytes:
    """EIP-712 digest exactly as ConfioPayrollVault.payoutDigest computes it."""
    struct_hash = keccak(abi_encode(
        ['bytes32', 'address', 'address', 'uint8', 'uint256', 'uint256', 'bool',
         'uint256', 'bytes32', 'uint256'],
        [PAYOUT_TYPEHASH, p['business'], p['recipient'], _payout_asset(p),
         int(p['net_amount']), int(p['fee_amount']), bool(p['redeem_to_usdt']),
         int(p['min_usdt_out']), bytes.fromhex(p['item_id'][2:]), int(p['deadline'])],
    ))
    domain_separator = keccak(abi_encode(
        ['bytes32', 'bytes32', 'bytes32', 'uint256', 'address'],
        [P_DOMAIN_TYPEHASH, P_NAME_HASH, P_VERSION_HASH, chain_id, _payroll_address()],
    ))
    return keccak(b'\x19\x01' + domain_separator + struct_hash)


def payout_calldata(p: dict, signature_hex: str) -> str:
    """ABI-encode ConfioPayrollVault.payout(Payout, bytes)."""
    encoded = abi_encode(
        ['(address,address,uint8,uint256,uint256,bool,uint256,bytes32,uint256)', 'bytes'],
        [(p['business'], p['recipient'], _payout_asset(p), int(p['net_amount']),
          int(p['fee_amount']), bool(p['redeem_to_usdt']), int(p['min_usdt_out']),
          bytes.fromhex(p['item_id'][2:]), int(p['deadline'])),
         bytes.fromhex(signature_hex.replace('0x', ''))],
    )
    return '0x' + SEL_PAYOUT + encoded.hex()


def item_id_bytes32(internal_id: str) -> str:
    """Deterministic bytes32 for a PayrollItem — keccak of the internal id
    (uniform width regardless of id format; the contract replay-keys on it
    per business)."""
    return '0x' + keccak(text=internal_id).hex()


def _eth_call(to: str, data: str) -> str:
    from cusd_plus.sponsor_7702 import _rpc
    return _rpc('eth_call', [{'to': to, 'data': data}, 'latest'])


def escrow_shares_raw(business_addr: str) -> int:
    out = _eth_call(_payroll_address(), '0x' + SEL_ESCROW_SHARES + _addr_word(business_addr))
    return int(out, 16) if out and out != '0x' else 0


def escrow_usdt_raw(business_addr: str) -> int:
    out = _eth_call(_payroll_address(), '0x' + SEL_ESCROW_USDT + _addr_word(business_addr))
    return int(out, 16) if out and out != '0x' else 0


def escrow_raw(business_addr: str, asset: int) -> int:
    """Parked amount in one pool, in that asset's own units."""
    return (escrow_usdt_raw(business_addr) if asset == ASSET_USDT
            else escrow_shares_raw(business_addr))


def escrow_split_usd(business_addr: str) -> dict:
    """Both pools in USD, separately: {'CUSD_PLUS': x, 'USDT': y}.

    The screens need this because the pools are NOT fungible — a business
    holding both can only move one per operation, and a single summed figure
    let the top-up screen validate a withdrawal against money the chosen pool
    did not have (audit 2026-08-02, [P1]). None per pool on a read failure,
    for the same reason escrow_usd returns None: "we could not reach the
    node" and "$0.00" are different sentences to an employer.
    """
    out = {'CUSD_PLUS': None, 'USDT': None}
    if not business_addr or not _payroll_address():
        return out
    key = business_addr.lower()
    try:
        from cusd_plus import vault as cp_vault
        shares = escrow_shares_raw(key)
        out['CUSD_PLUS'] = (0.0 if shares == 0
                            else (shares * cp_vault.p_plus_wad()) / (WAD * WAD))
    except Exception:  # noqa: BLE001
        logger.warning('[PAYROLL][BSC] cUSD+ escrow read failed for %s', key)
    try:
        out['USDT'] = escrow_usdt_raw(key) / WAD
    except Exception:  # noqa: BLE001
        logger.warning('[PAYROLL][BSC] USDT escrow read failed for %s', key)
    return out


def fundable_split_usd(business_addr: str) -> dict:
    """What the business could move INTO escrow, per pool, in USD — its own
    wallet balances, the exact figures prepare_bsc_payroll_admin checks."""
    out = {'CUSD_PLUS': None, 'USDT': None}
    if not business_addr:
        return out
    from cusd_plus import vault as cp_vault
    try:
        out['CUSD_PLUS'] = cp_vault.position_usd(business_addr)
    except Exception:  # noqa: BLE001
        logger.warning('[PAYROLL][BSC] cUSD+ wallet read failed for %s', business_addr)
    try:
        out['USDT'] = cp_vault.usdt_balance_raw(business_addr) / WAD
    except Exception:  # noqa: BLE001
        logger.warning('[PAYROLL][BSC] USDT wallet read failed for %s', business_addr)
    return out


def is_onchain_delegate(business_addr: str, delegate_addr: str) -> bool:
    out = _eth_call(
        _payroll_address(),
        '0x' + SEL_IS_DELEGATE + _addr_word(business_addr) + _addr_word(delegate_addr))
    return bool(int(out, 16)) if out and out != '0x' else False


# ── Read side — what the payroll screens actually display ────────────────
#
# The WRITE path moved to ConfioPayrollVault first and the reads stayed on
# the Algorand boxes, so a business that had funded the BSC vault and
# allowlisted its delegates still opened an empty, "not activated" payroll
# hub: escrow read as $0.00 and the delegate list came back empty, which is
# also what the client derives activation from. These are the BSC answers to
# the same two questions the Algorand resolvers answer.

ESCROW_TTL = 30              # matches cusd_plus.vault.POSITION_TTL
ESCROW_LAST_TTL = 7 * 24 * 3600
DELEGATES_TTL = 30


def _bump(key: str) -> None:
    try:
        cache.incr(key)
    except ValueError:  # not set yet
        cache.set(key, 1, None)


def invalidate_escrow(business_addr: str) -> None:
    """Drop the cached escrow read after a fund/withdraw/payout moves it.

    Versioned rather than deleted for the same reason as the delegate cache:
    a read that started before the write must not be able to land afterwards
    and re-publish the pre-transaction number."""
    if business_addr:
        key = business_addr.lower()
        cache.delete(f'payroll_escrow:{key}')
        _bump(f'payroll_escrow_ver:{key}')


def invalidate_delegates(business_addr: str) -> None:
    """Bump the version so every cached (business, delegate) answer for this
    business is bypassed at once — the set of candidates is not known here,
    and a toggle must be visible on the next read."""
    if business_addr:
        _bump(f'payroll_delegates_ver:{business_addr.lower()}')


def escrow_usd(business_addr: str):
    """USD value of a business's payroll escrow — BOTH pools summed
    (shares × pPlus, plus raw USDT at 1:1) — or None when we genuinely do
    not know.

    Summed on purpose: this is the "how much payroll float is parked"
    number the hub prints, and a business that funded in USDT after being
    geo-blocked has float that is every bit as real as a share position.
    Which pool a given RUN spends is a separate question, answered by the
    run's own token_type.

    Degradation contract, stricter than cusd_plus.vault.position_usd: a
    flaky node falls back to the last successfully read value, and if there
    is no last-known value it returns **None**, not 0.0. Returning 0.0 for
    "the node did not answer" is the same sentence to a business as "your
    payroll float is gone" — the screens render None as "—" instead."""
    if not business_addr or not _payroll_address():
        return None
    key = business_addr.lower()
    cached = cache.get(f'payroll_escrow:{key}')
    if cached is not None:
        return cached
    ver = cache.get(f'payroll_escrow_ver:{key}') or 0
    try:
        from cusd_plus import vault as cp_vault
        shares = escrow_shares_raw(key)
        value = 0.0 if shares == 0 else (shares * cp_vault.p_plus_wad()) / (WAD * WAD)
        value += escrow_usdt_raw(key) / WAD
    except Exception:  # noqa: BLE001 — a read failure must not break the screen
        logger.warning('[PAYROLL][BSC] escrow read failed for %s', business_addr,
                       exc_info=True)
        return cache.get(f'payroll_escrow_last:{key}')
    # Narrow, not atomic: if a fund/withdraw invalidated while this read was
    # in flight, drop the answer rather than publish a pre-transaction number
    # (and rather than poison the outage fallback with it).
    if (cache.get(f'payroll_escrow_ver:{key}') or 0) != ver:
        return value
    cache.set(f'payroll_escrow:{key}', value, ESCROW_TTL)
    cache.set(f'payroll_escrow_last:{key}', value, ESCROW_LAST_TTL)
    return value


def onchain_delegates(business_addr: str, candidate_addrs, with_status: bool = False):
    """The subset of `candidate_addrs` the contract actually allowlists.
    Returns the list, or `(list, degraded)` when `with_status` is set —
    `degraded` meaning at least one candidate could not be resolved at all,
    so an empty result must NOT be read as "this business has no delegates".

    isDelegate is a mapping with no enumerator, so the candidate set comes
    from our own records (the business EOA plus every active employee's
    personal address) and the chain decides which of them are real. That
    ordering matters: the DB proposes, the contract disposes — an address
    we no longer know about simply stops being listed, and one we know
    about but never allowlisted never appears."""
    def _out(allowed_map, degraded):
        result = [a for a in wanted if allowed_map.get(a)]
        return (result, degraded) if with_status else result

    wanted = []
    if not business_addr or not _payroll_address():
        return _out({}, True)
    key = business_addr.lower()
    seen = set()
    for addr in candidate_addrs:
        low = (addr or '').lower()
        if low and low not in seen:
            seen.add(low)
            wanted.append(low)
    if not wanted:
        return _out({}, False)

    # Cached PER PAIR, not per business: keying the whole answer on the
    # business meant an employee who registered their address inside the TTL
    # was reported "not a delegate" without the chain ever being asked about
    # them. The version prefix lets a toggle drop every pair at once.
    ver = cache.get(f'payroll_delegates_ver:{key}') or 0
    live = {a: f'payroll_delegate:{ver}:{key}:{a}' for a in wanted}
    last = {a: f'payroll_delegate_last:{key}:{a}' for a in wanted}
    known = cache.get_many(list(live.values()))

    allowed = {}
    unknown = []
    for a in wanted:
        hit = known.get(live[a])
        if hit is None:
            unknown.append(a)
        else:
            allowed[a] = hit

    degraded = False
    if unknown:
        # One eth_call PER address, each in its own try. Wrapping the whole
        # comprehension meant a single dead call discarded every other
        # candidate's successful answer along with it.
        stale = cache.get_many([last[a] for a in unknown])
        fresh = {}
        for a in unknown:
            try:
                fresh[a] = is_onchain_delegate(key, a)
            except Exception:  # noqa: BLE001
                # A node outage is not a revocation: fall back to what the
                # chain last said about THIS pair. With nothing last-known we
                # have no answer at all, which is not the same as "no".
                logger.warning('[PAYROLL][BSC] delegate read failed for %s/%s',
                               business_addr, a, exc_info=True)
                remembered = stale.get(last[a])
                if remembered is None:
                    degraded = True
                else:
                    allowed[a] = remembered
        if fresh:
            cache.set_many({live[a]: v for a, v in fresh.items()}, DELEGATES_TTL)
            # Only if no invalidation raced us. `_last` is deliberately
            # unversioned so it survives a bump, which also means a reader
            # that started before a revoke could otherwise write the revoked
            # delegate back into the outage fallback.
            if (cache.get(f'payroll_delegates_ver:{key}') or 0) == ver:
                cache.set_many({last[a]: v for a, v in fresh.items()}, ESCROW_LAST_TTL)
            allowed.update(fresh)

    return _out(allowed, degraded)


def execution_rail(business_account) -> str:
    """Where NEW payroll work will execute: 'bsc' or 'algorand'.

    Deliberately the same condition the write path falls through on — the
    client's BSC-first branches treat `bsc_payroll_disabled`,
    `payroll_vault_not_configured` and `vault_not_configured` as "use the
    legacy rail", so this must agree or a run would be denominated in a token
    its payout never touches. This is what CreatePayrollRun asks."""
    if not getattr(settings, 'BSC_PAYROLL_ENABLED', False):
        return 'algorand'
    if not _payroll_address() or not _vault_address():
        return 'algorand'
    if not (business_account and (business_account.bsc_address or '')):
        return 'algorand'
    return 'bsc'


def display_rail(business_account) -> str:
    """Where this business's payroll money actually IS — what the screens
    must describe.

    Not the same question as execution_rail, and the difference is load-
    bearing during the kill switch. `withdraw` deliberately survives
    BSC_PAYROLL_ENABLED=False (exits are never gated), so with the flag off
    and escrow still parked in ConfioPayrollVault the execution rail says
    'algorand' while the withdraw button drains BSC. Reporting the Algorand
    box balance there shows a business one number beside a button that moves
    a different one. Follow the money instead; the escrow read is cached, so
    the extra probe costs at most one RPC per TTL."""
    if not _payroll_address() or not _vault_address():
        return 'algorand'
    addr = (business_account.bsc_address or '') if business_account else ''
    if not addr:
        return 'algorand'
    if getattr(settings, 'BSC_PAYROLL_ENABLED', False):
        return 'bsc'
    parked = escrow_usd(addr.lower())
    if parked is None:
        # We could not read the escrow. Coercing that to 0 picked 'algorand'
        # and served the legacy vault's balance and activation state as fact —
        # the same unknown-as-zero mistake, one layer up. Stay on BSC: the
        # screen then honestly shows "—" instead of another chain's number.
        return 'bsc'
    return 'bsc' if parked > 0 else 'algorand'


def funding_token(business_account, actor_user) -> str:
    """Which pool this business tops up and pays FROM: 'CUSD_PLUS' or 'USDT'.

    `actor_user` is whoever is acting on the business right now, not "the
    owner" — deliberately. A business account holds no jurisdiction of its
    own; the mint gate that decides whether its USDT becomes cUSD+ tests the
    HUMAN making the call. So the person who will actually run the top-up is
    the one whose eligibility answers this. Two delegates in different
    countries can only disagree while BOTH pools are empty, which is exactly
    the case where nothing has been decided yet anyway.

    Two inputs, in this order:
      1. What it already has parked. Float that is sitting in a pool is
         spendable from that pool, whatever the employer's status says
         today — an employer who was eligible when they funded must not be
         told their existing float is unusable the day their country
         changes.
      2. Otherwise, what its money WILL be. An Ondo-eligible owner's USDT
         is swept into cUSD+ (deposits land as USDT for everyone since the
         phase-out); a blocked owner's stays raw forever, because the mint
         gate refuses it.

    Phone-country eligibility ONLY, deliberately: this answer is pinned
    onto a run that outlives the request, and the full check's IP half
    would re-denominate a business's payroll because its owner opened the
    app from an airport. The mint gate stays the full check where it is
    actually enforced.
    """
    from cusd_plus.eligibility import is_ondo_eligible

    addr = ((getattr(business_account, 'bsc_address', None) or '') or '').lower()
    if addr:
        try:
            if escrow_shares_raw(addr) > 0:
                return 'CUSD_PLUS'
            if escrow_usdt_raw(addr) > 0:
                return 'USDT'
        except Exception:  # noqa: BLE001 — an RPC hiccup falls through to status
            logger.warning('[PAYROLL][BSC] escrow probe failed for %s', addr,
                           exc_info=True)
    return 'CUSD_PLUS' if is_ondo_eligible(actor_user) else 'USDT'


def rail_token(rail: str, business_account=None, actor_user=None) -> str:
    """The token a run created on this rail is denominated in.

    On BSC that is no longer a constant: the asset a run draws from must be
    one the employer can actually park. Callers without a business in hand
    (pure rail questions) still get the historical answer.
    """
    if rail != 'bsc':
        return 'CUSD'
    if business_account is None or actor_user is None:
        return 'CUSD_PLUS'
    return funding_token(business_account, actor_user)


# ── Shared context resolution ────────────────────────────────────────────

def _business_context(user, jwt_ctx):
    """Resolve (business, business_account, business_addr, signer_addr,
    error). signer_addr is the EXECUTING USER's own personal EVM address —
    the key that will sign the payout digest."""
    from users.models import Account

    if jwt_ctx.get('account_type') != 'business' or not jwt_ctx.get('business_id'):
        return None, None, None, None, 'business_context_required'
    business_account = Account.objects.filter(
        business_id=jwt_ctx['business_id'], account_type='business',
        account_index=jwt_ctx.get('account_index', 0),
        deleted_at__isnull=True).select_related('business').first()
    if not business_account:
        return None, None, None, None, 'business_account_not_found'
    business_addr = (business_account.bsc_address or '').lower()
    if not business_addr:
        return None, None, None, None, 'business_no_bsc_address'
    personal = user.accounts.filter(
        account_type='personal', account_index=0, deleted_at__isnull=True).first()
    signer_addr = ((getattr(personal, 'bsc_address', None) or '') or '').lower()
    return business_account.business, business_account, business_addr, signer_addr, None


def _flags_error():
    if not getattr(settings, 'BSC_PAYROLL_ENABLED', False):
        return 'bsc_payroll_disabled'
    if not _payroll_address():
        return 'payroll_vault_not_configured'
    if not _vault_address():
        return 'vault_not_configured'
    return None


# ── Admin ops (business EOA via 7702) ────────────────────────────────────

def build_admin_calls(action: str, shares: int = 0, delegate_addr: str = '',
                      allowed: bool = True, business_addr: str = '',
                      delegate_addrs=None, asset: int = ASSET_CUSD_PLUS) -> list:
    """Canonical batches for the three business ops. Deterministic from
    integer/address params — submit rebuilds and the signature must match.

    set_delegate takes either one address or a LIST: activation allowlists
    the owner plus every delegate they picked in the wizard, and one 7702
    batch of N setDelegate calls costs one sponsored batch instead of N —
    which matters directly, since the sponsor's daily batch cap is small
    enough that a five-delegate activation would otherwise exhaust it."""
    payroll = _payroll_address()
    if action == 'fund':
        # Approve the TOKEN BEING PARKED, not the cUSD+ vault by reflex: a
        # USDT top-up that approved shares would deposit nothing and revert
        # on the transferFrom.
        token = _escrow_token_address(asset)
        return [
            {'to': token, 'value': '0',
             'data': '0x' + '095ea7b3' + _addr_word(payroll) + _uint_word(shares)},
            {'to': payroll, 'value': '0',
             'data': '0x' + SEL_PAYROLL_DEPOSIT + _uint_word(asset) + _uint_word(shares)},
        ]
    if action == 'withdraw':
        # Destination pinned to the business's own EOA — a compromised
        # session cannot exfiltrate the float elsewhere.
        return [{'to': payroll, 'value': '0',
                 'data': '0x' + SEL_PAYROLL_WITHDRAW + _uint_word(asset)
                         + _uint_word(shares) + _addr_word(business_addr)}]
    if action == 'set_delegate':
        addrs = list(delegate_addrs) if delegate_addrs else (
            [delegate_addr] if delegate_addr else [])
        if not addrs:
            raise ValueError('set_delegate needs at least one delegate address')
        return [{'to': payroll, 'value': '0',
                 'data': '0x' + SEL_PAYROLL_SET_DELEGATE + _addr_word(a)
                         + _uint_word(1 if allowed else 0)}
                for a in addrs]
    raise ValueError(f'unknown admin action {action}')


def prepare_bsc_payroll_admin(user, jwt_ctx, action: str, amount=None,
                              delegate_user_id=None, allowed: bool = True,
                              delegate_user_ids=None,
                              include_self: bool = False,
                              token_type: str = '') -> dict:
    from cusd_plus import vault as cp_vault
    from django.contrib.auth import get_user_model

    err = _flags_error()
    if err and action != 'withdraw':
        # Withdraw must survive the kill switch (exits are never gated) as
        # long as the vault addresses exist to talk to.
        return {'success': False, 'error': err}
    if action == 'withdraw' and not _payroll_address():
        return {'success': False, 'error': 'payroll_vault_not_configured'}

    business, business_account, business_addr, signer_addr, err = _business_context(user, jwt_ctx)
    if err:
        return {'success': False, 'error': err}

    if action in ('fund', 'withdraw'):
        try:
            amount_usd = Decimal(str(amount))
        except Exception:  # noqa: BLE001
            return {'success': False, 'error': 'invalid_amount'}
        if amount_usd <= 0:
            return {'success': False, 'error': 'invalid_amount'}
        # WHICH pool — the CALLER says (audit 2026-08-02, [P1]). Deriving it
        # from one server-side answer could not express "this employer has
        # money in BOTH pools", which is the normal state after an
        # eligibility flip and the exact case this vault exists to serve: a
        # single answer preferring shares hid the whole USDT pool from
        # funding AND withdrawal, so a USDT-denominated run could never be
        # funded until the cUSD+ pool was drained to zero.
        #
        # Safe to take from the client: the asset goes into the batch the
        # business signs, and every path below re-checks the real balance of
        # the pool it names. funding_token() remains the DEFAULT for older
        # clients that send nothing, and remains what pins a run at creation.
        token = (token_type or '').upper() or funding_token(business_account, user)
        if token not in TOKEN_ASSET:
            return {'success': False, 'error': 'unknown_token_type'}
        asset = TOKEN_ASSET[token]
        if asset == ASSET_USDT:
            # USDT is the unit of account AND the token: no share price in
            # the path at all, so nothing to fail on and nothing to round.
            units = int(amount_usd * WAD)
        else:
            try:
                pps_wad = cp_vault.p_plus_wad()
            except Exception as exc:  # noqa: BLE001
                logger.warning('[PAYROLL][BSC] pps read failed: %s', exc)
                return {'success': False, 'error': 'balance_unavailable'}
            units = (int(amount_usd * WAD) * WAD) // pps_wad
        if units <= 0:
            return {'success': False, 'error': 'invalid_amount'}
        if action == 'fund':
            held = cp_vault.erc20_balance_raw(_escrow_token_address(asset), business_addr)
            if held < units:
                return {'success': False, 'error': 'insufficient_balance'}
        else:
            if escrow_raw(business_addr, asset) < units:
                return {'success': False, 'error': 'insufficient_escrow'}
        calls = build_admin_calls(action, shares=units, business_addr=business_addr,
                                  asset=asset)
        from cusd_plus.sponsor_7702 import intent_id_hex
        return {'success': True, 'calls': calls, 'shares': str(units),
                'asset': asset, 'token_type': token,
                'intent_id': intent_id_hex(f'payroll_{action}', business_account.id)}

    if action == 'set_delegate':
        User = get_user_model()
        wanted_ids = list(delegate_user_ids) if delegate_user_ids else (
            [delegate_user_id] if delegate_user_id else [])
        addrs = []
        if include_self and allowed:
            # Activation must allowlist the person doing it. Payouts are
            # signed with a PERSONAL key, so an owner who allowlisted only
            # their employees could not pay their own payroll — and resolving
            # "me" from the JWT here means it does not depend on the owner
            # having a BusinessEmployee row for the client to find.
            if not signer_addr:
                return {'success': False, 'error': 'no_bsc_address'}
            addrs.append(signer_addr)
        if not wanted_ids and not addrs:
            return {'success': False, 'error': 'delegate_not_found'}
        for uid in wanted_ids:
            delegate_user = User.objects.filter(id=uid).first()
            if not delegate_user:
                return {'success': False, 'error': 'delegate_not_found'}
            d_account = delegate_user.accounts.filter(
                account_type='personal', account_index=0,
                deleted_at__isnull=True).first()
            delegate_addr = ((getattr(d_account, 'bsc_address', None) or '') or '').lower()
            if not delegate_addr:
                # Named, so the app can say WHO still has to open the app
                # rather than failing the whole activation anonymously.
                return {'success': False, 'error': 'delegate_no_bsc_address',
                        'delegate_name': (delegate_user.get_full_name()
                                          or delegate_user.username or '')}
            if delegate_addr not in addrs:
                addrs.append(delegate_addr)
        calls = build_admin_calls('set_delegate', delegate_addrs=addrs,
                                  allowed=allowed)
        from cusd_plus.sponsor_7702 import intent_id_hex
        return {'success': True, 'calls': calls, 'delegate_address': addrs[0],
                'delegate_addresses': addrs,
                'intent_id': intent_id_hex(f'payroll_{action}', business_account.id)}

    return {'success': False, 'error': 'unknown_action'}


def submit_bsc_payroll_admin(user, jwt_ctx, action: str, nonce, deadline,
                             intent_signature, authorization=None,
                             shares=None, delegate_address='',
                             allowed: bool = True, delegate_addresses=None,
                             asset: int = ASSET_CUSD_PLUS) -> dict:
    """Rebuild the canonical batch from integer params and relay it. The
    signature only verifies against the server's own bytes.

    `asset` is echoed by the client rather than re-derived here, and that is
    safe for the same reason every other param is: it goes into the rebuilt
    calls, the business signed THOSE bytes, so naming a different pool than
    it signed for fails signature recovery. Re-deriving would be worse — the
    answer can legitimately change between prepare and submit (a payout in
    between emptying a pool), and the batch must match what was signed, not
    what is true a second later."""
    from cusd_plus import sponsor_7702

    err = _flags_error()
    if err and action != 'withdraw':
        return {'success': False, 'error': err}

    business, business_account, business_addr, _signer, err = _business_context(user, jwt_ctx)
    if err:
        return {'success': False, 'error': err}

    try:
        if action in ('fund', 'withdraw'):
            shares_int = int(shares or 0)
            if shares_int <= 0:
                return {'success': False, 'error': 'invalid_amount'}
            calls = build_admin_calls(action, shares=shares_int,
                                      business_addr=business_addr,
                                      asset=int(asset or ASSET_CUSD_PLUS))
        elif action == 'set_delegate':
            addrs = [(a or '').lower() for a in (delegate_addresses or [])] or (
                [(delegate_address or '').lower()] if delegate_address else [])
            if not addrs:
                return {'success': False, 'error': 'delegate_not_found'}
            from users.models import Account
            for addr in addrs:
                if not Account.objects.filter(
                        bsc_address__iexact=addr,
                        deleted_at__isnull=True).exists():
                    # Only addresses of real Confío accounts can enter the
                    # allowlist through this rail.
                    return {'success': False, 'error': 'delegate_not_found'}
            calls = build_admin_calls('set_delegate', delegate_addrs=addrs,
                                      allowed=allowed)
        else:
            return {'success': False, 'error': 'unknown_action'}

        now = int(time.time())
        if not (now + 30 <= int(deadline) <= now + 1800):
            return {'success': False, 'error': 'bad_deadline'}

        chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))
        intent_id = sponsor_7702.intent_id_for(f'payroll_{action}', business_account.id)
        digest = sponsor_7702.intent_digest(
            calls, int(nonce), int(deadline), business_addr, chain_id, intent_id)
        signer = sponsor_7702.recover_intent_signer(digest, intent_signature)
        if signer != business_addr:
            return {'success': False, 'error': 'bad_intent_signature'}

        auth_dict = None
        if not sponsor_7702.is_delegated(business_addr):
            if authorization is None:
                return {'success': False, 'error': 'authorization_required',
                        'authorization_required': True}
            auth_dict = sponsor_7702.normalize_and_validate_authorization(
                authorization, business_addr, chain_id)

        tx_hash, batch = sponsor_7702.send_sponsored_batch(
            user, business_addr, calls, int(nonce), int(deadline),
            intent_signature, auth_dict, f'payroll_{action}', source_id=business_account.id)
    except sponsor_7702.PolicyError as exc:
        if exc.code == 'stale_auth_nonce':
            return {'success': False, 'error': exc.code, 'authorization_required': True}
        return {'success': False, 'error': exc.code}
    except Exception as exc:  # noqa: BLE001
        logger.exception('[PAYROLL][BSC] admin %s failed', action)
        return {'success': False, 'error': str(exc)[:200]}

    try:
        from cusd_plus.vault import invalidate_position
        invalidate_position(business_addr)
        # The two numbers this op just changed and the hub reads back
        # immediately after it returns.
        invalidate_escrow(business_addr)
        if action == 'set_delegate':
            invalidate_delegates(business_addr)
        # ...and again once the transaction has had time to land. Invalidating
        # only here, at BROADCAST, means the next read re-caches PRE-transaction
        # chain state for a full TTL — so the business refreshes, sees the old
        # balance or the delegate they just revoked, and concludes nothing
        # happened.
        from .tasks import refresh_payroll_chain_caches
        refresh_payroll_chain_caches.apply_async(
            args=[business_addr], countdown=25)
    except Exception:  # noqa: BLE001
        pass
    return {'success': True, 'transaction_hash': tx_hash}


# ── Payout (delegate-signed, sponsor-broadcast) ──────────────────────────

def _notify_recipient_needs_app(recipient_user, business) -> None:
    try:
        from notifications import utils as notif_utils
        from notifications.models import NotificationType as NotifType
        notif_utils.create_notification(
            user=recipient_user,
            account=None,
            business=None,
            notification_type=NotifType.PAYROLL_RECEIVED,
            title='Tu pago te está esperando',
            message=(
                f'{business.name} quiere pagarte tu nómina. '
                'Abre Confío para activar tu cuenta y poder recibirla.'
            ),
            data={'transaction_type': 'payroll_blocked', 'reason': 'no_bsc_address'},
        )
    except Exception:  # noqa: BLE001
        logger.exception('payroll recipient-needs-app notification failed')


def prepare_bsc_payroll_payout(user, jwt_ctx, item) -> dict:
    from cusd_plus import vault as cp_vault
    from cusd_plus.eligibility import is_ondo_eligible

    # The run pins the rail, not the live flag — and this is checked BEFORE
    # the flags, on purpose. A run created while payroll was on Algorand is
    # denominated in cUSD and must be paid from THAT vault even if BSC has
    # been enabled since; a cUSD+ run can only ever be paid from here.
    if item.run.token_type not in ('CUSD_PLUS', 'USDT'):
        return {'success': False, 'error': 'run_on_legacy_rail'}

    err = _flags_error()
    if err:
        # Answering `bsc_payroll_disabled` here sent the client to the legacy
        # path, which then refused the same cUSD+ run — leaving a wage that
        # NEITHER path would pay and an error naming the wrong chain. This run
        # has exactly one rail; if that rail is paused, say that.
        return {'success': False, 'error': 'bsc_payroll_paused'}

    business, business_account, business_addr, signer_addr, err = _business_context(user, jwt_ctx)
    if err:
        return {'success': False, 'error': err}
    if item.run.business_id != business.id:
        return {'success': False, 'error': 'not_your_payroll'}
    if item.status not in ('PENDING', 'PREPARED', 'FAILED'):
        return {'success': False, 'error': 'item_not_pending'}
    if not signer_addr:
        return {'success': False, 'error': 'no_bsc_address'}

    recipient_addr = ((item.recipient_account.bsc_address or '') or '').lower()
    if not recipient_addr:
        _notify_recipient_needs_app(item.recipient_user, business)
        return {'success': False, 'error': 'recipient_no_bsc_address'}

    # The signature only helps if the contract will accept it: allowlist
    # membership is checked here (cheap read) AND enforced on-chain.
    if signer_addr != business_addr and not is_onchain_delegate(business_addr, signer_addr):
        return {'success': False, 'error': 'not_onchain_delegate'}

    # WHICH pool pays. Pinned on the run at creation, never re-derived here:
    # an employer whose eligibility changes mid-run must still be paying out
    # of the escrow the run was funded into.
    asset = TOKEN_ASSET[item.run.token_type]

    net_wei = int(Decimal(item.net_amount) * WAD)
    fee_wei = int(Decimal(item.fee_amount or 0) * WAD)
    if net_wei <= 0:
        return {'success': False, 'error': 'invalid_amount'}
    if asset == ASSET_USDT:
        # Dollars ARE the units — no share price anywhere in this branch.
        net_units, fee_units = net_wei, fee_wei
    else:
        try:
            pps_wad = cp_vault.p_plus_wad()
        except Exception as exc:  # noqa: BLE001
            logger.warning('[PAYROLL][BSC] pps read failed: %s', exc)
            return {'success': False, 'error': 'balance_unavailable'}
        net_units = (net_wei * WAD) // pps_wad
        fee_units = (fee_wei * WAD) // pps_wad
    if net_units <= 0:
        return {'success': False, 'error': 'invalid_amount'}

    if escrow_raw(business_addr, asset) < net_units + fee_units:
        return {'success': False, 'error': 'insufficient_escrow'}

    # Schedule and cap were decorative on this rail: neither BSC prepare nor
    # submit consulted them and the contract carries no window or cap state.
    # Enforced here so the normal path honours what the business configured.
    #
    # Honest about its reach: the payout authorization we sign is valid for
    # PAYOUT_DEADLINE_S, so a delegate holding one could call the contract
    # directly inside that window regardless. Real enforcement would need the
    # cap in ConfioPayrollVault; this is the guardrail, not the lock.
    from django.utils import timezone
    run = item.run
    scheduled_at = getattr(run, 'scheduled_at', None)
    if scheduled_at and scheduled_at > timezone.now():
        return {'success': False, 'error': 'run_not_due'}
    cap_amount = getattr(run, 'cap_amount', None)
    if cap_amount:
        from django.db.models import Sum
        paid = run.items.filter(
            status__in=('SUBMITTED', 'CONFIRMED'), deleted_at__isnull=True,
        ).exclude(id=item.id).aggregate(t=Sum('gross_amount'))['t'] or Decimal('0')
        if paid + Decimal(item.gross_amount or 0) > Decimal(cap_amount):
            logger.warning('[PAYROLL][BSC] run %s would exceed its cap %s (already %s)',
                           run.id, cap_amount, paid)
            return {'success': False, 'error': 'run_cap_exceeded'}

    # The recipient fork applies to the cUSD+ pool ONLY. Paying out of USDT
    # escrow there is nothing to redeem — the money is already the thing an
    # ineligible employee would have been redeemed INTO, and an eligible one
    # sweeps it into cUSD+ themselves exactly as they would a ramp deposit.
    redeem = (asset == ASSET_CUSD_PLUS) and not is_ondo_eligible(item.recipient_user)
    # Ondo refuses redemptions under $1. Unlike a payment there is no change
    # to leave behind — the employee is owed an exact wage — so catch it here
    # rather than letting the sponsored transaction revert on chain, burn gas
    # and mark the item FAILED.
    if redeem and net_wei < ONDO_MIN_REDEEM_WEI:
        logger.info('[PAYROLL][BSC] %s: %s wage to an Ondo-ineligible recipient is '
                    'below the $1 redemption floor', item.internal_id, item.net_amount)
        return {'success': False, 'error': 'wage_below_redeem_minimum'}
    min_usdt_out = (net_wei * REDEEM_MIN_OUT_BPS) // 10_000 if redeem else 0

    chain_id = int(getattr(settings, 'BSC_CHAIN_ID', 56))
    payout = {
        'business': business_addr,
        'recipient': recipient_addr,
        'asset': asset,
        'net_amount': str(net_units),
        'fee_amount': str(fee_units),
        'redeem_to_usdt': redeem,
        'min_usdt_out': str(min_usdt_out),
        'item_id': item_id_bytes32(item.internal_id),
        'deadline': int(time.time()) + PAYOUT_DEADLINE_S,
        'expected_signer': signer_addr,
        'chain_id': chain_id,
    }
    digest = payout_digest(payout, chain_id)

    data = dict(item.blockchain_data or {})
    data['bsc_payout'] = payout
    item.blockchain_data = data
    # What the EMPLOYEE ends up holding, which is not always what the run
    # spent: a cUSD+ run redeeming for an ineligible recipient lands USDT.
    item.token_type = 'USDT' if (asset == ASSET_USDT or redeem) else 'CUSD_PLUS'
    item.status = 'PREPARED'
    item.save(update_fields=['blockchain_data', 'token_type', 'status', 'updated_at'])

    return {
        'success': True,
        'digest': '0x' + digest.hex(),
        'deadline': payout['deadline'],
        'redeem_to_usdt': redeem,
    }


def submit_bsc_payroll_payout(user, jwt_ctx, item, signature: str) -> dict:
    from cusd_plus import sponsor_7702
    from cusd_plus.sponsor_7702 import (
        PolicyError,
        _rpc,
        acquire_sponsor_nonce_lock,
        release_sponsor_nonce_lock,
    )
    from blockchain.models import SponsoredBatch

    err = _flags_error()
    if err:
        return {'success': False, 'error': err}

    business, business_account, business_addr, _signer, err = _business_context(user, jwt_ctx)
    if err:
        return {'success': False, 'error': err}
    if item.run.business_id != business.id:
        return {'success': False, 'error': 'not_your_payroll'}
    if item.status != 'PREPARED':
        return {'success': False, 'error': 'item_not_prepared'}

    payout = (item.blockchain_data or {}).get('bsc_payout')
    if not payout or payout.get('business') != business_addr:
        return {'success': False, 'error': 'payout_not_prepared'}
    if 'net_amount' not in payout:
        # Prepared against the v1 vault (netShares/feeShares, no asset). Its
        # signature is worthless here whatever we do — different typehash,
        # different domain version, and a different contract address — so
        # say "re-prepare" rather than KeyError on the old shape. Only items
        # left PREPARED across the v2 deploy can hit this, and the client's
        # normal retry re-prepares them.
        logger.info('[PAYROLL][BSC] %s was prepared against the v1 vault; '
                    're-prepare required', item.internal_id)
        return {'success': False, 'error': 'payout_not_prepared'}
    if int(payout['deadline']) < int(time.time()) + 15:
        return {'success': False, 'error': 'payout_expired'}

    chain_id = int(payout.get('chain_id') or getattr(settings, 'BSC_CHAIN_ID', 56))
    digest = payout_digest(payout, chain_id)
    signer = sponsor_7702.recover_intent_signer(digest, signature)
    if not signer or signer != payout.get('expected_signer'):
        return {'success': False, 'error': 'bad_payout_signature'}

    calldata = payout_calldata(payout, signature)
    payroll_addr = _payroll_address()

    from blockchain.evm_kms_signer import get_bsc_sponsor_signer_from_settings
    signer_kms = get_bsc_sponsor_signer_from_settings()
    sponsor = signer_kms.address

    # Pre-flight the exact call before spending sponsor gas (bad sig,
    # consumed item, thin escrow all surface here).
    try:
        _rpc('eth_call', [{'from': sponsor, 'to': payroll_addr, 'data': calldata}, 'latest'])
    except Exception as exc:  # noqa: BLE001
        logger.warning('[PAYROLL][BSC] payout simulation reverted for %s: %s',
                       item.internal_id, exc)
        return {'success': False, 'error': 'simulation_reverted'}

    gas = GAS_PAYOUT_REDEEM if payout['redeem_to_usdt'] else GAS_PAYOUT_TRANSFER
    gas_price = max(int(_rpc('eth_gasPrice', []), 16),
                    int(getattr(settings, 'CUSD_PLUS_GAS_PRICE_FLOOR_WEI', 100_000_000)))
    price_cap = int(getattr(settings, 'CUSD_PLUS_7702_MAX_GAS_PRICE_WEI', 5_000_000_000))
    if gas_price > price_cap:
        return {'success': False, 'error': 'gas_price_too_high'}
    fee_per_gas = min((gas_price * 12) // 10, price_cap)

    if not acquire_sponsor_nonce_lock():
        return {'success': False, 'error': 'sponsor_busy'}
    try:
        sponsor_nonce = int(_rpc('eth_getTransactionCount', [sponsor, 'pending']), 16)
        sponsor_balance = int(_rpc('eth_getBalance', [sponsor, 'latest']), 16)
        if sponsor_balance < (gas * fee_per_gas * 11) // 10:
            logger.error('sponsor BNB too low for payroll payout — refill needed')
            return {'success': False, 'error': 'sponsor_balance_low'}
        from eth_utils import to_checksum_address
        tx = {
            'type': 2,
            'chainId': chain_id,
            'nonce': sponsor_nonce,
            'maxPriorityFeePerGas': fee_per_gas,
            'maxFeePerGas': fee_per_gas,
            'gas': gas,
            'to': to_checksum_address(payroll_addr),
            'value': 0,
            'data': calldata,
            'accessList': [],
        }
        raw, tx_hash = signer_kms.sign_typed_transaction(tx)
        # Durable BEFORE broadcast (audit 2026-07-31 P1-2). plain-KMS payout,
        # so delegate_nonce=None; the receipt task proves it via the
        # contract's own PaidOut log + finality. On-chain (business,itemId)
        # replay already blocks a double-payout, so a lost-then-retried row
        # cannot double-spend.
        batch = SponsoredBatch.objects.create(
            user=user,
            user_bsc_address=business_addr,
            kind='payroll_payout',
            source_id=item.id,
            num_calls=1,
            calls_json=json.dumps([{'to': payroll_addr, 'value': '0', 'data': calldata}]),
            tx_hash=tx_hash,
            gas_limit=gas,
            max_fee_wei=str(fee_per_gas),
            status='signed',
        )
        # Keep the node's answer: `sent` is read below and was never assigned,
        # so every successful payout raised NameError AFTER the money moved —
        # item stuck at PREPARED with no hash, confirmer refusing it (it takes
        # only SUBMITTED), run never completing, and the scanner recording the
        # salary as a generic external deposit because no PayrollItem carried
        # the hash to prove ownership. For a correctly signed transaction this
        # equals tx_hash; the fallback covers a node that answers with null.
        sent = _rpc('eth_sendRawTransaction', [raw])
        batch.status = 'sent'
        batch.save(update_fields=['status', 'updated_at'])
    except Exception as exc:  # noqa: BLE001
        logger.exception('[PAYROLL][BSC] payout broadcast failed for %s', item.internal_id)
        return {'success': False, 'error': str(exc)[:200]}
    finally:
        release_sponsor_nonce_lock()

    # RECORD BEFORE SCHEDULING. Anything between the broadcast and this save
    # can fail — a broker outage on apply_async, the process dying — and the
    # money has already moved. The item would stay PREPARED with no hash and
    # no recipient_address, which strands it permanently: the reconciler only
    # sweeps batches still in 'signed', the confirmer refuses anything not
    # SUBMITTED, and the scanner then books the wage as an external deposit
    # because nothing carries the hash that proves payroll owns it.
    #
    # The locally computed hash is AUTHORITATIVE: it is derived from the
    # signed payload, while the node's answer is only a claim. A node
    # returning something else must not desync item.transaction_hash from
    # batch.tx_hash, which would strand the confirmer forever.
    from django.utils import timezone
    if sent and str(sent).lower() != str(tx_hash).lower():
        logger.error(
            '[PAYROLL][BSC] node returned %s for a transaction signed as %s — '
            'keeping the signed hash', sent, tx_hash)
    item.transaction_hash = tx_hash
    item.status = 'SUBMITTED'
    item.executed_by_user = user
    item.executed_at = timezone.now()
    item.recipient_address = (payout.get('recipient') or '').lower()
    item.save(update_fields=['transaction_hash', 'status', 'executed_by_user',
                             'executed_at', 'recipient_address', 'updated_at'])

    from cusd_plus.tasks import check_sponsored_batch_receipt
    check_sponsored_batch_receipt.apply_async(args=[batch.id], countdown=6)

    try:
        from cusd_plus.vault import invalidate_position
        invalidate_position(payout['recipient'])
    except Exception:  # noqa: BLE001
        pass

    from .tasks import confirm_bsc_payroll_payout
    confirm_bsc_payroll_payout.apply_async(args=[item.id, batch.id], countdown=8)
    return {'success': True, 'transaction_hash': tx_hash}
