"""In-flight detection and confirmation invalidation for an account
contract's address (spec 7.2).

The existing checks look at SponsoredBatch rows at the signer's address.
For a Cuenta inteligente the effect lands at the CONTRACT address: either an
owner-signed batch (recorded at the owner's wallet, linked through its
prepared action) or a relayer transaction (SmartAccountRelayTx).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

IN_FLIGHT_MAX_AGE = timedelta(minutes=30)
ON_WIRE = ('signed', 'sent')


def address_in_flight(address: str) -> bool:
    """True while anything that can change this account contract's balances
    is on the wire. Cheap for a non-account address (one indexed lookup)."""
    from .models import SmartAccountPreparedAction, SmartAccountRelayTx
    address = (address or '').lower()
    from .chain import factory_address
    if not address or not factory_address():
        # No factory configured: no account contract can exist, so nothing
        # of this feature can be on the wire (and no query is made).
        return False
    since = timezone.now() - IN_FLIGHT_MAX_AGE
    if SmartAccountPreparedAction.objects.filter(
            target_address=address, consumed=True, sponsored_batch__status__in=ON_WIRE,
            sponsored_batch__created_at__gte=since).exists():
        return True
    from .abi import RELAY_KINDS_NO_BALANCE
    return SmartAccountRelayTx.objects.filter(
        smart_account__contract_address=address, status__in=ON_WIRE, created_at__gte=since,
    ).exclude(kind__in=RELAY_KINDS_NO_BALANCE).exists()


def invalidate_address(address: str, min_block: int | None = None) -> None:
    """Stored balances, stock holdings and crypto holdings of the contract
    address are stale now."""
    from cusd_plus import vault
    from cusd_plus.crypto_holdings import invalidate_holdings as invalidate_crypto
    from cusd_plus.gm_holdings import invalidate_holdings as invalidate_stocks
    address = (address or '').lower()
    if not address:
        return
    vault.invalidate_position(address, min_block=min_block)
    invalidate_stocks(address, min_block=min_block)
    invalidate_crypto(address, min_block=min_block)


def _targets(batch) -> list:
    from .models import SmartAccountPreparedAction
    return list(SmartAccountPreparedAction.objects.filter(sponsored_batch=batch)
                .values_list('target_address', flat=True).distinct())


def on_broadcast(action) -> None:
    invalidate_address(action.target_address)


def _reconcile_soon(addresses) -> None:
    try:
        from .tasks import reconcile_events
        reconcile_events.apply_async(countdown=2)
    except Exception:  # noqa: BLE001 — the beat schedule reconciles anyway
        logger.warning('smart account reconcile could not be scheduled', exc_info=True)


def on_batch_confirmed(batch, block_number: int) -> None:
    """Called by cusd_plus.check_sponsored_batch_receipt before the batch
    turns 'confirmed'. An exception here keeps the batch retryable."""
    targets = _targets(batch)
    for address in targets:
        invalidate_address(address, min_block=block_number)
    _reconcile_soon(targets)
    if batch.kind in ('smart_subscribe', 'smart_deposit'):
        try:
            from . import abi, funnel
            from .models import SmartAccountPreparedAction
            action = SmartAccountPreparedAction.objects.filter(sponsored_batch=batch).first()
            if action is not None and any(
                    (c.get('data') or '')[2:10] == abi.SEL_TRANSFER for c in (action.calls or [])):
                funnel.record(batch.user, 'first_deposit', plan=(action.payload or {}).get('plan', ''))
        except Exception:  # noqa: BLE001 — analytics never fail a settlement
            logger.warning('smart account first_deposit event failed', exc_info=True)


def on_batch_reorged(batch) -> None:
    for address in _targets(batch):
        invalidate_address(address)


def on_relay_final(relay_tx, block_number: int | None = None) -> None:
    invalidate_address(relay_tx.smart_account.contract_address, min_block=block_number)
