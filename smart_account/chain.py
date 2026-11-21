"""Chain reads for Cuenta inteligente. Everything that touches the RPC lives
here so tests mock one module. Reads raise on failure: callers on money
paths must not turn an unreadable chain into "nothing to do"."""
from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.conf import settings
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode

from . import abi

logger = logging.getLogger(__name__)

WAD = 10 ** 18


class ChainError(RuntimeError):
    pass


def _addr(name: str) -> str:
    return (getattr(settings, name, '') or '').strip().lower()


def factory_address() -> str:
    return _addr('SMART_ACCOUNT_FACTORY_ADDRESS')


def fee_collector_address() -> str:
    return _addr('SMART_ACCOUNT_FEE_COLLECTOR_ADDRESS')


def enabled() -> bool:
    """The feature flag AND a configured factory: every task and mutation is
    a no-op / refusal otherwise."""
    return bool(getattr(settings, 'SMART_ACCOUNT_ENABLED', False)) and bool(factory_address())


def cusd_plus_address() -> str:
    return _addr('CUSD_PLUS_VAULT_ADDRESS')


def cusd_address() -> str:
    return _addr('CUSD_VAULT_ADDRESS')


def usdt_address() -> str:
    from cusd_plus import vault
    return (vault.usdt_address() or '').lower()


def confio_address() -> str:
    return _addr('BSC_CONFIO_TOKEN_ADDRESS')


def stock_router_address() -> str:
    return _addr('CUSD_PLUS_STOCK_ROUTER_ADDRESS')


def swap_router_address() -> str:
    return _addr('CRYPTO_SWAP_ROUTER_ADDRESS')


def rpc(method: str, params: list):
    from cusd_plus.tasks import _rpc
    return _rpc(method, params)


def eth_call(to: str, data: str) -> bytes:
    res = rpc('eth_call', [{'to': to, 'data': data}, 'latest'])
    if not isinstance(res, str) or not res.startswith('0x'):
        raise ChainError(f'bad eth_call result from {to}')
    return bytes.fromhex(res[2:])


def _view(to: str, signature: str, arg_types: list, args: list, out_types: list):
    data = '0x' + abi.selector(signature) + abi_encode(arg_types, args).hex()
    raw = eth_call(to, data)
    try:
        return abi_decode(out_types, raw)
    except Exception as exc:  # noqa: BLE001
        raise ChainError(f'{signature} returned undecodable data') from exc


def to_dt(seconds: int):
    return datetime.fromtimestamp(int(seconds), tz=dt_timezone.utc) if int(seconds) else None


def usd(wei: int) -> Decimal:
    return Decimal(int(wei)) / Decimal(WAD)


# ── factory ─────────────────────────────────────────────────────────────

def factory_fee_usd_wei(plan: str) -> int:
    return int(_view(factory_address(), 'feeUsd(uint8)', ['uint8'], [abi.PLAN_IDS[plan]], ['uint256'])[0])


def factory_scheduled_fee(plan: str) -> tuple[int, int]:
    fee, at = _view(factory_address(), 'scheduledFee(uint8)', ['uint8'], [abi.PLAN_IDS[plan]],
                    ['uint256', 'uint64'])
    return int(fee), int(at)


def _factory_view(name: str, *args):
    signature, arg_types, out_types = abi.FACTORY_VIEWS[name]
    return _view(factory_address(), signature, arg_types, list(args), out_types)[0]


def predict_address(owner: str) -> str:
    """factory.predictAddress(owner): accountOf(owner) while it is still the
    owner's (createAccount then reverts), generation 0 with no account, the
    next generation once the current one is inherited (spec 4.3)."""
    return _factory_view('predictAddress', owner).lower()


def predict_address_at(owner: str, generation: int) -> str:
    return _factory_view('predictAddressAt', owner, int(generation)).lower()


def generation_of(owner: str) -> int:
    """Generation of accountOf(owner): 0 for the first account."""
    return int(_factory_view('generationOf', owner))


def account_of(owner: str) -> str:
    """The owner's current account (zero when none). It may be one their
    beneficiary has since inherited, until they open a new one."""
    return _factory_view('accountOf', owner).lower()


def inheritance_enabled() -> bool:
    return bool(_view(factory_address(), 'inheritanceEnabled()', [], [], ['bool'])[0])


