"""Platform-level cUSD+ metrics for admin / ops surfaces.

The twin of `blockchain/cusd_metrics.py`, which does the same job for the
Algorand cUSD rail: one cached call that returns supply, collateral and
rate for the whole rail, so a dashboard does not have to know how many
`eth_call`s that takes.

The BSC vault is the source of truth. Unlike the cUSD module there is NO
database fallback for supply: cUSD+ shares are minted by the vault against
USDY the vault holds, and the conversion table only records the sagas that
went through Confío — an external USDT deposit that a holder minted with
never produced a `to_savings` row we could sum. Summing it anyway would
publish a confidently wrong supply. When the chain is unreadable the
metrics come back with `source='unavailable'` and None values, and callers
render "unavailable" rather than a zero that reads as "the vault is empty".
"""
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.core.cache import cache
from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.functions import Cast
from django.utils import timezone

logger = logging.getLogger(__name__)

WAD = Decimal(10 ** 18)


@dataclass(frozen=True)
class CUSDPlusPlatformMetrics:
    """Live vault state. Every on-chain field is Optional: None means "we
    could not read it", which is a different fact from 0."""

    wired: bool
    address: Optional[str]
    # Sigma of every holder's shares, in share units (cUSD+ is 18-decimal).
    total_shares: Optional[Decimal]
    # Share price in USD (1e18 on chain). Shares x p_plus = holder liability.
    p_plus: Optional[Decimal]
    # What the vault owes holders in USD, as the contract computes it.
    total_owed_usd: Optional[Decimal]
    # USD value of the USDY the vault actually holds (balance x oracle price).
    usdy_reserve_usd: Optional[Decimal]
    # reserve / owed, in bps. 10_000 = exactly collateralised.
    backing_ratio_bps: Optional[int]
    gross_apy_pct: Optional[float]
    net_apy_pct: Optional[float]
    # None when the exit is open; a reason string when a redeem would revert.
    redeem_blocked_reason: Optional[str]
    source: str
    as_of: object

    @property
    def circulating_cusd_plus(self) -> Optional[Decimal]:
        """Holder-facing supply in USD — the cUSD+ analogue of
        `circulating_cusd`. Prefers the contract's own `totalOwedUsd` and
        falls back to shares x price only if that read is the one missing."""
        if self.total_owed_usd is not None:
            return self.total_owed_usd
        if self.total_shares is not None and self.p_plus is not None:
            return self.total_shares * self.p_plus
        return None

    @property
    def is_undercollateralised(self) -> bool:
        """True only when we READ a shortfall. An unreadable ratio is not a
        shortfall — it must not light the alarm, and must not clear it."""
        return self.backing_ratio_bps is not None and self.backing_ratio_bps < 10_000


def _unavailable(wired: bool, address: Optional[str], source: str) -> CUSDPlusPlatformMetrics:
    return CUSDPlusPlatformMetrics(
        wired=wired,
        address=address,
        total_shares=None,
        p_plus=None,
        total_owed_usd=None,
        usdy_reserve_usd=None,
        backing_ratio_bps=None,
        gross_apy_pct=None,
        net_apy_pct=None,
        redeem_blocked_reason=None,
        source=source,
        as_of=timezone.now(),
    )


