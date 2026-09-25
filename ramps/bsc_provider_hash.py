"""Attach a Koywe Dollar+ deposit's BSC arrival from the hash Koywe reports.

The live scanner links a USDT arrival to its ramp when it sees the transfer
land. Koywe often reports the delivery hash (order.txHash) only in a LATER
status sync, and nothing retried once it appeared, so ~97 completed deposits
kept no arrival proof. A static list of Koywe wallets is not the answer —
Koywe rotates them. The hash Koywe itself reports, verified on chain, is:

- the ramp is a COMPLETED Koywe on-ramp into Dollar+ without arrival proof;
- the hash comes from Koywe's own payload (or its order API);
- no other ramp already claims that hash;
- the receipt succeeded and holds exactly one USDT Transfer to the ramp's
  wallet for an amount within the live attribution tolerance (5%).

The recorded amount is the on-chain one. Writes are a silent
queryset.update(): evidence only — no status change, notification, funnel
event or history rewrite.
"""
from __future__ import annotations

import logging
from decimal import ROUND_DOWN, Decimal

logger = logging.getLogger(__name__)

TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
USDT_BSC = '0x55d398326f99059ff775485246999027b3197955'
UNITS = Decimal('0.000001')
TOLERANCE = Decimal('0.05')  # same as ramps.signals.attribute_bsc_ramp_arrival


def eligible_ramps():
    from ramps.models import RampTransaction
    return RampTransaction.objects.filter(
        provider='koywe', destination='cusd_plus', direction='on_ramp', status='COMPLETED',
    ).exclude(metadata__has_key='bsc_arrival_tx_hash')


def verify_delivery(rpc, tx_hash: str, wallet: str, expected: Decimal):
    """(on-chain amount, log index) of the single USDT Transfer to `wallet` in
    a successful receipt, within tolerance of `expected`; else None."""
    receipt = rpc('eth_getTransactionReceipt', [tx_hash])
    if not receipt or receipt.get('status') != '0x1':
        return None
    matches = []
    for log in receipt.get('logs') or []:
        topics = log.get('topics') or []
        if ((log.get('address') or '').lower() != USDT_BSC or len(topics) < 3
                or topics[0].lower() != TRANSFER_TOPIC or '0x' + topics[2][-40:].lower() != wallet):
            continue
        amount = (Decimal(int(log.get('data') or '0x0', 16)) / Decimal(10 ** 18)).quantize(UNITS, rounding=ROUND_DOWN)
        if expected > 0 and abs(amount - expected) <= expected * TOLERANCE:
            matches.append((amount, int(log.get('logIndex') or '0x0', 16)))
    return matches[0] if len(matches) == 1 else None


def _lock_hash(tx_hash: str) -> None:
    """Serialize claims on one transfer across workers (Postgres advisory
    lock, released at transaction end)."""
    from django.db import connection
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [tx_hash])


def attach_arrival(ramp, rpc, *, tx_hash: str | None = None, apply: bool = True,
                   seen: set | None = None, record_mismatch: bool = False) -> str:
    """Outcome label; writes the arrival proof when verified and apply.

    A transfer is (hash, log index): one provider transaction can pay several
    wallets. `seen` carries transfers already verified in this run, so a dry
    run reports what a real run would do (one transfer proves one ramp). With
    `record_mismatch`, a failed verification is remembered per hash so the
    live hook doesn't repeat the RPC on every later sync of the same order.
    """
    from django.db import transaction
    from ramps.models import RampTransaction
    from ramps.signals import find_provider_tx_hash

    tx_hash = (tx_hash or find_provider_tx_hash(ramp.metadata or {}) or '').lower()
    if not tx_hash:
        return 'no_provider_hash'

    def claimed(log_index: int) -> bool:
        return ((tx_hash, log_index) in (seen or ()) or RampTransaction.objects.filter(
            metadata__bsc_arrival_tx_hash=tx_hash, metadata__bsc_arrival_log_index=log_index,
        ).exclude(pk=ramp.pk).exists())

    wallet = (ramp.actor_address or '').lower()
    expected = Decimal(ramp.crypto_amount_actual or ramp.crypto_amount_estimated or ramp.final_amount or 0)
    if not wallet or expected <= 0:
        return 'missing_wallet_or_amount'
    verified = verify_delivery(rpc, tx_hash, wallet, expected)
    if verified is None:
        if record_mismatch and apply:
            # Re-read under the row lock: a concurrent sync may have stored a
            # newer Koywe payload; never write back a stale metadata copy.
            # 'checked_hash', not 'tx_hash': hash finders must never read our
            # own failed guess as a provider-reported hash.
            with transaction.atomic():
                current = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
                if not (current.metadata or {}).get('bsc_arrival_tx_hash'):
                    metadata = dict(current.metadata or {})
                    metadata['bsc_arrival_check'] = {'checked_hash': tx_hash, 'outcome': 'chain_mismatch'}
                    RampTransaction.objects.filter(pk=ramp.pk).update(metadata=metadata)
        return 'chain_mismatch'
    amount, log_index = verified
    if claimed(log_index):
        return 'hash_claimed_by_another_ramp'
    if seen is not None:
        seen.add((tx_hash, log_index))
    if not apply:
        return 'verified'
    with transaction.atomic():
        _lock_hash(tx_hash)
        # Re-check under the lock: another worker may have claimed it meanwhile.
        if RampTransaction.objects.filter(
                metadata__bsc_arrival_tx_hash=tx_hash, metadata__bsc_arrival_log_index=log_index,
        ).exclude(pk=ramp.pk).exists():
            return 'hash_claimed_by_another_ramp'
        current = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        if (current.metadata or {}).get('bsc_arrival_tx_hash'):
            return 'already_attached'
        metadata = dict(current.metadata or {})
        metadata.pop('bsc_arrival_check', None)
        metadata.update({
            'bsc_arrival_tx_hash': tx_hash,
            'bsc_arrival_log_index': log_index,
            'bsc_arrival_amount': format(amount, 'f'),
            'bsc_arrival_source': 'provider_hash',
        })
        # Silent: evidence only — no signals, notifications or funnel events.
        RampTransaction.objects.filter(pk=ramp.pk).update(metadata=metadata, crypto_amount_actual=amount)
    return 'verified'


