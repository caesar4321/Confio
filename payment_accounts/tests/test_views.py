import json
from unittest import mock

from django.test import RequestFactory, TestCase, override_settings

from payment_accounts.models import ProviderWebhookEvent
from payment_accounts.views import cobre_webhook


@override_settings(COBRE_WEBHOOK_SECRET='webhook-secret')
class WebhookDispatchTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def _request():
        import hashlib
        import hmac

        body = json.dumps({
            'id': 'evt_dispatch',
            'event_key': 'money_movement.completed',
            'content': {'id': 'mm_1'},
        }).encode()
        timestamp = '1723377600'
        signature = hmac.new(
            b'webhook-secret', timestamp.encode() + b'.' + body, hashlib.sha256
        ).hexdigest()
        return RequestFactory().post(
            '/api/payment-accounts/cobre/webhook/',
            data=body,
            content_type='application/json',
            HTTP_EVENT_TIMESTAMP=timestamp,
            HTTP_EVENT_SIGNATURE=signature,
        )

    @mock.patch('payment_accounts.views.process_webhook.delay')
    def test_duplicate_received_event_is_reenqueued_after_broker_failure(self, delay):
        delay.side_effect = RuntimeError('broker unavailable')
        first = cobre_webhook(self._request())
        self.assertEqual(first.status_code, 503)
        self.assertEqual(ProviderWebhookEvent.objects.count(), 1)

        delay.side_effect = None
        second = cobre_webhook(self._request())

        self.assertEqual(second.status_code, 200)
        self.assertJSONEqual(second.content, {'ok': True, 'duplicate': True})
        self.assertEqual(delay.call_count, 2)