def get_cusd_plus_platform_metrics(*, use_cache: bool = True) -> CUSDPlusPlatformMetrics:
    """Read the live cUSD+ vault. Never raises — an ops dashboard that 500s
    because a BSC node blipped is worse than one that says "unavailable"."""
    cache_key = "cusd_plus_platform_metrics:v1"
    if use_cache:
        cached = cache.get(cache_key)
        if cached:
            return cached

    from . import vault

    address = vault.vault_address()
    if not address:
        # Not a failure: the rail is simply not wired in this environment.
        return _unavailable(wired=False, address=None, source="unconfigured")

    try:
        total_shares = Decimal(vault.total_supply_shares_raw()) / WAD
        p_plus = Decimal(vault.p_plus_wad()) / WAD
        total_owed_usd = Decimal(vault.total_owed_usd_wad()) / WAD
        backing_ratio_bps = vault.backing_ratio_bps()
    except Exception as exc:  # noqa: BLE001 — surface as "unavailable", not 0
        logger.warning("Unable to read cUSD+ vault state from BSC: %s", exc)
        return _unavailable(wired=True, address=address, source="unavailable")

    # These three have their own last-known caches inside vault.py and
    # degrade to a stale-but-real value rather than raising, so a failure
    # here should not discard the supply figures we just read.
    try:
        usdy_reserve_usd = Decimal(str(vault.usdy_reserve_usd()))
    except Exception:  # noqa: BLE001
        logger.warning("cUSD+ reserve read failed", exc_info=True)
        usdy_reserve_usd = None
    try:
        gross, net = vault.apy_split()
    except Exception:  # noqa: BLE001
        logger.warning("cUSD+ APY read failed", exc_info=True)
        gross, net = None, None

    metrics = CUSDPlusPlatformMetrics(
        wired=True,
        address=address,
        total_shares=total_shares,
        p_plus=p_plus,
        total_owed_usd=total_owed_usd,
        usdy_reserve_usd=usdy_reserve_usd,
        backing_ratio_bps=backing_ratio_bps,
        gross_apy_pct=gross,
        net_apy_pct=net,
        redeem_blocked_reason=vault.redeem_blocked_reason(),
        source="bsc",
        as_of=timezone.now(),
    )

    if use_cache:
        cache.set(cache_key, metrics, 30)
    return metrics


def get_savings_saga_stats(*, since=None) -> dict:
    """Database-side health of the cUSD+ savings rail.

    Deliberately separate from the chain read above: these are OUR rows
    (what users asked us to do and how far it got), not the vault's state.
    A saga that halts still leaves value at a user-owned address, so the
    counters below are ops attention lists, not loss figures.
    """
    from conversion.models import Conversion

    rows = Conversion.objects.filter(
        conversion_type__in=Conversion.SAVINGS_TYPES,
        is_deleted=False,
    )
    windowed = rows
    if since is not None:
        # Settled value is dated by completion; a saga opened last month and
        # completed today belongs to today's inflow, exactly as the Algorand
        # conversion volumes are dated.
        windowed = rows.filter(
            Q(completed_at__gte=since) | Q(completed_at__isnull=True, created_at__gte=since)
        )

    volume = windowed.filter(status='COMPLETED').aggregate(
        to_savings=Sum('from_amount', filter=Q(conversion_type='to_savings')),
        from_savings=Sum('from_amount', filter=Q(conversion_type='from_savings')),
    )
    to_savings_volume = volume['to_savings'] or Decimal('0')
    from_savings_volume = volume['from_savings'] or Decimal('0')

    by_source = list(
        windowed.filter(
            conversion_type='to_savings', status='COMPLETED',
        ).values('source').annotate(
            count=Count('id'), volume=Sum('from_amount'),
        ).order_by('-volume')
    )
    source_labels = dict(Conversion.SOURCES)
    for row in by_source:
        row['label'] = source_labels.get(row['source'], row['source'] or 'unknown')

    # Attention counters are NOT windowed: a saga stuck since last month is
    # more urgent than one stuck today, and windowing would hide it.
    attention = rows.aggregate(
        in_flight=Count('id', filter=Q(status__in=Conversion.IN_FLIGHT_STATUSES)),
        created=Count('id', filter=Q(status='CREATED')),
        src_committed=Count('id', filter=Q(status='SRC_COMMITTED')),
        stuck=Count('id', filter=Q(status='STUCK')),
        dest_arrived=Count('id', filter=Q(status='DEST_ARRIVED')),
        delivered_usdt=Count('id', filter=Q(status='DELIVERED_USDT')),
        abandoned=Count('id', filter=Q(status='ABANDONED')),
        completed=Count('id', filter=Q(status='COMPLETED')),
    )

    return {
        'to_savings_volume': to_savings_volume,
        'from_savings_volume': from_savings_volume,
        'net_savings_inflow': to_savings_volume - from_savings_volume,
        'by_source': by_source,
        **attention,
        'total': rows.count(),
    }


