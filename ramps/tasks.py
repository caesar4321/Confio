from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from ramps.koywe_client import KoyweClient, KoyweError
from ramps.koywe_sync import sync_koywe_ramp_transaction_from_order
from ramps.models import KoyweBankInfo, RampTransaction

import logging

logger = logging.getLogger(__name__)

KOYWE_SUPPORTED_COUNTRIES = ['COL', 'PER', 'BOL', 'ARG', 'MEX', 'CHL', 'BRA']


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
    Poll Koywe for recent non-terminal ramp orders.
    Webhooks are the primary source of truth; this is a reconciliation fallback.
    """
    client = KoyweClient()
    if not client.is_configured:
        logger.warning('Skipping Koywe ramp poll: client not configured')
        return 'Koywe not configured'

    threshold = timezone.now() - timedelta(days=7)
    pending_ramps = RampTransaction.objects.filter(
        provider='koywe',
        created_at__gte=threshold,
        status__in=['PENDING', 'PROCESSING', 'AML_REVIEW'],
    ).order_by('-created_at')

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
            ramp_tx.refresh_from_db(fields=['status', 'status_detail'])
            if ramp_tx.status != previous_status or ramp_tx.status_detail != previous_detail:
                updated_count += 1
        except KoyweError as exc:
            logger.warning('Koywe poll failed for %s: %s', ramp_tx.provider_order_id, exc)
        except Exception:
            logger.exception('Unexpected Koywe poll failure for %s', ramp_tx.provider_order_id)

    return f'Polled {checked_count} Koywe ramps, updated {updated_count}'
