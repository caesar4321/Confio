"""
Read-only view of the cUSD+ vault on BSC (chain-first: the chain is the
truth). Thin eth_call helpers over the deployed CusdPlusVault — the same
pattern as gm_api.py, no web3 dependency.

Nothing here signs or moves funds; it reads the user's position and the
vault's public health so the Ahorros surfaces show real numbers.
"""
import logging
import time

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Selectors computed from signatures once (no hand-copy errors).
from eth_utils import keccak  # noqa: E402


def _sel(sig: str) -> str:
    return '0x' + keccak(text=sig)[:4].hex()


SEL_BALANCE_OF = _sel('balanceOf(address)')
SEL_PPLUS = _sel('pPlus()')
SEL_TOTAL_SUPPLY = _sel('totalSupply()')
SEL_BACKING = _sel('backingRatioBps()')
SEL_TOTAL_OWED = _sel('totalOwedUsd()')
SEL_SURPLUS_USDY = _sel('surplusUsdy(uint256)')
SEL_RANGES = _sel('ranges(uint256)')  # Ondo RWADynamicOracle rate schedule
SEL_GET_PRICE = _sel('getPrice()')     # oracle: USD per USDY, 1e18
SEL_YIELD_SHARE = _sel('CONFIO_YIELD_SHARE_BPS()')

RAY = 10 ** 27  # oracle dailyInterestRate scale


def vault_address() -> str | None:
    return getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', None)


def oracle_address() -> str | None:
    return getattr(settings, 'CUSD_PLUS_ORACLE_ADDRESS', None)


def _rpc(method: str, params: list, timeout: int = 12):
    # Same pooled, keep-alive session as tasks._rpc (see the CONNECTION REUSE
    # note there). Deliberately keeps this module's OWN single-URL setting
    # rather than borrowing the rotation pool — only the transport is shared.
    from .tasks import _rpc_session

    url = getattr(settings, 'BSC_RPC_URL', 'https://bsc-dataseed.bnbchain.org')
    resp = _rpc_session(url).post(
        url, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params},
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    if 'error' in body:
        raise RuntimeError(f"bsc rpc {method}: {body['error']}")
    return body['result']


def _call(to: str, data: str) -> int:
    res = _rpc('eth_call', [{'to': to, 'data': data}, 'latest'])
    return int(res, 16) if res and res != '0x' else 0


def p_plus_wad(fresh: bool = False) -> int:
    """Share price in USD, 1e18. Cached briefly — moves only on accrual.

    fresh=True skips the cache: authorizing a withdrawal must not price the
    position off a 30s-old read (re-audit [P2] #9).
    """
    addr = vault_address()
    if not addr:
        return 10 ** 18
    cached = None if fresh else cache.get('cusd_plus_pplus')
    if cached is None:
        cached = _call(addr, SEL_PPLUS) or 10 ** 18
        cache.set('cusd_plus_pplus', cached, 30)
    return cached


def total_supply_shares_raw() -> int:
    """Sigma of every holder's cUSD+ shares, 18 decimals. Uncached and
    raising: the callers that want a supply figure (ops metrics) must be
    able to tell a read failure from an empty vault."""
    addr = vault_address()
    if not addr:
        return 0
    return _call(addr, SEL_TOTAL_SUPPLY)


def total_owed_usd_wad() -> int:
    """What the vault owes holders in USD, 1e18, as the contract computes
    it. Uncached and raising — see total_supply_shares_raw."""
    addr = vault_address()
    if not addr:
        return 0
    return _call(addr, SEL_TOTAL_OWED)


def backing_ratio_bps() -> int:
    """reserve / owed in bps; 10_000 is exactly collateralised. Uncached
    and raising — see total_supply_shares_raw."""
    addr = vault_address()
    if not addr:
        return 0
    return _call(addr, SEL_BACKING)


