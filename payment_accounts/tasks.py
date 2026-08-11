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
                age = timezone.now() - (operation.submitted_at or operation.created_at)
                if operation.provider == 'infinia' or age < timedelta(hours=23):
                    operation.status = 'unknown'
                    operation.save(update_fields=['status', 'updated_at'])
                    submit_money_operation(operation)
                    reconciled += 1
                else:
                    # Cobre idempotency keys expire after 24 hours. Retrying an
                    # unresolved older request could create a duplicate payout.
                    operation.status = 'needs_review'
                    operation.failure_code = 'reconciliation_not_found'
                    operation.failure_detail = (
                        'Provider operation was not found before idempotency expiry'
                    )
                    operation.save(
                        update_fields=[
                            'status', 'failure_code', 'failure_detail', 'updated_at'
                        ]
                    )
                    _sync_flow_status(operation.money_flow)
        except Exception:
            logger.exception('Payment operation reconciliation failed: %s', operation.internal_id)
    return reconciled
