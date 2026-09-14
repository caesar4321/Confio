from decimal import Decimal
from unittest import mock

from django.test import TestCase, SimpleTestCase
from django.core.exceptions import ValidationError
from django.utils import timezone

from payment_accounts.models import AccountCapability, LedgerEntry, MoneyFlow, MoneyOperation, ThirdPartyPayinSwitch
from payment_accounts.payin_admission import assess, sender_matches, require_source_admitted
from payment_accounts.services import PaymentAccountError
from .test_bridge import BridgeQuoteTests


class SenderTests(SimpleTestCase):
    def test_controls_registered_on_actual_confio_admin_site(self):
        from config.admin_dashboard import confio_admin_site
        from payment_accounts.models import PayinAdmission
        self.assertTrue(confio_admin_site.is_registered(ThirdPartyPayinSwitch))
        self.assertTrue(confio_admin_site.is_registered(PayinAdmission))

    def test_name_word_boundaries_and_non_strings_do_not_match(self):
        identity = dict(full_name='Ann A', document_number='123', document_type='DNI', document_issuing_country='PE')
        sender = dict(type='FIAT', full_name='Anna', document_number='123', document_type='DNI')
        self.assertFalse(sender_matches(sender, identity, 'PE'))
        sender.update(full_name='Ann A', document_number=123)
        self.assertFalse(sender_matches(sender, identity, 'PE'))

    def test_documents_and_names_required(self):
        identity = dict(full_name='José Pérez', document_number='12-34', document_type='DNI', document_issuing_country='PER')
        sender = dict(type='FIAT', full_name='JOSE PEREZ', document_number='1234', document_type='DNI')
        self.assertTrue(sender_matches(sender, identity, 'PE'))
        for field in ('full_name', 'document_number', 'document_type'):
            self.assertFalse(sender_matches(dict(sender, **{field: None}), identity, 'PE'))
        self.assertFalse(sender_matches(sender, identity, 'AR'))
        self.assertFalse(sender_matches(sender, identity, ''))
        self.assertFalse(sender_matches(dict(sender, document_number='999'), identity, 'PE'))


