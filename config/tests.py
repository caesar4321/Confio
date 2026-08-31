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
        self.account = SimpleNamespace(
            algorand_address='A' * 58,
            bsc_address='0x' + '12' * 20,
        )
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
        with patch('users.models.User.objects.get', return_value=self.user), \
                patch('cusd_plus.cusd_vault.require_operational'):
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

        provider_payload = json.loads(mock_post.call_args.kwargs['data'])
        self.assertEqual(provider_payload['customer']['contact_info']['email'], self.user.email)
        self.assertEqual(provider_payload['payout_info']['payout_address'], self.account.algorand_address)
        self.assertTrue(provider_payload['payout_info']['skip_choose_payout_address'])

    @override_settings(
        GUARDARIAN_API_KEY='test-api-key',
        GUARDARIAN_API_URL='https://api-payments.guardarian.com/v1',
        CUSD_CONVERSION_FEE_ENABLED=True,
    )
    @patch('security.integrity_service.app_check_service.verify_request_header')
    @patch('config.views.jwt_decode')
    @patch('cusd_plus.cusd_vault.current_fee_bps', return_value=50)
    @patch('config.views.requests.post')
    def test_bsc_buy_returns_confio_fee_preview(
        self, mock_post, _mock_fee_bps, mock_jwt_decode, mock_app_check,
    ):
        mock_app_check.return_value = {'success': True}
        mock_jwt_decode.return_value = {
            'user_id': self.user.id,
            'account_type': 'personal',
            'account_index': 0,
        }
        provider_response = Mock(ok=True, status_code=200)
        provider_response.json.return_value = {
            'redirect_url': 'https://guardarian.example/checkout?session=bsc',
            'status': 'waiting',
            'estimated_exchange_amount': '123.456',
        }
        mock_post.return_value = provider_response
        request = self.factory.post(
            '/api/guardarian/transaction/',
            data=json.dumps({
                'amount': 500,
                'from_currency': 'PEN',
                'to_currency': 'USDT',
                'to_network': 'BSC',
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION='JWT test-token',
            HTTP_X_FIREBASE_APPCHECK='test-app-check',
        )
        with patch('users.models.User.objects.get', return_value=self.user), \
                patch('cusd_plus.cusd_vault.require_operational'):
            response = guardarian_transaction_proxy(request)

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['confio_fee_bps'], 50)
        self.assertEqual(body['confio_gross_crypto_amount'], '123.456')
        self.assertEqual(body['confio_fee_amount'], '0.617280000000000000')
        self.assertEqual(body['confio_net_crypto_amount'], '122.838720000000000000')
        provider_payload = json.loads(mock_post.call_args.kwargs['data'])
        self.assertEqual(provider_payload['payout_info']['payout_address'], self.account.bsc_address)
        self.assertEqual(provider_payload['to_network'], 'BSC')

    @override_settings(
        GUARDARIAN_API_KEY='test-api-key',
        GUARDARIAN_API_URL='https://api-payments.guardarian.com/v1',
        CUSD_CONVERSION_FEE_ENABLED=True,
    )
    @patch('security.integrity_service.app_check_service.verify_request_header')
    @patch('config.views.jwt_decode')
    @patch('cusd_plus.cusd_vault.current_fee_bps', return_value=90)
    @patch('cusd_plus.cusd_vault.preview_redeem_wei')
    @patch('config.views.requests.post')
    def test_bsc_sell_orders_provider_net_and_returns_exact_fee(
        self, mock_post, mock_preview, _mock_fee_bps,
        mock_jwt_decode, mock_app_check,
    ):
        from cusd_plus.cusd_vault import ConversionPreview

        self.user.phone_country = 'BR'
        mock_app_check.return_value = {'success': True}
        mock_jwt_decode.return_value = {
            'user_id': self.user.id,
            'account_type': 'personal',
            'account_index': 0,
        }
        mock_preview.return_value = ConversionPreview(
            gross_wei=100 * 10 ** 18,
            fee_wei=9 * 10 ** 17,
            net_wei=991 * 10 ** 17,
            fee_bps=90,
        )
        provider_response = Mock(ok=True, status_code=200)
        provider_response.json.return_value = {
            'redirect_url': 'https://guardarian.example/sell',
            'from_amount': '99.100000',
            'deposit_address': '0x' + '34' * 20,
        }
        mock_post.return_value = provider_response
        request = self.factory.post(
            '/api/guardarian/transaction/',
            data=json.dumps({
                'amount': 100,
                'from_currency': 'USDT',
                'from_network': 'BSC',
                'to_currency': 'PEN',
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION='JWT test-token',
            HTTP_X_FIREBASE_APPCHECK='test-app-check',
            HTTP_X_CONFIO_FEE_CAPABLE='1',
            HTTP_CF_IPCOUNTRY='BR',
        )
        with patch('users.models.User.objects.get', return_value=self.user), \
                patch('cusd_plus.cusd_vault.require_operational'), \
                patch('cusd_plus.vault.withdrawable_usdt_wei', return_value=100 * 10 ** 18), \
                patch('cusd_plus.vault.cusd_withdrawable_usdt_wei', return_value=100 * 10 ** 18), \
                patch('cusd_plus.vault.usdt_balance_raw', return_value=0):
            response = guardarian_transaction_proxy(request)

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['confio_gross_crypto_amount'], '100')
        self.assertEqual(body['confio_fee_amount'], '0.9')
        self.assertEqual(body['confio_net_crypto_amount'], '99.1')
        provider_payload = json.loads(mock_post.call_args.kwargs['data'])
        self.assertEqual(provider_payload['from_amount'], 99.1)

    @override_settings(
        GUARDARIAN_API_KEY='test-api-key',
        GUARDARIAN_API_URL='https://api-payments.guardarian.com/v1',
        CUSD_CONVERSION_FEE_ENABLED=True,
    )
    @patch('security.integrity_service.app_check_service.verify_request_header')
    @patch('config.views.jwt_decode')
    @patch('cusd_plus.cusd_vault.current_fee_bps', side_effect=RuntimeError('RPC unavailable'))
    @patch('config.views.requests.post')
    def test_legacy_ineligible_bsc_sell_requires_update_before_fee_preflight(
        self, mock_post, mock_fee_bps, mock_jwt_decode, mock_app_check,
    ):
        self.user.phone_country = 'BR'
        mock_app_check.return_value = {'success': True}
        mock_jwt_decode.return_value = {
            'user_id': self.user.id,
            'account_type': 'personal',
            'account_index': 0,
        }
        request = self.factory.post(
            '/api/guardarian/transaction/',
            data=json.dumps({
                'amount': 100,
                'from_currency': 'USDT',
                'from_network': 'BSC',
                'to_currency': 'PEN',
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION='JWT test-token',
            HTTP_X_FIREBASE_APPCHECK='test-app-check',
            HTTP_CF_IPCOUNTRY='BR',
        )

        with patch('users.models.User.objects.get', return_value=self.user):
            response = guardarian_transaction_proxy(request)

        self.assertEqual(response.status_code, 426)
        body = json.loads(response.content)
        self.assertIn('Actualiza la app', body['error'])
        self.assertIn('cUSD en BNB Smart Chain', body['error'])
        mock_fee_bps.assert_not_called()
        mock_post.assert_not_called()

    @override_settings(
        GUARDARIAN_API_KEY='test-api-key',
        GUARDARIAN_API_URL='https://api-payments.guardarian.com/v1',
        CUSD_CONVERSION_FEE_ENABLED=True,
    )
    @patch('security.integrity_service.app_check_service.verify_request_header')
    @patch('config.views.jwt_decode')
    @patch('cusd_plus.cusd_vault.current_fee_bps', return_value=90)
    @patch('cusd_plus.cusd_vault.preview_redeem_wei')
    @patch('config.views.requests.post')
    def test_fee_capable_bsc_sell_cannot_be_funded_by_raw_usdt(
        self, mock_post, mock_preview, _mock_fee_bps,
        mock_jwt_decode, mock_app_check,
    ):
        from cusd_plus.cusd_vault import ConversionPreview

        self.user.phone_country = 'BR'
        mock_app_check.return_value = {'success': True}
        mock_jwt_decode.return_value = {
            'user_id': self.user.id,
            'account_type': 'personal',
            'account_index': 0,
        }
        mock_preview.return_value = ConversionPreview(
            gross_wei=100 * 10 ** 18,
            fee_wei=9 * 10 ** 17,
            net_wei=991 * 10 ** 17,
            fee_bps=90,
        )
        request = self.factory.post(
            '/api/guardarian/transaction/',
            data=json.dumps({
                'amount': 100,
                'from_currency': 'USDT',
                'from_network': 'BSC',
                'to_currency': 'PEN',
            }),
            content_type='application/json',
            HTTP_AUTHORIZATION='JWT test-token',
            HTTP_X_FIREBASE_APPCHECK='test-app-check',
            HTTP_X_CONFIO_FEE_CAPABLE='1',
            HTTP_CF_IPCOUNTRY='BR',
        )

        with patch('users.models.User.objects.get', return_value=self.user), \
                patch('cusd_plus.vault.withdrawable_usdt_wei', return_value=100 * 10 ** 18), \
                patch('cusd_plus.vault.usdt_balance_raw', return_value=100 * 10 ** 18), \
                patch('cusd_plus.vault.cusd_withdrawable_usdt_wei', return_value=0), \
                patch('cusd_plus.vault.redeem_blocked_reason') as redeem_blocked:
            response = guardarian_transaction_proxy(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn('saldo disponible', json.loads(response.content)['error'])
        redeem_blocked.assert_not_called()
        mock_post.assert_not_called()