def uncollected_yield_earnings_usd_wad() -> int:
    """Confío's currently withdrawable vault surplus, valued in USD (1e18).

    The vault withholds Confío's yield share as USDY surplus rather than
    minting separate fee tokens. Use lastOraclePrice, the guard-approved
    accounting snapshot used by collectFees(), so pending holder accrual is
    never misreported as Confío revenue. This is the uncollected balance, not
    lifetime earnings: collectFees() legitimately reduces it.
    """
    addr = vault_address()
    if not addr:
        return 0
    price = last_oracle_price_wad(fresh=True)
    data = SEL_SURPLUS_USDY + hex(price)[2:].rjust(64, '0')
    surplus_usdy = _call(addr, data)
    return surplus_usdy * price // (10 ** 18)


def last_oracle_price_wad(fresh: bool = False) -> int:
    """The vault's guard-validated USDY price snapshot, 1e18.

    Needed to predict a redeem's USDT output exactly: redeemToUsdt floors
    TWICE (shares -> USDY at this price, then USDY -> USDT), so
    shares * pPlus / 1e18 is an OVER-estimate and cannot be used to decide
    whether Ondo's 1.00 USDT floor is cleared.

    fresh=True skips the cache — see p_plus_wad.
    """
    addr = vault_address()
    if not addr:
        return 10 ** 18
    cached = None if fresh else cache.get('cusd_plus_oracle_p')
    if cached is None:
        cached = _call(addr, _sel('lastOraclePrice()')) or 10 ** 18
        cache.set('cusd_plus_oracle_p', cached, 30)
    return cached


def redeem_blocked_reason() -> str | None:
    """Why a redeem would revert right now, or None if the exit is open.

    `redeemToUsdt` is `whenNotPaused` and refuses while the oracle guard is
    tripped. Authorizing an order without checking either creates a provider
    order the client's batch cannot possibly execute (re-audit [P2] #9).
    """
    addr = vault_address()
    if not addr:
        return None
    try:
        if _call(addr, _sel('oracleGuardTripped()')):
            return 'oracle_guard_tripped'
        if _call(addr, _sel('paused()')):
            return 'vault_paused'
    except Exception:  # noqa: BLE001
        # FAIL CLOSED. This is only consulted when a redeem is actually
        # required, and "we could not read whether the exit is open" is not
        # a reason to promise a provider an order we may be unable to fund
        # (round 3 [P2] #8). The user's money stays in their own wallet and
        # the raw-USDT exit is unaffected — it never reaches this check.
        logger.warning('cUSD+ redeem-state read failed', exc_info=True)
        return 'redeem_state_unreadable'
    return None


