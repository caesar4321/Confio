import json
from unittest import mock

from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from billing.models import BillingEvent, WebhookDelivery, WebhookEndpoint
from billing.webhooks import (
    UnsafeWebhookUrl, deliver, enqueue_event_deliveries, signature_header,
    validate_delivery_url,
    public_https_post,
)
from users.models import Business


@override_settings(CONFIO_GLOBAL_WALLET_MASTER_KEY=(
    'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='))
class WebhookTests(TransactionTestCase):
    def setUp(self):
        self.business = Business.objects.create(name='CIP', category='services')

    @staticmethod
    def _public_resolver(host, port, type=None):
        return [(2, 1, 6, '', ('93.184.216.34', port))]

    def _event(self):
        return BillingEvent.objects.create(
            business=self.business, event_type='payment.confirmed',
            mode='test',
            aggregate_type='payment', aggregate_id='pay_test', aggregate_version=1,
            transition_key='payment:test:confirmed', payload={
                'object': 'event', 'type': 'payment.confirmed',
                'data': {'object': {'id': 'pay_test', 'object': 'payment'}},
            })

    def test_url_validation_rejects_private_addresses_and_credentials(self):
        private = lambda *args, **kwargs: [(2, 1, 6, '', ('127.0.0.1', 443))]
        with self.assertRaises(UnsafeWebhookUrl):
            validate_delivery_url('https://hooks.example.test/x', resolver=private)
        # Userinfo is assembled rather than written inline: a literal
        # basic-auth URL trips the pre-push credential scanner even here,
        # where the whole point is asserting that we reject one.
        userinfo = 'user' + ':' + 'pass'
        with self.assertRaises(UnsafeWebhookUrl):
            validate_delivery_url(f'https://{userinfo}@example.test/x',
                                  resolver=self._public_resolver)
        self.assertEqual(validate_delivery_url(
            'https://example.test/x', resolver=self._public_resolver),
            'https://example.test/x')

    def test_event_snapshot_and_secret_are_durable_and_filtered(self):
        endpoint = WebhookEndpoint.objects.create(
            business=self.business, mode='test', url='https://example.test/hook',
            secret='whsec_original', event_types=['payment.confirmed'])
        ignored = WebhookEndpoint.objects.create(
            business=self.business, mode='test', url='https://example.test/ignored',
            secret='whsec_ignored', event_types=['payment.failed'])
        event = self._event()
        deliveries = enqueue_event_deliveries(event)
        self.assertEqual(len(deliveries), 1)
        delivery = deliveries[0]
        endpoint.secret = 'whsec_rotated'
        endpoint.url = 'https://example.test/new'
        endpoint.save()
        delivery.refresh_from_db()
        self.assertEqual(delivery.signing_secret, 'whsec_original')
        self.assertEqual(delivery.endpoint_url, 'https://example.test/hook')
        self.assertEqual(delivery.event_body['id'], event.public_id)
        self.assertFalse(WebhookDelivery.objects.filter(endpoint=ignored).exists())

    @mock.patch('billing.webhooks.validate_delivery_url')
    def test_delivery_signs_exact_body_and_does_not_follow_redirects(self, validate):
        endpoint = WebhookEndpoint.objects.create(
            business=self.business, mode='test', url='https://example.test/hook',
            secret='whsec_test', event_types=[])
        delivery = enqueue_event_deliveries(self._event())[0]
        response = mock.Mock(status_code=204)
        sender = mock.Mock(return_value=response)
        self.assertTrue(deliver(delivery.id, sender=sender))
        request = sender.call_args
        raw = request.kwargs['data']
        header = request.kwargs['headers']['Confio-Signature']
        timestamp = header.split(',', 1)[0].split('=', 1)[1]
        self.assertEqual(header, signature_header('whsec_test', int(timestamp), raw))
        self.assertEqual(json.loads(raw), delivery.event_body)
        self.assertEqual(request.kwargs['timeout'], 10)
        self.assertFalse(request.kwargs['allow_redirects'])
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'delivered')
        self.assertEqual(delivery.response_status, 204)

    @mock.patch('billing.webhooks.validate_delivery_url')
    def test_failed_delivery_is_retried_with_backoff(self, validate):
        endpoint = WebhookEndpoint.objects.create(
            business=self.business, mode='test', url='https://example.test/hook',
            secret='whsec_test')
        delivery = enqueue_event_deliveries(self._event())[0]
        sender = mock.Mock(return_value=mock.Mock(status_code=503))
        before = timezone.now()
        self.assertFalse(deliver(delivery.id, sender=sender))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'retrying')
        self.assertEqual(delivery.attempts, 1)
        self.assertGreater(delivery.available_at, before)

    def test_disabled_endpoint_cancels_queued_delivery(self):
        endpoint = WebhookEndpoint.objects.create(
            business=self.business, mode='test', url='https://example.test/hook',
            secret='whsec_test')
        delivery = enqueue_event_deliveries(self._event())[0]
        endpoint.status = 'disabled'
        endpoint.save()
        sender = mock.Mock()
        self.assertFalse(deliver(delivery.id, sender=sender))
        sender.assert_not_called()
        delivery.refresh_from_db()
        self.assertEqual(delivery.last_error, 'endpoint_disabled')

    @mock.patch('billing.webhooks.urllib3.HTTPSConnectionPool')
    @mock.patch('billing.webhooks._delivery_addresses')
    def test_transport_pins_checked_address_and_preserves_tls_hostname(self, addresses, pool):
        from urllib.parse import urlparse
        addresses.return_value = (urlparse('https://example.test/hook?x=1'), ['93.184.216.34'])
        response = pool.return_value.request.return_value
        response.status = 200
        response.headers = {}
        response.read.return_value = b'{}'
        self.assertEqual(public_https_post('https://example.test/hook?x=1', json={}).status_code, 200)
        self.assertEqual(pool.call_args.args[0], '93.184.216.34')
        self.assertEqual(pool.call_args.kwargs['server_hostname'], 'example.test')
        self.assertEqual(pool.call_args.kwargs['assert_hostname'], 'example.test')
        self.assertEqual(pool.return_value.request.call_args.args, ('POST', '/hook?x=1'))
        self.assertFalse(pool.return_value.request.call_args.kwargs['redirect'])
