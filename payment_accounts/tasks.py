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
    from .auto_payin import reconcile as reconcile_payins
    reconcile_payins()
    from .models import InfiniaJourney
    from .infinia_journeys import advance_journey
    from .infinia_bridge import live_journeys
    rows = live_journeys(InfiniaJourney.objects.all()).order_by('updated_at')[:100]
    count = 0
    for row in rows:
        try:
            advance_journey(row.pk)
            count += 1
        except Exception:
            logger.exception('Infinia journey reconciliation failed: %s', row.internal_id)
        finally:
            InfiniaJourney.objects.filter(pk=row.pk).update(updated_at=timezone.now())
    # Terminal journeys no longer advance, but their wallet projection can
    # still need repair after a missed callback or a later mint confirmation.
    from .activity import refresh_stale_activity
    refresh_stale_activity()
    return count


@shared_task(name='payment_accounts.reconcile_cobre_journeys')
def reconcile_cobre_journeys():
    from .models import CobreJourney
    from .cobre_journeys import advance_journey
    from .infinia_bridge import live_journeys
    rows = live_journeys(CobreJourney.objects.all(), recoverable=()).order_by('updated_at')[:100]
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


@shared_task(name='payment_accounts.reconcile_activations')
def reconcile_activations():
    from .models import AccountActivation
    from .activation import reconcile
    rows = AccountActivation.objects.filter(status__in=['provisioning', 'awaiting_payment', 'payment_pending']).order_by('updated_at')[:100]
    for row in rows:
        try:
            reconcile(row.pk)
        except Exception:
            logger.exception('Account activation reconciliation failed: %s', row.internal_id)
        finally:
            AccountActivation.objects.filter(pk=row.pk).update(updated_at=timezone.now())


@shared_task(name='payment_accounts.forward_edd', autoretry_for=(Exception,),
             retry_backoff=True, retry_kwargs={'max_retries': 5})
def forward_edd(request_id):
    from .edd import forward_to_provider
    from .models import LimitIncreaseRequest
    row = LimitIncreaseRequest.objects.get(pk=request_id)
    if row.status not in ('submitted', 'in_review'):
        return row.status
    try:
        return forward_to_provider(row).status
    except Exception:
        # HTTP exception chains can contain presigned evidence credentials.
        # Celery logs the raised exception on retries and final failure.
        from .services import PaymentAccountError
        raise PaymentAccountError('Automatic EDD handoff failed; retry pending') from None


@shared_task(name='payment_accounts.reconcile_edd')
def reconcile_edd():
    """Recover missed dispatches and retry handoffs, including owners opened later."""
    from .edd import forward_to_provider, sync_edd_session
    from .models import LimitIncreaseRequest
    rows = LimitIncreaseRequest.objects.filter(
        status__in=['started', 'submitted', 'in_review'],
        didit_session_id__isnull=False,
    ).order_by('updated_at')[:100]
    forwarded = 0
    for row in rows:
        try:
            # Polling also recovers a missed Didit webhook. Dispatch directly here.
            row = sync_edd_session(row.didit_session_id, enqueue=False)
            if row.status in ('submitted', 'in_review'):
                forwarded += forward_to_provider(row).status == 'forwarded'
        except Exception:
            logger.warning('EDD handoff pending: %s', row.internal_id)
        finally:
            LimitIncreaseRequest.objects.filter(pk=row.pk).update(updated_at=timezone.now())
    return forwarded