def reserved_usdt_wei(user, bsc_address: str) -> int:
    """Raw USDT the wallet holds but has already committed elsewhere.

    Nothing on BSC escrows these — a prepared send is a database row and an
    off-ramp order is a promise to a provider — so the only thing standing
    between them and an auto-mint is this subtraction. Sweeping the whole
    balance moved funds out from under both (audit 2026-08-01).

    Counted:
      - PENDING send rows whose call batch spends WALLET USDT. A send funded
        from the VAULT (send_redeem / send_cusd_plus) reserves nothing here.
      - in-flight off-ramp orders on the savings rail, which transfer raw
        USDT to the provider's deposit address.
      - in-flight savings sagas: their delivered USDT belongs to that mint,
        not to a deposit sweep.
    """
    from decimal import Decimal

    from django.db.models import Sum

    total = Decimal(0)
    addr = (bsc_address or '').lower()
    if not addr:
        return 0

    try:
        from send.models import SendTransaction
        pending = SendTransaction.objects.filter(
            sender_user=user, status='PENDING', token_type='USDT',
        ).exclude(bsc_calls_json='')
        # No slice: a capped scan silently stopped reserving the 101st pending
        # send, and that USDT then read back as sweepable (Codex audit
        # 2026-08-02, P2). Row-wise is required here because the kind lives
        # inside the JSON blob.
        for row in pending.only('amount', 'bsc_calls_json').iterator():
            import json
            try:
                if json.loads(row.bsc_calls_json or '{}').get('kind') == 'send_usdt':
                    total += Decimal(str(row.amount))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001 — a reservation we cannot read must not
        logger.exception('reserved usdt: pending sends unreadable')
        raise      # ...silently become spendable

    try:
        from ramps.models import RampTransaction
        orders_total = RampTransaction.objects.filter(
            direction='off_ramp', destination='cusd_plus',
            status__in=('PENDING', 'PROCESSING'), actor_address__iexact=bsc_address,
        ).aggregate(s=Sum('crypto_amount_estimated'))['s']
        total += Decimal(str(orders_total or 0))
    except Exception:  # noqa: BLE001
        logger.exception('reserved usdt: ramp orders unreadable')
        raise

    try:
        from conversion.models import Conversion
        sagas_total = Conversion.objects.filter(
            conversion_type='to_savings', user_bsc_address__iexact=bsc_address,
            status__in=Conversion.IN_FLIGHT_STATUSES, is_deleted=False,
        ).aggregate(s=Sum('to_amount'))['s']
        total += Decimal(str(sagas_total or 0))
    except Exception:  # noqa: BLE001
        logger.exception('reserved usdt: in-flight sagas unreadable')
        raise

    try:
        # Prepared-but-unsigned BSC presale buys: the batch spends wallet USDT
        # (plus a savings redeem for any shortfall), so an auto-mint — or a
        # second prepare — must not spend it first. Reserving the full amount
        # slightly over-reserves a redeem-funded buy; that is the safe
        # direction, and abandon_stale_bsc_purchases releases it after 24h.
        from django.db.models import Sum
        from presale.bsc_flow import BSC_FUNDING_SOURCES
        from presale.models import PresalePurchase
        # Aggregate, never slice: a [:50] cap silently stopped reserving the
        # 51st prepared purchase, so USDT already promised to it read back as
        # sweepable and could be minted away (Codex audit 2026-08-02, P2).
        pending_buys = PresalePurchase.objects.filter(
            user=user, status='processing', transaction_hash__isnull=True,
            funding_source__in=BSC_FUNDING_SOURCES,
        ).aggregate(s=Sum('cusd_amount'))['s']
        total += Decimal(str(pending_buys or 0))
    except Exception:  # noqa: BLE001
        logger.exception('reserved usdt: in-flight presale buys unreadable')
        raise

    return int(total * (10 ** 18))


def sweepable_usdt_wei(user, bsc_address: str) -> int:
    """USDT that may be auto-minted into savings: a FRESH balance minus
    everything already committed. Never negative.

    fresh=True on purpose — the cached balance is display-grade (30s TTL with
    a last-known fallback), and minting a stale figure either misses a deposit
    or reverts for insufficient funds.
    """
    balance = usdt_balance_raw(bsc_address, fresh=True)
    return max(0, balance - reserved_usdt_wei(user, bsc_address))


def redeem_usdt_out(shares: int, pps_wad: int, oracle_p_wad: int) -> int:
    """USDT a redeemToUsdt(shares) would actually deliver.

    Mirrors CusdPlusVault.redeemToUsdt + _imRedeem exactly:
        usdyOut = mulDiv(shares, pPlus, p)   # floor
        usdtOut = usdyOut * p / 1e18         # floor
    """
    if oracle_p_wad <= 0:
        return 0
    usdy_out = (shares * pps_wad) // oracle_p_wad
    return (usdy_out * oracle_p_wad) // (10 ** 18)


