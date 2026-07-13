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
SEL_RANGES = _sel('ranges(uint256)')  # Ondo RWADynamicOracle rate schedule
SEL_YIELD_SHARE = _sel('CONFIO_YIELD_SHARE_BPS()')

RAY = 10 ** 27  # oracle dailyInterestRate scale


def vault_address() -> str | None:
    return getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', None)


def oracle_address() -> str | None:
    return getattr(settings, 'CUSD_PLUS_ORACLE_ADDRESS', None)


def _rpc(method: str, params: list, timeout: int = 12):
    url = getattr(settings, 'BSC_RPC_URL', 'https://bsc-dataseed.bnbchain.org')
    resp = requests.post(
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


def p_plus_wad() -> int:
    """Share price in USD, 1e18. Cached briefly — moves only on accrual."""
    addr = vault_address()
    if not addr:
        return 10 ** 18
    cached = cache.get('cusd_plus_pplus')
    if cached is None:
        cached = _call(addr, SEL_PPLUS) or 10 ** 18
        cache.set('cusd_plus_pplus', cached, 30)
    return cached


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
    """Drop the fresh-read cache so the next summary re-reads the chain
    (called when a conversion leg lands and the balance just changed)."""
    if user_bsc_address:
        cache.delete(f'cusd_plus_pos:{user_bsc_address.lower()}')


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
            'total_owed_usd': _call(addr, SEL_TOTAL_OWED) / 1e18,
            'backing_ratio_bps': _call(addr, SEL_BACKING),
            'usdy_daily_rate': usdy_daily_rate(),
            'gross_apy_pct': gross_apy_pct(),
            'net_apy_pct': net_apy_pct(),
        }
    except Exception as exc:  # noqa: BLE001
        return {'wired': True, 'address': addr, 'error': str(exc)}