# Statuses a SponsoredBatch row can hold that mean "a user-facing BSC
# operation did not do what the user asked". Kept beside the model's
# STATUS_CHOICES rather than inlined in a template so the dashboard cannot
# silently drift when a status is added.
SPONSOR_FAILURE_STATUSES = ('reverted', 'noop_failed', 'dropped', 'reorged')


def get_sponsorship_stats(*, since=None) -> dict:
    """EIP-7702 sponsorship health — the rail every user-facing BSC action
    rides (send, pay, payroll, invite, presale buy, subscribe, redeem).

    `signed`/`sent` rows are only unresolved, not failed: they mean the
    database has not seen an outcome yet. They are reported separately from
    the failure statuses for exactly that reason.
    """
    from blockchain.models import SponsoredBatch

    rows = SponsoredBatch.objects.all()
    windowed = rows if since is None else rows.filter(created_at__gte=since)

    by_status = {
        row['status']: row['count']
        for row in windowed.values('status').annotate(count=Count('id'))
    }
    by_kind = list(
        windowed.values('kind').annotate(count=Count('id')).order_by('-count')[:12]
    )

    return {
        'total': windowed.count(),
        'by_status': by_status,
        'by_kind': by_kind,
        'confirmed': by_status.get('confirmed', 0),
        'unresolved': by_status.get('signed', 0) + by_status.get('sent', 0),
        'failed': sum(by_status.get(s, 0) for s in SPONSOR_FAILURE_STATUSES),
        'reverted': by_status.get('reverted', 0),
        'noop_failed': by_status.get('noop_failed', 0),
        'dropped': by_status.get('dropped', 0),
        'reorged': by_status.get('reorged', 0),
        # Not windowed: an unresolved batch from last week is the one that
        # needs a human, and a 24h window would hide it.
        'unresolved_all_time': rows.filter(status__in=('signed', 'sent')).count(),
        'failed_all_time': rows.filter(status__in=SPONSOR_FAILURE_STATUSES).count(),
    }


def get_stock_trade_stats(*, since=None) -> dict:
    """Database-backed Ondo Stocks activity and settlement metrics.

    ``SponsoredBatch`` is the attempt/finality ledger. The linked unified row
    is the exact event-backed USD value shown in account history, so volumes
    intentionally come from that row rather than calldata estimates. A count
    of confirmed batches without a unified row is surfaced as an integrity
    alert instead of silently reducing volume.
    """
    from blockchain.models import SponsoredBatch
    from users.models_unified import UnifiedTransactionTable

    rows = SponsoredBatch.objects.filter(kind__in=('stock_buy', 'stock_sell'))
    windowed = rows if since is None else rows.filter(created_at__gte=since)
    by_status = {
        row['status']: row['count']
        for row in windowed.values('status').annotate(count=Count('id'))
    }

    confirmed = windowed.filter(status='confirmed')
    settlements = UnifiedTransactionTable.objects.filter(
        sponsored_batch__in=confirmed,
        deleted_at__isnull=True,
        status='CONFIRMED',
        amount_denomination='USD_VALUE',
    )
    amount = Cast(
        'amount',
        output_field=DecimalField(max_digits=38, decimal_places=18),
    )
    volumes = settlements.aggregate(
        buy=Sum(amount, filter=Q(sponsored_batch__kind='stock_buy')),
        sell=Sum(amount, filter=Q(sponsored_batch__kind='stock_sell')),
    )
    buy_volume = volumes['buy'] or Decimal('0')
    sell_volume = volumes['sell'] or Decimal('0')
    confirmed_count = confirmed.count()
    settlement_count = settlements.count()

    return {
        'total': windowed.count(),
        'buy_attempts': windowed.filter(kind='stock_buy').count(),
        'sell_attempts': windowed.filter(kind='stock_sell').count(),
        'confirmed': confirmed_count,
        'confirmed_buys': confirmed.filter(kind='stock_buy').count(),
        'confirmed_sells': confirmed.filter(kind='stock_sell').count(),
        'unique_traders': confirmed.values('user_id').distinct().count(),
        'buy_volume': buy_volume,
        'sell_volume': sell_volume,
        'total_volume': buy_volume + sell_volume,
        'failed': sum(by_status.get(status, 0) for status in SPONSOR_FAILURE_STATUSES),
        'unresolved': by_status.get('signed', 0) + by_status.get('sent', 0),
        'unresolved_all_time': rows.filter(status__in=('signed', 'sent')).count(),
        'failed_all_time': rows.filter(status__in=SPONSOR_FAILURE_STATUSES).count(),
        'history_missing': max(0, confirmed_count - settlement_count),
        'by_status': by_status,
    }


