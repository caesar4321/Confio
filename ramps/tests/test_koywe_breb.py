from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from ramps.koywe_client import KoyweClient, KoyweError
from users.models import BankInfo


class KoyweBrebTests(SimpleTestCase):
    def setUp(self):
        self.client = KoyweClient()
        self.client.ensure_account_profile = Mock(return_value='holder@example.com')
        self.client._resolve_bank_code = Mock(return_value='co_bancolombia')
        self.client._request = Mock(return_value={'id': 'destination-id'})
        self.bank = SimpleNamespace(
            account_number='+573001234567', account_type='ahorro',
            phone_number=None, email=None, username=None, bank=None,
            payment_method=SimpleNamespace(name='WIRECO'),
            provider_metadata={'rail': 'BREB', 'bankCode': 'co_bancolombia'},
        )

    def register(self, country='CO', currency='COP'):
        return self.client.create_bank_account(
            bank_info=self.bank, email='holder@example.com',
            country_code=country, fiat_symbol=currency,
        )

    def test_supported_keys_are_preserved_and_bank_fields_retained(self):
        for key in ['+573001234567', '3001234567', '900123456-7', 'Holder@example.com', '+receipts@example.com', '@MiAlias', 'a' * 60 + '@example.com']:
            with self.subTest(key=key):
                self.bank.account_number = key
                self.register()
                payload = self.client._request.call_args.kwargs['json_payload']
                self.assertEqual(payload['rail'], 'BREB')
                self.assertEqual(payload['accountNumber'], key)
                self.assertEqual(payload['bankCode'], 'co_bancolombia')
                self.assertEqual(payload['accountType'], 'savings')
                self.assertEqual(payload['countryCode'], 'COL')
                self.assertEqual(payload['currencySymbol'], 'COP')

    def test_traditional_account_does_not_send_rail(self):
        del self.bank.provider_metadata['rail']
        self.bank.account_number = '1234567890'
        self.register()
        payload = self.client._request.call_args.kwargs['json_payload']
        self.assertNotIn('rail', payload)
        self.assertEqual(payload['accountNumber'], '1234567890')

    def test_breb_key_takes_precedence_over_unrelated_metadata(self):
        self.bank.provider_metadata.update(pixKey='wrong-pix', cci='wrong-cci')
        self.register(country='COL')
        self.assertEqual(self.client._request.call_args.kwargs['json_payload']['accountNumber'], '+573001234567')

    def test_invalid_key_rejected_before_provider_calls(self):
        for key in ['', '   ', 'has spaces', '+513001234567', '+57300', 'a' * 255]:
            with self.subTest(key=key), self.assertRaises(KoyweError):
                self.bank.account_number = key
                self.register()
        self.client.ensure_account_profile.assert_not_called()
        self.client._request.assert_not_called()

    def test_wrong_corridor_and_unknown_rail_rejected(self):
        for country, currency in [('PE', 'PEN'), ('CO', 'USD')]:
            with self.subTest(country=country), self.assertRaises(KoyweError):
                self.register(country=country, currency=currency)
        self.bank.provider_metadata['rail'] = 'UNKNOWN'
        with self.assertRaises(KoyweError):
            self.register()
        self.client._request.assert_not_called()

    def test_bank_and_account_type_are_required(self):
        self.bank.account_type = None
        with self.assertRaises(KoyweError):
            self.register()
        self.bank.account_type = 'ahorro'
        del self.bank.provider_metadata['bankCode']
        with self.assertRaises(KoyweError):
            self.register()
        self.client._request.assert_not_called()

    def test_provider_rejection_is_not_retried_as_traditional_transfer(self):
        self.client._request.side_effect = KoyweError('Invalid key or holder mismatch')
        with self.assertRaises(KoyweError):
            self.register()
        self.client._request.assert_called_once()
        self.assertEqual(self.client._request.call_args.kwargs['json_payload']['rail'], 'BREB')

    def test_saved_destination_is_labeled_breb(self):
        bank = BankInfo(
            provider_metadata={'rail': 'BREB', 'bankName': 'Bancolombia'},
            account_number='+573001234567', account_type='ahorro',
        )
        self.assertEqual(bank.full_bank_name, 'Bre-B · Bancolombia')
        self.assertIn('Bre-B · Bancolombia', bank.summary_text)
        self.assertIn('4567', bank.summary_text)
        self.assertNotIn('+573001234567', bank.summary_text)

    def test_email_key_fits_saved_destination_field(self):
        key = 'a' * 60 + '@example.com'
        field = BankInfo._meta.get_field('account_number')
        self.assertEqual(field.clean(key, BankInfo()), key)


