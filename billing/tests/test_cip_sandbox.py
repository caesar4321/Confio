import io
import json
import base64
from urllib.parse import parse_qs, urlparse
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from billing.institutions import apply_payment, create_payment_applications
from billing.models import (
    BillingInvoice,
    BillingInvoiceObligation,
    BillingObligation,
    BillingPayment,
    BillingPaymentIntent,
    CipSandboxApplicationReceipt,
    CipSandboxMember,
    InstitutionApplication,
    InstitutionConnection,
    ObligationSubject,
)
from billing.services import post_full_balance_payment
from payments.models import Invoice, PaymentTransaction
from users.models import Account, Business


SANDBOX_TOKEN = 'test-cip-sandbox-token'


@override_settings(
    BILLING_CIP_SANDBOX_ENABLED=True,
    BILLING_CIP_SANDBOX_TOKEN=SANDBOX_TOKEN,
    BILLING_INSTITUTION_TOKEN_KEY='test-institution-signing-key',
)
class CipSandboxTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.merchant_user = User.objects.create_user(
            username='cip-sandbox-merchant', firebase_uid='cip-sm-uid')
        self.member_user = User.objects.create_user(
            username='cip-sandbox-member', firebase_uid='cip-su-uid')
        self.business = Business.objects.create(name='CIP Test', category='services')
        self.merchant_account = Account.objects.create(
            user=self.merchant_user, account_type='business', account_index=0,
            business=self.business, bsc_address='0x' + '22' * 20)
        self.payer_account = Account.objects.create(
            user=self.member_user, account_type='personal', account_index=0,
            bsc_address='0x' + '11' * 20)
        self.connection = InstitutionConnection.objects.create(
            business=self.business, provider='cip', mode='test', status='sandbox')
        self.subject = ObligationSubject.objects.create(
            business=self.business, mode='test', external_id='cip:000042',
            subject_type='membership', masked_reference='CIP ••••0042')
        self.member = CipSandboxMember.objects.create(
            connection=self.connection, subject=self.subject,
            member_number='000042', habilidad='inactive')
        now = timezone.now()
        self.obligation = BillingObligation.objects.create(
            business=self.business, mode='test', subject=self.subject,
            external_reference='cip:000042:2026-09', period_key='2026-09',
            currency='PEN', original_amount_minor=5000,
            amount_remaining_minor=5000,
            line_items_snapshot=[{'description': 'Cuota CIP', 'amount_minor': 5000}],
            period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
            issued_at=now, due_at=now + timedelta(days=10), status='open')
        self.client = Client()

    def _post(self, path, payload, idempotency_key=''):
        headers = {'HTTP_AUTHORIZATION': f'Bearer {SANDBOX_TOKEN}'}
        if idempotency_key:
            headers['HTTP_IDEMPOTENCY_KEY'] = idempotency_key
        return self.client.post(
            path, data=json.dumps(payload), content_type='application/json', **headers)

    def test_verify_contract_returns_one_use_link_and_no_raw_identity(self):
        response = self._post('/v1/sandbox/cip/verify', {'member_number': '000042'})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['matched'])
        self.assertEqual(body['habilidad'], 'inactive')
        self.assertEqual(body['member_reference'], 'CIP ••••0042')
        self.assertTrue(body['membership_link'].startswith('confio://memberships?'))
        self.assertNotIn('000042', body['membership_link'])
        token = parse_qs(urlparse(body['membership_link']).query)['token'][0]
        encoded_claims = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded_claims + '=' * (-len(encoded_claims) % 4)))
        for private_field in ('dni', 'email', 'phone', 'member_number'):
            self.assertNotIn(private_field, body)
            self.assertNotIn(private_field, claims)
        self.assertNotIn('000042', json.dumps(claims))

    @override_settings(BILLING_CIP_SANDBOX_ENABLED=False)
    def test_contract_is_indistinguishable_from_missing_when_disabled(self):
        response = self._post('/v1/sandbox/cip/verify', {'member_number': '000042'})
        self.assertEqual(response.status_code, 404)

    def test_contract_rejects_unbounded_identifiers(self):
        verify = self._post('/v1/sandbox/cip/verify', {'member_number': 'x' * 81})
        apply = self._post(
            '/v1/sandbox/cip/payments/apply', {}, idempotency_key='x' * 256)
        self.assertEqual(verify.status_code, 400)
        self.assertEqual(apply.status_code, 400)

    def test_invalid_utf8_and_non_ascii_credentials_fail_cleanly(self):
        response = self.client.post(
            '/v1/sandbox/cip/verify', data=b'\xff', content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {SANDBOX_TOKEN}')
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            '/v1/sandbox/cip/verify', data='{}', content_type='application/json',
            HTTP_AUTHORIZATION='Bearer inválido')
        self.assertEqual(response.status_code, 404)

    def test_apply_contract_is_idempotent_and_detects_key_payload_mismatch(self):
        payload = {'subject_reference': self.subject.external_id,
                   'period_end': '2026-09-30', 'payment_id': 'pay_test'}
        first = self._post(
            '/v1/sandbox/cip/payments/apply', payload, 'apply-000042-2026-09')
        replay = self._post(
            '/v1/sandbox/cip/payments/apply', payload, 'apply-000042-2026-09')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(first.json(), replay.json())
        self.member.refresh_from_db()
        self.assertEqual(self.member.habilidad, 'active')
        self.assertEqual(self.member.paid_through, date(2026, 9, 30))
        self.assertEqual(CipSandboxApplicationReceipt.objects.count(), 1)
        changed = dict(payload, period_end='2026-10-31')
        conflict = self._post(
            '/v1/sandbox/cip/payments/apply', changed, 'apply-000042-2026-09')
        self.assertEqual(conflict.status_code, 409)

    def test_confirmed_payment_creates_and_applies_cip_application(self):
        now = timezone.now()
        billing_invoice = BillingInvoice.objects.create(
            business=self.business, subject=self.subject, number='CIP-SBX-1',
            status='payment_pending', currency='PEN', subtotal_minor=5000,
            amount_remaining_minor=5000, period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30), due_at=now, source='dashboard')
        BillingInvoiceObligation.objects.create(
            invoice=billing_invoice, obligation=self.obligation,
            selected_amount_minor=5000, allocation_order=1)
        legacy_invoice = Invoice.objects.create(
            created_by_user=self.merchant_user, merchant_business=self.business,
            merchant_account=self.merchant_account, amount=Decimal('14.00'),
            token_type='CUSD_PLUS', settlement_chain='BSC', status='PENDING',
            expires_at=now + timedelta(minutes=15))
        intent = BillingPaymentIntent.objects.create(
            billing_invoice=billing_invoice, payer_user=self.member_user,
            payer_account=self.payer_account, status='succeeded', amount_minor=5000,
            currency='PEN', expires_at=now + timedelta(minutes=15),
            legacy_invoice=legacy_invoice)
        legacy_payment = PaymentTransaction.objects.create(
            payer_user=self.member_user, merchant_account_user=self.merchant_user,
            merchant_business=self.business, payer_account=self.payer_account,
            merchant_account=self.merchant_account, payer_address='0x' + '11' * 20,
            merchant_address='0x' + '22' * 20, amount=Decimal('14.00'),
            token_type='CUSD', status='CONFIRMED',
            transaction_hash='0x' + 'aa' * 32, invoice=legacy_invoice)
        gross = 14 * 10**18
        fee = (gross * 90 + 9999) // 10000
        payment = BillingPayment.objects.create(
            billing_invoice=billing_invoice, payment_intent=intent,
            legacy_payment=legacy_payment, status='confirmed',
            commercial_amount_minor=5000, commercial_currency='PEN',
            settlement_asset='CUSD', settlement_decimals=18,
            gross_units=gross, fee_units=fee, receiver_net_units=gross - fee,
            chain='BSC', transaction_hash=legacy_payment.transaction_hash,
            confirmed_at=now)
        effect = post_full_balance_payment(
            billing_payment_id=payment.id,
            semantic_key='cip-sandbox-payment-confirmed')
        applications = create_payment_applications(payment=payment, effect=effect)
        self.assertEqual(len(applications), 1)
        self.assertEqual(apply_payment(applications[0].id), 'acknowledged')
        application = InstitutionApplication.objects.get(pk=applications[0].pk)
        self.assertEqual(application.returned_status, 'active')
        self.member.refresh_from_db()
        self.assertEqual(self.member.paid_through, date(2026, 9, 30))

    def test_setup_command_is_idempotent_and_outputs_device_link(self):
        operator = get_user_model().objects.create_user(
            username='cip-command-merchant', firebase_uid='cip-command-merchant-uid')
        output = io.StringIO()
        args = [
            '--merchant-username', operator.username,
            '--merchant-bsc-address', '0x' + '33' * 20,
            '--member-number', '009999', '--amount-pen', '50.00',
            '--period', '2026-09',
        ]
        call_command('setup_cip_sandbox_pilot', *args, stdout=output)
        call_command('setup_cip_sandbox_pilot', *args, stdout=output)
        self.assertIn('confio://memberships?', output.getvalue())
        self.assertEqual(CipSandboxMember.objects.filter(member_number='009999').count(), 1)
        self.assertEqual(BillingObligation.objects.filter(
            external_reference='cip:009999:2026-09').count(), 1)
        account = Account.objects.get(user=operator, account_type='business')
        changed_args = list(args)
        changed_args[3] = '0x' + '44' * 20
        with self.assertRaisesRegex(CommandError, 'cannot replace'):
            call_command('setup_cip_sandbox_pilot', *changed_args, stdout=output)
        account.refresh_from_db()
        self.assertEqual(account.bsc_address, '0x' + '33' * 20)
        member = CipSandboxMember.objects.get(member_number='009999')
        self.assertEqual(member.subject.mode, 'test')