def get_stock_router_metrics(*, use_cache: bool = True) -> dict:
    """Live stock-router state for operations; never raises.

    Accrued fees are contract accounting, while the raw USDT balance can also
    include accidental transfers. Reporting both keeps the admin from calling
    sweepable USDT revenue. Values are cached briefly because the main admin
    dashboard is refreshed far more often than this state changes.
    """
    from django.conf import settings

    address = (getattr(settings, 'CUSD_PLUS_STOCK_ROUTER_ADDRESS', '') or '').strip()
    base = {
        'wired': bool(address),
        'address': address or None,
        'stocks_enabled': bool(getattr(settings, 'CUSD_PLUS_STOCKS_ENABLED', False)),
        'trading_enabled': bool(getattr(settings, 'CUSD_PLUS_STOCK_TRADING_ENABLED', False)),
        'fee_bps_configured': int(getattr(settings, 'CUSD_PLUS_GM_TRADE_FEE_BPS', 30)),
    }
    if not address:
        return {
            **base,
            'accrued_usdt_fees': None,
            'router_usdt_balance': None,
            'fee_bps_onchain': None,
            'paused': None,
            'source': 'unconfigured',
        }

    cache_key = f'ondo_stock_router_metrics:v1:{address.lower()}'
    if use_cache:
        cached = cache.get(cache_key)
        if cached:
            return {**base, **cached}

    try:
        from eth_utils import keccak
        from .tasks import _rpc

        def _selector(signature):
            return '0x' + keccak(text=signature)[:4].hex()

        def _call_uint(to, signature, suffix=''):
            result = _rpc(
                'eth_call',
                [{'to': to, 'data': _selector(signature) + suffix}, 'latest'],
                timeout=6,
            )
            return int(result, 16)

        accrued = _call_uint(address, 'accruedUsdtFees()')
        fee_bps = _call_uint(address, 'stockFeeBps()')
        paused = bool(_call_uint(address, 'paused()'))
        usdt_word = _call_uint(address, 'USDT()')
        usdt = '0x' + usdt_word.to_bytes(32, 'big')[-20:].hex()
        router_word = address.lower().removeprefix('0x').rjust(64, '0')
        usdt_balance = _call_uint(usdt, 'balanceOf(address)', router_word)
        chain = {
            'accrued_usdt_fees': Decimal(accrued) / WAD,
            'router_usdt_balance': Decimal(usdt_balance) / WAD,
            'fee_bps_onchain': fee_bps,
            'paused': paused,
            'source': 'bsc',
        }
        if use_cache:
            cache.set(cache_key, chain, 30)
        return {**base, **chain}
    except Exception as exc:  # noqa: BLE001 — ops page must remain available
        logger.warning('Unable to read Ondo stock router state from BSC: %s', exc)
        return {
            **base,
            'accrued_usdt_fees': None,
            'router_usdt_balance': None,
            'fee_bps_onchain': None,
            'paused': None,
            'source': 'unavailable',
        }


