"""Celery tasks for Cuenta inteligente (spec 7.8). Registered in the beat
schedule in config/celery.py.

Two classes, by what switching the feature flag off must still allow:
- protective and exit work needs only SMART_ACCOUNT_FACTORY_ADDRESS:
  mirroring events (reconcile_events, check/reconcile_relay_txs), claim
  notices to an owner whose account is being claimed (claim_notices) and
  returning an expired account's assets (return_expired). An owner must
  never lose an account, or find assets trapped, because the flag is off;
- everything that starts new activity also needs SMART_ACCOUNT_ENABLED:
  fee collection, payment notices, forced sales, USDT conversion, rules,
  the CONFIO latch, entitlement sync, and Confío IA+'s monthly review notes
  and alerts."""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import chain

logger = logging.getLogger(__name__)


def _single(name: str, ttl: int, fn):
    """One run at a time per task: two overlapping runs would only race for
    the same idempotency keys, but there is no reason to pay for it."""
    key, owner = f'smart_account_task_lock:{name}', uuid.uuid4().hex
    if not cache.add(key, owner, ttl):
        return {'skipped': 'already_running'}
    try:
        return fn()
    finally:
        # A run that outlived its lock never releases the next one's. (The
        # lock only saves work: sending and closing exclude each other in
        # the database, relayer claim / close_unfunded / close_unsent.)
        if cache.get(key) == owner:
            cache.delete(key)


@shared_task(name='smart_account.reconcile_events', ignore_result=True)
def reconcile_events():
    # The chain moves whether or not the flag is on (a cancellation, a claim
    # against an owner's account): the mirror must follow it.
    if not chain.factory_address():
        return {'skipped': 'disabled'}
    from . import reconcile

    def follow():
        try:
            return reconcile.reconcile()
        finally:
            # Money already sent is followed to its end, the flag on or off,
            # and whether or not the event scan worked.
            from . import infinia_payouts, payouts
            for mirror in (infinia_payouts.mirror_payouts, payouts.mirror_ramp_payouts):
                try:
                    mirror()
                except Exception:  # noqa: BLE001 — retried next minute
                    logger.exception('payout mirror failed')
    return _single('reconcile_events', 240, follow)


@shared_task(name='smart_account.collect_due_fees', ignore_result=True)
def collect_due_fees():
    from . import automation
    return _single('collect_due_fees', 900, automation.collect_due_fees)


@shared_task(name='smart_account.start_payment_notices', ignore_result=True)
def start_payment_notices():
    from . import automation
    return _single('start_payment_notices', 900, automation.start_payment_notices)


@shared_task(name='smart_account.run_forced_sales', ignore_result=True)
def run_forced_sales():
    from . import automation
    return _single('run_forced_sales', 1800, automation.run_forced_sales)


@shared_task(name='smart_account.convert_usdt', ignore_result=True)
def convert_usdt():
    from . import automation
    return _single('convert_usdt', 280, automation.convert_usdt)


@shared_task(name='smart_account.run_rules', ignore_result=True)
def run_rules():
    from . import automation
    return _single('run_rules', 280, automation.run_rules)


@shared_task(name='smart_account.return_expired', ignore_result=True)
def return_expired():
    from . import automation
    return _single('return_expired', 900, automation.return_expired)


@shared_task(name='smart_account.claim_notices', ignore_result=True)
def claim_notices():
    from . import automation
    return _single('claim_notices', 1800, automation.claim_notices)


@shared_task(name='smart_account.sync_entitlements', ignore_result=True)
def sync_entitlements():
    if not chain.enabled():
        return {'skipped': 'disabled'}
    from . import automation, entitlements
    automation.check_price_settings()
    return {'synced': entitlements.sync_all()}


@shared_task(name='smart_account.monthly_review_notes', ignore_result=True)
def monthly_review_notes():
    """Confío IA+ (decision 34): last month's review as an assistant-thread
    note for each subscriber. Idempotent per (account, month) by the note's
    tag, so a second run posts nothing."""
    if not chain.enabled():
        return {'skipped': 'disabled'}
    from . import assistant_ops
    return _single('monthly_review_notes', 3600, assistant_ops.post_monthly_notes)


@shared_task(name='smart_account.evaluate_watches', ignore_result=True)
def evaluate_watches():
    """Owner-set alerts: at most one trigger per watch per cooldown."""
    if not chain.enabled():
        return {'skipped': 'disabled'}
    from . import watches
    return _single('evaluate_watches', 280, watches.evaluate)


@shared_task(name='smart_account.latch_confio_sale', ignore_result=True)
def latch_confio_sale():
    from . import automation
    return _single('latch_confio_sale', 900, automation.latch_confio_sale)


