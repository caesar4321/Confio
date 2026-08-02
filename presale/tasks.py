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
    """Create pending credit rows for enrolled users (bsc_address present).

    ONLY legacy Algorand purchases are migratable. A BSC purchase already
    credited `purchased[buyer]` on-chain when it settled, so including it
    here would hand the same CONFIO out twice — the second time from
    migratedPool, i.e. out of backing reserved for genuine Algorand buyers
    (Codex audit 2026-08-02, P1).

    Amounts are re-synced, not snapshotted: a user who buys again on
    Algorand before cutover would otherwise keep the stale total forever.
    A row that is already queued/credited can't be topped up in place
    (one row per user), so the delta is logged loudly for a manual credit.
    """
    from users.models import Account
    from presale.models import PresalePurchase, PresaleMigrationCredit

    totals = (
        PresalePurchase.objects.filter(
            status='completed', funding_source='algorand_cusd',
        )
        .values('user_id')
        .annotate(total=Sum('confio_amount'))
    )
    existing = {
        row.user_id: row for row in PresaleMigrationCredit.objects.all()
    }

    created, updated, skipped_unlinked, needs_manual = 0, 0, 0, 0
    for row in totals:
        user_id, total = row['user_id'], row['total'] or Decimal('0')
        if total <= 0:
            continue

        credit = existing.get(user_id)
        if credit:
            if credit.confio_amount >= total:
                continue
            if credit.status == 'pending':
                credit.confio_amount = total
                credit.save(update_fields=['confio_amount', 'updated_at'])
                updated += 1
            else:
                needs_manual += 1
                logger.warning(
                    '[PRESALE][MIGRATION] user %s bought %s more CONFIO after its '
                    'credit was %s (row has %s, DB total %s) — needs a manual '
                    'top-up credit', user_id, total - credit.confio_amount,
                    credit.status, credit.confio_amount, total,
                )
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
        f"[PRESALE][MIGRATION] sync: created={created} updated={updated} "
        f"awaiting_bsc_address={skipped_unlinked} needs_manual_topup={needs_manual}"
    )
    return {
        'created': created, 'updated': updated,
        'awaiting_bsc_address': skipped_unlinked, 'needs_manual_topup': needs_manual,
    }


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


@shared_task(bind=True, max_retries=40, name='presale.confirm_bsc_purchase')
def confirm_bsc_presale_purchase(self, purchase_id: int, batch_id: int):
    """Resolve a BSC presale buy to its outcome by following the
    SponsoredBatch row (whose own receipt task handles the tricky cases:
    revert, and the silent 7702 no-op where the delegation never applied).

    confirmed → purchase completed + per-user limit + unified row.
    reverted/noop_failed → purchase failed (funds untouched; user retries).
    """
    from blockchain.models import SponsoredBatch
    from users.models_unified import UnifiedTransactionTable

    from .models import PresalePurchase, UserPresaleLimit

    try:
        purchase = PresalePurchase.objects.get(id=purchase_id)
        batch = SponsoredBatch.objects.get(id=batch_id)
    except (PresalePurchase.DoesNotExist, SponsoredBatch.DoesNotExist):
        return
    # Isolation: this batch must actually belong to this purchase. Without it a
    # mis-scheduled or replayed task could settle a purchase from a STRANGER's
    # batch — completing it on someone else's tx hash and making its real
    # confirmation return early on a non-processing row. The other domain
    # confirmers already assert this (Codex audit 2026-08-02).
    if batch.kind != 'presale_buy' or batch.source_id != purchase.id:
        logger.error(
            '[PRESALE][BSC] batch %s (%s/%s) does not belong to purchase %s — refusing',
            batch.id, batch.kind, batch.source_id, purchase.id)
        return
    if purchase.status != 'processing':
        return  # already resolved

    if batch.status == 'sent':
        raise self.retry(countdown=15)

    if batch.status == 'confirmed':
        # Serialize the limit increment: two purchases confirming at once would
        # otherwise both read the same total and the later save would erase the
        # earlier one, understating the ledger the per-user cap is built on
        # (Codex audit 2026-08-02, P1). The row lock also makes this task's
        # completion atomic with the increment, so a worker dying mid-way can't
        # leave a completed purchase that never counted.
        from django.db import transaction
        with transaction.atomic():
            # Re-read the purchase UNDER LOCK. The status check above ran on a
            # copy fetched before this transaction, so two Celery deliveries of
            # the same task could both pass it and each add the amount again
            # (Codex audit 2026-08-02, P2). Whoever gets the lock second sees
            # 'completed' and leaves.
            purchase = PresalePurchase.objects.select_for_update().get(id=purchase.id)
            if purchase.status != 'processing':
                return
            upl, _ = UserPresaleLimit.objects.get_or_create(
                user=purchase.user, phase=purchase.phase)
            upl = UserPresaleLimit.objects.select_for_update().get(pk=upl.pk)
            purchase.complete_purchase(batch.tx_hash)
            upl.total_purchased += purchase.cusd_amount
            upl.last_purchase_at = timezone.now()
            upl.save(update_fields=['total_purchased', 'last_purchase_at'])
            UnifiedTransactionTable.objects.filter(presale_purchase=purchase).update(
                status='CONFIRMED', transaction_hash=batch.tx_hash,
            )
        logger.info('[PRESALE][BSC] purchase %s confirmed: %s', purchase.id, batch.tx_hash)
    else:  # reverted / noop_failed / dropped / reorged
        # THE INVARIANT (mirror of presale.bsc_flow.submit_purchase): a
        # purchase is 'failed' only while it has no live batch. A terminal
        # batch frees the uniqueness slot, so the user may already have
        # retried — and failing the purchase then would book an executing buy
        # as failed while the replacement's own confirm returns early on a
        # non-processing row.
        #
        # Decided UNDER THE PURCHASE LOCK, the same one submit_purchase takes
        # before recording its batch. Reading it outside the lock was a
        # check-then-act: a submit that had passed its status guard but not
        # yet created its row was invisible here (Codex audit 2026-08-02).
        from django.db import transaction

        from blockchain.models import SponsoredBatch
        with transaction.atomic():
            purchase = PresalePurchase.objects.select_for_update().get(id=purchase.id)
            if purchase.status != 'processing':
                return  # resolved by someone else while we waited for the lock
            if SponsoredBatch.objects.filter(
                kind='presale_buy', source_id=purchase.id,
                status__in=('signed', 'sent', 'confirmed'),
            ).exclude(pk=batch.pk).exists():
                logger.info(
                    '[PRESALE][BSC] batch %s is %s but purchase %s has a live '
                    'replacement — leaving it processing',
                    batch.id, batch.status, purchase.id)
                return
            purchase.status = 'failed'
            purchase.notes = (purchase.notes or '') + f'\n[Error] batch {batch.status}: {batch.tx_hash}'
            purchase.save(update_fields=['status', 'notes'])
            UnifiedTransactionTable.objects.filter(presale_purchase=purchase).update(
                status='FAILED', error_message=f'batch_{batch.status}',
            )
        logger.warning('[PRESALE][BSC] purchase %s failed: batch %s %s',
                       purchase.id, batch.id, batch.status)


