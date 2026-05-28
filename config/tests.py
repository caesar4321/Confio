import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from django.test import RequestFactory, SimpleTestCase, override_settings

from config.views import guardarian_transaction_proxy


class _FakeAccountQuerySet:
    def __init__(self, account):
        self.account = account

    def filter(self, **kwargs):
        return self

    def first(self):
        return self.account


class GuardarianTransactionProxyTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.account = SimpleNamespace(algorand_address='A' * 58)
        self.user = SimpleNamespace(
            id=123,
            email='user@example.com',
            phone_country='AR',
            accounts=_FakeAccountQuerySet(self.account),
        )

    @override_settings(
        GUARDARIAN_API_KEY='test-api-key',
        GUARDARIAN_API_URL='https://api-payments.guardarian.com/v1',
    )
    @patch('security.integrity_service.app_check_service.verify_request_header')
    @patch('config.views.jwt_decode')
    @patch('config.views.requests.post')
    def test_redirect_url_keeps_email_and_wallet_out_of_query(self, mock_post, mock_jwt_decode, mock_app_check):
        mock_app_check.return_value = {'success': True}
        mock_jwt_decode.return_value = {
            'user_id': self.user.id,
            'account_type': 'personal',
            'account_index': 0,
        }

        guardarian_response = Mock()
        guardarian_response.ok = True
        guardarian_response.status_code = 200
        guardarian_response.json.return_value = {
            'redirect_url': 'https://guardarian.example/checkout?session=abc123',
            'status': 'waiting',
        }
        mock_post.return_value = guardarian_response

        request = self.factory.post(
            '/api/guardarian/transaction/',
            data=json.dumps({
                'amount': 100,
                'from_currency': 'EUR',
                'to_currency': 'USDC',
                'email': 'client@example.com',
                'payout_address': 'B' * 58,
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION='JWT test-token',
            HTTP_X_FIREBASE_APPCHECK='test-app-check',
        )
        with patch('users.models.User.objects.get', return_value=self.user):
            response = guardarian_transaction_proxy(request)

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['redirect_url'], 'https://guardarian.example/checkout?session=abc123')

        query = parse_qs(urlparse(body['redirect_url']).query)
        self.assertEqual(query, {'session': ['abc123']})
        self.assertNotIn('email', query)
        self.assertNotIn('payout_address', query)
        self.assertNotIn('default_payout_address', query)
        self.assertNotIn('skip_choose_payout_address', query)

        provider_payload = mock_post.call_args.kwargs['json']
        self.assertEqual(provider_payload['customer']['contact_info']['email'], self.user.email)
        self.assertEqual(provider_payload['payout_info']['payout_address'], self.account.algorand_address)
        self.assertTrue(provider_payload['payout_info']['skip_choose_payout_address'])
