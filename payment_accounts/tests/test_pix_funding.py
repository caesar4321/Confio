from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from payment_accounts import activation, local_money
from payment_accounts.models import AccountActivation, FinancialAccount, FundingInstruction, ProviderProfile
from payment_accounts.services import sync_embedded_funding_instructions
from users.models import Account, User


class PixFundingTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username='pix-funding', firebase_uid='pix-funding')
        self.owner = Account.objects.create(user=user, account_type='personal')
        profile = ProviderProfile.objects.create(confio_account=self.owner, provider='infinia',
                                                 owner_type='individual', status='active')
        self.local = FinancialAccount.objects.create(provider_profile=profile, country='BRA', asset='BRL',
            status='active', provider_account_id='brl', ownership_structure='provider_named')
        crypto = FinancialAccount.objects.create(provider_profile=profile, country='XXX', asset='USDC_POL',
            status='active', provider_account_id='usdc', ownership_structure='provider_named')
        FundingInstruction.objects.create(financial_account=crypto, kind='crypto_address', status='active',
                                          display_value='0x' + '1' * 40, provider_resource_id='crypto')
        self.row = AccountActivation.objects.create(confio_account=self.owner, country='BRA', asset='BRL',
                                                    method_id='br_pix', status='provisioning')

    def sync(self, fields):
        self.local.provider_data = {'latest': {'funding_instructions': {
            'type': 'fiat', 'bank_name': 'STARK BANK S.A.', 'account_number': None,
            'pix_key_brl': None, **fields,
        }}}
        self.local.save(update_fields=['provider_data'])
        sync_embedded_funding_instructions(self.local)

    def test_real_br_code_shapes_unlock_opening_without_a_payment(self):
        for fields in ({'br_code': 'pix-copy-paste'}, {'br_code_brl': {'br_code': 'pix-copy-paste'}}):
            with self.subTest(fields=fields):
                self.sync(fields)
                instruction = self.local.funding_instructions.get(kind='qr')
                self.assertEqual(instruction.display_value, 'pix-copy-paste')
                self.assertTrue(activation.opening_ready(self.row))
                with mock.patch('payment_accounts.schema._verified_identity', return_value=None), \
                     mock.patch('payment_accounts.local_money.activate', return_value='active'), \
                     mock.patch.object(activation, '_prepare_send') as pay:
                    row = activation.reconcile(self.row.pk)
                self.assertEqual(row.status, 'awaiting_payment')
                self.assertIsNone(row.payment_id)
                pay.assert_not_called()

    def test_legacy_empty_record_does_not_hide_repaired_qr(self):
        FundingInstruction.objects.create(financial_account=self.local, kind='bank_details', status='active',
                                          display_value='', provider_resource_id='embedded:brl:bank_details')
        self.sync({'br_code_brl': {'br_code': 'pix-copy-paste'}})
        self.row.status = 'active'
        self.row.save()
        view = local_money.receive_account(self.owner, 'br_pix_receive')
        self.assertEqual(view['value'], 'pix-copy-paste')
        self.assertEqual(view['instruction_kind'], 'qr')
        self.assertEqual(view['institution'], 'STARK BANK S.A.')

    def test_pix_keys_remain_supported_in_both_shapes(self):
        for fields in ({'pix_key': 'ana@example.com'}, {'pix_key_brl': {'pix_key': 'ana@example.com'}}):
            with self.subTest(fields=fields):
                self.sync(fields)
                instruction = self.local.funding_instructions.get(kind='pix_key')
                self.assertEqual(instruction.display_value, 'ana@example.com')
                self.assertTrue(activation.opening_ready(self.row))

    def test_empty_or_malformed_pix_data_never_unlocks_payment(self):
        for fields in ({'br_code': ''}, {'br_code': {}}, {'br_code_brl': {'br_code': []}},
                       {'pix_key_brl': {'pix_key': {}}}, {'br_code': '   '}):
            with self.subTest(fields=fields):
                self.local.funding_instructions.all().delete()
                self.sync(fields)
                self.assertFalse(activation.opening_ready(self.row))

    def test_expired_qr_is_neither_ready_nor_displayed(self):
        self.sync({'br_code': 'pix-copy-paste'})
        self.local.funding_instructions.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.row.status = 'active'
        self.row.save()
        self.assertFalse(activation.opening_ready(self.row))
        self.assertEqual(local_money.receive_account(self.owner, 'br_pix_receive')['value'], '')

    def test_unpaid_opening_withholds_qr(self):
        self.sync({'br_code': 'pix-copy-paste'})
        self.assertEqual(local_money.receive_account(self.owner, 'br_pix_receive')['value'], '')

    def test_removed_or_malformed_qr_closes_previous_receiving_instruction(self):
        for fields in ({'br_code': ''}, {'br_code_brl': {'br_code': {}}}, {}):
            with self.subTest(fields=fields):
                self.sync({'br_code': 'old-pix-code'})
                self.assertTrue(activation.opening_ready(self.row))
                self.sync(fields)
                self.assertFalse(activation.opening_ready(self.row))
                self.row.status = 'active'
                self.row.save()
                self.assertEqual(local_money.receive_account(self.owner, 'br_pix_receive')['value'], '')

    def test_qr_can_replace_key_and_recover_after_missing_data(self):
        self.sync({'pix_key': 'old@example.com'})
        self.sync({})
        self.sync({'br_code': 'new-pix-code'})
        self.row.status = 'active'
        self.row.save()
        self.assertEqual(self.local.funding_instructions.get(kind='pix_key').status, 'closed')
        self.assertEqual(local_money.receive_account(self.owner, 'br_pix_receive')['value'], 'new-pix-code')
        self.assertTrue(activation.opening_ready(self.row))

    def test_long_payload_is_stored_without_truncation(self):
        value = '000201' + 'a' * 400
        self.sync({'br_code_brl': {'br_code': value}})
        self.assertEqual(self.local.funding_instructions.get(kind='qr').display_value, value)

    def test_existing_generic_qr_value_shape_remains_supported(self):
        self.sync({'type': 'qr', 'value': 'existing-qr'})
        self.assertEqual(self.local.funding_instructions.get(kind='qr').display_value, 'existing-qr')

    def test_api_exposes_actual_qr_kind_and_preserves_fee_gate(self):
        from payment_accounts import local_money_schema as schema
        self.sync({'br_code': 'pix-copy-paste'})
        info = SimpleNamespace(context=SimpleNamespace(META={}))
        with mock.patch.object(schema, '_owner', return_value=self.owner):
            unpaid = schema.LocalMoneyQuery.resolve_local_receive_account(None, info, 'br_pix_receive')
            self.assertEqual(unpaid.value, '')
            self.row.status = 'active'
            self.row.save()
            paid = schema.LocalMoneyQuery.resolve_local_receive_account(None, info, 'br_pix_receive')
        self.assertEqual((paid.instruction_kind, paid.value), ('qr', 'pix-copy-paste'))
