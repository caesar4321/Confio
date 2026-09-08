from celery import shared_task
import logging
from datetime import timedelta
from django.utils import timezone

from .institutions import apply_payment
from django.db import transaction
from django.db.models import Q

from .models import BillingOutboxMessage, InstitutionApplication, WebhookDelivery
from .webhooks import deliver, enqueue_event_deliveries
from .scheduling import emit_due_reminders, generate_due_schedule_periods

logger = logging.getLogger(__name__)


@shared_task(name='billing.deliver_webhook')
def deliver_webhook(delivery_id):
    return deliver(delivery_id)


@shared_task(name='billing.dispatch_due_webhooks')
def dispatch_due_webhooks(limit=100):
    ids = list(WebhookDelivery.objects.filter(
        Q(status__in=('pending', 'retrying'), available_at__lte=timezone.now())
        | (Q(status='leased') & (
            Q(leased_at__lte=timezone.now() - timedelta(minutes=2))
            | Q(leased_at__isnull=True)))
    ).order_by('available_at', 'id').values_list('id', flat=True)[:limit])
    for delivery_id in ids:
        deliver_webhook.delay(delivery_id)
    return len(ids)


@shared_task(name='billing.dispatch_outbox')
def dispatch_outbox(limit=100):
    dispatched = 0
    while dispatched < limit:
        with transaction.atomic():
            message = BillingOutboxMessage.objects.select_for_update(
                skip_locked=True).select_related('event').filter(
                    status__in=('pending', 'failed'),
                    available_at__lte=timezone.now()).order_by('available_at', 'id').first()
            if message is None:
                break
            try:
                with transaction.atomic():
                    enqueue_event_deliveries(message.event)
                message.status = 'dispatched'
                message.dispatched_at = timezone.now()
                message.last_error = ''
            except Exception as exc:
                message.status = 'failed'
                message.last_error = type(exc).__name__[:500]
                message.available_at = timezone.now() + timedelta(minutes=1)
            message.attempts += 1
            message.save(update_fields=(
                'status', 'dispatched_at', 'last_error', 'attempts', 'available_at',
                'updated_at'))
        dispatched += 1
    return dispatched


@shared_task(name='billing.apply_institution_payment')
def apply_institution_payment(application_id):
    return apply_payment(application_id)


@shared_task(name='billing.dispatch_due_institution_applications')
def dispatch_due_institution_applications(limit=100):
    ids = list(InstitutionApplication.objects.filter(
        status='application_pending', available_at__lte=timezone.now()
    ).order_by('available_at', 'id').values_list('id', flat=True)[:limit])
    for application_id in ids:
        apply_institution_payment.delay(application_id)
    return len(ids)


@shared_task(name='billing.generate_due_schedule_periods')
def generate_due_schedules(limit=500):
    return generate_due_schedule_periods(limit=limit)


@shared_task(name='billing.emit_due_reminders')
def emit_reminders(limit=500):
    count = emit_due_reminders(limit=limit)
    dispatch_member_reminder_pushes(limit=min(limit, 100))
    return count


def dispatch_member_reminder_pushes(*, limit=100):
    """Retry durable member notifications through the existing push service."""
    from notifications.models import Notification
    from notifications.fcm_service import send_push_notification
    from .models import BillingObligation

    now = timezone.now()
    ids = list(Notification.objects.filter(
        related_object_type='BillingReminder', push_sent=False,
        created_at__gte=now - timedelta(days=7),
        updated_at__lte=now - timedelta(minutes=1),
    ).order_by('updated_at', 'id').values_list('id', flat=True)[:limit])
    for notification_id in ids:
        with transaction.atomic():
            notification = Notification.objects.select_for_update(skip_locked=True).filter(
                id=notification_id, push_sent=False).first()
            if notification is None:
                continue
            obligation = BillingObligation.objects.filter(
                public_id=notification.data.get('obligation'), mode='live',
                subject__confio_user_id=notification.user_id,
                status__in=('open', 'past_due'),
            ).first()
            if obligation is None:
                notification.updated_at = timezone.now()
                notification.save(update_fields=('updated_at',))
                continue
            # The notification lock prevents concurrent workers pushing the
            # same reminder. Failed pushes stay durable and retry next run.
            try:
                send_push_notification(notification)
            except Exception:
                logger.exception('Member reminder push failed for %s', notification.id)
            finally:
                notification.updated_at = timezone.now()
                notification.save(update_fields=('updated_at',))
    return len(ids)