def withdrawable_usdt_wei(user_bsc_address: str) -> int:
    """What an address can ACTUALLY move out right now, in USDT wei.

    raw wallet USDT + the true redeem output of the whole position. Use this
    to authorize a withdrawal; `position_usd` is a DISPLAY figure and is
    wrong here twice over (audit 2026-08-03 [P2] #11):

      - it is cached (30s, and up to 7 days of last-known on RPC failure), so
        an order could be created against shares that were already spent;
      - shares x pPlus OVER-states the exit, because redeemToUsdt floors
        twice on the way out (see redeem_usdt_out).

    Every read is FRESH — balance, shares AND both prices — and failures
    RAISE: refusing to quote is correct when the chain is unreadable, whereas
    a stale figure creates a provider order that can never be funded.

    Callers that authorize a withdrawal should ALSO consult
    redeem_blocked_reason(); a position is not withdrawable while the vault is
    paused or the oracle guard is tripped, however much it is worth.
    """
    if not user_bsc_address:
        return 0
    addr = vault_address()
    raw = usdt_balance_raw(user_bsc_address, fresh=True)
    if not addr:
        return raw
    shares = erc20_balance_raw(addr, user_bsc_address.lower())
    if shares <= 0:
        return raw
    return raw + redeem_usdt_out(
        shares, p_plus_wad(fresh=True), last_oracle_price_wad(fresh=True))


def confio_yield_share_bps() -> int:
    """The vault's immutable yield share, read from the chain so the
    displayed rate can never drift from what the contract actually keeps.
    Falls back to the locked 1500 (15%) if the read fails."""
    cached = cache.get('cusd_plus_yield_share_bps')
    if cached is not None:
        return cached
    addr = vault_address()
    if addr:
        try:
            bps = _call(addr, SEL_YIELD_SHARE)
            if 0 < bps < 10_000:
                cache.set('cusd_plus_yield_share_bps', bps, 24 * 3600)
                return bps
        except Exception:  # noqa: BLE001 — fall through to the locked value
            logger.warning('cUSD+ yield share read failed', exc_info=True)
    return 1500


def usdy_daily_rate() -> float:
    """USDY's forward daily accrual rate from the oracle's on-chain rate
    schedule: dailyInterestRate (RAY) of the ranges[] entry covering now.

    Returns 0.0 when now falls outside every posted range — the oracle
    price is genuinely flat there until Ondo posts the next range, so 0
    is the honest forward rate, not an error."""
    oracle = oracle_address()
    if not oracle:
        return 0.0
    now = int(time.time())
    current = None
    # No length getter on the deployed oracle: walk ranges(i) until the
    # index reverts. Ondo posts roughly one range a month, so the walk is
    # a handful of calls; cap it against a pathological node.
    for i in range(500):
        try:
            res = _rpc('eth_call', [
                {'to': oracle, 'data': SEL_RANGES + hex(i)[2:].rjust(64, '0')},
                'latest',
            ])
        except RuntimeError as exc:
            if 'revert' in str(exc).lower():
                break  # out-of-bounds index reverts — that's the length probe
            raise  # real node fault: let the caller serve last-known, not 0%
        if not res or res == '0x' or len(res) < 2 + 3 * 64:
            break
        words = res[2:]
        start = int(words[0:64], 16)
        end = int(words[64:128], 16)
        daily_ir = int(words[128:192], 16)
        if start <= now < end:
            current = daily_ir
    if current is None:
        return 0.0
    return current / RAY - 1.0


# APY moves only when Ondo posts a new range (~monthly); an hour of cache
# keeps summary queries free while still tracking rate changes same-day.
APY_TTL = 3600
APY_LAST_TTL = 7 * 24 * 3600


