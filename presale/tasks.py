"""
Algorand→BSC presale migration credits.

The BSC ConfioPresaleVault seeds the whole Algorand-sold amount as an
aggregate (`initialSold` → `migratedPool`) at deploy time; per-user
assignment can only happen later, because a user's BSC address exists only
after they open the updated app. This module is the DB↔chain bridge:

  sync_presale_migration_credits   DB → rows: users with completed Algorand
                                   purchases AND a bsc_address get a
                                   PresaleMigrationCredit row (pending).
  build_presale_credit_batch       rows → Safe: marks pending rows queued
                                   under a batch_id and produces the exact
                                   creditMigrated(buyers[], amounts[])
                                   calldata for the 3-of-5 Safe to execute.
                                   Calldata is derivable from the rows at
                                   any time, so nothing but the rows needs
                                   persisting.
  verify_presale_migration_credits chain → rows: flips queued rows to
                                   credited only after reading the vault's
                                   migratedCredited(addr) back.

Credits are not time-critical: claims cannot unlock before the CONFIO
BEP-20 exists, and the app shows DB totals until then. A weekly Safe batch
is fine — which is why nothing here signs anything; the hot sponsor key
deliberately has no credit powers.
"""
import logging
import re
import uuid
from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from eth_abi import encode as abi_encode
from eth_utils import keccak

logger = logging.getLogger(__name__)

_ADDR_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')

# creditMigrated(address[],uint256[])
CREDIT_MIGRATED_SELECTOR = keccak(text='creditMigrated(address[],uint256[])')[:4]
# migratedCredited(address) view
MIGRATED_CREDITED_SELECTOR = keccak(text='migratedCredited(address)')[:4]


def _vault_address() -> str | None:
    addr = getattr(settings, 'BSC_PRESALE_VAULT_ADDRESS', None)
    return addr if addr and _ADDR_RE.match(addr) else None


@shared_task(name='presale.sync_migration_credits')
def sync_presale_migration_credits() -> dict:
    """Create pending credit rows for enrolled users (bsc_address present)."""
    from users.models import Account
    from presale.models import PresalePurchase, PresaleMigrationCredit

    totals = (
        PresalePurchase.objects.filter(status='completed')
        .values('user_id')
        .annotate(total=Sum('confio_amount'))
    )
    existing = set(
        PresaleMigrationCredit.objects.values_list('user_id', flat=True)
    )

    created, skipped_unlinked = 0, 0
    for row in totals:
        user_id, total = row['user_id'], row['total'] or Decimal('0')
        if user_id in existing or total <= 0:
            continue
        account = Account.objects.filter(
            user_id=user_id,
            account_type='personal',
            deleted_at__isnull=True,
        ).exclude(bsc_address__isnull=True).exclude(bsc_address='').first()
        if not account or not _ADDR_RE.match(account.bsc_address or ''):
            skipped_unlinked += 1
            continue
        PresaleMigrationCredit.objects.create(
            user_id=user_id,
            bsc_address=account.bsc_address,
            confio_amount=total,
        )
        created += 1

    logger.info(
        f"[PRESALE][MIGRATION] sync: created={created} awaiting_bsc_address={skipped_unlinked}"
    )
    return {'created': created, 'awaiting_bsc_address': skipped_unlinked}


def build_presale_credit_batch(limit: int = 100, batch_id: str | None = None) -> dict:
    """
    Queue up to `limit` pending rows under one batch_id and return the Safe
    transaction for them: {to, value, data} for the Safe UI / Transaction
    Builder. Pass an existing batch_id to REPRINT that batch's calldata
    (idempotent — encoding is a pure function of the rows).
    """
    from presale.models import PresaleMigrationCredit

    vault = _vault_address()
    if not vault:
        raise RuntimeError('BSC_PRESALE_VAULT_ADDRESS is not configured')

    if batch_id:
        rows = list(
            PresaleMigrationCredit.objects.filter(batch_id=batch_id)
            .exclude(status='credited').order_by('id')
        )
    else:
        batch_id = uuid.uuid4().hex[:16]
        rows = list(
            PresaleMigrationCredit.objects.filter(status='pending').order_by('id')[:limit]
        )
        for r in rows:
            r.status = 'queued'
            r.batch_id = batch_id
            r.save(update_fields=['status', 'batch_id', 'updated_at'])

    if not rows:
        return {'batch_id': batch_id, 'count': 0, 'to': vault, 'data': None}

    buyers = [r.bsc_address for r in rows]
    amounts = [r.confio_base_units for r in rows]
    data = CREDIT_MIGRATED_SELECTOR + abi_encode(
        ['address[]', 'uint256[]'], [buyers, amounts]
    )

    result = {
        'batch_id': batch_id,
        'count': len(rows),
        'total_confio': str(sum((r.confio_amount for r in rows), Decimal('0'))),
        'to': vault,
        'value': 0,
        'data': '0x' + data.hex(),
    }
    logger.info(
        f"[PRESALE][MIGRATION] batch {batch_id}: {result['count']} credits, "
        f"{result['total_confio']} CONFIO → Safe call to {vault}"
    )
    return result


@shared_task(name='presale.verify_migration_credits')
def verify_presale_migration_credits() -> dict:
    """Confirm queued rows against the vault's migratedCredited(addr)."""
    from cusd_plus.tasks import _rpc
    from presale.models import PresaleMigrationCredit

    vault = _vault_address()
    if not vault:
        return {'verified': 0, 'still_pending': 0, 'skipped': 'vault_not_configured'}

    verified, still_pending = 0, 0
    for row in PresaleMigrationCredit.objects.filter(status='queued'):
        try:
            calldata = MIGRATED_CREDITED_SELECTOR + abi_encode(['address'], [row.bsc_address])
            raw = _rpc('eth_call', [{'to': vault, 'data': '0x' + calldata.hex()}, 'latest'])
            onchain = int(raw, 16) if raw and raw != '0x' else 0
        except Exception as e:
            logger.warning(f"[PRESALE][MIGRATION] verify rpc failed for {row.bsc_address}: {e}")
            continue
        if onchain >= row.confio_base_units:
            row.status = 'credited'
            row.credited_at = timezone.now()
            row.save(update_fields=['status', 'credited_at', 'updated_at'])
            verified += 1
        else:
            still_pending += 1

    logger.info(
        f"[PRESALE][MIGRATION] verify: credited={verified} awaiting_safe_execution={still_pending}"
    )
    return {'verified': verified, 'still_pending': still_pending}
