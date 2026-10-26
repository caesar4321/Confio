from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from django.db.models import Q

from ramps.koywe import COUNTRY_METHODS
from ramps.koywe_client import KoyweClient, KoyweError
from ramps.koywe_sync import sync_koywe_ramp_transaction_from_order
from ramps.models import KoyweBankInfo, RampTransaction

import logging

logger = logging.getLogger(__name__)

KOYWE_SUPPORTED_COUNTRIES = ['COL', 'PER', 'BOL', 'ARG', 'MEX', 'CHL', 'BRA']


@shared_task(name='ramps.refresh_koywe_ramp_limits')
def refresh_koywe_ramp_limits():
    """
    Pre-warm the Koywe dynamic ramp limits cache for every supported country.

    The off-ramp limits need several preview quotes to estimate, so computing
    them inline made rampAvailability (Recargar/Retiro screens) slow on cache
    misses. This runs hourly via celery beat; the cache TTL is 12h so limits
    survive Koywe outages but requests always hit a warm cache.
    """
    client = KoyweClient()
    refreshed = []
    for country_code, config in COUNTRY_METHODS.items():
        if not config['methods']:
            continue
        fiat = config['fiat_currency']
        try:
            client.get_dynamic_ramp_limits(fiat_symbol=fiat, force_refresh=True)
            refreshed.append(fiat)
        except KoyweError as exc:
            logger.warning('Koywe ramp limits refresh failed for %s (%s): %s', country_code, fiat, exc)
        except Exception:
            logger.exception('Unexpected error refreshing Koywe ramp limits for %s (%s)', country_code, fiat)
    return f'Refreshed Koywe ramp limits for {", ".join(refreshed) or "no currencies"}'


@shared_task
def sync_koywe_bank_info():
    """
    Sync bank info from Koywe /rest/bank-info/{countryCode} for all supported countries.
    Runs daily. Safe to re-run at any time.
    """
    client = KoyweClient()
    if not client.is_configured:
        logger.warning('Skipping Koywe bank info sync: client not configured')
        return 'Koywe not configured'

    total_synced = 0
    for country_code in KOYWE_SUPPORTED_COUNTRIES:
        try:
            banks = client.get_bank_info(country_code=country_code)
            if not banks:
                continue
            for bank in banks:
                bank_code = bank.get('bankCode') or ''
                name = bank.get('name') or ''
                institution_name = bank.get('institutionName') or ''
                if not bank_code or not name:
                    continue
                KoyweBankInfo.objects.update_or_create(
                    bank_code=bank_code,
                    country_code=country_code,
                    defaults={
                        'name': name,
                        'institution_name': institution_name,
                        'is_active': True,
                    },
                )
                total_synced += 1
        except KoyweError as exc:
            logger.warning('Koywe bank info sync failed for %s: %s', country_code, exc)
        except Exception:
            logger.exception('Unexpected error syncing Koywe bank info for %s', country_code)

    return f'Synced {total_synced} Koywe bank entries'


@shared_task
def poll_koywe_ramp_transactions():
    """
    Poll recent active orders, all unpaid deposits and unresolved payout refunds.
    Webhooks are the primary source of truth; this is a reconciliation fallback.
    """
    client = KoyweClient()
    if not client.is_configured:
        logger.warning('Skipping Koywe ramp poll: client not configured')
        return 'Koywe not configured'

    threshold = timezone.now() - timedelta(days=7)
    pending_ramps = RampTransaction.objects.filter(
        provider='koywe',
    ).filter(
        Q(created_at__gte=threshold, status__in=['PENDING', 'PROCESSING', 'AML_REVIEW'])
        # Unpaid deposits occupy the per-user slot even after seven days.
        # Keep reconciling them; age alone must neither release nor strand it.
        | Q(direction='on_ramp', status='PENDING')
        | Q(direction='off_ramp', status='FAILED', status_detail__startswith='invalid_withdrawals_details')
        | Q(direction='off_ramp', status='FAILED', status_detail__startswith='refund_')
        | Q(koywe_refund__state__in=['pending', 'requesting', 'unknown', 'requested', 'started', 'in_progress'])
    ).exclude(koywe_refund__state__in=['delivered', 'not_required']).exclude(provider_order_id='').order_by('updated_at')

    if not pending_ramps.exists():
        return 'No pending Koywe ramps'

    updated_count = 0
    checked_count = 0

    for ramp_tx in pending_ramps.iterator():
        checked_count += 1
        auth_email = str((ramp_tx.metadata or {}).get('auth_email') or '').strip() or None
        try:
            previous_status = ramp_tx.status
            previous_detail = ramp_tx.status_detail
            result = client.get_ramp_order_status(
                order_id=ramp_tx.provider_order_id,
                email=auth_email,
            )
            sync_koywe_ramp_transaction_from_order(
                ramp_tx=ramp_tx,
                order_payload=result.raw_response,
                next_action_url=result.next_action_url,
            )
            if ramp_tx.direction == 'off_ramp' and (
                ramp_tx.status_detail.startswith(('invalid_withdrawals_details', 'refund_'))
                or hasattr(ramp_tx, 'koywe_refund')
            ):
                from ramps.koywe_refunds import reconcile_refund
                reconcile_refund(ramp_id=ramp_tx.pk, client=client)
            ramp_tx.refresh_from_db(fields=['status', 'status_detail'])
            if ramp_tx.status != previous_status or ramp_tx.status_detail != previous_detail:
                updated_count += 1
        except KoyweError as exc:
            logger.warning('Koywe poll failed for %s: %s', ramp_tx.provider_order_id, exc)
        except Exception:
            logger.exception('Unexpected Koywe poll failure for %s', ramp_tx.provider_order_id)

    return f'Polled {checked_count} Koywe ramps, updated {updated_count}'


