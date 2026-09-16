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
        identity = dict(full_name='Ann A')
        for name in ('Anna', None, 123, [], {}, '', '   ', '---'):
            with self.subTest(name=name):
                self.assertFalse(sender_matches(dict(type='FIAT', full_name=name), identity))

    def test_name_matches_ignore_all_document_evidence(self):
        identity = dict(full_name='José Pérez', document_number='12-34', document_type='DNI', document_issuing_country='PER')
        sender = dict(type='FIAT', full_name='JOSE PEREZ')
        for documents in ({}, {'document_number': None, 'document_type': None},
                {'document_number': '999', 'document_type': 'OTHER'},
                {'document_number': 123, 'document_type': []}):
            with self.subTest(documents=documents):
                self.assertTrue(sender_matches(dict(sender, **documents), identity))
        self.assertTrue(sender_matches(sender, {'full_name': 'José Pérez'}))

    def test_complete_name_components_allow_formatting_and_order(self):
        for name in ('  JOSE   PEREZ\t', 'Pérez, José', 'JOSE-PEREZ', 'Jose\u0301 Pe\u0301rez'):
            with self.subTest(name=name):
                self.assertTrue(sender_matches(dict(type='FIAT', full_name=name), {'full_name': 'José Pérez'}))

    def test_similar_incomplete_or_extra_names_do_not_match(self):
        for name in ('Maria Elena', 'M Elena Santos', 'Marie Elena Santos', 'Maria Elena Santos Other',
                'Maria Elena Elena Santos'):
            with self.subTest(name=name):
                self.assertFalse(sender_matches(dict(type='FIAT', full_name=name), {'full_name': 'Maria Elena Santos'}))
        self.assertFalse(sender_matches({'type': 'CRYPTO', 'full_name': 'Owner'}, {'full_name': 'Owner'}))
        for identity in (None, [], {'full_name': None}, {'full_name': '---'}):
            self.assertFalse(sender_matches({'type': 'FIAT', 'full_name': 'Owner'}, identity))


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

    def test_missing_provider_capability_uses_confio_controls_not_pending_default(self):
        from payment_accounts.services import _infinia_capabilities
        self.account.provider_data = {'latest': {}}
        _infinia_capabilities(self.account)
        self.assertEqual(AccountCapability.objects.get(financial_account=self.account,
            capability='receive_third_party').status, 'enabled')
        self.assertFalse(assess(self.entry).allowed)
        self.grants()
        self.assertTrue(assess(self.entry).allowed)
        ThirdPartyPayinSwitch.objects.filter(confio_account=self.owner).update(enabled=False)
        self.assertEqual(assess(self.entry).reason, 'user_not_enabled')

    def test_explicit_provider_restrictions_override_confio_managed_default(self):
        from payment_accounts.services import _infinia_capabilities
        self.grants()
        for value in (False, 'DISABLED', 'PENDING', 'UPON_APPROVAL'):
            self.account.provider_data = {'latest': {'capabilities': {'payin_third_party': value}}}
            _infinia_capabilities(self.account)
            self.assertEqual(assess(self.entry).reason, 'provider_third_party_not_enabled')

    def test_wildcard_grants_keep_exact_stops_and_other_gates(self):
        self.grants()
        ThirdPartyPayinSwitch.objects.filter(rail='BANK').update(rail='*')
        self.assertTrue(assess(self.entry).allowed)
        for owner, reason in ((None, 'rail_not_enabled'), (self.owner, 'user_not_enabled')):
            stop = ThirdPartyPayinSwitch.objects.create(provider='infinia', country='PE',
                rail='BANK', confio_account=owner, enabled=False, evidence='Explicit stop')
            self.assertEqual(assess(self.entry).reason, reason)
            stop.enabled, stop.evidence = True, ''
            stop.save()
            self.assertEqual(assess(self.entry).reason, reason)
            stop.delete()
        ThirdPartyPayinSwitch.objects.filter(rail='').update(enabled=False)
        self.assertEqual(assess(self.entry).reason, 'country_not_enabled')
        ThirdPartyPayinSwitch.objects.filter(rail='').update(enabled=True)
        AccountCapability.objects.filter(capability='receive_third_party').update(status='pending')
        self.assertEqual(assess(self.entry).reason, 'provider_third_party_not_enabled')
        for rail in ('', '*'):
            self.account.payin_rail = rail
            self.assertEqual(assess(self.entry).reason, 'unverified_rail')

    def test_wildcard_grants_do_not_cross_recipients_or_countries(self):
        self.grants()
        ThirdPartyPayinSwitch.objects.filter(rail='BANK').update(rail='*')
        ThirdPartyPayinSwitch.objects.filter(confio_account=self.owner).delete()
        self.assertEqual(assess(self.entry).reason, 'user_not_enabled')
        self.account.country = 'COL'
        self.assertEqual(assess(self.entry).reason, 'country_not_enabled')

    def test_same_owner_does_not_need_third_party_grants(self):
        self.entry.provider_data['third_party'].update(full_name='Owner', document_number='123')
        self.assertEqual(assess(self.entry).reason, 'same_owner')
        self.assertTrue(assess(self.entry).allowed)

    def test_mxn_payload_shape_matches_by_name_without_document_jurisdiction(self):
        # Synthetic identifiers preserve the observed MXN shape without customer PII.
        self.account.country = 'MEX'
        self.account.asset = self.entry.asset = 'MXN'
        self.account.payin_rail = 'SPEI'
        self.account.payin_document_country = ''
        self.profile.identity_snapshot = dict(full_name='María Elena Santos',
            document_number='VERIFIED0000000001', document_type='national_id')
        self.entry.provider_data = {'operation': {'type': 'CREDIT', 'operation_id': None},
            'third_party': dict(type='FIAT', full_name='MARIA ELENA SANTOS                       ',
                document_number='SENDER0000001', document_type=None, bank_name=None)}
        result = assess(self.entry)
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, 'same_owner')

    def test_same_name_still_requires_rail_identity_and_provider_permission(self):
        self.entry.provider_data = {'third_party': {'type': 'FIAT', 'full_name': 'Owner'}}
        AccountCapability.objects.filter(capability='receive_same_name').update(status='pending')
        self.assertEqual(assess(self.entry).reason, 'provider_same_name_not_enabled')
        self.account.payin_rail = ''
        self.assertEqual(assess(self.entry).reason, 'unverified_rail')
        self.profile.identity_verification.status = 'pending'
        self.assertEqual(assess(self.entry).reason, 'identity_not_verified')

    def test_third_party_without_documents_requires_all_switches(self):
        self.entry.provider_data = {'third_party': {'type': 'FIAT', 'full_name': 'Other'}}
        self.assertFalse(assess(self.entry).allowed)
        self.grants()
        self.assertTrue(assess(self.entry).allowed)
        ThirdPartyPayinSwitch.objects.filter(confio_account=self.owner).update(enabled=False)
        self.assertEqual(assess(self.entry).reason, 'user_not_enabled')

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
