from datetime import timedelta
from unittest import mock

from django.db import IntegrityError
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from billing.models import BillingEvent, BillingOutboxMessage, WebhookEndpoint
from billing.tasks import dispatch_due_webhooks, dispatch_outbox
from billing.webhooks import enqueue_event_deliveries
from users.models import Business


@override_settings(CONFIO_GLOBAL_WALLET_MASTER_KEY=(
    'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='))
class BillingDispatchTests(TransactionTestCase):
    def setUp(self):
        self.business = Business.objects.create(name='Task merchant', category='services')
        self.event = BillingEvent.objects.create(
            business=self.business, event_type='payment.confirmed', mode='test',
            aggregate_type='payment', aggregate_id='pay_dispatch', aggregate_version=1,
            transition_key='payment:dispatch', payload={'object': 'event'})

    def test_stale_webhook_lease_is_dispatched_after_worker_crash(self):
        WebhookEndpoint.objects.create(
            business=self.business, mode='test', url='https://example.test/hook',
            secret='whsec_task')
        delivery = enqueue_event_deliveries(self.event)[0]
        delivery.status = 'leased'
        delivery.leased_at = timezone.now() - timedelta(minutes=3)
        delivery.save()
        with mock.patch('billing.tasks.deliver_webhook.delay') as send:
            self.assertEqual(dispatch_due_webhooks(), 1)
        send.assert_called_once_with(delivery.id)
        delivery.leased_at = timezone.now()
        delivery.save()
        with mock.patch('billing.tasks.deliver_webhook.delay') as send:
            self.assertEqual(dispatch_due_webhooks(), 0)
        send.assert_not_called()

    def test_database_dispatch_failure_can_be_saved_and_retried(self):
        message = BillingOutboxMessage.objects.create(
            event=self.event, available_at=timezone.now())

        def database_failure(event):
            BillingOutboxMessage.objects.create(event=event, available_at=timezone.now())

        with mock.patch('billing.tasks.enqueue_event_deliveries', side_effect=database_failure):
            self.assertEqual(dispatch_outbox(), 1)
        message.refresh_from_db()
        self.assertEqual(message.status, 'failed')
        self.assertEqual(message.last_error, IntegrityError.__name__)
        self.assertEqual(message.attempts, 1)
        self.assertGreater(message.available_at, timezone.now())