def apy_split() -> tuple[float, float]:
    """(gross, net) APY in %, derived live from the chain — never hardcoded
    (locked design rule; rates float with US Treasuries).

    Gross compounds the oracle's daily rate over a year. Net mirrors
    accrue() exactly: the oracle price steps once per UTC day by
    dailyInterestRate, and the vault keeps (1 − CONFIO_YIELD_SHARE) of
    each step, so a year of holding compounds to (1 + kept·daily)^365.

    On RPC failure serves the last good value, then the settings fallback
    (default 0.0 — an honest 0% beats a made-up rate)."""
    fallback = (0.0, getattr(settings, 'CUSD_PLUS_NET_APY_PCT', 0.0))
    if not oracle_address():
        return fallback
    cached = cache.get('cusd_plus_apy')
    if cached is not None:
        return cached
    try:
        daily = usdy_daily_rate()
        kept = 1.0 - confio_yield_share_bps() / 10_000.0
        gross = ((1.0 + daily) ** 365 - 1.0) * 100.0
        net = ((1.0 + daily * kept) ** 365 - 1.0) * 100.0
    except Exception:  # noqa: BLE001 — read failure must not break the screen
        logger.warning('cUSD+ APY read failed', exc_info=True)
        last = cache.get('cusd_plus_apy_last')
        return last if last is not None else fallback
    cache.set('cusd_plus_apy', (gross, net), APY_TTL)
    cache.set('cusd_plus_apy_last', (gross, net), APY_LAST_TTL)
    return gross, net


def gross_apy_pct() -> float:
    """USDY gross APY, % — the Treasuries side of the transparency split."""
    return apy_split()[0]


def net_apy_pct() -> float:
    """User-facing net APY, % — what the holder actually compounds at."""
    return apy_split()[1]


def erc20_balance_raw(token_address: str, holder: str) -> int:
    """Raw balanceOf(holder) on any BSC ERC-20 (vault shares, GM tokens…)."""
    return _call(
        token_address,
        SEL_BALANCE_OF + holder.lower().replace('0x', '').rjust(64, '0'),
    )


# Fresh-read window per address; within it, summary queries cost zero RPCs.
POSITION_TTL = 30
# How long a last-known value may stand in when the node is unreachable.
POSITION_LAST_TTL = 7 * 24 * 3600


def invalidate_position(user_bsc_address: str) -> None:
    """Drop the fresh-read caches so the next summary re-reads the chain
    (called when a conversion leg lands and the balances just changed —
    a mint moves BOTH the vault position and the wallet USDT)."""
    if user_bsc_address:
        key = user_bsc_address.lower()
        cache.delete(f'cusd_plus_pos:{key}')
        cache.delete(f'cusd_plus_usdt:{key}')


def position_usd(user_bsc_address: str) -> float:
    """USD value of an address's cUSD+ position = shares × pPlus.
    Returns 0.0 if the vault isn't wired or the address holds nothing.

    Cached POSITION_TTL per address. On RPC failure falls back to the last
    successfully read value — a flaky node must degrade to a slightly stale
    savings balance, never to a false $0."""
    addr = vault_address()
    if not addr or not user_bsc_address:
        return 0.0
    key = user_bsc_address.lower()
    cached = cache.get(f'cusd_plus_pos:{key}')
    if cached is not None:
        return cached
    try:
        shares = erc20_balance_raw(addr, key)
        value = 0.0 if shares == 0 else (shares * p_plus_wad()) / (10 ** 36)
    except Exception:  # noqa: BLE001 — read failure must not break the screen
        logger.warning('cUSD+ position read failed for %s', user_bsc_address, exc_info=True)
        last = cache.get(f'cusd_plus_pos_last:{key}')
        return last if last is not None else 0.0
    cache.set(f'cusd_plus_pos:{key}', value, POSITION_TTL)
    cache.set(f'cusd_plus_pos_last:{key}', value, POSITION_LAST_TTL)
    return value


# Reserve stat cadence: this is a platform-wide marketing number, not a
# per-user balance — a minute of staleness is invisible, a hammered node
# is not.
RESERVE_TTL = 60
RESERVE_LAST_TTL = 7 * 24 * 3600


def usdy_address() -> str:
    """Ondo USDY on BNB (18 decimals) — the vault's backing asset."""
    return getattr(
        settings, 'CUSD_PLUS_USDY_BSC',
        '0x608593d17A2decBbc4399e4185bE4922F97eD32E',
    )


