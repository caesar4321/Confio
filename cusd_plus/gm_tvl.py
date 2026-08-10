"""Cached aggregate market value of Ondo Stocks held by Confío traders.

The chain remains authoritative. A scheduled task finds addresses with a
confirmed Confío stock trade, scans every BSC Ondo token balance for those
addresses through Multicall3, and prices only the non-zero balances from the
shared Ondo market cache. GraphQL reads the finished cache value; it never
runs a portfolio-wide RPC scan in a request.

Why confirmed participants instead of every Account.bsc_address: most Confío
accounts have never touched a stock. Limiting the universe by the durable
sponsored-batch audit ledger keeps the work proportional to actual adoption
without making a database ledger the balance source of truth.
"""
import logging
import secrets
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from . import gm_api, gm_holdings, vault

logger = logging.getLogger(__name__)

TVL_CACHE_KEY = 'gm_confio_tvl_v1'
TVL_LAST_CACHE_KEY = 'gm_confio_tvl_last_v1'
TVL_LOCK_KEY = 'gm_confio_tvl_refresh_lock_v1'
TVL_TTL = 10 * 60
# Do not present a week-old financial aggregate as current when the UI has no
# stale badge. One hour tolerates several missed runs, then honestly shows "—".
TVL_LAST_TTL = 60 * 60
TVL_LOCK_TTL = 30 * 60


def _participant_addresses() -> list[str]:
    """Unique wallets whose Confío stock transaction reached finality."""
    from blockchain.models import SponsoredBatch

    return list(
        SponsoredBatch.objects.filter(
            kind__in=('stock_buy', 'stock_sell'),
            status='confirmed',
        )
        .exclude(user_bsc_address='')
        .values_list('user_bsc_address', flat=True)
        .order_by()
        .distinct()
    )


def _price_by_symbol() -> dict[str, Decimal]:
    prices = {}
    for item in gm_api.all_market():
        primary = item.get('primaryMarket') or {}
        symbol = str(primary.get('symbol') or '')
        price = primary.get('price')
        if symbol and price is not None:
            value = Decimal(str(price))
            if value.is_finite() and value > 0:
                prices[symbol] = value
    return prices


def _acquire_lock():
    """Return an owner-safe release callback, or None when already running."""
    if hasattr(cache, 'lock'):
        lock = cache.lock(TVL_LOCK_KEY, timeout=TVL_LOCK_TTL, blocking_timeout=0)
        if not lock.acquire(blocking=False):
            return None

        def release():
            try:
                lock.release()
            except Exception:  # expired locks must never delete a new owner's key
                logger.warning('Ondo Stocks TVL lock expired before release')

        return release

    # LocMemCache is process-local and has no distributed lock API. The token
    # still prevents an expired refresh from normally deleting its successor.
    token = secrets.token_urlsafe(24)
    if not cache.add(TVL_LOCK_KEY, token, TVL_LOCK_TTL):
        return None

    def release():
        if cache.get(TVL_LOCK_KEY) == token:
            cache.delete(TVL_LOCK_KEY)

    return release


def _publish(result: dict) -> dict:
    cache.set(TVL_CACHE_KEY, result, TVL_TTL)
    cache.set(TVL_LAST_CACHE_KEY, result, TVL_LAST_TTL)
    # statsSummary has its own short cache. Invalidate both the prior and
    # current versions so the new aggregate is visible on the next read.
    cache.delete('stats_summary_v12')
    cache.delete('stats_summary_v13')
    return result


def refresh() -> dict | None:
    """Recompute and cache TVL. None means another refresh owns the lock.

    Any participant scan failure aborts publication: a partial aggregate
    would look like money vanished. The prior last-known snapshot remains
    available to readers for one hour.
    """
    release_lock = _acquire_lock()
    if release_lock is None:
        return None
    try:
        participants = sorted({a.lower() for a in _participant_addresses() if a})
        if not participants:
            return _publish({
                'value_usd': 0.0,
                'accounts_scanned': 0,
                'positions': 0,
                'as_of_block': None,
                'updated_at': timezone.now().isoformat(),
            })

        token_registry = gm_holdings.registry()
        if token_registry is None:
            raise RuntimeError('GM token registry unavailable')

        prices = _price_by_symbol()
        if token_registry and not prices:
            raise RuntimeError('GM prices unavailable')

        # All balanceOf calls in this refresh observe one canonical height,
        # rather than drifting across blocks while participant scans run.
        block_hex = vault._rpc('eth_blockNumber', [])
        block_number = int(block_hex, 16)
        block_tag = hex(block_number)

        total = Decimal('0')
        positions = 0
        for address in participants:
            units_by_symbol = gm_holdings._scan(
                address,
                token_registry,
                block_tag=block_tag,
                require_complete=True,
            )
            for symbol, units in units_by_symbol.items():
                price = prices.get(symbol)
                if price is None:
                    # Do not publish a knowingly understated number. A held,
                    # halted or newly-listed asset still needs a real price.
                    raise RuntimeError(f'No live price for held GM asset {symbol}')
                total += Decimal(str(units)) * price
                positions += 1

        result = {
            'value_usd': float(total),
            'accounts_scanned': len(participants),
            'positions': positions,
            'as_of_block': block_number,
            'updated_at': timezone.now().isoformat(),
        }
        return _publish(result)
    except Exception:  # noqa: BLE001 — keep last-known rather than partial TVL
        logger.exception('Confío Ondo Stocks TVL refresh failed; keeping last-known value')
        return None
    finally:
        release_lock()


def snapshot() -> dict | None:
    """Fresh aggregate, or last-known when the scheduled refresh is down."""
    return cache.get(TVL_CACHE_KEY) or cache.get(TVL_LAST_CACHE_KEY)


def value_usd() -> float | None:
    current = snapshot()
    return float(current['value_usd']) if current is not None else None
