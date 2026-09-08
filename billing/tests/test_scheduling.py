from datetime import date, timedelta
from unittest import mock

from django.test import TransactionTestCase
from django.utils import timezone

from billing.models import (
    BillingEvent, BillingObligation, BillingOutboxMessage, BillingReminder,
    BillingSchedule, ObligationSubject,
)
from billing.scheduling import emit_due_reminders, generate_due_schedule_periods
from billing.tasks import dispatch_member_reminder_pushes
from users.models import Business, User


class BillingSchedulingTests(TransactionTestCase):
    def setUp(self):
        self.business = Business.objects.create(name='CIP', category='services')
        self.subject = ObligationSubject.objects.create(
            business=self.business, external_id='cip:42', subject_type='membership')

    def test_already_ended_schedule_does_not_generate_one_extra_debt(self):
        schedule = BillingSchedule.objects.create(
            business=self.business, subject=self.subject,
            external_reference='ended', amount_minor=5000,
            next_period_start=date(2026, 9, 1), end_date=date(2026, 8, 31))
        self.assertEqual(generate_due_schedule_periods(through_date=date(2026, 9, 1)), 0)
        schedule.refresh_from_db()
        self.assertEqual(schedule.status, 'completed')
        self.assertFalse(BillingObligation.objects.exists())

    def test_max_length_schedule_reference_generates_bounded_debt_reference(self):
        schedule = BillingSchedule.objects.create(
            business=self.business, subject=self.subject, external_reference='x' * 255,
            amount_minor=5000, next_period_start=date(2026, 9, 1), max_periods=1)
        self.assertEqual(generate_due_schedule_periods(through_date=date(2026, 9, 1)), 1)
        obligation = BillingObligation.objects.get(schedule=schedule)
        self.assertLessEqual(len(obligation.external_reference), 255)
        self.assertIn(schedule.public_id, obligation.external_reference)

    def test_sandbox_schedule_preserves_mode_in_debt_and_reminder_event(self):
        subject = ObligationSubject.objects.create(
            business=self.business, external_id='cip:42', mode='test')
        schedule = BillingSchedule.objects.create(
            business=self.business, subject=subject, mode='test',
            external_reference='sandbox', amount_minor=5000, max_periods=1,
            next_period_start=date(2026, 9, 1), reminder_offsets_days=[0])
        generate_due_schedule_periods(through_date=date(2026, 9, 1))
        obligation = BillingObligation.objects.get(schedule=schedule)
        self.assertEqual(obligation.mode, 'test')
        BillingReminder.objects.filter(obligation=obligation).update(
            scheduled_for=timezone.now() - timedelta(minutes=1))
        emit_due_reminders()
        self.assertEqual(BillingEvent.objects.get().mode, 'test')

    def test_generation_is_deterministic_bounded_and_never_auto_charges(self):
        schedule = BillingSchedule.objects.create(
            business=self.business, subject=self.subject,
            external_reference='cip:42:monthly', amount_minor=5_000,
            next_period_start=date(2026, 8, 1), anchor_day=1, max_periods=2)
        count = generate_due_schedule_periods(
            through_date=date(2026, 12, 31), limit=20)
        self.assertEqual(count, 2)
        schedule.refresh_from_db()
        self.assertEqual(schedule.status, 'completed')
        self.assertEqual(schedule.generated_periods, 2)
        obligations = BillingObligation.objects.filter(schedule=schedule).order_by('period_start')
        self.assertEqual(list(obligations.values_list('period_key', flat=True)),
                         ['2026-08-01', '2026-09-01'])
        self.assertTrue(all(item.status == 'open' for item in obligations))
        self.assertFalse(any(hasattr(item, 'payment') for item in obligations))
        self.assertEqual(BillingReminder.objects.filter(
            obligation__schedule=schedule).count(), 6)
        self.assertEqual(generate_due_schedule_periods(
            through_date=date(2026, 12, 31), limit=20), 0)

    def test_paid_obligation_suppresses_reminder(self):
        schedule = BillingSchedule.objects.create(
            business=self.business, subject=self.subject,
            external_reference='cip:42:once', amount_minor=5_000,
            next_period_start=date(2026, 9, 1), anchor_day=1, max_periods=1,
            reminder_offsets_days=[0])
        generate_due_schedule_periods(through_date=date(2026, 9, 1))
        obligation = BillingObligation.objects.get(schedule=schedule)
        reminder = BillingReminder.objects.get(obligation=obligation)
        BillingReminder.objects.filter(id=reminder.id).update(
            scheduled_for=timezone.now() - timedelta(minutes=1))
        BillingObligation.objects.filter(id=obligation.id).update(status='paid')
        self.assertEqual(emit_due_reminders(), 1)
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, 'suppressed')
        self.assertFalse(BillingEvent.objects.exists())

    def test_in_flight_payment_defers_reminder_until_failure_can_reopen_debt(self):
        schedule = BillingSchedule.objects.create(
            business=self.business, subject=self.subject,
            external_reference='pending-payment', amount_minor=5000,
            next_period_start=date(2026, 9, 1), max_periods=1,
            reminder_offsets_days=[0])
        generate_due_schedule_periods(through_date=date(2026, 9, 1))
        obligation = BillingObligation.objects.get(schedule=schedule)
        reminder = BillingReminder.objects.get(obligation=obligation)
        BillingReminder.objects.filter(id=reminder.id).update(
            scheduled_for=timezone.now() - timedelta(minutes=1))
        BillingObligation.objects.filter(id=obligation.id).update(status='payment_pending')
        emit_due_reminders()
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, 'pending')
        self.assertGreater(reminder.scheduled_for, timezone.now())
        self.assertFalse(BillingEvent.objects.exists())
        BillingObligation.objects.filter(id=obligation.id).update(status='open')
        BillingReminder.objects.filter(id=reminder.id).update(
            scheduled_for=timezone.now() - timedelta(minutes=1))
        emit_due_reminders()
        reminder.refresh_from_db()
        self.assertEqual(reminder.status, 'emitted')

    def test_due_reminder_is_an_idempotent_outbox_event(self):
        schedule = BillingSchedule.objects.create(
            business=self.business, subject=self.subject,
            external_reference='cip:42:reminder', amount_minor=5_000,
            next_period_start=date(2026, 9, 1), anchor_day=1, max_periods=1,
            reminder_offsets_days=[0])
        generate_due_schedule_periods(through_date=date(2026, 9, 1))
        reminder = BillingReminder.objects.get(obligation__schedule=schedule)
        BillingReminder.objects.filter(id=reminder.id).update(
            scheduled_for=timezone.now() - timedelta(minutes=1))
        self.assertEqual(emit_due_reminders(), 1)
        self.assertEqual(emit_due_reminders(), 0)
        event = BillingEvent.objects.get(event_type='obligation.reminder_due')
        self.assertEqual(event.payload['data']['object']['subject'], self.subject.public_id)
        self.assertEqual(BillingOutboxMessage.objects.filter(event=event).count(), 1)

    def test_linked_member_receives_one_durable_reminder_and_retryable_push(self):
        from notifications.models import Notification

        user = User.objects.create_user(username='reminded-member')
        self.subject.confio_user = user
        self.subject.save()
        schedule = BillingSchedule.objects.create(
            business=self.business, subject=self.subject,
            external_reference='member-reminder', amount_minor=5000,
            next_period_start=date(2026, 9, 1), max_periods=1,
            reminder_offsets_days=[0])
        generate_due_schedule_periods(through_date=date(2026, 9, 1))
        BillingReminder.objects.filter(obligation__schedule=schedule).update(
            scheduled_for=timezone.now() - timedelta(minutes=1))
        with mock.patch('notifications.utils.send_push_notification') as push:
            emit_due_reminders()
            emit_due_reminders()
        push.assert_not_called()
        notification = Notification.objects.get(user=user, related_object_type='BillingReminder')
        self.assertEqual(notification.action_url, 'confio://memberships')
        Notification.objects.filter(id=notification.id).update(
            updated_at=timezone.now() - timedelta(minutes=2))
        with mock.patch('notifications.fcm_service.send_push_notification',
                        side_effect=RuntimeError('temporary push outage')) as push:
            self.assertEqual(dispatch_member_reminder_pushes(), 1)
        push.assert_called_once()
        notification.refresh_from_db()
        self.assertFalse(notification.push_sent)
        self.assertGreater(notification.updated_at, timezone.now() - timedelta(minutes=1))