def get_bsc_scanner_health() -> dict:
    """Inbound-USDT scanner health — the BSC twin of the Algorand indexer
    cursor row on the blockchain analytics page.

    `lag` is None, not 0, when either side is unreadable: "we don't know how
    far behind the scanner is" must not render as "the scanner is current".
    """
    from django.conf import settings

    from .tasks import _FAILURE_KEY, SCAN_FAILURE_ALERT_THRESHOLD

    cursor = cache.get('cusd_plus_bsc_scan_cursor')
    failures = int(cache.get(_FAILURE_KEY) or 0)

    latest_block = None
    error = None
    try:
        from .tasks import _rpc

        latest_block = int(_rpc('eth_blockNumber', [], timeout=6), 16)
    except Exception as exc:  # noqa: BLE001 — an ops page must still render
        logger.warning('BSC head read failed: %s', exc)
        error = str(exc)

    cursor = int(cursor) if cursor else None
    lag = (latest_block - cursor) if (latest_block is not None and cursor is not None) else None

    return {
        'rpc_url': getattr(settings, 'BSC_RPC_URL', None),
        'rpc_pool': getattr(settings, 'CUSD_PLUS_BSC_RPC_URLS', '') or None,
        'latest_block': latest_block,
        'scan_cursor': cursor,
        'lag': lag,
        'consecutive_failures': failures,
        'failure_threshold': SCAN_FAILURE_ALERT_THRESHOLD,
        'dead': failures >= SCAN_FAILURE_ALERT_THRESHOLD,
        'finality_depth': getattr(settings, 'CUSD_PLUS_FINALITY_DEPTH', 15),
        'sponsorship_enabled': getattr(settings, 'CUSD_PLUS_7702_ENABLED', False),
        'error': error,
    }


def get_sponsor_balance() -> dict:
    """Live BNB balance of the sponsor hot key. Read-only.

    One key broadcasts every user-facing BSC operation, so this is the
    single number that predicts a total BSC outage. Mirrors the thresholds
    the `check_sponsor_balance` beat alerts on, so the dashboard and the
    log alerts can never disagree.
    """
    from django.conf import settings

    address = getattr(settings, 'BSC_SPONSOR_ADDRESS', None)
    if not address:
        return {'configured': False}

    warn = int(getattr(settings, 'BSC_SPONSOR_BALANCE_WARN_WEI', 50_000_000_000_000_000))
    crit = int(getattr(settings, 'BSC_SPONSOR_BALANCE_CRITICAL_WEI', 20_000_000_000_000_000))
    try:
        from .tasks import _rpc

        balance = int(_rpc('eth_getBalance', [address, 'latest'], timeout=6), 16)
    except Exception as exc:  # noqa: BLE001
        logger.warning('BSC sponsor balance read failed: %s', exc)
        # 'unknown', never 'ok': an unreadable balance is not a healthy one.
        return {'configured': True, 'address': address, 'level': 'unknown', 'error': str(exc)}

    level = 'critical' if balance < crit else ('warning' if balance < warn else 'ok')
    return {
        'configured': True,
        'address': address,
        'balance_bnb': balance / 1e18,
        'level': level,
        'warn_bnb': warn / 1e18,
        'critical_bnb': crit / 1e18,
    }


def get_bnb_autoconvert_stats() -> dict:
    """Mis-deposited native BNB awaiting a client-signed swap to USDT.

    These rows are also the authoritative allowlist for outbound native BNB
    (see PendingAutoSwap.ASSET_CHOICES), so a growing PENDING pile is both a
    stranded-user signal and an audit surface.
    """
    from blockchain.models import PendingAutoSwap

    rows = PendingAutoSwap.objects.filter(asset_type='BNB')
    counts = rows.aggregate(
        pending=Count('id', filter=Q(status='PENDING')),
        submitted=Count('id', filter=Q(status='SUBMITTED')),
        completed=Count('id', filter=Q(status='COMPLETED')),
        failed=Count('id', filter=Q(status='FAILED')),
        cancelled=Count('id', filter=Q(status='CANCELLED')),
        pending_amount=Sum('amount_decimal', filter=Q(status='PENDING')),
    )
    counts['pending_amount'] = counts['pending_amount'] or Decimal('0')
    counts['total'] = rows.count()
    return counts
