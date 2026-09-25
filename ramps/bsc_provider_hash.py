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


def attach_arrival(ramp, rpc, *, tx_hash: str | None = None, apply: bool = True) -> str:
    """Outcome label; writes the arrival proof when verified and apply."""
    from ramps.models import RampTransaction
    from ramps.signals import find_provider_tx_hash

    tx_hash = (tx_hash or find_provider_tx_hash(ramp.metadata or {}) or '').lower()
    if not tx_hash:
        return 'no_provider_hash'
    if RampTransaction.objects.filter(metadata__bsc_arrival_tx_hash=tx_hash).exclude(pk=ramp.pk).exists():
        return 'hash_claimed_by_another_ramp'
    wallet = (ramp.actor_address or '').lower()
    expected = Decimal(ramp.crypto_amount_actual or ramp.crypto_amount_estimated or ramp.final_amount or 0)
    if not wallet or expected <= 0:
        return 'missing_wallet_or_amount'
    verified = verify_delivery(rpc, tx_hash, wallet, expected)
    if verified is None:
        return 'chain_mismatch'
    if not apply:
        return 'verified'
    amount, log_index = verified
    metadata = dict(ramp.metadata or {})
    metadata.update({
        'bsc_arrival_tx_hash': tx_hash,
        'bsc_arrival_log_index': log_index,
        'bsc_arrival_amount': format(amount, 'f'),
        'bsc_arrival_source': 'provider_hash',
    })
    written = RampTransaction.objects.filter(pk=ramp.pk).exclude(
        metadata__has_key='bsc_arrival_tx_hash').update(metadata=metadata, crypto_amount_actual=amount)
    return 'verified' if written else 'already_attached'


def attach_after_koywe_sync(ramp) -> None:
    """Live hook after a Koywe status sync: the moment the hash appears, prove
    the arrival. Never raises — a miss stays unproven (conservative) and the
    attach_koywe_bsc_arrivals command can retry it."""
    try:
        from ramps.models import RampTransaction
        if not isinstance(ramp, RampTransaction) or not ramp.pk:
            return  # only persisted ramps carry proof
        if (ramp.provider != 'koywe' or ramp.destination != 'cusd_plus' or ramp.direction != 'on_ramp'
                or ramp.status != 'COMPLETED' or (ramp.metadata or {}).get('bsc_arrival_tx_hash')):
            return
        from cusd_plus.tasks import _rpc
        outcome = attach_arrival(ramp, _rpc)
        if outcome != 'verified':
            logger.info('koywe ramp %s: arrival not attached (%s)', ramp.pk, outcome)
    except Exception:  # noqa: BLE001 — proof is best-effort; the sync itself must not fail
        logger.exception('koywe ramp %s: arrival attachment failed', ramp.pk)