class AdmissionTests(TestCase):
    def setUp(self):
        BridgeQuoteTests.setUp(self)
        self.account = self.instruction.financial_account
        self.account.country, self.account.asset = 'PER', 'PEN'
        self.account.payin_rail, self.account.payin_document_country = 'BANK', 'PE'
        self.account.save()
        self.profile = self.account.provider_profile
        self.profile.identity_snapshot = dict(full_name='Owner', document_number='123', document_type='DNI', document_issuing_country='PE')
        self.profile.save()
        self.sender = dict(type='FIAT', full_name='Other', document_number='456', document_type='DNI')
        self.entry = LedgerEntry.objects.create(provider='infinia', financial_account=self.account,
            provider_entry_id='test', direction='credit', asset='PEN', amount=Decimal('10'),
            occurred_at=timezone.now(), provider_data={'third_party': self.sender})
        for capability in ('receive_third_party', 'receive_same_name'):
            AccountCapability.objects.create(financial_account=self.account, capability=capability, status='enabled')

    def grants(self):
        for rail, owner in (('', None), ('BANK', None), ('BANK', self.owner)):
            ThirdPartyPayinSwitch.objects.create(provider='infinia', country='PE', rail=rail,
                confio_account=owner, enabled=True, evidence='Reviewed approval')

    def test_all_three_scopes_required_and_revocable(self):
        self.assertEqual(assess(self.entry).reason, 'country_not_enabled')
        self.grants()
        self.assertTrue(assess(self.entry).allowed)
        for filters, reason in (({'rail': ''}, 'country_not_enabled'),
                ({'rail': 'BANK', 'confio_account__isnull': True}, 'rail_not_enabled'),
                ({'confio_account': self.owner}, 'user_not_enabled')):
            ThirdPartyPayinSwitch.objects.filter(**filters).update(enabled=False)
            self.assertEqual(assess(self.entry).reason, reason)
            ThirdPartyPayinSwitch.objects.filter(**filters).update(enabled=True)

    def test_provider_capability_is_independent(self):
        self.grants()
        AccountCapability.objects.filter(capability='receive_third_party').update(status='pending')
        self.assertEqual(assess(self.entry).reason, 'provider_third_party_not_enabled')

    def test_same_owner_does_not_need_third_party_grants(self):
        self.entry.provider_data['third_party'].update(full_name='Owner', document_number='123')
        self.assertEqual(assess(self.entry).reason, 'same_owner')
        self.assertTrue(assess(self.entry).allowed)

    def test_unknown_sender_rail_and_revoked_identity_fail_closed(self):
        self.grants()
        self.entry.provider_data = {'third_party': None}
        self.assertEqual(assess(self.entry).reason, 'sender_identity_missing')
        self.account.payin_rail = ''
        self.assertEqual(assess(self.entry).reason, 'unverified_rail')
        self.profile.identity_verification.status = 'pending'
        self.assertEqual(assess(self.entry).reason, 'identity_not_verified')

    def test_country_rail_and_owner_do_not_leak(self):
        self.grants()
        self.account.country = 'COL'
        self.assertFalse(assess(self.entry).allowed)
        self.account.country, self.account.payin_rail = 'PER', 'OTHER'
        self.assertFalse(assess(self.entry).allowed)
        self.account.payin_rail = 'BANK'
        ThirdPartyPayinSwitch.objects.filter(confio_account=self.owner).delete()
        self.assertFalse(assess(self.entry).allowed)

    def test_generic_balance_spend_is_blocked(self):
        with self.assertRaises(PaymentAccountError):
            require_source_admitted(self.account)

    def test_generic_submission_cannot_spend_before_webhook(self):
        from payment_accounts.services import submit_money_operation
        self.entry.delete()
        flow = MoneyFlow.objects.create(confio_account=self.owner, kind='convert', source_asset='PEN', source_amount=10)
        operation = MoneyOperation.objects.create(money_flow=flow, provider='infinia', operation_type='conversion',
            source_account=self.account, idempotency_key='missing-webhook', source_asset='PEN', source_amount=10)
        with mock.patch('payment_accounts.services.get_provider') as adapter:
            with self.assertRaisesRegex(PaymentAccountError, 'admitted payment journey'):
                submit_money_operation(operation)
            adapter.assert_not_called()

    def test_switch_validation_requires_evidence_and_rail_for_user(self):
        switch = ThirdPartyPayinSwitch(provider='infinia', country='PE', enabled=True, evidence='  ')
        with self.assertRaises(ValidationError):
            switch.clean()
        switch.evidence, switch.confio_account = 'Approved', self.owner
        with self.assertRaises(ValidationError):
            switch.clean()
        switch.rail = 'bank'
        switch.clean()
        self.assertEqual(switch.rail, 'BANK')

    def test_uncorrelated_internal_credit_is_not_exempt(self):
        self.entry.provider_data = {'operation': {'type': 'INTERNAL_TRANSFER'}}
        self.assertFalse(assess(self.entry).allowed)

    def test_correlated_same_owner_transfer_is_exempt(self):
        flow = MoneyFlow.objects.create(confio_account=self.owner, kind='convert', source_asset='PEN', source_amount=10)
        operation = MoneyOperation.objects.create(money_flow=flow, provider='infinia',
            operation_type='conversion', source_account=self.account, destination_account=self.account,
            provider_operation_id='internal-1', idempotency_key='internal-1', source_asset='PEN', source_amount=10)
        self.entry.provider_data = {'operation': {'type': 'INTERNAL_TRANSFER', 'operation_id': 'internal-1'}}
        self.assertIsNone(assess(self.entry))
        operation.destination_account = None
        operation.save()
        self.assertFalse(assess(self.entry).allowed)

    def test_whitespace_evidence_is_not_an_approval(self):
        self.grants()
        ThirdPartyPayinSwitch.objects.filter(confio_account=self.owner).update(evidence='  ')
        self.assertEqual(assess(self.entry).reason, 'user_not_enabled')

    def test_unknown_fiat_is_not_a_bypass(self):
        self.account.asset = self.entry.asset = 'NEW_FIAT'
        self.assertFalse(assess(self.entry).allowed)

    def test_malformed_sender_is_held(self):
        self.grants()
        self.entry.provider_data = ['bad payload']
        self.assertEqual(assess(self.entry).reason, 'sender_identity_missing')

    def test_mismatched_asset_is_held(self):
        self.grants()
        self.entry.asset = 'USD'
        self.assertEqual(assess(self.entry).reason, 'asset_mismatch')

    def test_business_cannot_match_representative_name(self):
        self.profile.owner_type = 'business'
        self.entry.provider_data['third_party'].update(full_name='Owner', document_number='123')
        self.assertFalse(assess(self.entry).allowed)
