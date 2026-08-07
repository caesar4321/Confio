from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.test import SimpleTestCase

from ramps.koywe import build_ramp_field_schema, get_country_ramp_config
from ramps.koywe_client import KoyweClient
from ramps.tasks import refresh_koywe_ramp_limits


class KoyweBoliviaOffRampConfigTests(SimpleTestCase):
    def test_bolivia_exposes_bank_transfer_off_ramp(self):
        config = get_country_ramp_config('BO')
        wire = next(method for method in config['methods'] if method['code'] == 'WIREBO')

        self.assertTrue(wire['supports_off_ramp'])
        self.assertFalse(wire['supports_on_ramp'])
        self.assertTrue(wire['requires_account_number'])
        self.assertEqual(config['on_ramp_min_amount'], 350)
        self.assertEqual(config['on_ramp_max_amount'], 56000)
        self.assertGreater(config['off_ramp_min_amount'], 0)
        self.assertGreater(config['off_ramp_max_amount'], config['off_ramp_min_amount'])

    @patch('ramps.tasks.KoyweClient')
    def test_periodic_limit_refresh_includes_bob(self, client_class):
        client = client_class.return_value

        refresh_koywe_ramp_limits()

        self.assertIn(
            call(fiat_symbol='BOB', force_refresh=True),
            client.get_dynamic_ramp_limits.call_args_list,
        )

    def test_bolivia_wire_schema_requires_bank_picker(self):
        config = get_country_ramp_config('BO')
        wire = next(method for method in config['methods'] if method['code'] == 'WIREBO')

        schema = build_ramp_field_schema(country_code='BO', method=wire)

        self.assertTrue(schema['accountField']['required'])
        self.assertTrue(schema['showAccountTypeField'])
        self.assertEqual(schema['providerFields'][0]['key'], 'bankName')
        self.assertEqual(schema['providerFields'][0]['picker'], 'bank')
        self.assertTrue(schema['providerFields'][0]['required'])


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


class KoyweBoliviaBankAccountPayloadTests(SimpleTestCase):
    def setUp(self):
        self.client = KoyweClient()
        self.client._request = Mock(return_value={'_id': 'bank-account-id'})

    @patch.object(KoyweClient, 'ensure_account_profile', return_value='user@example.com')
    @patch.object(KoyweClient, '_resolve_bank_code', return_value='BANCO_UNION')
    def test_wirebo_uses_selected_bank_and_canonical_account_type(
        self, resolve_bank_code, _ensure_account_profile
    ):
        bank_info = SimpleNamespace(
            provider_metadata={'bankCode': 'BANCO_UNION'},
            payment_method=SimpleNamespace(name='WIREBO'),
            ramp_payment_method=None,
            account_number='12345678',
            phone_number=None,
            email=None,
            username=None,
            bank=None,
            account_type='ahorro',
        )

        result = self.client.create_bank_account(
            bank_info=bank_info,
            email='user@example.com',
            country_code='BO',
            fiat_symbol='BOB',
            contact_profile={
                'email': 'user@example.com',
                'documentNumber': '7654321',
                'documentType': 'CI',
            },
        )

        self.assertEqual(result['_id'], 'bank-account-id')
        resolve_bank_code.assert_called_once_with(
            country_code='BOL', bank_code='BANCO_UNION'
        )
        self.client._request.assert_called_once_with(
            'POST',
            '/rest/bank-accounts',
            email='user@example.com',
            json_payload={
                'countryCode': 'BOL',
                'currencySymbol': 'BOB',
                'email': 'user@example.com',
                'documentNumber': '7654321',
                'accountNumber': '12345678',
                'bankCode': 'BANCO_UNION',
                'accountType': 'savings',
            },
        )
