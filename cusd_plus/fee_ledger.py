"""Confío's fee ledger: every cUSD perimeter fee, once, tagged by source.

Since router v2 (2026-10) every Confío fee is charged by the cUSD vault:
deposits and withdrawals, ramps, sends to outside wallets, Pay, and stock,
Bitcoin and gold trades all emit one of the four perimeter events. The
finalized-log scanner records each event once (conversion.CusdFeeEvent);
this module derives where it came from at READ time, so ramp attribution
that lands after the scan is still picked up.

The only fee NOT here is the legacy 0.30% stock-router fee that pre-v2 app
builds still pay during the transition (ConfioStockRouter.accruedUsdtFees);
the admin shows it beside this ledger, never added into it twice.
"""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

WAD = Decimal(10) ** 18

# Display order and labels for the admin.
SOURCES = OrderedDict([
    ('stock', 'Stocks (Ondo)'),
    ('bitcoin', 'Bitcoin'),
    ('gold', 'Gold'),
    ('crypto', 'Other crypto'),
    ('onramp', 'On-ramp (local money in)'),
    ('offramp', 'Off-ramp (local money out)'),
    ('usdt_in', 'Outside USDT in'),
    ('usdt_out', 'Outside USDT out'),
    ('pay', 'Confío Pay'),
])

_SEND_REDEEM_KINDS = ('send_redeem', 'send_cusd_redeem', 'send_mixed_cusd_redeem')
_PAY_KINDS = ('pay_cusd_plus', 'pay_cusd', 'pay_usdt', 'pay_confio')


# ── recording (scanner) ─────────────────────────────────────────────────

def record_fee_events(tx_hash: str, logs: list, block_times: dict) -> int:
    """Store every perimeter fee event in `logs` (one tx). Idempotent on
    (tx_hash, log_index). `block_times` maps block number -> datetime."""
    from conversion.models import CusdFeeEvent

    from .tasks import _cusd_fee_events

    stored = 0
    blocks = {}
    for log in logs:
        try:
            blocks[int(log.get('logIndex', '0x0'), 16)] = int(log.get('blockNumber', '0x0'), 16)
        except (TypeError, ValueError):
            continue
    for event in _cusd_fee_events({'logs': logs}):
        block = blocks.get(event['log_index'], 0)
        when = block_times.get(block)
        row, created = CusdFeeEvent.objects.get_or_create(
            tx_hash=tx_hash.lower(), log_index=event['log_index'],
            defaults={
                'block_number': block,
                'block_time': when,
                'direction': event['direction'],
                'event_type': event['conversion_type'],
                'gross_wei': event['gross_wei'],
                'fee_wei': event['fee_wei'],
                'net_wei': event['net_wei'],
                'fee_bps': event['fee_bps'],
            },
        )
        if not created and row.block_time is None and when is not None:
            # A replay (scanner retry or backfill) repairs a missing time.
            CusdFeeEvent.objects.filter(pk=row.pk, block_time__isnull=True).update(block_time=when)
        stored += int(created)
    return stored


def block_time(rpc, block_number: int, cache: dict) -> datetime | None:
    """Block timestamp (UTC), memoized per scan."""
    if block_number in cache:
        return cache[block_number]
    try:
        block = rpc('eth_getBlockByNumber', [hex(block_number), False]) or {}
        stamp = int(block.get('timestamp') or '0x0', 16)
        # A null/empty response is UNKNOWN, never the 1970 epoch.
        when = datetime.fromtimestamp(stamp, tz=dt_timezone.utc) if stamp > 0 else None
    except Exception:  # noqa: BLE001 — a missing time only drops the event from time windows
        when = None
    cache[block_number] = when
    return when


# ── attribution (read time) ─────────────────────────────────────────────

def _crypto_source(batch) -> str:
    trade = getattr(batch, 'crypto_trade', None)
    symbol = trade.symbol if trade is not None else None
    if symbol is None:
        from .crypto_policy import CryptoPolicyError, decode_crypto_call

        try:
            for call in json.loads(batch.calls_json or '[]'):
                action = decode_crypto_call(call, historical=True)
                if action is not None:
                    symbol = action['token'].symbol
                    break
        except (CryptoPolicyError, ValueError):
            symbol = None
    if symbol is None:
        return 'crypto'
    from .crypto_catalog import by_symbol

    token = by_symbol(symbol, include_unlisted=True)
    if token is not None and token.category == 'metal':
        return 'gold'
    return 'bitcoin' if symbol == 'BTCB' else 'crypto'


def _usdt_transfer_recipients(batch) -> set:
    from .sponsor_7702 import SEL_TRANSFER, USDT_BSC

    try:
        calls = json.loads(batch.calls_json or '[]')
    except ValueError:
        return set()
    out = set()
    for c in calls:
        data = (c.get('data') or '').lower()
        if (c.get('to') or '').lower() == USDT_BSC and data[2:10] == SEL_TRANSFER and len(data) >= 10 + 64:
            out.add('0x' + data[10:74][-40:])
    return out