def window_allowed(seconds: int) -> bool:
    return bool(_view(factory_address(), 'allowedChallengeWindows(uint64)', ['uint64'], [int(seconds)], ['bool'])[0])


def relayer_paused() -> bool:
    return bool(_view(factory_address(), 'relayerPaused()', [], [], ['bool'])[0])


def designation_approved_until(account: str, beneficiary: str, window_seconds: int) -> int:
    """Expiry (unix seconds) of the factory approval for this exact
    designation; 0 = none."""
    return int(_view(factory_address(), 'designationApprovedUntil(address,bytes32)', ['address', 'bytes32'],
                     [account, abi.designation_key(beneficiary, window_seconds)], ['uint64'])[0])


def acceptance_approved_until(account: str, beneficiary: str) -> int:
    return int(_view(factory_address(), 'acceptanceApprovedUntil(address,address)', ['address', 'address'],
                     [account, beneficiary], ['uint64'])[0])


def card_spender_allowed(spender: str) -> bool:
    """factory.cardSpenderAllowed: isCardSpender(spender) && !cardPaused, the
    one read an account makes at Card rule creation and on every pull."""
    return bool(_factory_view('cardSpenderAllowed', spender))


def card_paused() -> bool:
    return bool(_factory_view('cardPaused'))


def confio_sale() -> tuple[str, str]:
    venue, ref = _view(factory_address(), 'confioSale()', [], [], ['address', 'address'])
    return venue.lower(), ref.lower()


# ── account ─────────────────────────────────────────────────────────────

_ACCOUNT_VIEWS = [
    ('owner', 'address'), ('inherited', 'bool'), ('plan', 'uint8'), ('nextPlan', 'uint8'),
    ('paidUntil', 'uint64'), ('cancelRequested', 'bool'), ('noticeStartedAt', 'uint64'),
    ('forcedSaleForPeriod', 'uint64'), ('feeUsd', 'uint256'), ('dollarsUsd', 'uint256'),
    ('pendingBeneficiary', 'address'), ('pendingChallengeWindow', 'uint64'),
    ('pendingBeneficiaryExpiresAt', 'uint64'), ('beneficiary', 'address'), ('challengeWindow', 'uint64'),
    ('claimStartedAt', 'uint64'), ('claimExecutableAt', 'uint64'), ('claimCooldownUntil', 'uint64'),
    ('nextRuleId', 'uint256'), ('confioSaleVenue', 'address'), ('confioSalePriceRef', 'address'),
    ('status', 'uint8'), ('billingStatus', 'uint8'), ('claimStatus', 'uint8'),
    # Bumped by every subscribe, never by a renewal (spec 4.4, invariant 22).
    ('subscriptionEpoch', 'uint64'),
]


def account_state(address: str) -> dict:
    """Every view of the account, read fresh. Raises if any read fails."""
    out = {}
    for name, type_ in _ACCOUNT_VIEWS:
        value = _view(address, f'{name}()', [], [], [type_])[0]
        out[name] = value.lower() if type_ == 'address' else value
    return out


def account_view(address: str, name: str):
    type_ = dict(_ACCOUNT_VIEWS)[name]
    value = _view(address, f'{name}()', [], [], [type_])[0]
    return value.lower() if type_ == 'address' else value


def account_control(address: str, *, with_claim: bool = False) -> dict:
    """{'owner', 'inherited'[, 'claimStartedAt']} read fresh: who controls the
    account on chain right now (spec 6.5). The RPC helper has no batch call,
    so these are sequential eth_calls. Raises if any read fails."""
    out = {'owner': account_view(address, 'owner'), 'inherited': bool(account_view(address, 'inherited'))}
    if with_claim:
        out['claimStartedAt'] = int(account_view(address, 'claimStartedAt'))
    return out


def _nonzero_address(value) -> bool:
    try:
        return bool(int(str(value or '0x0'), 16))
    except ValueError:
        return False


def confio_sale_of(address: str) -> tuple[str, str] | None:
    """(venue, price reference) the account latched for CONFIO forced
    sales (spec 5.5), or None while it has not latched. Raises if unreadable."""
    venue = account_view(address, 'confioSaleVenue')
    if not _nonzero_address(venue):
        return None
    ref = account_view(address, 'confioSalePriceRef')
    if not _nonzero_address(ref):
        raise ChainError(f'{address} latched a CONFIO venue without a price reference')
    return str(venue).lower(), str(ref).lower()