class BrebSavedDestinationTests(SimpleTestCase):
    def setUp(self):
        from unittest.mock import patch
        self.method = SimpleNamespace(
            code='WIRECO', country_code='CO', legacy_payment_method=None,
            requires_account_number=True, requires_phone=False, requires_email=False,
            bank=None,
        )
        self.user = SimpleNamespace(is_authenticated=True)
        self.info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        self.account = SimpleNamespace(account_type='personal')
        self.bank = SimpleNamespace(
            ramp_payment_method=self.method, payment_method=None, account=self.account,
            country=None, bank=None, provider_metadata={'rail': 'BREB', 'bankCode': 'co_bancolombia'},
            save=Mock(),
        )
        patches = {
            'jwt_context': patch('users.jwt_context.get_jwt_business_context_with_validation', return_value={'account_type': 'personal', 'account_index': 0}),
            'account_get': patch('users.schema.Account.objects.get', return_value=self.account),
            'method_get': patch('ramps.models.RampPaymentMethod.objects.get', return_value=self.method),
            'bank_objects': patch('users.schema.BankInfo.objects'),
        }
        for name, patcher in patches.items():
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.bank_objects.filter.return_value.values_list.return_value = []
        self.bank_objects.select_related.return_value.get.return_value = self.bank

    def create(self, **overrides):
        from users.schema import CreateBankInfo
        args = dict(
            account_holder_name='Holder', ramp_payment_method_id='123',
            account_number='+receipts@example.com', account_type='ahorro',
            provider_metadata={'rail': 'BREB', 'bankCode': 'co_bancolombia'},
        )
        args.update(overrides)
        return CreateBankInfo.mutate(None, self.info, **args)

    def update(self, **overrides):
        from users.schema import UpdateBankInfo
        args = dict(
            bank_info_id='321', account_holder_name='Holder',
            account_number='+receipts@example.com', account_type='ahorro',
            provider_metadata={'rail': 'BREB', 'bankCode': 'co_bancolombia'},
        )
        args.update(overrides)
        return UpdateBankInfo.mutate(None, self.info, **args)

    def test_create_preserves_email_key_and_canonicalizes_rail(self):
        result = self.create(provider_metadata={'rail': ' breb ', 'bankCode': 'co_bancolombia'})
        self.assertTrue(result.success, result.error)
        saved = self.bank_objects.create.call_args.kwargs
        self.assertEqual(saved['provider_metadata']['rail'], 'BREB')
        self.assertEqual(saved['account_number'], '+receipts@example.com')

    def test_invalid_destinations_rejected_before_create_or_update(self):
        invalid = [
            {'account_number': ' '},
            {'account_number': '+57300'},
            {'account_number': 'a' * 255},
            {'account_number': 'contains spaces'},
            {'account_type': ' '},
            {'provider_metadata': {'rail': 'BREB'}},
            {'provider_metadata': {'rail': 'UNKNOWN', 'bankCode': 'co_bancolombia'}},
        ]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                self.assertFalse(self.create(**kwargs).success)
                self.assertFalse(self.update(**kwargs).success)
        self.bank_objects.create.assert_not_called()
        self.bank.save.assert_not_called()

    def test_breb_rejected_for_other_countries_and_nonbank_methods(self):
        self.method.country_code = 'PE'
        self.assertFalse(self.create().success)
        self.assertFalse(self.update().success)
        self.method.country_code = 'CO'
        self.method.code = 'NEQUI'
        self.assertFalse(self.create().success)
        self.assertFalse(self.update().success)
        self.bank_objects.create.assert_not_called()
        self.bank.save.assert_not_called()

    def test_same_identifier_can_be_saved_on_different_rails(self):
        self.bank_objects.filter.return_value.values_list.return_value = [{'bankCode': 'co_bancolombia'}]
        self.assertTrue(self.create(account_number='3001234567').success)
        self.bank_objects.filter.return_value.values_list.return_value = [{'rail': 'BREB', 'bankCode': 'co_bancolombia'}]
        self.assertTrue(self.create(account_number='3001234567', provider_metadata={'bankCode': 'co_bancolombia'}).success)

    def test_same_identifier_on_same_rail_is_duplicate(self):
        self.bank_objects.filter.return_value.values_list.return_value = [{'rail': 'breb'}]
        result = self.create(account_number=' 3001234567 ')
        self.assertFalse(result.success)
        self.assertIn('Ya tienes registrado', result.error)
        self.assertEqual(self.bank_objects.filter.call_args.kwargs['account_number'], '3001234567')
        self.bank_objects.create.assert_not_called()

    def test_traditional_duplicate_still_rejected(self):
        self.bank_objects.filter.return_value.values_list.return_value = [{}]
        self.assertFalse(self.create(provider_metadata={}).success)
        self.bank_objects.create.assert_not_called()

    def test_older_client_omitting_metadata_does_not_erase_breb(self):
        result = self.update(provider_metadata=None)
        self.assertTrue(result.success, result.error)
        self.assertEqual(self.bank.provider_metadata['rail'], 'BREB')
        self.bank.save.assert_called_once()

    def test_explicit_switch_to_traditional_removes_breb(self):
        result = self.update(account_number='1234567890', provider_metadata={'bankCode': 'co_bancolombia'})
        self.assertTrue(result.success, result.error)
        self.assertNotIn('rail', self.bank.provider_metadata)
        self.bank.save.assert_called_once()

    def test_ramp_only_bancolombia_saves_bank_code_for_provider_registration(self):
        self.method.code = 'BANCOLOMBIA'
        result = self.create(provider_metadata={'rail': 'BREB'})
        self.assertTrue(result.success, result.error)
        saved = self.bank_objects.create.call_args.kwargs
        self.assertEqual(saved['provider_metadata']['bankCode'], 'co_bancolombia')
        # No legacy payment method exists to supply the provider fallback.
        client = KoyweClient()
        client.ensure_account_profile = Mock(return_value='holder@example.com')
        client._resolve_bank_code = Mock(return_value='co_bancolombia')
        client._request = Mock(return_value={'id': 'destination'})
        client.create_bank_account(
            bank_info=SimpleNamespace(**saved, bank=None),
            email='holder@example.com', country_code='CO', fiat_symbol='COP',
        )
        payload = client._request.call_args.kwargs['json_payload']
        self.assertEqual(payload['bankCode'], 'co_bancolombia')
        self.assertEqual(payload['rail'], 'BREB')

    def test_migration_preserves_existing_field_properties(self):
        from importlib import import_module
        migration = import_module('users.migrations.0043_bankinfo_breb_key_length')
        operation = migration.Migration.operations[0]
        current = BankInfo._meta.get_field('account_number').deconstruct()
        migrated = operation.field.deconstruct()
        self.assertEqual(current[1:], migrated[1:])

    def test_standalone_breb_catalog_entry_is_offramp_and_has_key_schema(self):
        from ramps.koywe import get_country_ramp_config, build_ramp_field_schema
        method = next(m for m in get_country_ramp_config('CO')['methods'] if m['code'] == 'BREB')
        self.assertEqual(method['display_name'], 'Bre-B')
        self.assertTrue(method['supports_off_ramp'])
        self.assertFalse(method['supports_on_ramp'])
        schema = build_ramp_field_schema(country_code='CO', method=method)
        self.assertEqual(schema['defaultProviderMetadata'], {'rail': 'BREB'})
        self.assertEqual(schema['accountField']['keyboardType'], 'default')
        self.assertTrue(schema['accountTypeRequired'])
        self.assertEqual(schema['providerFields'][0]['key'], 'bankName')
        self.assertTrue(schema['providerFields'][0]['required'])

    def test_standalone_breb_cannot_be_saved_as_traditional(self):
        self.method.code = 'BREB'
        result = self.create(provider_metadata={'bankCode': 'co_bancolombia'})
        self.assertTrue(result.success, result.error)
        self.assertEqual(self.bank_objects.create.call_args.kwargs['provider_metadata']['rail'], 'BREB')

    def test_breb_resolves_existing_wireco_provider_instead_of_inventing_provider(self):
        client = KoyweClient()
        client.list_payment_providers = Mock(return_value=[{'code': 'WIRECO', '_id': 'wire-provider', 'displayName': 'Transferencia bancaria'}])
        provider_id, _, _ = client.resolve_payment_provider(fiat_symbol='COP', payment_method_code='BREB')
        self.assertEqual(provider_id, 'wire-provider')

    def test_breb_order_rejects_bank_destination_without_a_key(self):
        from decimal import Decimal
        client = KoyweClient()
        self.method.code = 'WIRECO'
        self.bank.provider_metadata = {'bankCode': 'co_bancolombia'}
        with self.assertRaisesMessage(KoyweError, 'llave Bre-B'):
            client.create_ramp_order(
                direction='OFF_RAMP', amount=Decimal('10'), fiat_symbol='COP',
                payment_method_code='BREB', email='holder@example.com',
                wallet_address=None, country_code='CO', bank_info=self.bank,
            )
