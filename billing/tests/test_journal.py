from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from eth_abi import encode
from eth_utils import keccak

from billing.finalizer import ReceiptPending, finalize_bsc_payment
from billing.institutions import _identity_payload, apply_payment
from billing.models import (
    BillingEvent,
    BillingInvoice,
    BillingInvoiceObligation,
    BillingObligation,
    BillingOutboxMessage,
    BillingPayment,
    BillingPaymentIntent,
    InstitutionApplication,
    InstitutionConnection,
    InstitutionDataGrant,
    InstitutionDataRequirement,
    ObligationSubject,
    PaymentAllocationEntry,
    PaymentEffect,
    SettlementLeg,
    SubjectIdentityValue,
)
from billing.money import fee_units
from billing.services import JournalInvariantError, post_full_balance_payment
from billing.settlement import (
    PAYMENT_MADE_V4,
    SettlementEvidenceError,
    persist_finalized_payment_settlement,
)
from payments.bsc_flow import invoice_id_bytes32
from blockchain.models import SponsoredBatch
from payments.models import Invoice, PaymentTransaction
from users.models import Account, Business


class BillingJournalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.merchant_user = User.objects.create_user(
            username='billing-merchant', firebase_uid='billing-merchant-uid')
        self.payer_user = User.objects.create_user(
            username='billing-payer', firebase_uid='billing-payer-uid')
        self.business = Business.objects.create(name='CIP Pilot', category='services')
        self.merchant_account = Account.objects.create(
            user=self.merchant_user, account_type='business', account_index=0,
            business=self.business, bsc_address='0x' + '22' * 20)
        self.payer_account = Account.objects.create(
            user=self.payer_user, account_type='personal', account_index=0,
            bsc_address='0x' + '11' * 20)
        self.subject = ObligationSubject.objects.create(
            business=self.business, external_id='cip:member:102938',
            subject_type='membership', display_label='Colegiado ••••2938',
            masked_reference='CIP ••••2938')
        now = timezone.now()
        self.obligations = [
            BillingObligation.objects.create(
                business=self.business, subject=self.subject,
                external_reference=f'cip:102938:2026-{month:02d}',
                currency='PEN', original_amount_minor=amount,
                amount_remaining_minor=amount,
                line_items_snapshot=[{'kind': 'base_dues', 'amount_minor': amount}],
                period_start=date(2026, month, 1),
                period_end=date(2026, month, 28),
                issued_at=now, due_at=now + timedelta(days=10), status='open')
            for month, amount in ((8, 3_000), (9, 2_000))
        ]
        self.billing_invoice = BillingInvoice.objects.create(
            business=self.business, subject=self.subject, number='CIP-2026-0001',
            status='payment_pending', currency='PEN', subtotal_minor=5_000,
            amount_remaining_minor=5_000, period_start=date(2026, 8, 1),
            period_end=date(2026, 9, 30), due_at=now + timedelta(days=10),
            source='import')
        for order, obligation in enumerate(self.obligations, start=1):
            BillingInvoiceObligation.objects.create(
                invoice=self.billing_invoice, obligation=obligation,
                selected_amount_minor=obligation.original_amount_minor,
                allocation_order=order)
        self.legacy_invoice = Invoice.objects.create(
            created_by_user=self.merchant_user, merchant_business=self.business,
            merchant_account=self.merchant_account, amount=Decimal('50'),
            token_type='CUSD_PLUS', settlement_chain='BSC', status='PENDING',
            expires_at=now + timedelta(hours=23))
        self.intent = BillingPaymentIntent.objects.create(
            billing_invoice=self.billing_invoice, payer_user=self.payer_user,
            payer_account=self.payer_account, status='succeeded',
            amount_minor=5_000, currency='PEN', expires_at=now + timedelta(hours=1),
            legacy_invoice=self.legacy_invoice, idempotency_key='intent-1')
        self.legacy_payment = PaymentTransaction.objects.create(
            payer_user=self.payer_user, merchant_account_user=self.merchant_user,
            merchant_business=self.business, payer_display_name='Payer',
            merchant_display_name='CIP Pilot', payer_account=self.payer_account,
            merchant_account=self.merchant_account,
            payer_address='0x' + '11' * 20, merchant_address='0x' + '22' * 20,
            amount=Decimal('50'), token_type='CUSD', status='CONFIRMED',
            transaction_hash='0x' + 'aa' * 32, invoice=self.legacy_invoice)
        gross = 50 * 10**18
        fee = fee_units(gross)
        self.payment = BillingPayment.objects.create(
            billing_invoice=self.billing_invoice, payment_intent=self.intent,
            legacy_payment=self.legacy_payment, status='confirmed',
            commercial_amount_minor=5_000, commercial_currency='PEN',
            settlement_asset='CUSD', settlement_decimals=18,
            gross_units=gross, fee_units=fee, receiver_net_units=gross - fee,
            transaction_hash=self.legacy_payment.transaction_hash,
            confirmed_at=now, settlement_snapshot={'source': 'PaymentMade'})

    def _batch(self, status, kind='pay_cusd'):
        return SponsoredBatch.objects.create(
            user=self.payer_user, user_bsc_address=self.payer_account.bsc_address,
            kind=kind, source_id=self.legacy_payment.id, num_calls=2,
            calls_json='[]', tx_hash=self.legacy_payment.transaction_hash,
            delegate_nonce=1, delegate_nonce_claimed=True, gas_limit=300000,
            max_fee_wei='1', status=status, block_number=1,
            block_hash='0x' + '10' * 32)

    def _settlement_leg(self, batch):
        return SettlementLeg.objects.create(
            billing_payment=self.payment, chain_id=56,
            contract_version='v4-cusd-routing',
            contract_address='0x' + '55' * 20,
            invoice_id_bytes32='0x' + '77' * 32,
            payer_address=self.payer_account.bsc_address,
            receiver_address=self.merchant_account.bsc_address,
            input_token_address='0x' + '66' * 20,
            input_token_symbol='CUSD', input_token_decimals=18,
            gross_units=self.payment.gross_units,
            fee_token_address='0x' + '66' * 20,
            fee_units=self.payment.fee_units,
            output_token_address='0x' + '66' * 20,
            output_token_symbol='CUSD', output_token_decimals=18,
            output_units=self.payment.receiver_net_units, routed=False,
            receiver_net_units=self.payment.receiver_net_units,
            transaction_hash=batch.tx_hash, block_number=batch.block_number,
            block_hash=batch.block_hash, transaction_index=0, log_index=0)

    def _payment_receipt(self, *, token, gross=None, fee=None, routed=False,
                         output_units=0, merchant=None, duplicate=False):
        gross = int(self.payment.gross_units) if gross is None else gross
        fee = int(self.payment.fee_units) if fee is None else fee
        pay_contract = '0x' + '55' * 20
        topics = [
            '0x' + keccak(text=PAYMENT_MADE_V4).hex(),
            invoice_id_bytes32(self.legacy_invoice.internal_id),
            '0x' + self.payer_account.bsc_address[2:].rjust(64, '0'),
            '0x' + (merchant or self.merchant_account.bsc_address)[2:].rjust(64, '0'),
        ]
        log = {
            'address': pay_contract,
            'topics': topics,
            'data': '0x' + encode(
                ['address', 'uint256', 'uint256', 'bool', 'uint256'],
                [token, gross, fee, routed, output_units],
            ).hex(),
            'transactionHash': self.legacy_payment.transaction_hash,
            'blockNumber': '0x1',
            'blockHash': '0x' + '10' * 32,
            'transactionIndex': '0x2',
            'logIndex': '0x3',
        }
        return {
            'status': '0x1',
            'transactionHash': self.legacy_payment.transaction_hash,
            'blockNumber': '0x1',
            'blockHash': '0x' + '10' * 32,
            'transactionIndex': '0x2',
            'logs': [log, dict(log)] if duplicate else [log],
        }

    def test_full_balance_posting_is_balanced_and_idempotent(self):
        effect = post_full_balance_payment(
            billing_payment_id=self.payment.id, semantic_key='payment:confirmed:1')
        replay = post_full_balance_payment(
            billing_payment_id=self.payment.id, semantic_key='payment:confirmed:1')

        self.assertEqual(replay.id, effect.id)
        entries = list(effect.allocations.order_by('allocation_order'))
        self.assertEqual([entry.commercial_delta_minor for entry in entries], [3_000, 2_000])
        self.assertEqual(sum(entry.commercial_delta_minor for entry in entries),
                         effect.commercial_delta_minor)
        self.billing_invoice.refresh_from_db()
        self.assertEqual(self.billing_invoice.status, 'paid')
        self.assertEqual(self.billing_invoice.amount_paid_minor, 5_000)
        self.assertEqual(self.billing_invoice.amount_remaining_minor, 0)
        self.assertEqual(
            list(BillingObligation.objects.order_by('period_start').values_list(
                'status', 'amount_paid_minor', 'amount_remaining_minor')),
            [('paid', 3_000, 0), ('paid', 2_000, 0)],
        )

    def test_partial_tender_is_rejected_without_journal_side_effects(self):
        self.payment.commercial_amount_minor = 4_999
        self.payment.save(update_fields=('commercial_amount_minor', 'updated_at'))
        with self.assertRaises(JournalInvariantError):
            post_full_balance_payment(
                billing_payment_id=self.payment.id, semantic_key='payment:partial')
        self.assertFalse(PaymentEffect.objects.exists())
        self.billing_invoice.refresh_from_db()
        self.assertEqual(self.billing_invoice.amount_remaining_minor, 5_000)

    def test_institution_application_shares_identity_only_after_field_grant(self):
        # A sandbox connector must use a wholly test-mode financial fixture.
        for record in (self.subject, *self.obligations):
            record.mode = 'test'
            record.save(update_fields=('mode',))
        effect = post_full_balance_payment(
            billing_payment_id=self.payment.id, semantic_key='payment:identity-application')
        allocation = effect.allocations.order_by('allocation_order').first()
        connection = InstitutionConnection.objects.create(
            business=self.business, provider='cip', mode='test', status='sandbox')
        InstitutionDataRequirement.objects.create(
            connection=connection, field_name='dni', purpose='Member match')
        SubjectIdentityValue.objects.create(
            subject=self.subject, field_name='dni', encrypted_value='12345678')
        application = InstitutionApplication.objects.create(
            connection=connection, billing_payment=self.payment, allocation=allocation,
            opaque_subject_reference=self.subject.external_id,
            status='application_pending', idempotency_key='apply:identity:1',
            payment_confirmed_at=self.payment.confirmed_at,
            payload_snapshot={'payment_id': self.payment.public_id})

        self.assertEqual(apply_payment(application.id), 'application_pending')
        application.refresh_from_db()
        self.assertIn('grant', application.last_error)

        InstitutionDataGrant.objects.create(
            connection=connection, subject=self.subject, field_names=['dni', 'phone'],
            purpose_snapshot={'dni': 'Member match'}, consent_version='cip-v1',
            granted_at=timezone.now())
        SubjectIdentityValue.objects.create(
            subject=self.subject, field_name='phone', encrypted_value='+51999999999')
        self.assertEqual(_identity_payload(application), {'dni': '12345678'})
        self.assertEqual(apply_payment(application.id), 'acknowledged')
        application.refresh_from_db()
        self.assertEqual(application.returned_status, 'active')
        self.assertNotIn('12345678', str(list(
            BillingEvent.objects.values_list('payload', flat=True))))

    def test_live_application_disabled_connection_and_bad_response_are_retryable(self):
        effect = post_full_balance_payment(
            billing_payment_id=self.payment.id, semantic_key='payment:live-application')
        connection = InstitutionConnection.objects.create(
            business=self.business, provider='cip', mode='live', status='disabled',
            live_approved=True, application_url='https://example.test/apply',
            settlement_authority='CIP', refund_authority='CIP')
        application = InstitutionApplication.objects.create(
            connection=connection, billing_payment=self.payment,
            allocation=effect.allocations.order_by('allocation_order').first(),
            opaque_subject_reference=self.subject.external_id,
            status='application_pending', idempotency_key='apply:live:1',
            payment_confirmed_at=self.payment.confirmed_at,
            payload_snapshot={'payment_id': self.payment.public_id})
        sender = mock.Mock(return_value=mock.Mock(status_code=200))
        sender.return_value.json.return_value = []
        self.assertEqual(apply_payment(application.id, sender=sender), 'application_pending')
        sender.assert_not_called()
        application.refresh_from_db()
        self.assertIn('disabled', application.last_error)
        connection.status = 'active'
        connection.save()
        with mock.patch('billing.institutions.validate_delivery_url'):
            self.assertEqual(apply_payment(application.id, sender=sender), 'application_pending')
        application.refresh_from_db()
        self.assertIn('must be an object', application.last_error)
        self.assertIsNone(application.leased_at)
        self.assertEqual(application.lease_token, '')

        private_status = 'DNI 12345678 member@example.test'
        sender.return_value.json.return_value = {'status': private_status}
        with mock.patch('billing.institutions.validate_delivery_url'):
            self.assertEqual(apply_payment(application.id, sender=sender), 'acknowledged')
        application.refresh_from_db()
        from billing.api.views import _application_dto
        self.assertEqual(_application_dto(application)['returned_status'], '')
        self.assertNotIn(private_status, str(list(
            BillingEvent.objects.values_list('payload', flat=True))))
        # Internal connector state remains available to operators without
        # becoming an unreviewed public identity disclosure.
        self.assertEqual(application.returned_status, private_status)

    def test_database_trigger_makes_journal_append_only(self):
        effect = post_full_balance_payment(
            billing_payment_id=self.payment.id, semantic_key='payment:immutable')
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                PaymentEffect.objects.filter(id=effect.id).update(
                    commercial_delta_minor=1)
        allocation = PaymentAllocationEntry.objects.get(effect=effect, allocation_order=1)
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                PaymentAllocationEntry.objects.filter(id=allocation.id).delete()
        leg = SettlementLeg.objects.create(
            billing_payment=self.payment, chain_id=56, contract_version='v4',
            receiver_address='0x' + '22' * 20,
            input_token_address='0x' + '66' * 20,
            input_token_symbol='CUSD', input_token_decimals=18,
            gross_units=10_000, fee_token_address='0x' + '66' * 20,
            fee_units=90, output_token_address='0x' + '66' * 20,
            output_token_symbol='CUSD', output_token_decimals=18,
            output_units=9_910,
            receiver_net_units=9_910, transaction_hash='0x' + 'ff' * 32,
            block_number=1, block_hash='0x' + '10' * 32,
            transaction_index=0, log_index=0)
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                SettlementLeg.objects.filter(id=leg.id).update(block_number=2)

    def test_database_enforces_settlement_conservation(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SettlementLeg.objects.create(
                    billing_payment=self.payment, chain_id=56,
                    contract_version='v4', receiver_address='0x' + '22' * 20,
                    input_token_address='0x' + '66' * 20,
                    input_token_symbol='CUSD', input_token_decimals=18,
                    gross_units=100, fee_token_address='0x' + '66' * 20,
                    fee_units=1, output_token_address='0x' + '66' * 20,
                    output_token_symbol='CUSD', output_token_decimals=18,
                    output_units=98,
                    receiver_net_units=98,
                    transaction_hash='0x' + 'bb' * 32, block_number=1,
                    block_hash='0x' + 'cc' * 32, transaction_index=0, log_index=0)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SettlementLeg.objects.create(
                    billing_payment=self.payment, chain_id=56,
                    contract_version='v4', receiver_address='0x' + '22' * 20,
                    input_token_address='0x' + '66' * 20,
                    input_token_symbol='CUSD', input_token_decimals=18,
                    gross_units=10_000, fee_token_address='0x' + '66' * 20,
                    fee_units=89, output_token_address='0x' + '66' * 20,
                    output_token_symbol='CUSD', output_token_decimals=18,
                    output_units=9_911,
                    receiver_net_units=9_911,
                    transaction_hash='0x' + 'dd' * 32, block_number=1,
                    block_hash='0x' + 'ee' * 32, transaction_index=0, log_index=1)

    def test_database_allows_only_one_active_intent(self):
        BillingPaymentIntent.objects.create(
            billing_invoice=self.billing_invoice, status='processing',
            amount_minor=5_000, currency='PEN',
            expires_at=timezone.now() + timedelta(hours=1))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BillingPaymentIntent.objects.create(
                    billing_invoice=self.billing_invoice,
                    status='requires_confirmation', amount_minor=5_000,
                    currency='PEN', expires_at=timezone.now() + timedelta(hours=1))

    def test_locked_finalizer_atomically_posts_journal_and_outbox(self):
        InstitutionConnection.objects.create(
            business=self.business, provider='cip', mode='live', status='active',
            live_approved=True, settlement_authority='cip_treasury',
            refund_authority='cip_finance')
        type(self.legacy_payment).objects.filter(id=self.legacy_payment.id).update(
            status='SUBMITTED')
        type(self.intent).objects.filter(id=self.intent.id).update(status='processing')
        type(self.payment).objects.filter(id=self.payment.id).update(
            status='processing', confirmed_at=None)
        BillingObligation.objects.filter(
            id__in=[item.id for item in self.obligations]).update(
                status='payment_pending')
        batch = self._batch('confirmed')
        self._settlement_leg(batch)

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            result = finalize_bsc_payment(
                payment_id=self.legacy_payment.id, batch_id=batch.id)

        self.assertTrue(result.transitioned)
        self.assertEqual(result.outcome, 'confirmed')
        self.assertEqual(len(callbacks), 1)
        self.legacy_payment.refresh_from_db()
        self.intent.refresh_from_db()
        self.payment.refresh_from_db()
        self.billing_invoice.refresh_from_db()
        self.assertEqual(self.legacy_payment.status, 'CONFIRMED')
        self.assertEqual(self.intent.status, 'succeeded')
        self.assertEqual(self.payment.status, 'confirmed')
        self.assertEqual(self.billing_invoice.status, 'paid')
        self.assertEqual(PaymentEffect.objects.count(), 1)
        event = BillingEvent.objects.get(event_type='payment.confirmed')
        self.assertNotIn('display_label', event.payload['data']['object'])
        self.assertEqual(BillingOutboxMessage.objects.filter(
            event=event, status='pending').count(), 1)
        self.assertEqual(InstitutionApplication.objects.filter(
            billing_payment=self.payment, status='application_pending').count(), 2)

        replay = finalize_bsc_payment(
            payment_id=self.legacy_payment.id, batch_id=batch.id)
        self.assertFalse(replay.transitioned)
        self.assertEqual(PaymentEffect.objects.count(), 1)
        self.assertEqual(BillingEvent.objects.count(), 1)

        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                BillingEvent.objects.filter(id=event.id).update(event_type='tampered')

    def test_confirmed_finalizer_waits_for_exact_settlement_evidence(self):
        type(self.legacy_payment).objects.filter(id=self.legacy_payment.id).update(
            status='SUBMITTED')
        type(self.intent).objects.filter(id=self.intent.id).update(status='processing')
        type(self.payment).objects.filter(id=self.payment.id).update(
            status='processing', confirmed_at=None)
        batch = self._batch('confirmed')

        with self.assertRaises(ReceiptPending):
            finalize_bsc_payment(
                payment_id=self.legacy_payment.id, batch_id=batch.id)

        self.legacy_payment.refresh_from_db()
        self.assertEqual(self.legacy_payment.status, 'SUBMITTED')
        self.assertFalse(PaymentEffect.objects.exists())
        self.assertFalse(BillingEvent.objects.exists())

    def test_webhook_fanout_outage_cannot_roll_back_confirmed_payment(self):
        type(self.legacy_payment).objects.filter(id=self.legacy_payment.id).update(status='SUBMITTED')
        type(self.intent).objects.filter(id=self.intent.id).update(status='processing')
        type(self.payment).objects.filter(id=self.payment.id).update(status='processing', confirmed_at=None)
        batch = self._batch('confirmed')
        self._settlement_leg(batch)
        with mock.patch('billing.webhooks.enqueue_event_deliveries',
                        side_effect=RuntimeError('webhook configuration unavailable')) as fanout:
            result = finalize_bsc_payment(payment_id=self.legacy_payment.id, batch_id=batch.id)
        self.assertEqual(result.outcome, 'confirmed')
        fanout.assert_not_called()
        self.assertEqual(BillingOutboxMessage.objects.filter(status='pending').count(), 1)

    @override_settings(
        BSC_PAY_CONTRACT_ADDRESS='0x' + '55' * 20,
        CUSD_VAULT_ADDRESS='0x' + '66' * 20,
        CUSD_PLUS_VAULT_ADDRESS='0x' + '88' * 20,
        BSC_CONFIO_TOKEN_ADDRESS='0x' + '99' * 20,
        BSC_CHAIN_ID=56,
    )
    def test_finalized_payment_event_persists_exact_direct_leg_idempotently(self):
        batch = self._batch('sent')
        receipt = self._payment_receipt(token='0x' + '66' * 20)

        leg = persist_finalized_payment_settlement(
            batch_id=batch.id, receipt=receipt)
        replay = persist_finalized_payment_settlement(
            batch_id=batch.id, receipt=receipt)

        self.assertEqual(replay.id, leg.id)
        self.assertEqual(SettlementLeg.objects.count(), 1)
        self.assertEqual(leg.input_token_symbol, 'CUSD')
        self.assertFalse(leg.routed)
        self.assertEqual(int(leg.output_units), int(self.payment.receiver_net_units))
        self.assertEqual(leg.transaction_index, 2)
        self.assertEqual(leg.log_index, 3)

    @override_settings(
        BSC_PAY_CONTRACT_ADDRESS='0x' + '55' * 20,
        CUSD_VAULT_ADDRESS='0x' + '66' * 20,
        CUSD_PLUS_VAULT_ADDRESS='0x' + '88' * 20,
        BSC_CONFIO_TOKEN_ADDRESS='0x' + '99' * 20,
        BSC_CHAIN_ID=56,
    )
    def test_finalized_payment_event_preserves_routed_output_units(self):
        self.payment.settlement_asset = 'CUSD_PLUS'
        self.payment.save(update_fields=('settlement_asset', 'updated_at'))
        self.legacy_payment.blockchain_data = {'v4_redeem': True}
        self.legacy_payment.save(update_fields=('blockchain_data', 'updated_at'))
        batch = self._batch('sent', kind='pay_cusd_plus')
        routed_out = 49_500_000_000_000_000_000
        receipt = self._payment_receipt(
            token='0x' + '88' * 20, routed=True, output_units=routed_out)

        leg = persist_finalized_payment_settlement(
            batch_id=batch.id, receipt=receipt)

        self.assertTrue(leg.routed)
        self.assertEqual(leg.input_token_symbol, 'CUSD_PLUS')
        self.assertEqual(int(leg.receiver_net_units),
                         int(self.payment.receiver_net_units))
        self.assertEqual(leg.output_token_symbol, 'CUSD')
        self.assertEqual(int(leg.output_units), routed_out)

    @override_settings(
        BSC_PAY_CONTRACT_ADDRESS='0x' + '55' * 20,
        CUSD_VAULT_ADDRESS='0x' + '66' * 20,
        CUSD_PLUS_VAULT_ADDRESS='0x' + '88' * 20,
        BSC_CONFIO_TOKEN_ADDRESS='0x' + '99' * 20,
        BSC_CHAIN_ID=56,
    )
    def test_finalized_payment_event_rejects_mismatch_and_ambiguity(self):
        batch = self._batch('sent')
        bad_merchant = self._payment_receipt(
            token='0x' + '66' * 20, merchant='0x' + 'ab' * 20)
        with self.assertRaisesRegex(SettlementEvidenceError, 'merchant mismatch'):
            persist_finalized_payment_settlement(
                batch_id=batch.id, receipt=bad_merchant)
        with self.assertRaisesRegex(SettlementEvidenceError, 'found 2'):
            persist_finalized_payment_settlement(
                batch_id=batch.id,
                receipt=self._payment_receipt(
                    token='0x' + '66' * 20, duplicate=True),
            )
        self.assertFalse(SettlementLeg.objects.exists())

    @override_settings(
        BSC_PAY_CONTRACT_ADDRESS='0x' + '55' * 20,
        CUSD_VAULT_ADDRESS='0x' + '66' * 20,
        CUSD_PLUS_VAULT_ADDRESS='0x' + '88' * 20,
        BSC_CONFIO_TOKEN_ADDRESS='0x' + '99' * 20,
    )
    def test_finalized_leg_rejects_stale_or_removed_receipt_logs(self):
        batch = self._batch('sent')
        for change in ({'blockHash': '0x' + 'ee' * 32},
                       {'blockNumber': '0xff'}, {'removed': True}):
            receipt = self._payment_receipt(token='0x' + '66' * 20)
            receipt['logs'][0].update(change)
            with self.assertRaises(SettlementEvidenceError):
                persist_finalized_payment_settlement(batch_id=batch.id, receipt=receipt)
        self.assertFalse(SettlementLeg.objects.exists())

    def test_failed_receipt_reopens_billing_without_payment_effect(self):
        type(self.legacy_payment).objects.filter(id=self.legacy_payment.id).update(
            status='SUBMITTED')
        type(self.intent).objects.filter(id=self.intent.id).update(status='processing')
        type(self.payment).objects.filter(id=self.payment.id).update(
            status='processing', confirmed_at=None)
        BillingObligation.objects.filter(
            id__in=[item.id for item in self.obligations]).update(
                status='payment_pending')
        batch = self._batch('reverted')

        result = finalize_bsc_payment(
            payment_id=self.legacy_payment.id, batch_id=batch.id)

        self.assertEqual(result.outcome, 'failed')
        self.legacy_payment.refresh_from_db()
        self.intent.refresh_from_db()
        self.payment.refresh_from_db()
        self.billing_invoice.refresh_from_db()
        self.assertEqual(self.legacy_payment.status, 'FAILED')
        self.assertEqual(self.intent.status, 'failed')
        self.assertEqual(self.payment.status, 'failed')
        self.assertEqual(self.billing_invoice.status, 'open')
        self.assertFalse(PaymentEffect.objects.exists())
        self.assertEqual(
            set(BillingObligation.objects.values_list('status', flat=True)), {'open'})
        self.assertEqual(BillingEvent.objects.get().event_type, 'payment.failed')
        self.assertEqual(BillingOutboxMessage.objects.count(), 1)

    def test_finalizer_crash_rolls_back_every_projection_and_journal_write(self):
        type(self.legacy_payment).objects.filter(id=self.legacy_payment.id).update(
            status='SUBMITTED')
        type(self.intent).objects.filter(id=self.intent.id).update(status='processing')
        type(self.payment).objects.filter(id=self.payment.id).update(
            status='processing', confirmed_at=None)
        BillingObligation.objects.filter(
            id__in=[item.id for item in self.obligations]).update(
                status='payment_pending')
        batch = self._batch('confirmed')
        self._settlement_leg(batch)

        with mock.patch(
                'billing.finalizer._append_payment_event',
                side_effect=RuntimeError('simulated crash after journal posting')):
            with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
                finalize_bsc_payment(
                    payment_id=self.legacy_payment.id, batch_id=batch.id)

        self.legacy_payment.refresh_from_db()
        self.legacy_invoice.refresh_from_db()
        self.intent.refresh_from_db()
        self.payment.refresh_from_db()
        self.billing_invoice.refresh_from_db()
        self.assertEqual(self.legacy_payment.status, 'SUBMITTED')
        self.assertEqual(self.legacy_invoice.status, 'PENDING')
        self.assertEqual(self.intent.status, 'processing')
        self.assertEqual(self.payment.status, 'processing')
        self.assertEqual(self.billing_invoice.status, 'payment_pending')
        self.assertEqual(
            set(BillingObligation.objects.values_list('status', flat=True)),
            {'payment_pending'},
        )
        self.assertFalse(PaymentEffect.objects.exists())
        self.assertFalse(PaymentAllocationEntry.objects.exists())
        self.assertFalse(BillingEvent.objects.exists())
        self.assertFalse(BillingOutboxMessage.objects.exists())