def usdy_reserve_usd() -> float:
    """USD value of the USDY the vault actually holds — the cUSD+ side of
    the public reserve stat (the cUSD side is USDC, 1:1).

    USDY is ACCUMULATING: the token count stays put while its price rises,
    so a token count would understate the reserve and sit visually frozen.
    We therefore publish balance x oracle price, the same unit as the USDC
    figure and the same unit as what holders are owed. It grows with yield
    even absent deposits — correct, because the liability (Sigma cUSD+
    value) grows in lockstep; the vault's own invariant keeps reserve >=
    owed at every state change.

    Cached RESERVE_TTL, last-known fallback: an unreachable node must never
    publish a false 0 reserve."""
    vault = vault_address()
    oracle = oracle_address()
    if not vault or not oracle:
        return 0.0
    cached = cache.get('cusd_plus_reserve_usd')
    if cached is not None:
        return cached
    try:
        held = erc20_balance_raw(usdy_address(), vault)
        value = 0.0 if held == 0 else (held * _call(oracle, SEL_GET_PRICE)) / (10 ** 36)
    except Exception:  # noqa: BLE001 — a flaky node must not zero the stat
        logger.warning('cUSD+ reserve read failed', exc_info=True)
        last = cache.get('cusd_plus_reserve_usd_last')
        return last if last is not None else 0.0
    cache.set('cusd_plus_reserve_usd', value, RESERVE_TTL)
    cache.set('cusd_plus_reserve_usd_last', value, RESERVE_LAST_TTL)
    return value


def usdt_address() -> str:
    """Binance-Peg BSC-USD (18 decimals) — the ramp delivery + exit asset."""
    return getattr(
        settings, 'CUSD_PLUS_USDT_BSC',
        '0x55d398326f99059fF775485246999027B3197955',
    )


def usdt_balance_raw(user_bsc_address: str, fresh: bool = False) -> int:
    """Wei of raw wallet USDT (pre-mint, or held as "Confío Dollar" by
    geo-ineligible users). Cached POSITION_TTL like position_usd, with a
    last-known fallback — a flaky node degrades to slightly stale, never to
    a false 0 (which would make just-landed money vanish from the screen).
    fresh=True bypasses the cache for exactness-sensitive callers (off-ramp
    sufficiency); it raises on RPC failure instead of falling back."""
    if not user_bsc_address:
        return 0
    key = user_bsc_address.lower()
    if fresh:
        return erc20_balance_raw(usdt_address(), key)
    cached = cache.get(f'cusd_plus_usdt:{key}')
    if cached is not None:
        return cached
    try:
        raw = erc20_balance_raw(usdt_address(), key)
    except Exception:  # noqa: BLE001 — read failure must not break the screen
        logger.warning('USDT balance read failed for %s', user_bsc_address, exc_info=True)
        last = cache.get(f'cusd_plus_usdt_last:{key}')
        return last if last is not None else 0
    cache.set(f'cusd_plus_usdt:{key}', raw, POSITION_TTL)
    cache.set(f'cusd_plus_usdt_last:{key}', raw, POSITION_LAST_TTL)
    return raw


def usdt_balance_usd(user_bsc_address: str) -> float:
    """USD value of raw wallet USDT, display-grade (cached read)."""
    return usdt_balance_raw(user_bsc_address) / (10 ** 18)


def health() -> dict:
    """Public vault health for admin / verify surfaces."""
    addr = vault_address()
    if not addr:
        return {'wired': False}
    try:
        return {
            'wired': True,
            'address': addr,
            'p_plus': p_plus_wad() / 1e18,
            'total_owed_usd': total_owed_usd_wad() / 1e18,
            'backing_ratio_bps': backing_ratio_bps(),
            'usdy_daily_rate': usdy_daily_rate(),
            'gross_apy_pct': gross_apy_pct(),
            'net_apy_pct': net_apy_pct(),
        }
    except Exception as exc:  # noqa: BLE001
        return {'wired': True, 'address': addr, 'error': str(exc)}