# ConfioSmartAccount.CONFIO_FEED_MAX_AGE: an older price the account refuses.
CONFIO_FEED_MAX_AGE = 26 * 3600


def feed_price_usd(feed: str, max_age: int) -> Decimal | None:
    """US dollars per whole token from a Chainlink-style feed
    (latestRoundData / decimals), or None when the answer is not positive or
    older than `max_age` (the contract would refuse a sale on it). Raises if
    unreadable."""
    import time
    _round, answer, _started, updated_at, _answered = _view(
        feed, 'latestRoundData()', [], [], ['uint80', 'int256', 'uint256', 'uint256', 'uint80'])
    decimals = int(_view(feed, 'decimals()', [], [], ['uint8'])[0])
    if int(answer) <= 0 or time.time() > int(updated_at) + int(max_age):
        return None
    return Decimal(int(answer)) / Decimal(10 ** decimals)


def account_rule(address: str, rule_id: int) -> dict:
    row = _view(address, 'rule(uint256)', ['uint256'], [int(rule_id)], [abi.RULE_ABI])[0]
    kind, frequency, active, token_in, token_out, payee, payout_ref, amount_usd, next_run_at, epoch = row
    # `active` is the contract's effective flag: false for a rule of an
    # earlier subscription epoch, whatever was stored.
    return {
        'kind': abi.RULE_KIND_KEYS[kind], 'frequency': abi.FREQUENCY_KEYS[frequency], 'active': bool(active),
        'token_in': token_in.lower(), 'token_out': token_out.lower(), 'payee': payee.lower(),
        'payout_ref': '0x' + bytes(payout_ref).hex(), 'amount_usd_wei': int(amount_usd),
        'next_run_at': int(next_run_at), 'epoch': int(epoch),
    }


def card_spent_usd_wei(address: str, rule_id: int) -> int:
    """cardSpentUsd(id): gross USD (18 decimals) taken in the period that
    starts at rule(id).nextRunAt. Stale (in effect zero) once that period
    ended; the contract resets it on the next pull."""
    signature, arg_types, out_types = abi.ACCOUNT_ARG_VIEWS['cardSpentUsd']
    return int(_view(address, signature, arg_types, [int(rule_id)], out_types)[0])


def has_code(address: str) -> bool:
    code = rpc('eth_getCode', [address, 'latest'])
    return bool(code) and code != '0x'


# ── tokens ──────────────────────────────────────────────────────────────

def balance_of(token: str, holder: str) -> int:
    return int(_view(token, 'balanceOf(address)', ['address'], [holder], ['uint256'])[0])


def p_plus_wad() -> int:
    from cusd_plus import vault
    value = int(vault.p_plus_wad(fresh=True))
    if value <= 0:
        raise ChainError('pPlus unreadable')
    return value


def conversion_fee_bps() -> int:
    from cusd_plus.crypto_policy import live_fee_bps
    return int(live_fee_bps())


# ── blocks and logs ─────────────────────────────────────────────────────

def head_block() -> int:
    return int(rpc('eth_blockNumber', []), 16)


def finalized_block() -> int:
    """Finalized head, or head minus the depth heuristic."""
    from cusd_plus.tasks import _finality_depth, _finalized_block_number
    finalized = _finalized_block_number()
    if finalized is not None:
        return int(finalized)
    return head_block() - _finality_depth()


def block_time(block_number: int):
    blk = rpc('eth_getBlockByNumber', [hex(int(block_number)), False])
    if not blk or not blk.get('timestamp'):
        raise ChainError(f'block {block_number} unreadable')
    return to_dt(int(blk['timestamp'], 16)), (blk.get('hash') or '').lower()


def get_logs(addresses: list, from_block: int, to_block: int) -> list:
    from cusd_plus.tasks import _get_logs_chunked
    if not addresses:
        return []
    logs = []
    # Providers cap the address list; 200 per request is well inside it.
    for i in range(0, len(addresses), 200):
        logs += _get_logs_chunked(from_block, to_block, None, address=addresses[i:i + 200])
    return logs


def receipt(tx_hash: str):
    return rpc('eth_getTransactionReceipt', [tx_hash])