@shared_task(name='ramps.tasks.poll_ve_pagomovil')
def poll_ve_pagomovil():
    """Reconcile VE Pago Móvil orders: VEXPay top-ups and bolívar sends.
    Provider webhooks are single-attempt hints; this poll is the source of
    truth, not a fallback."""
    from ramps import ve_pagomovil, ve_send
    from ramps.vexpay import due_for_sync, ensure_alerted, open_ramps, sync_vexpay_ramp
    from ramps.vexpay_client import VexPayClient, VexPayError

    checked = changed = 0
    client = VexPayClient()
    if client.is_configured:
        for ramp_tx in open_ramps().iterator():
            if not due_for_sync(ramp_tx):
                continue
            checked += 1
            before = (ramp_tx.status, ramp_tx.status_detail)
            try:
                ramp_tx = sync_vexpay_ramp(ramp_tx, client)
                ensure_alerted(ramp_tx)
            except VexPayError as exc:
                logger.warning('VEXPay poll failed for ramp %s: %s', ramp_tx.pk, exc)
                continue
            except Exception:
                logger.exception('Unexpected VEXPay poll failure for ramp %s', ramp_tx.pk)
                continue
            if (ramp_tx.status, ramp_tx.status_detail) != before:
                changed += 1
    # A send whose provider has no adapter any more is never dropped silently.
    # (VEXPay's manual send path was removed before any order existed.)
    orphans = RampTransaction.objects.filter(
        direction=ve_pagomovil.SEND, provider='vexpay', status__in=('PENDING', 'PROCESSING'),
    ).values_list('pk', 'provider')
    for pk, provider in orphans[:20]:
        try:
            from config.ops_alerts import send_ops_alert
            send_ops_alert(f'⚠️ Envío VE {pk} ({provider}) sin adaptador: revísalo a mano.',
                           dedupe_key=f've_send:orphan:{pk}', dedupe_seconds=86400)
        except Exception:
            logger.exception('VE send orphan alert failed for %s', pk)
    for ramp_tx in ve_send.open_sends().iterator():
        # Alerts are retried for every send, even ones waiting on ops.
        try:
            ve_send.ensure_alerted(ramp_tx)
        except Exception:
            logger.exception('VE send alert retry failed for %s', ramp_tx.pk)
        if not ve_send.due_for_sync(ramp_tx):
            continue
        checked += 1
        before = (ramp_tx.status, ramp_tx.status_detail)
        try:
            ramp_tx = ve_send.sync(ramp_tx)
            ve_send.ensure_alerted(ramp_tx)
        except Exception:
            logger.exception('VE send poll failed for %s', ramp_tx.pk)
            continue
        if (ramp_tx.status, ramp_tx.status_detail) != before:
            changed += 1
    return f'Polled {checked} VE Pago Móvil orders, updated {changed}'


@shared_task(name='ramps.tasks.poll_bolivia_qr_receives')
def poll_bolivia_qr_receives():
    """Advance QR Bolivia receives: payment, the provider's deposit on
    Polygon, then Relay's delivery to the person's BSC wallet. Sends ride
    poll_ve_pagomovil (the shared send core)."""
    from ramps import bolivia_qr_receive
    checked = changed = 0
    for ramp_tx in bolivia_qr_receive.open_orders().iterator():
        checked += 1
        before = (ramp_tx.status, ramp_tx.status_detail)
        try:
            ramp_tx = bolivia_qr_receive.sync(ramp_tx)
        except Exception:
            logger.exception('QR Bolivia receive poll failed for %s', ramp_tx.pk)
            continue
        if (ramp_tx.status, ramp_tx.status_detail) != before:
            changed += 1
    return f'Polled {checked} QR Bolivia receives, updated {changed}'


@shared_task(name='ramps.tasks.sync_ve_pagomovil_order')
def sync_ve_pagomovil_order(ramp_id: int):
    """A provider webhook's hint: re-read one order now."""
    from ramps import ve_pagomovil, ve_send
    from ramps.vexpay import sync_vexpay_ramp

    ramp_tx = RampTransaction.objects.filter(pk=ramp_id, country_code='VE').first()
    if ramp_tx is None:
        return
    if ramp_tx.direction == ve_pagomovil.SEND and ramp_tx.provider in ve_pagomovil.SEND_ADAPTERS:
        ve_send.sync(ramp_tx)
    elif ramp_tx.direction == ve_pagomovil.TOPUP and ramp_tx.provider == 'vexpay':
        sync_vexpay_ramp(ramp_tx)
