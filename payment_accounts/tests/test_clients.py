import base64
import hashlib
import hmac
import requests
from unittest import mock

from django.test import SimpleTestCase, override_settings

from payment_accounts.clients import (
    CobreClient,
    ComplianceHandoffError,
    InfiniaClient,
    ProviderAPIError,
    first_item,
    verify_cobre_signature,
    verify_infinia_signature,
)


class _Response:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.ok = 200 <= status < 300
        self.text = str(payload)

    def json(self):
        return self._payload


class ProviderClientTests(SimpleTestCase):
    def test_first_item_supports_cobre_paginated_contents(self):
        self.assertEqual(
            first_item({'contents': [{'id': 'acc_1'}], 'total_items': 1}),
            {'id': 'acc_1'},
        )

    @override_settings(INFINIA_SECRET_ID='client', INFINIA_SECRET_PASSWORD='password')
    def test_non_object_error_payload_is_wrapped_safely(self):
        session = mock.Mock()
        session.headers = {}
        session.request.return_value = _Response(400, ['invalid request'])

        with self.assertRaisesRegex(ProviderAPIError, 'invalid request'):
            InfiniaClient(session=session).get_account('491')

    @override_settings(COBRE_USER_ID='uid', COBRE_SECRET='secret')
    @mock.patch('payment_accounts.clients.cache')
    def test_cobre_authenticates_and_sends_idempotency_header(self, cache):
        cache.get.return_value = None
        session = mock.Mock()
        session.headers = {}
        session.post.return_value = _Response(200, {'access_token': 'token'})
        session.request.return_value = _Response(201, {'id': 'mm_1'})
        client = CobreClient(session=session)

        client.create_money_movement({'amount': 100}, idempotency_key='123456789')

        session.post.assert_called_once()
        self.assertEqual(
            session.request.call_args.kwargs['headers']['idempotency'], '123456789'
        )
        self.assertEqual(
            session.request.call_args.kwargs['headers']['Authorization'], 'Bearer token'
        )

    @override_settings(COBRE_USER_ID='uid', COBRE_SECRET='secret')
    @mock.patch('payment_accounts.clients.cache')
    def test_cobre_cross_border_movement_uses_documented_endpoint(self, cache):
        cache.get.return_value = 'token'
        session = mock.Mock()
        session.headers = {}
        session.request.return_value = _Response(201, {'id': 'mm_1'})

        CobreClient(session=session).create_cross_border_movement(
            {'forex_quote_id': 'fxq_1'}, idempotency_key='123456789'
        )

        call = session.request.call_args
        self.assertTrue(call.args[1].endswith('/cross_border_money_movements'))
        self.assertEqual(call.kwargs['headers']['idempotency'], '123456789')

    @override_settings(
        INFINIA_SECRET_ID='client', INFINIA_SECRET_PASSWORD='password', INFINIA_COMPANY_ID='42'
    )
    def test_infinia_uses_basic_auth_and_company_scope(self):
        session = mock.Mock()
        session.headers = {}
        session.request.return_value = _Response(200, {'id': 'owner_1'})
        client = InfiniaClient(session=session)

        client.create_owner({'type': 'INDIVIDUAL'})

        call = session.request.call_args
        self.assertEqual(call.kwargs['auth'], ('client', 'password'))
        self.assertEqual(call.kwargs['headers']['X-Company-Id'], '42')

    @override_settings(INFINIA_SECRET_ID='', INFINIA_SECRET_PASSWORD='')
    def test_unconfigured_infinia_fails_before_network(self):
        session = mock.Mock()
        session.headers = {}
        with self.assertRaises(ProviderAPIError):
            InfiniaClient(session=session).get_account('a')
        session.request.assert_not_called()

    @override_settings(INFINIA_SECRET_ID='client', INFINIA_SECRET_PASSWORD='password')
    def test_infinia_unwraps_success_data_envelope(self):
        session = mock.Mock()
        session.headers = {}
        session.request.return_value = _Response(
            200, {'status': 'success', 'data': {'id': 491, 'status': 'ACTIVE'}}
        )

        result = InfiniaClient(session=session).get_account('491')

        self.assertEqual(result, {'id': 491, 'status': 'ACTIVE'})

    @override_settings(INFINIA_SECRET_ID='client', INFINIA_SECRET_PASSWORD='password')
    def test_network_failure_is_retryable_provider_error(self):
        session = mock.Mock()
        session.headers = {}
        session.request.side_effect = requests.Timeout('timeout')

        with self.assertRaises(ProviderAPIError) as raised:
            InfiniaClient(session=session).get_account('491')

        self.assertTrue(raised.exception.retryable)

    @override_settings(INFINIA_SECRET_ID='client', INFINIA_SECRET_PASSWORD='password')
    def test_infinia_412_returns_terminal_payout_record(self):
        session = mock.Mock()
        session.headers = {}
        session.request.return_value = _Response(
            412,
            {'message': 'insufficient balance', 'data': {'id': 'po_1', 'status': 'ERROR'}},
        )

        result = InfiniaClient(session=session).create_payout({'originId': 'idem'})

        self.assertEqual(result['id'], 'po_1')
        self.assertEqual(result['status'], 'ERROR')

    def test_infinia_document_upload_rejects_non_https_presigned_url(self):
        session = mock.Mock()
        session.headers = {}

        with self.assertRaisesRegex(ComplianceHandoffError, 'must use HTTPS'):
            InfiniaClient(session=session).upload_owner_document(
                'http://upload.example/document', b'evidence', content_type='image/jpeg'
            )

        session.put.assert_not_called()


class WebhookSignatureTests(SimpleTestCase):
    def test_cobre_signature_covers_timestamp_dot_raw_body(self):
        body, timestamp, secret = b'{"id":"1"}', '123', 'secret'
        signature = hmac.new(
            secret.encode(), timestamp.encode() + b'.' + body, hashlib.sha256
        ).hexdigest()
        self.assertTrue(verify_cobre_signature(body, timestamp, signature, secret))
        self.assertFalse(verify_cobre_signature(body + b'x', timestamp, signature, secret))

    def test_infinia_signature_is_base64_hmac(self):
        body, secret = b'{"id":"1"}', 'client-id'
        signature = base64.b64encode(
            hmac.new(secret.encode(), body, hashlib.sha256).digest()
        ).decode()
        self.assertTrue(verify_infinia_signature(body, signature, secret))
        self.assertFalse(verify_infinia_signature(body + b'x', signature, secret))
