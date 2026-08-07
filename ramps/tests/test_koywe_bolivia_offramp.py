from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.test import SimpleTestCase

from ramps.koywe import get_country_ramp_config
from ramps.koywe_client import KoyweClient
from ramps.schema import CreateRampOrder
from ramps.tasks import refresh_koywe_ramp_limits


class KoyweBoliviaOffRampConfigTests(SimpleTestCase):
    def test_bolivia_exposes_on_ramp_only(self):
        config = get_country_ramp_config('BO')
        methods = config['methods']

        self.assertEqual([method['code'] for method in methods], ['QRI-BO'])
        self.assertTrue(methods[0]['supports_on_ramp'])
        self.assertFalse(methods[0]['supports_off_ramp'])
        self.assertEqual(config['on_ramp_min_amount'], 350)
        self.assertEqual(config['on_ramp_max_amount'], 56000)
        self.assertEqual(config['off_ramp_min_amount'], 0)
        self.assertEqual(config['off_ramp_max_amount'], 0)

    @patch('ramps.tasks.KoyweClient')
    def test_periodic_limit_refresh_includes_bob(self, client_class):
        client = client_class.return_value

        refresh_koywe_ramp_limits()

        self.assertIn(
            call(fiat_symbol='BOB', force_refresh=True),
            client.get_dynamic_ramp_limits.call_args_list,
        )

    @patch('ramps.schema._employee_ramp_denial', return_value=None)
    @patch('ramps.schema._get_wallet_upgrade_blocker', return_value=None)
    @patch('ramps.schema._get_ramp_account_for_user', return_value=SimpleNamespace())
    def test_real_order_mutation_blocks_bolivia_off_ramp(
        self, _get_account, _wallet_blocker, _employee_denial
    ):
        info = SimpleNamespace(context=SimpleNamespace(user=SimpleNamespace(is_authenticated=True)))

        result = CreateRampOrder().mutate(
            info,
            direction='OFF_RAMP',
            amount='36',
            payment_method_code='WIREBO',
            country_code='BO',
            fiat_currency='BOB',
            bank_info_id='463',
        )

        self.assertFalse(result.success)
        self.assertEqual(
            result.error,
            'Retiro en BOB no está disponible por ahora. En Bolivia solo está habilitada la recarga.',
        )


class KoyweBoliviaBankCatalogTests(SimpleTestCase):
    def setUp(self):
        self.client = KoyweClient()
        self.client.base_url = 'https://api.koywe.test'
        self.client.session = Mock()

    def test_uses_legacy_bank_info_when_available(self):
        legacy = Mock(ok=True)
        legacy.json.return_value = [
            {'bankCode': 'LEGACY_BANK', 'name': 'Legacy Bank', 'institutionName': ''},
        ]
        self.client.session.get.return_value = legacy

        banks = self.client.get_bank_info(country_code='BOL')

        self.assertEqual(banks[0]['bankCode'], 'LEGACY_BANK')
        self.client.session.get.assert_called_once_with(
            'https://api.koywe.test/rest/bank-info/BOL', timeout=15
        )

    def test_falls_back_to_platform_bank_catalog_for_bolivia(self):
        legacy = Mock(ok=False, status_code=400)
        platform = Mock(ok=True, status_code=200)
        platform.json.return_value = [
            {'name': 'Banco Unión S.A.', 'value': 'BANCO_UNION', 'bank_code': '016'},
        ]
        self.client.session.get.side_effect = [legacy, platform]

        banks = self.client.get_bank_info(country_code='BOL')

        self.assertEqual(
            banks,
            [
                {
                    'bankCode': 'BANCO_UNION',
                    'name': 'Banco Unión S.A.',
                    'institutionName': '',
                }
            ],
        )
        self.client.session.get.assert_any_call(
            'https://api.koywe.test/api/v1/banks',
            params={'countrySymbol': 'BO'},
            timeout=15,
        )
