import hashlib
import hmac
import json
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings

from ramps.stereum_client import StereumClient, StereumError, amount, resource_id


@override_settings(STEREUM_TEST_ENABLED=True, STEREUM_ENV='sandbox', STEREUM_API_KEY='test-key', STEREUM_SECRET_KEY='test-secret', STEREUM_TEST_WRITES_ENABLED=True)
class StereumClientTests(SimpleTestCase):
    def setUp(self):
        self.session = Mock()
        self.session.request.return_value.status_code = 200
        self.session.request.return_value.json.return_value = {'id': 'test-id'}
        self.client = StereumClient(session=self.session)

    def test_signature_covers_exact_utf8_body_and_timestamp(self):
        with patch('ramps.stereum_client.time.time', return_value=1800000000):
            self.client.send_transfer({'comment': 'Pago de José', 'amount': '1.00'})
        kwargs = self.session.request.call_args.kwargs
        body = kwargs['data']
        self.assertEqual(json.loads(body), {'comment': 'Pago de José', 'amount': '1.00'})
        self.assertEqual(kwargs['headers']['x-signature'], hmac.new(b'test-secret', body, hashlib.sha256).hexdigest())
        self.assertEqual(kwargs['headers']['x-timestamp'], '1800000000')
        self.assertFalse(kwargs['allow_redirects'])

    def test_qr_payment_has_long_timeout_and_signature(self):
        self.client.send_transfer({'amount': '1.00'}, qr=True)
        args, kwargs = self.session.request.call_args
        self.assertTrue(args[1].endswith('/send-qr'))
        self.assertEqual(kwargs['timeout'], 70)
        self.assertIn('x-signature', kwargs['headers'])

    def test_quotes_are_not_signed_and_use_correct_networks(self):
        self.client.create_quote(side='BUY', value='1000')
        kwargs = self.session.request.call_args.kwargs
        payload = json.loads(kwargs['data'])
        self.assertEqual(payload['inputNetwork'], 'CSL')
        self.assertEqual(payload['outputNetwork'], 'POLYGON')
        self.assertNotIn('x-signature', kwargs['headers'])

    @override_settings(STEREUM_TEST_WRITES_ENABLED=False)
    def test_disabled_writes_cannot_reach_provider(self):
        with self.assertRaises(StereumError):
            self.client.create_order({'quoteId': 'id'})
        self.session.request.assert_not_called()

    @override_settings(STEREUM_ENV='production')
    def test_production_is_not_a_sandbox_alias(self):
        with self.assertRaises(StereumError):
            StereumClient(session=self.session)

    def test_production_response_is_quarantined(self):
        self.session.request.return_value.json.return_value = {'id': 'x', 'on_main_net': True}
        with self.assertRaises(StereumError) as caught:
            self.client.create_charge({})
        self.assertTrue(caught.exception.ambiguous)

    def test_post_timeout_is_ambiguous_and_not_retried(self):
        self.session.request.side_effect = requests.Timeout('secret-key-in-exception')
        with self.assertRaises(StereumError) as caught:
            self.client.create_order({})
        self.assertTrue(caught.exception.ambiguous)
        self.assertNotIn('secret-key', str(caught.exception))
        self.assertEqual(self.session.request.call_count, 1)

    def test_errors_do_not_echo_provider_personal_data(self):
        self.session.request.return_value.status_code = 400
        self.session.request.return_value.json.return_value = {'code': 'INVENTORY_NOT_FOUND', 'message': 'secret-key customer details'}
        with self.assertRaises(StereumError) as caught:
            self.client.create_quote(side='SELL', value='100')
        self.assertEqual(caught.exception.code, 'INVENTORY_NOT_FOUND')
        self.assertNotIn('customer', str(caught.exception))

    def test_webhook_requires_valid_raw_body_signature(self):
        body = b'{"notification_type":"order"}'
        signature = hmac.new(b'test-secret', body, hashlib.sha256).hexdigest()
        self.assertTrue(self.client.verify_webhook(body, signature))
        self.assertFalse(self.client.verify_webhook(body + b' ', signature))
        self.assertFalse(self.client.verify_webhook(body, ''))

    def test_untrusted_ids_cannot_change_paths(self):
        for value in ['../auth', 'id?x=1', 'id/other', '']:
            with self.subTest(value=value), self.assertRaises(StereumError):
                resource_id(value)

    def test_non_finite_or_overprecision_amounts_are_rejected(self):
        for value in ['NaN', 'Infinity', '-1', '0', '1.001', '69600.01', None]:
            with self.subTest(value=value), self.assertRaises(StereumError):
                amount(value)

    def test_invalid_json_after_mutation_requires_reconciliation(self):
        self.session.request.return_value.json.side_effect = ValueError
        with self.assertRaises(StereumError) as caught:
            self.client.create_order({})
        self.assertTrue(caught.exception.ambiguous)

    def test_nested_mainnet_history_and_conflicting_flags_are_rejected(self):
        for result in [{'items': [{'on_main_net': True}]}, {'on_main_net': False, 'onMainNet': True}]:
            self.session.request.return_value.json.return_value = result
            with self.assertRaises(StereumError):
                self.client.banks()

    def test_nonfinite_provider_json_is_rejected(self):
        self.session.request.return_value.json.return_value = {'id': 'quote', 'expireAt': float('nan')}
        with self.assertRaises(StereumError):
            self.client.create_quote(side='BUY', value='10')

    def test_invalid_payload_does_not_reach_network(self):
        with self.assertRaises(StereumError):
            self.client.create_charge({'amount': float('nan')})
        self.session.request.assert_not_called()

    @override_settings(STEREUM_TEST_ENABLED=False)
    def test_global_disable_blocks_direct_client_mutations(self):
        with self.assertRaises(StereumError):
            self.client.create_charge({})
        self.session.request.assert_not_called()

    def test_redirect_after_mutation_requires_reconciliation(self):
        self.session.request.return_value.status_code = 302
        with self.assertRaises(StereumError) as caught:
            self.client.create_charge({})
        self.assertTrue(caught.exception.ambiguous)
        self.assertEqual(self.session.request.call_count, 1)

    def test_customer_endpoints_sign_the_exact_body(self):
        for method, path in [(self.client.validate_identity, '/api/v1/segip/validate'),
                             (self.client.create_customer, '/api/v1/customers/create')]:
            method({'name': 'José'})
            args, kwargs = self.session.request.call_args
            self.assertTrue(args[1].endswith(path))
            self.assertEqual(kwargs['headers']['x-signature'], hmac.new(b'test-secret', kwargs['data'], hashlib.sha256).hexdigest())
