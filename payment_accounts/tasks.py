from datetime import timedelta
import logging

from celery import shared_task
from django.utils import timezone

from payment_accounts.models import MoneyOperation, ProviderWebhookEvent
from payment_accounts.providers import get_provider
from payment_accounts.services import _sync_flow_status, apply_operation_result
from payment_accounts.services import submit_money_operation
from payment_accounts.webhooks import process_webhook_event

logger = logging.getLogger(__name__)


@shared_task(name='payment_accounts.reconcile_bridges')
def reconcile_bridges():
    from .models import PaymentBridgeTransfer
    from .bridge_execution import reconcile_bridge
    from django.db.models import Q
    rows = PaymentBridgeTransfer.objects.filter(
        Q(status__in=['prepared', 'submitted', 'bridging', 'needs_review']) |
        Q(status='delivered', provider_credit__isnull=True, quote__destination_token_id='POL:USDC',
          quote__funding_instruction__financial_account__provider_profile__provider__in=['cobre', 'infinia'])
    ).select_related('quote__confio_account', 'quote__money_flow', 'batch').order_by('updated_at')[:100]
    count = 0
    for row in rows:
        try:
            reconcile_bridge(row)
            count += 1
        except Exception:
            logger.exception('Bridge reconciliation failed: %s', row.internal_id)
        finally:
            # Fair rotation even for an unavailable RPC or a manual-review row.
            PaymentBridgeTransfer.objects.filter(pk=row.pk).update(updated_at=timezone.now())
    return count


@shared_task(
    name='payment_accounts.process_webhook',
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={'max_retries': 5},
)
def process_webhook(event_id):
    event = ProviderWebhookEvent.objects.get(id=event_id)
    process_webhook_event(event)


@shared_task(name='payment_accounts.reconcile_operations')
def reconcile_operations():
    cutoff = timezone.now() - timedelta(minutes=30)
    operations = MoneyOperation.objects.filter(
        status__in=['submitted', 'processing', 'settling', 'unknown'],
        updated_at__lte=cutoff,
    ).select_related('source_account', 'destination_account')[:200]
    reconciled = 0
    for operation in operations:
        try:
            result = get_provider(operation.provider).retrieve_operation_by_idempotency(operation)
            if result:
                apply_operation_result(operation, result)
                reconciled += 1
            else:
                # The lookup runs outside a transaction. A webhook or another
                # reconciler may change the operation while it is in flight.
                # CAS the complete submission snapshot; do not hold operation
                # locks while submitting (which also locks accounts/journeys).
                snapshot = {field: getattr(operation, field) for field in (
                    'pk', 'provider', 'status', 'updated_at', 'submitted_at',
                    'provider_operation_id', 'idempotency_key', 'money_flow_id',
                    'operation_type', 'source_account_id', 'destination_account_id',
                    'source_asset', 'source_amount', 'target_asset', 'external_destination',
                )}
                age = timezone.now() - (operation.submitted_at or operation.created_at)
                can_retry = operation.provider == 'infinia' or age < timedelta(hours=23)
                updates = {'status': 'unknown' if can_retry else 'needs_review', 'updated_at': timezone.now()}
                if not can_retry:
                    # Cobre idempotency keys expire after 24 hours. Never
                    # recreate an unresolved older economic instruction.
                    updates.update(failure_code='reconciliation_not_found', failure_detail=(
                        'Provider operation was not found before idempotency expiry'))
                if not MoneyOperation.objects.filter(**snapshot).update(**updates):
                    continue
                if can_retry:
                    submit_money_operation(operation)
                    reconciled += 1
                else:
                    _sync_flow_status(operation.money_flow)
        except Exception:
            logger.exception('Payment operation reconciliation failed: %s', operation.internal_id)
    return reconciled


@shared_task(name='payment_accounts.reconcile_infinia_journeys')
def reconcile_infinia_journeys():
    from .models import InfiniaJourney
    from .infinia_journeys import advance_journey
    rows = InfiniaJourney.objects.exclude(stage__in=['completed', 'failed', 'needs_review']).order_by('updated_at')[:100]
    count = 0
    for row in rows:
        try:
            advance_journey(row.pk)
            count += 1
        except Exception:
            logger.exception('Infinia journey reconciliation failed: %s', row.internal_id)
        finally:
            InfiniaJourney.objects.filter(pk=row.pk).update(updated_at=timezone.now())
    return count


@shared_task(name='payment_accounts.reconcile_cobre_journeys')
def reconcile_cobre_journeys():
    from .models import CobreJourney
    from .cobre_journeys import advance_journey
    rows = CobreJourney.objects.exclude(stage__in=['completed', 'failed', 'needs_review']).order_by('updated_at')[:100]
    count = 0
    for row in rows:
        try:
            advance_journey(row.pk)
            count += 1
        except Exception:
            logger.exception('Cobre journey reconciliation failed: %s', row.internal_id)
        finally:
            CobreJourney.objects.filter(pk=row.pk).update(updated_at=timezone.now())
    return count
