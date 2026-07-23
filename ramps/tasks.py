from datetime import timedelta

from celery import shared_task
from django.utils import timezone

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


@shared_task
def poll_coinbase_ramp_transactions():
    """Reconcile Coinbase on/off-ramp records against CDP's transaction APIs.

    Coinbase has no partner webhooks, so this is the polling mirror of
    poll_guardarian_transactions: for every user with a non-final coinbase
    RampTransaction from the last 7 days, pull their buy and sell histories
    (keyed by partnerUserRef/partnerUserId = confio-<user_id>) and sync
    status + actual amounts. On-chain truth (the ALGO deposit / our signed
    payout group) is tracked separately by the deposit monitor and the
    Conversion rows; this task covers the FIAT side Coinbase owns.
    """
    from ramps.coinbase_cdp import (
        CoinbaseCdpError, list_buy_transactions, list_sell_transactions,
        map_cdp_status, partner_user_ref, _parse_amount,
    )

    window = timezone.now() - timedelta(days=7)
    pending = RampTransaction.objects.filter(
        provider='coinbase',
        status__in=['PENDING', 'PROCESSING'],
        created_at__gte=window,
        actor_user__isnull=False,
    ).select_related('actor_user')
    if not pending.exists():
        return 'No pending Coinbase ramps'

    updated = 0
    checked = 0
    # One CDP fetch per user, not per row.
    by_user: dict[int, list[RampTransaction]] = {}
    for tx in pending:
        by_user.setdefault(tx.actor_user_id, []).append(tx)

    for user_id, rows in by_user.items():
        ref = partner_user_ref(user_id)
        try:
            remote = {
                'on_ramp': list_buy_transactions(ref),
                'off_ramp': list_sell_transactions(ref),
            }
        except CoinbaseCdpError as exc:
            logger.warning('Coinbase poll failed for %s: %s', ref, exc)
            continue

        for row in rows:
            checked += 1
            candidates = remote.get(row.direction) or []
            match = None
            if row.provider_order_id:
                for c in candidates:
                    cid = c.get('transaction_id') or c.get('id') or ''
                    if cid and cid == row.provider_order_id:
                        match = c
                        break
            if match is None and candidates and not row.provider_order_id:
                # Session-time rows have no CDP id yet; adopt the newest
                # transaction in this direction (CDP returns newest first).
                match = candidates[0]
                row.provider_order_id = match.get('transaction_id') or match.get('id') or ''
            if match is None:
                continue

            new_status = map_cdp_status(str(match.get('status', '')))
            changed = False
            if new_status != row.status:
                row.status = new_status
                row.status_detail = str(match.get('status', ''))[:500]
                if new_status == 'COMPLETED':
                    row.completed_at = timezone.now()
                changed = True
            amount_key = 'purchase_amount' if row.direction == 'on_ramp' else 'sell_amount'
            actual = _parse_amount(match.get(amount_key))
            if actual and row.crypto_amount_actual is None:
                try:
                    from decimal import Decimal
                    row.crypto_amount_actual = Decimal(actual)
                    changed = True
                except Exception:
                    pass
            if changed:
                row.save(update_fields=[
                    'status', 'status_detail', 'completed_at',
                    'crypto_amount_actual', 'provider_order_id', 'updated_at',
                ])
                updated += 1
                logger.info('Coinbase ramp %s -> %s', row.internal_id, row.status)

    return f'Polled {checked} Coinbase ramps, updated {updated}'