def _provider_deposit_addresses() -> set:
    """Deposit addresses providers gave for off-ramp orders (the evidence
    that a raw USDT transfer paid a provider, not someone's own wallet)."""
    from ramps.models import RampTransaction
    from ramps.schema import _KOYWE_DEPOSIT_ADDRESS_FIELDS

    out = set()
    for metadata in RampTransaction.objects.filter(direction='off_ramp').values_list('metadata', flat=True):
        details = (metadata or {}).get('payment_details') or {}
        if not isinstance(details, dict):
            continue
        # The same documented fields the funding path resolves, plus the
        # annotated/destination spellings; never the provider-details
        # fallback, which is generic metadata rather than this order's target.
        keys = ('confioDepositAddress', 'destinationAddress') + tuple(
            k for k in _KOYWE_DEPOSIT_ADDRESS_FIELDS
            if not (k == 'providedAddress' and details.get('providedAddressFromProviderDetails')))
        for key in keys:
            value = str(details.get(key) or '').strip().lower()
            if len(value) == 42 and value.startswith('0x'):
                out.add(value)
    return out


def classify(event, batch, ramp_directions: dict, bridge_payouts: set, provider_addresses: set = frozenset()) -> str:
    """The source tag of one fee event.

    `batch`: the SponsoredBatch with this tx hash, or None (permissionless).
    `ramp_directions`: {tx_hash: 'on_ramp'|'off_ramp'} from ramp-linked
    conversions. `bridge_payouts`: tx hashes of bridges that pay out to a
    local bank account (off-ramp) rather than a merchant (Pay).
    """
    tx = event.tx_hash
    if batch is not None:
        kind = batch.kind
        if kind in ('stock_buy', 'stock_sell'):
            return 'stock'
        if kind in ('crypto_buy', 'crypto_sell'):
            return _crypto_source(batch)
        if kind in _PAY_KINDS:
            return 'pay'
        if kind == 'payment_bridge':
            return 'offramp' if tx in bridge_payouts else 'pay'
        if (batch.client_request_id or '').startswith('local-mint-'):
            return 'onramp'  # Infinia local-account deposit
    if tx in ramp_directions:
        return 'onramp' if ramp_directions[tx] == 'on_ramp' else 'offramp'
    if batch is not None:
        if batch.kind in _SEND_REDEEM_KINDS:
            return 'usdt_out'
        if event.direction == 'exit' and _usdt_transfer_recipients(batch) & provider_addresses:
            # The exit paid a provider's off-ramp deposit address (order
            # evidence), not the user's own outside wallet.
            return 'offramp'
    return 'usdt_in' if event.direction == 'entry' else 'usdt_out'


def _context(tx_hashes: set):
    from blockchain.models import SponsoredBatch
    from payment_accounts.models import CobreJourney, InfiniaJourney
    from ramps.models import RampTransaction

    from django.db.models.functions import Lower

    batches = {}
    # Batch hashes may be stored in any case; the ledger stores lower-case.
    for b in (SponsoredBatch.objects.annotate(tx_lower=Lower('tx_hash'))
              .filter(tx_lower__in=tx_hashes).select_related('crypto_trade')
              .only('tx_hash', 'kind', 'client_request_id', 'calls_json', 'crypto_trade__symbol')):
        batches[b.tx_lower] = b
    ramp_directions = {}
    for direction, tx in RampTransaction.objects.filter(
            conversion__to_transaction_hash__isnull=False).values_list('direction', 'conversion__to_transaction_hash'):
        if tx:
            ramp_directions[tx.lower()] = direction
    for direction, tx in InfiniaJourney.objects.filter(wallet_conversion__isnull=False).values_list(
            'direction', 'wallet_conversion__to_transaction_hash'):
        if tx:
            ramp_directions[tx.lower()] = 'on_ramp' if direction == 'to_wallet' else 'off_ramp'
    bridge_payouts = set()
    for journeys in (InfiniaJourney, CobreJourney):
        for tx in journeys.objects.filter(direction='to_bank', bridge__batch__isnull=False).values_list(
                'bridge__batch__tx_hash', flat=True):
            if tx:
                bridge_payouts.add(tx.lower())
    return batches, ramp_directions, bridge_payouts, _provider_deposit_addresses()


def summary(now=None) -> dict:
    """Fee totals by source: lifetime and last 30 days, in USD."""
    from conversion.models import CusdFeeEvent

    now = now or datetime.now(dt_timezone.utc)
    since = now - timedelta(days=30)
    events = list(CusdFeeEvent.objects.all().only(
        'tx_hash', 'direction', 'fee_wei', 'gross_wei', 'block_time'))
    batches, ramps, payouts, providers = _context({e.tx_hash for e in events})
    rows = OrderedDict((key, {'key': key, 'label': label, 'count': 0, 'fee_usd': Decimal('0'),
                              'volume_usd': Decimal('0'), 'fee_usd_30d': Decimal('0'), 'count_30d': 0})
                       for key, label in SOURCES.items())
    unknown_time = 0
    for event in events:
        tag = classify(event, batches.get(event.tx_hash), ramps, payouts, providers)
        row = rows[tag]
        fee = Decimal(event.fee_wei) / WAD
        row['count'] += 1
        row['fee_usd'] += fee
        row['volume_usd'] += Decimal(event.gross_wei) / WAD
        if event.block_time is None:
            unknown_time += 1
        elif event.block_time >= since:
            row['count_30d'] += 1
            row['fee_usd_30d'] += fee
    total = {
        'count': sum(r['count'] for r in rows.values()),
        'fee_usd': sum((r['fee_usd'] for r in rows.values()), Decimal('0')),
        'fee_usd_30d': sum((r['fee_usd_30d'] for r in rows.values()), Decimal('0')),
        'volume_usd': sum((r['volume_usd'] for r in rows.values()), Decimal('0')),
    }
    return {'rows': list(rows.values()), 'total': total, 'undated_events': unknown_time}