@shared_task(name='presale.abandon_stale_bsc_purchases')
def abandon_stale_bsc_purchases() -> dict:
    """BSC purchase rows the user prepared but never signed (no tx hash)
    expire after a day — keeps quotes honest and the admin list clean.
    (In-flight rows WITH a tx hash are resolved by confirm_bsc_purchase.)"""
    from datetime import timedelta

    from .models import PresalePurchase
    from users.models_unified import UnifiedTransactionTable

    cutoff = timezone.now() - timedelta(hours=24)
    # Every BSC funding source, not just direct_cusd. cusd_plus.vault
    # reserved_usdt_wei() reserves prepared-but-unsigned buys for BOTH sources
    # and documents THIS reaper as what releases them — so reaping only one
    # left an unsigned cusd_plus_redeem row 'processing' forever, permanently
    # subtracting its amount from sweepableUsdtUsd. The auto-mint then finds
    # nothing to sweep and the user's deposits silently stop converting.
    #
    # "No tx hash" does NOT prove nothing was broadcast. send_sponsored_batch
    # flips its row to 'sent' and submit_purchase saves the hash separately —
    # a crash between those leaves an EXECUTED purchase with a null hash, and
    # failing it here would tell the user their money did nothing while the
    # chain says otherwise. An active SponsoredBatch is the durable proof, so
    # those rows are left for reconciliation instead of being reaped.
    # Exists(), NOT `id__in=...values('source_id')`. source_id is nullable, so
    # a single NULL in that subquery makes `id NOT IN (…)` evaluate to UNKNOWN
    # for EVERY candidate row in PostgreSQL — silently disabling this reaper
    # completely. A correlated EXISTS has no such trap.
    from django.db.models import Exists, OuterRef

    from blockchain.models import SponsoredBatch

    from .bsc_flow import BSC_FUNDING_SOURCES
    live_batch = SponsoredBatch.objects.filter(
        kind='presale_buy',
        source_id=OuterRef('pk'),
        status__in=('signed', 'sent', 'confirmed'),
    )
    stale = PresalePurchase.objects.filter(
        status='processing',
        funding_source__in=BSC_FUNDING_SOURCES,
        transaction_hash__isnull=True,
        created_at__lt=cutoff,
    ).annotate(_live_batch=Exists(live_batch)).filter(_live_batch=False)
    ids = list(stale.values_list('id', flat=True))
    updated = stale.update(status='failed')
    if updated:
        UnifiedTransactionTable.objects.filter(presale_purchase_id__in=ids).update(
            status='FAILED', error_message='abandoned_unsigned')
        logger.info('[PRESALE][BSC] abandoned %d stale unsigned purchases', updated)
    return {'abandoned': updated}


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