def _link_completed_conversion(ramp) -> None:
    """If the wallet's auto-conversion completed BEFORE the hash arrived, the
    conversion signal found no attributable arrival and left the order
    unlinked. Re-run ONLY the exact-sum attributed linking for the wallet's
    unlinked sweeps — never the signal's other fallbacks."""
    from django.db import transaction
    from django.db.models import Q
    from conversion.models import Conversion
    from ramps.models import RampTransaction
    from ramps.signals import BSC_RAMP_ATTRIBUTION_WINDOW, link_attributed_bsc_ramps

    address = (ramp.actor_address or '').lower()
    candidates = Conversion.objects.filter(
        status='COMPLETED', is_deleted=False, conversion_type__in=('to_savings', 'usdt_to_cusd'),
        ramp_transactions__isnull=True,
        created_at__gte=ramp.created_at - BSC_RAMP_ATTRIBUTION_WINDOW,
        created_at__lte=ramp.created_at + BSC_RAMP_ATTRIBUTION_WINDOW,
    ).filter(Q(actor_address__iexact=address) | Q(user_bsc_address__iexact=address)).order_by('created_at')
    for conversion in candidates:
        with transaction.atomic():
            link_attributed_bsc_ramps(conversion)
        if RampTransaction.objects.filter(pk=ramp.pk, conversion__isnull=False).exists():
            return


def attach_after_koywe_sync(ramp) -> None:
    """Live hook after a Koywe status sync: the moment the hash appears, prove
    the arrival, then link an already-completed conversion. Never raises — a
    miss stays unproven (conservative) and attach_koywe_bsc_arrivals can
    retry it."""
    try:
        from ramps.models import RampTransaction
        from ramps.signals import find_provider_tx_hash
        if not isinstance(ramp, RampTransaction) or not ramp.pk:
            return  # only persisted ramps carry proof
        metadata = ramp.metadata or {}
        if (ramp.provider != 'koywe' or ramp.destination != 'cusd_plus' or ramp.direction != 'on_ramp'
                or ramp.status != 'COMPLETED' or metadata.get('bsc_arrival_tx_hash')):
            return
        tx_hash = find_provider_tx_hash(metadata)
        if not tx_hash or (metadata.get('bsc_arrival_check') or {}).get('checked_hash') == tx_hash:
            return  # nothing new to verify since the last attempt
        from cusd_plus.tasks import _rpc
        outcome = attach_arrival(ramp, _rpc, tx_hash=tx_hash, record_mismatch=True)
        if outcome == 'verified':
            ramp.refresh_from_db()
            if ramp.conversion_id is None:
                _link_completed_conversion(ramp)
        else:
            logger.info('koywe ramp %s: arrival not attached (%s)', ramp.pk, outcome)
    except Exception:  # noqa: BLE001 — proof is best-effort; the sync itself must not fail
        logger.exception('koywe ramp %s: arrival attachment failed', getattr(ramp, 'pk', None))
