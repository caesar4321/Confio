import calendar
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from .models import (
    BillingEvent, BillingObligation, BillingOutboxMessage, BillingReminder,
    BillingSchedule,
)


def add_months(value, months, anchor_day):
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return value.replace(
        year=year, month=month,
        day=min(anchor_day, calendar.monthrange(year, month)[1]))


def _create_period(schedule):
    start = schedule.next_period_start
    next_start = add_months(start, schedule.interval_months, schedule.anchor_day)
    end = next_start - timedelta(days=1)
    period_key = start.isoformat()
    obligation, created = BillingObligation.objects.get_or_create(
        schedule=schedule, period_key=period_key,
        defaults={
            'business': schedule.business, 'subject': schedule.subject,
            'mode': schedule.mode,
            'external_reference': f'{schedule.public_id}:{period_key}',
            'currency': schedule.currency,
            'original_amount_minor': schedule.amount_minor,
            'amount_remaining_minor': schedule.amount_minor,
            'line_items_snapshot': [{
                'kind': 'recurring_bill', 'schedule': schedule.public_id,
                'amount_minor': schedule.amount_minor,
            }],
            'period_start': start, 'period_end': end,
            'issued_at': timezone.now(),
            'due_at': datetime.combine(
                start + timedelta(days=schedule.days_until_due), time(23, 59, 59),
                tzinfo=ZoneInfo(schedule.timezone)),
            'status': 'open', 'source_version': 'schedule-v1',
        })
    if created:
        for offset in sorted(set(schedule.reminder_offsets_days), reverse=True):
            if not isinstance(offset, int) or not -365 <= offset <= 365:
                continue
            scheduled_date = obligation.due_at.astimezone(
                ZoneInfo(schedule.timezone)).date() - timedelta(days=offset)
            BillingReminder.objects.create(
                obligation=obligation, offset_days=offset,
                scheduled_for=datetime.combine(
                    scheduled_date, time(9), tzinfo=ZoneInfo(schedule.timezone)))
    schedule.next_period_start = next_start
    schedule.generated_periods += 1
    if ((schedule.end_date and next_start > schedule.end_date)
            or (schedule.max_periods and schedule.generated_periods >= schedule.max_periods)):
        schedule.status = 'completed'
    schedule.version += 1
    schedule.save(update_fields=(
        'next_period_start', 'generated_periods', 'status', 'version', 'updated_at'))
    return obligation, created


def generate_due_schedule_periods(*, through_date=None, limit=500):
    through_date = through_date or timezone.localdate()
    generated = 0
    while generated < limit:
        with transaction.atomic():
            schedule = BillingSchedule.objects.select_for_update(skip_locked=True).filter(
                status='active', next_period_start__lte=through_date,
            ).order_by('next_period_start', 'id').first()
            if schedule is None:
                break
            if ((schedule.end_date and schedule.next_period_start > schedule.end_date)
                    or (schedule.max_periods is not None
                        and schedule.generated_periods >= schedule.max_periods)):
                schedule.status = 'completed'
                schedule.save(update_fields=('status', 'updated_at'))
                continue
            if schedule.subject.mode != schedule.mode:
                raise ValueError('schedule and subject modes differ')
            _create_period(schedule)
        generated += 1
    return generated


def emit_due_reminders(*, limit=500):
    emitted = 0
    while emitted < limit:
        with transaction.atomic():
            reminder = BillingReminder.objects.select_for_update(skip_locked=True).select_related(
                'obligation__subject').filter(
                    status='pending', scheduled_for__lte=timezone.now(),
                ).order_by('scheduled_for', 'id').first()
            if reminder is None:
                break
            obligation = reminder.obligation
            if obligation.status == 'payment_pending':
                # An in-flight payment may still fail. Delay the reminder
                # until its outcome is known instead of consuming it forever.
                reminder.scheduled_for = timezone.now() + timedelta(minutes=5)
                reminder.save(update_fields=('scheduled_for', 'updated_at'))
                emitted += 1
                continue
            if obligation.status not in ('open', 'past_due'):
                reminder.status = 'suppressed'
            else:
                kind = ('upcoming' if reminder.offset_days > 0 else
                        'due' if reminder.offset_days == 0 else 'past_due')
                event, _ = BillingEvent.objects.get_or_create(
                    business_id=obligation.business_id,
                    transition_key=f'obligation:{obligation.id}:reminder:{reminder.offset_days}',
                    defaults={
                        'event_type': f'obligation.reminder_{kind}',
                        'mode': obligation.mode,
                        'aggregate_type': 'obligation',
                        'aggregate_id': obligation.public_id,
                        'aggregate_version': 10_000 + reminder.offset_days,
                        'payload': {
                            'object': 'event', 'type': f'obligation.reminder_{kind}',
                            'data': {'object': {
                                'id': obligation.public_id, 'object': 'obligation',
                                'subject': obligation.subject.public_id,
                                'status': obligation.status,
                                'due_at': obligation.due_at.isoformat(),
                                'commercial_amount': {
                                    'minor_units': obligation.amount_remaining_minor,
                                    'currency': obligation.currency,
                                },
                            }},
                        },
                    })
                BillingOutboxMessage.objects.get_or_create(
                    event=event, defaults={'available_at': timezone.now()})
                if obligation.mode == 'live' and obligation.subject.confio_user_id:
                    from notifications.models import NotificationType
                    from notifications.utils import create_notification

                    create_notification(
                        user=obligation.subject.confio_user,
                        notification_type=NotificationType.SYSTEM,
                        title='Tienes una cuota pendiente',
                        message='Revisa tu cuota y confirma el pago cuando estés listo.',
                        data={'obligation': obligation.public_id,
                              'reminder': str(reminder.id)},
                        related_object_type='BillingReminder',
                        related_object_id=str(reminder.id),
                        action_url='confio://memberships', send_push=False,
                    )
                reminder.status = 'emitted'
                reminder.emitted_at = timezone.now()
            reminder.save(update_fields=('status', 'emitted_at', 'updated_at'))
        emitted += 1
    return emitted
