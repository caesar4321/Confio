from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.test import SimpleTestCase, override_settings

from ramps.koywe import (
    BOLIVIA_OFF_RAMP_UNAVAILABLE,
    build_ramp_field_schema,
    get_country_ramp_config,
    off_ramp_offered,
)
from ramps.koywe_client import KoyweClient
from ramps.schema import CreateRampOrder
from ramps.tasks import refresh_koywe_ramp_limits


class KoyweBoliviaOffRampConfigTests(SimpleTestCase):
    def test_bolivia_offers_qr_top_up_and_bank_withdrawal(self):
        config = get_country_ramp_config('BO')
        methods = {method['code']: method for method in config['methods']}

        self.assertEqual(list(methods), ['QRI-BO', 'WIREBO'])
        self.assertTrue(methods['QRI-BO']['supports_on_ramp'])
        self.assertFalse(methods['QRI-BO']['supports_off_ramp'])
        self.assertFalse(methods['WIREBO']['supports_on_ramp'])
        self.assertTrue(methods['WIREBO']['supports_off_ramp'])
        self.assertEqual(config['on_ramp_min_amount'], 350)
        # Withdrawal limits are dollars (crypto in), not bolivianos.
        self.assertLess(config['off_ramp_min_amount'], 50)
        self.assertLess(config['off_ramp_max_amount'], 10000)

    def test_wirebo_schema_requires_bank_picker(self):
        definition = next(m for m in get_country_ramp_config('BO')['methods'] if m['code'] == 'WIREBO')
        schema = build_ramp_field_schema(country_code='BO', method=definition)

        self.assertEqual(schema['providerFields'][0]['key'], 'bankName')
        self.assertEqual(schema['providerFields'][0]['picker'], 'bank')

    @patch('ramps.tasks.KoyweClient')
    def test_periodic_limit_refresh_includes_bob(self, client_class):
        client = client_class.return_value

        refresh_koywe_ramp_limits()

        self.assertIn(
            call(fiat_symbol='BOB', force_refresh=True),
            client.get_dynamic_ramp_limits.call_args_list,
        )


class KoyweBoliviaOffRampGateTests(SimpleTestCase):
    NEW = {'HTTP_X_CONFIO_VERSION': '5.3.7'}
    OLD = {'HTTP_X_CONFIO_VERSION': '5.3.6'}

    @override_settings(KOYWE_BO_OFF_RAMP_MIN_APP_VERSION='')
    def test_unset_floor_offers_bolivia_to_nobody(self):
        self.assertFalse(off_ramp_offered('BO', {'HTTP_X_CONFIO_VERSION': '9.9.9'}))

    @override_settings(KOYWE_BO_OFF_RAMP_MIN_APP_VERSION='5.3.7')
    def test_only_builds_at_the_floor_get_bolivia(self):
        self.assertTrue(off_ramp_offered('BO', self.NEW))
        self.assertTrue(off_ramp_offered('bo', self.NEW))
        self.assertFalse(off_ramp_offered('BO', self.OLD))
        self.assertFalse(off_ramp_offered('BO', {}))
        self.assertFalse(off_ramp_offered('BO', None))

    @override_settings(KOYWE_BO_OFF_RAMP_MIN_APP_VERSION='')
    def test_other_countries_are_never_gated(self):
        self.assertTrue(off_ramp_offered('PE', None))
        self.assertTrue(off_ramp_offered('CO', self.OLD))

    @override_settings(KOYWE_BO_OFF_RAMP_MIN_APP_VERSION='5.3.7')
    @patch('security.face_step_up.missing_face_step_up', return_value=None)
    @patch('ramps.schema._employee_ramp_denial', return_value=None)
    @patch('ramps.schema._get_wallet_upgrade_blocker', return_value=None)
    @patch('ramps.schema._get_ramp_account_for_user', return_value=SimpleNamespace())
    def test_old_build_order_is_refused(self, _get_account, _wallet_blocker, _employee_denial, _face):
        info = SimpleNamespace(context=SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True), META=self.OLD))

        result = CreateRampOrder().mutate(
            info,
            direction='OFF_RAMP',
            amount='400',
            payment_method_code='WIREBO',
            country_code='BO',
            fiat_currency='BOB',
            bank_info_id='463',
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error, BOLIVIA_OFF_RAMP_UNAVAILABLE)


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


class RampFeeDisplayUnitTests(SimpleTestCase):
    def test_koywe_dollar_tokens_read_as_dollars(self):
        from ramps.currencies import fee_display_unit
        self.assertEqual(fee_display_unit('USDC Polygon'), 'US$')
        self.assertEqual(fee_display_unit('USDT BSC'), 'US$')
        self.assertEqual(fee_display_unit('BOB'), 'BOB')  # top-up fees stay in the local currency
        self.assertEqual(fee_display_unit('USDC Algorand'), 'USDC Algorand')  # the app shows it as cUSD
