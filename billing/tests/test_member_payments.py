from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
import graphene

from billing.member_payments import MemberCheckoutError, create_member_payment_intent
from billing.identity_tokens import create_identity_session, issue_identity_token
from billing.models import (
    BillingObligation, BillingSchedule, InstitutionConnection,
    ObligationSubject,
)
from billing.models import BillingPayment
from billing.schema import Mutation, Query
from exchange_rates.models import ExchangeRate
from users.models import Account, Business
from payments import bsc_flow

schema = graphene.Schema(query=Query, mutation=Mutation)


@override_settings(
    BILLING_RATE_MAX_AGE_HOURS=36, BILLING_QUOTE_TTL_MINUTES=15,
    BILLING_INSTITUTION_TOKEN_KEY='test-institution-signing-key',
    CUSD_PLUS_VAULT_ADDRESS='0x' + '44' * 20,
    CUSD_VAULT_ADDRESS='0x' + '66' * 20,
    BSC_PAY_CONTRACT_ADDRESS='0x' + '55' * 20,
    BSC_PAY_ENABLED=True,
    BILLING_LIVE_API_KEYS_ENABLED=True,
    BILLING_CIP_SANDBOX_ENABLED=True,
)
class MemberPaymentTests(TestCase):
    def setUp(self):
        context_patch = mock.patch(
            'billing.schema.get_jwt_business_context_with_validation',
            side_effect=lambda info, **kwargs: {
                'user_id': info.context.user.id, 'account_type': 'personal',
                'account_index': 0, 'business_id': None,
            })
        self.jwt_context = context_patch.start()
        self.addCleanup(context_patch.stop)
        User = get_user_model()
        self.member = User.objects.create_user(
            username='cip-member', firebase_uid='cip-member-uid')
        self.other = User.objects.create_user(
            username='another-member', firebase_uid='another-member-uid')
        merchant_user = User.objects.create_user(
            username='cip-merchant', firebase_uid='cip-merchant-uid')
        self.business = Business.objects.create(name='CIP', category='services')
        Account.objects.create(
            user=merchant_user, account_type='business', account_index=0,
            business=self.business, bsc_address='0x' + '22' * 20)
        Account.objects.create(
            user=self.member, account_type='personal', account_index=0,
            bsc_address='0x' + '11' * 20)
        self.subject = ObligationSubject.objects.create(
            business=self.business, external_id='cip:42', confio_user=self.member,
            subject_type='membership', display_label='Secret Name',
            masked_reference='CIP ••••0042')
        now = timezone.now()
        self.schedule = BillingSchedule.objects.create(
            business=self.business, subject=self.subject,
            external_reference='cip:monthly:42', amount_minor=3500,
            presentation_mode='payer_amount', next_period_start=date(2026, 10, 1))
        self.obligation = BillingObligation.objects.create(
            business=self.business, subject=self.subject, schedule=self.schedule,
            period_key='2026-09', external_reference='cip:42:2026-09',
            currency='PEN', original_amount_minor=3500,
            amount_remaining_minor=3500,
            line_items_snapshot=[{'description': 'Cuota de septiembre'}],
            period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
            issued_at=now, due_at=now + timedelta(days=7), status='open')
        self.rate = ExchangeRate.objects.create(
            source_currency='PEN', target_currency='USD', rate=Decimal('3.5'),
            rate_type='official', source='manual', fetched_at=now)

    def _entry_summary(self, user=None):
        result = schema.execute(
            '{ myBillingSummary { linked entry { id institutionName status applicationStatus } } }',
            context_value=SimpleNamespace(user=user or self.member))
        self.assertIsNone(result.errors)
        return result.data['myBillingSummary']

    def test_entry_is_only_for_linked_member_with_actionable_bill(self):
        self.assertEqual(self._entry_summary(self.other), {'linked': False, 'entry': None})
        entry = self._entry_summary()['entry']
        self.assertEqual(entry['id'], self.obligation.public_id)
        self.assertEqual(entry['institutionName'], 'CIP')
        for status in ('paid', 'void', 'held', 'disputed', 'draft'):
            self.obligation.status = status
            self.obligation.save(update_fields=('status',))
            self.assertEqual(self._entry_summary(), {'linked': True, 'entry': None})

    @override_settings(BILLING_LIVE_API_KEYS_ENABLED=False, BILLING_CIP_SANDBOX_ENABLED=False)
    def test_disabled_rollout_keeps_home_entry_hidden(self):
        self.assertIsNone(self._entry_summary()['entry'])

    def test_inactive_membership_keeps_home_entry_hidden(self):
        self.subject.status = 'inactive'
        self.subject.save(update_fields=('status',))
        self.assertIsNone(self._entry_summary()['entry'])

    def test_payer_amount_quote_keeps_fee_on_receiver_and_reuses_intent(self):
        intent = create_member_payment_intent(
            obligation_public_id=self.obligation.public_id, user=self.member)
        quote = intent.settlement_quote
        self.assertEqual(intent.legacy_invoice.amount, Decimal('10.000000'))
        self.assertEqual(int(quote.gross_units), 10 * 10**18)
        self.assertEqual(int(quote.fee_units), 9 * 10**16)
        self.assertEqual(int(quote.receiver_net_units), 991 * 10**16)
        reused = create_member_payment_intent(
            obligation_public_id=self.obligation.public_id, user=self.member)
        self.assertEqual(reused.id, intent.id)

    def test_receiver_net_target_grosses_up(self):
        self.schedule.presentation_mode = 'receiver_net_target'
        self.schedule.save(update_fields=('presentation_mode', 'updated_at'))
        intent = create_member_payment_intent(
            obligation_public_id=self.obligation.public_id, user=self.member)
        quote = intent.settlement_quote
        self.assertGreater(int(quote.gross_units), 10 * 10**18)
        self.assertGreaterEqual(int(quote.receiver_net_units), 10 * 10**18)

    def test_expired_quote_is_canceled_before_replacement(self):
        first = create_member_payment_intent(
            obligation_public_id=self.obligation.public_id, user=self.member)
        first.expires_at = timezone.now() - timedelta(seconds=1)
        first.save(update_fields=('expires_at', 'updated_at'))
        replacement = create_member_payment_intent(
            obligation_public_id=self.obligation.public_id, user=self.member)
        self.assertNotEqual(replacement.id, first.id)
        first.refresh_from_db()
        first.legacy_invoice.refresh_from_db()
        self.assertEqual(first.status, 'canceled')
        self.assertEqual(first.legacy_invoice.status, 'EXPIRED')

    def test_other_user_cannot_create_or_query_member_due(self):
        with self.assertRaises(BillingObligation.DoesNotExist):
            create_member_payment_intent(
                obligation_public_id=self.obligation.public_id, user=self.other)
        result = schema.execute(
            '{ myBillingObligations { id institutionName memberReference } }',
            context_value=SimpleNamespace(user=self.other),
        )
        self.assertIsNone(result.errors)
        self.assertEqual(result.data['myBillingObligations'], [])

    def test_member_query_exposes_masked_reference_not_identity_or_external_id(self):
        result = schema.execute(
            '{ myBillingObligations { id institutionName memberReference status } }',
            context_value=SimpleNamespace(user=self.member),
        )
        self.assertIsNone(result.errors)
        row = result.data['myBillingObligations'][0]
        self.assertEqual(row['memberReference'], 'CIP ••••0042')
        self.assertNotIn('externalId', row)
        self.assertNotIn('Secret Name', str(result.data))

    def test_missing_mask_does_not_fall_back_to_private_display_label(self):
        self.subject.masked_reference = ''
        self.subject.save(update_fields=('masked_reference', 'updated_at'))
        result = schema.execute(
            '{ myBillingObligations { memberReference } }',
            context_value=SimpleNamespace(user=self.member))
        self.assertIsNone(result.errors)
        self.assertNotIn('Secret Name', str(result.data))

    def test_member_reads_and_checkout_require_valid_jwt_context(self):
        self.jwt_context.side_effect = None
        self.jwt_context.return_value = None
        for query in (
                '{ myBillingObligations { id } }',
                '{ myBillingSummary { linked } }',
                'mutation { createMemberPaymentIntent(obligationId: "%s") { success } }'
                % self.obligation.public_id):
            result = schema.execute(query, context_value=SimpleNamespace(user=self.member))
            self.assertTrue(result.errors)
            self.assertIn('permission_denied', str(result.errors))

    def test_checkout_uses_jwt_selected_payer_account(self):
        second = Account.objects.create(
            user=self.member, account_type='personal', account_index=1,
            bsc_address='0x' + '33' * 20)
        self.jwt_context.side_effect = None
        self.jwt_context.return_value = {'account_type': 'personal', 'account_index': 1}
        result = schema.execute(
            'mutation { createMemberPaymentIntent(obligationId: "%s") { success } }'
            % self.obligation.public_id, context_value=SimpleNamespace(user=self.member))
        self.assertIsNone(result.errors)
        self.assertTrue(result.data['createMemberPaymentIntent']['success'])
        from billing.models import BillingPaymentIntent
        self.assertEqual(BillingPaymentIntent.objects.get().payer_account_id, second.id)
        self.assertEqual(self.jwt_context.call_args.kwargs['required_permission'], 'send_funds')

    def test_conflicting_claim_does_not_consume_membership_link(self):
        connection = InstitutionConnection.objects.create(
            business=self.business, provider='cip', mode='live', status='active', live_approved=True)
        session = create_identity_session(
            connection=connection, subject=self.subject, requested_fields=[])
        token = issue_identity_token(session)
        result = schema.execute(
            'mutation Claim($token: String!) { claimInstitutionMembership(provider: "cip", token: $token) { success errors } }',
            variable_values={'token': token}, context_value=SimpleNamespace(user=self.other))
        self.assertIsNone(result.errors)
        self.assertFalse(result.data['claimInstitutionMembership']['success'])
        session.refresh_from_db()
        self.assertIsNone(session.token_used_at)

    def test_identity_fields_require_separate_consent_before_claim(self):
        from billing.models import InstitutionDataRequirement
        connection = InstitutionConnection.objects.create(
            business=self.business, provider='cip', mode='live', status='active', live_approved=True)
        InstitutionDataRequirement.objects.create(
            connection=connection, field_name='dni', purpose='Verify membership', retention_days=30)
        session = create_identity_session(
            connection=connection, subject=self.subject, requested_fields=['dni'])
        result = schema.execute(
            'mutation Claim($token: String!) { claimInstitutionMembership(provider: "cip", token: $token) { success errors } }',
            variable_values={'token': issue_identity_token(session)},
            context_value=SimpleNamespace(user=self.member))
        self.assertIsNone(result.errors)
        self.assertIn('identity_consent_required', result.data['claimInstitutionMembership']['errors'])
        session.refresh_from_db()
        self.assertIsNone(session.token_used_at)

    def test_stale_rate_fails_closed(self):
        ExchangeRate.objects.filter(pk=self.rate.pk).update(
            fetched_at=timezone.now() - timedelta(hours=37))
        with self.assertRaisesRegex(MemberCheckoutError, 'settlement_rate_unavailable'):
            create_member_payment_intent(
                obligation_public_id=self.obligation.public_id, user=self.member)

    def _prepare_member(self):
        intent = create_member_payment_intent(
            obligation_public_id=self.obligation.public_id, user=self.member)
        gross = int(intent.legacy_invoice.amount * 10**18)
        with mock.patch('cusd_plus.vault.p_plus_wad', return_value=10**18), \
             mock.patch('cusd_plus.vault.last_oracle_price_wad', return_value=10**18), \
             mock.patch('cusd_plus.vault.erc20_balance_raw', return_value=gross * 2), \
             mock.patch('cusd_plus.vault.usdt_balance_raw', return_value=0), \
             mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True), \
             mock.patch.object(
                 bsc_flow, '_sign_pay_authorization',
                 return_value=('0x' + '11' * 65, '0x' + '33' * 20)):
            result = bsc_flow.prepare_bsc_payment(
                self.member, {'account_type': 'personal', 'account_index': 0},
                intent.legacy_invoice, 'member-payment')
        self.assertTrue(result['success'], result)
        return intent

    def test_bsc_prepare_attaches_billing_payment_and_marks_due_pending(self):
        intent = self._prepare_member()
        gross = int(intent.legacy_invoice.amount * 10**18)
        payment = BillingPayment.objects.get(payment_intent=intent)
        self.assertEqual(payment.status, 'processing')
        self.assertEqual(int(payment.gross_units), gross)
        self.obligation.refresh_from_db()
        intent.refresh_from_db()
        self.assertEqual(intent.status, 'processing')
        self.assertEqual(self.obligation.status, 'payment_pending')

    def test_prepared_checkout_can_be_resumed_and_deadline_is_bounded_by_quote(self):
        intent = self._prepare_member()
        payment = BillingPayment.objects.get(payment_intent=intent)
        self.assertLessEqual(payment.legacy_payment.blockchain_data['pay_deadline'],
                             int(intent.expires_at.timestamp()))
        resumed = create_member_payment_intent(
            obligation_public_id=self.obligation.public_id, user=self.member)
        self.assertEqual(resumed.id, intent.id)

    def test_reprepare_preserves_issued_calls_and_settlement_snapshot(self):
        intent = self._prepare_member()
        payment = BillingPayment.objects.get(payment_intent=intent)
        calls = payment.legacy_payment.blockchain_data['bsc_calls']
        gross = payment.gross_units
        with mock.patch('cusd_plus.vault.p_plus_wad', side_effect=AssertionError('must reuse quote')):
            result = bsc_flow.prepare_bsc_payment(self.member,
                {'account_type': 'personal', 'account_index': 0}, intent.legacy_invoice)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['calls'], calls)
        payment.refresh_from_db()
        self.assertEqual(payment.gross_units, gross)

    def test_reprepare_does_not_replace_another_accounts_authorization(self):
        intent = self._prepare_member()
        Account.objects.create(user=self.member, account_type='personal', account_index=1,
                               bsc_address='0x' + '77' * 20)
        result = bsc_flow.prepare_bsc_payment(self.member,
            {'account_type': 'personal', 'account_index': 1}, intent.legacy_invoice)
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'payment_account_changed')

    def test_member_application_status_is_separate_and_does_not_expose_raw_connector_values(self):
        from billing.models import InstitutionApplication
        from billing.services import post_full_balance_payment
        intent = self._prepare_member()
        payment = BillingPayment.objects.get(payment_intent=intent)
        payment.status = 'confirmed'
        payment.confirmed_at = timezone.now()
        payment.save(update_fields=('status', 'confirmed_at', 'updated_at'))
        effect = post_full_balance_payment(billing_payment_id=payment.id, semantic_key='member-query-paid')
        application = InstitutionApplication.objects.create(
            billing_payment=payment, allocation=effect.allocations.get(),
            opaque_subject_reference='private-member-reference', status='application_pending',
            idempotency_key='member-query-application', payment_confirmed_at=payment.confirmed_at,
            returned_status='private-response-dni-12345678')
        query = '{ myBillingObligations { institutionApplicationStatus institutionMemberStatus institutionAppliedAt } }'
        result = schema.execute(query, context_value=SimpleNamespace(user=self.member))
        self.assertIsNone(result.errors)
        row = result.data['myBillingObligations'][0]
        self.assertEqual(row['institutionApplicationStatus'], 'application_pending')
        self.assertIsNone(row['institutionMemberStatus'])
        self.assertIsNone(row['institutionAppliedAt'])
        self.assertEqual(self._entry_summary()['entry']['applicationStatus'], 'application_pending')
        application.status = 'acknowledged'
        application.returned_status = 'active'
        application.institution_applied_at = timezone.now()
        application.save(update_fields=('status', 'returned_status', 'institution_applied_at', 'updated_at'))
        result = schema.execute(query, context_value=SimpleNamespace(user=self.member))
        row = result.data['myBillingObligations'][0]
        self.assertEqual(row['institutionMemberStatus'], 'active')
        self.assertIsNotNone(row['institutionAppliedAt'])
        self.assertIsNone(self._entry_summary()['entry'])

    def test_abandoned_preparation_can_expire_after_authorization_guard(self):
        intent = self._prepare_member()
        intent.expires_at = timezone.now() - timedelta(minutes=5)
        intent.save(update_fields=('expires_at', 'updated_at'))
        payment = BillingPayment.objects.get(payment_intent=intent)
        legacy = payment.legacy_payment
        legacy.blockchain_data['pay_deadline'] = int(intent.expires_at.timestamp())
        legacy.save(update_fields=('blockchain_data', 'updated_at'))
        replacement = create_member_payment_intent(
            obligation_public_id=self.obligation.public_id, user=self.member)
        self.assertNotEqual(replacement.id, intent.id)
        payment.refresh_from_db()
        legacy.refresh_from_db()
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(legacy.status, 'FAILED')

    def test_expired_quote_cannot_replace_still_valid_onchain_authorization(self):
        intent = self._prepare_member()
        intent.expires_at = timezone.now() - timedelta(seconds=1)
        intent.save(update_fields=('expires_at', 'updated_at'))
        with self.assertRaisesRegex(MemberCheckoutError, 'payment_in_progress'):
            create_member_payment_intent(
                obligation_public_id=self.obligation.public_id, user=self.member)
        intent.refresh_from_db()
        self.assertEqual(intent.status, 'processing')

    def test_unobserved_sponsor_submission_prevents_replacement_and_reprepare(self):
        from blockchain.models import SponsoredBatch
        intent = self._prepare_member()
        payment = BillingPayment.objects.get(payment_intent=intent)
        SponsoredBatch.objects.create(
            user=self.member, user_bsc_address=payment.legacy_payment.payer_address,
            source_id=payment.legacy_payment_id, kind='pay_cusd_plus',
            num_calls=2, calls_json='[]', gas_limit=300000, max_fee_wei='1',
            status='signed', tx_hash='0x' + '88' * 32)
        with self.assertRaisesRegex(MemberCheckoutError, 'payment_in_progress'):
            create_member_payment_intent(
                obligation_public_id=self.obligation.public_id, user=self.member)

    @override_settings(BILLING_LIVE_API_KEYS_ENABLED=False)
    def test_live_launch_gate_applies_to_first_party_checkout(self):
        with self.assertRaisesRegex(MemberCheckoutError, 'billing_payments_disabled'):
            create_member_payment_intent(
                obligation_public_id=self.obligation.public_id, user=self.member)

    def test_signed_membership_claim_links_once_without_identity_input(self):
        self.subject.confio_user = None
        self.subject.save(update_fields=('confio_user', 'updated_at'))
        connection = InstitutionConnection.objects.create(
            business=self.business, provider='cip', mode='live', status='active', live_approved=True)
        session = create_identity_session(
            connection=connection, subject=self.subject, requested_fields=[])
        token = issue_identity_token(session)
        mutation = '''
          mutation Claim($token: String!) {
            claimInstitutionMembership(provider: "cip", token: $token) {
              success errors
            }
          }
        '''
        result = schema.execute(
            mutation, variable_values={'token': token},
            context_value=SimpleNamespace(user=self.member))
        self.assertIsNone(result.errors)
        self.assertTrue(result.data['claimInstitutionMembership']['success'])
        self.subject.refresh_from_db()
        self.assertEqual(self.subject.confio_user_id, self.member.id)
        replay = schema.execute(
            mutation, variable_values={'token': token},
            context_value=SimpleNamespace(user=self.member))
        self.assertFalse(replay.data['claimInstitutionMembership']['success'])
        self.assertIn('already used', replay.data['claimInstitutionMembership']['errors'][0])