@shared_task(name='smart_account.check_relay_tx', bind=True, max_retries=40, ignore_result=True)
def check_relay_tx(self, relay_tx_id: int):
    """Resolve one relayer transaction to a final status by its receipt."""
    from . import automation, relayer
    from .models import SmartAccountRelayTx
    row = SmartAccountRelayTx.objects.select_related('smart_account').filter(pk=relay_tx_id).first()
    if row is None or row.status not in ('signed', 'sent'):
        return
    try:
        status = relayer.resolve_receipt(row)
    except Exception as exc:  # noqa: BLE001 — never guess an outcome
        logger.warning('relay tx %s receipt check failed: %s', row.signed_tx_hash, exc)
        raise self.retry(countdown=min(60, 3 + 2 * self.request.retries))
    if status in ('signed', 'sent'):
        raise self.retry(countdown=min(60, 3 + 2 * self.request.retries))
    automation.on_relay_tx_final(row)
    if status == 'confirmed':
        reconcile_events.apply_async(countdown=1)


@shared_task(name='smart_account.reconcile_relay_txs', ignore_result=True)
def reconcile_relay_txs():
    """Relayer transactions left 'signed' (the process died between the
    durable write and the broadcast, or the broadcast raised) or 'sent'
    (the receipt task gave up). Read the chain by the deterministic hash:
    known -> sent and re-checked; unknown after the grace window -> dropped,
    which frees the idempotency slot so the task sends again. Needs only a
    configured factory: expiry returns run with the feature flag off too."""
    if not chain.factory_address():
        return {'skipped': 'disabled'}
    from . import automation, relayer
    from .models import SmartAccountRelayTx
    grace = timedelta(minutes=int(getattr(settings, 'CUSD_PLUS_SIGNED_GRACE_MIN', 3)))
    # A 'sent' row with no receipt this long after signing is checked against
    # the sponsor's mined nonce (relayer.drop_if_nonce_passed): one whose
    # nonce was taken by another transaction is dropped, so its forced sale,
    # fee period or rule slot is released and retried instead of blocked.
    sent_grace = timedelta(minutes=int(getattr(settings, 'SMART_ACCOUNT_SENT_DROP_GRACE_MIN', 10)))
    now = timezone.now()
    out = {'promoted': 0, 'dropped': 0, 'resolved': 0, 'errors': 0}
    stuck = SmartAccountRelayTx.objects.select_related('smart_account').filter(
        status__in=('signed', 'sent'), updated_at__lt=now - grace).order_by('id')[:200]
    for row in stuck:
        try:
            if row.status == 'signed':
                tx = chain.rpc('eth_getTransactionByHash', [row.signed_tx_hash])
                if tx is None:
                    # Compare-and-set: a receipt worker may have advanced it.
                    if SmartAccountRelayTx.objects.filter(pk=row.pk, status='signed').update(
                            status='dropped', updated_at=now):
                        row.status = 'dropped'
                        automation.on_relay_tx_final(row)
                        out['dropped'] += 1
                    continue
                if SmartAccountRelayTx.objects.filter(pk=row.pk, status='signed').update(
                        status='sent', updated_at=now):
                    row.status = 'sent'
                    out['promoted'] += 1
            status = relayer.resolve_receipt(row)
            if status not in ('signed', 'sent'):
                automation.on_relay_tx_final(row)
                out['resolved'] += 1
            elif row.created_at < now - sent_grace and relayer.drop_if_nonce_passed(row):
                automation.on_relay_tx_final(row)
                out['dropped'] += 1
        except Exception:  # noqa: BLE001 — never guess; next run
            logger.exception('relay tx %s could not be reconciled', row.signed_tx_hash)
            out['errors'] += 1
    if out['resolved']:
        reconcile_events.apply_async(countdown=1)
    return out


@shared_task(name='smart_account.run_relay_trade', bind=True, max_retries=120, ignore_result=True)
def run_relay_trade(self, trade_id: int):
    """One hands-off chat trade (relay_trades.py): quote, check, send."""
    from . import relay_trades
    try:
        relay_trades.run(trade_id)
    except relay_trades.Later as wait:
        raise self.retry(countdown=wait.seconds)


@shared_task(name='smart_account.finish_relay_trade', bind=True, max_retries=200, ignore_result=True)
def finish_relay_trade(self, trade_id: int):
    """After a hands-off trade's broadcast: the receipt decides, the chat is told."""
    from . import relay_trades
    try:
        relay_trades.finish(trade_id)
    except relay_trades.Later as wait:
        raise self.retry(countdown=wait.seconds)
    except Exception as exc:  # noqa: BLE001 — never guess an outcome; read again
        logger.warning('relay trade %s finish failed: %s', trade_id, exc)
        raise self.retry(countdown=min(60, 5 + 2 * self.request.retries))
