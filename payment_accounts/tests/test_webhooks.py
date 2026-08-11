import json
from decimal import Decimal

from django.test import TestCase

from payment_accounts.models import (
    FinancialAccount,
    FundingInstruction,
    LedgerEntry,
    MoneyFlow,
    MoneyOperation,
    ProviderProfile,
)
from payment_accounts.webhooks import process_webhook_event, store_webhook
from payment_accounts.services import PaymentAccountError, create_money_operation
from users.models import Account, User


class WebhookAccountingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='payment-account-user',
            email='payment-account@example.com',
            password='password123',
            firebase_uid='payment-account-firebase-id',
        )
        self.confio_account = Account.objects.create(
            user=self.user, account_type='personal', account_index=0
        )

    def _profile(self, provider):
        return ProviderProfile.objects.create(
            confio_account=self.confio_account,
            provider=provider,
            owner_type='individual',
            status='active',
            identity_snapshot={'full_name': 'Persona Prueba'},
        )

    def _account(self, profile, provider_id, *, country='COL', asset='COP'):
        return FinancialAccount.objects.create(
            provider_profile=profile,
            provider_account_id=provider_id,
            ownership_structure=(
                'omnibus_subledger' if profile.provider == 'cobre' else 'provider_named'
            ),
            country=country,
            asset=asset,
            status='active',
        )

    def test_cobre_unsolicited_credit_creates_one_ledger_fact_and_fund_flow(self):
        account = self._account(self._profile('cobre'), 'acc_cobre')
        body = json.dumps({
            'id': 'evt_cobre_credit',
            'event_key': 'money_movement.completed',
            'content': {
                'id': 'txn_cobre_credit',
                'account_id': 'acc_cobre',
                'amount': 25000,
                'balance': 40000,
                'currency': 'cop',
                'type': 'credit',
                'status': {'state': 'completed'},
                'created_at': '2026-08-11T12:00:00Z',
            },
        }).encode()
        event, created = store_webhook(provider='cobre', raw_body=body, headers={})
        self.assertTrue(created)

        process_webhook_event(event)
        process_webhook_event(event)

        entry = LedgerEntry.objects.get(provider_entry_id='txn_cobre_credit')
        account.refresh_from_db()
        self.assertEqual(entry.amount, Decimal('250'))
        self.assertEqual(entry.direction, 'credit')
        self.assertEqual(account.current_balance, Decimal('400'))
        self.assertEqual(MoneyFlow.objects.count(), 1)
        self.assertEqual(entry.operation.operation_type, 'deposit')
        self.assertEqual(entry.operation.status, 'succeeded')

    def test_infinia_destination_credit_settles_internal_transfer(self):
        profile = self._profile('infinia')
        source = self._account(profile, 'acc_source')
        destination = self._account(
            profile, 'acc_target', country='XXX', asset='USDT'
        )
        flow = MoneyFlow.objects.create(
            confio_account=self.confio_account,
            kind='convert',
            status='processing',
            source_asset='COP',
            source_amount=Decimal('100'),
            target_asset='USDT',
        )
        operation = MoneyOperation.objects.create(
            money_flow=flow,
            provider='infinia',
            operation_type='conversion',
            source_account=source,
            destination_account=destination,
            provider_operation_id='it_1',
            idempotency_key='infinia-transfer-idempotency',
            status='settling',
            source_asset='COP',
            source_amount=Decimal('100'),
            target_asset='USDT',
        )
        body = json.dumps({
            'id': 'movement_1',
            'account_id': 'acc_target',
            'amount': '25.5',
            'currency': 'USDT',
            'status': 'COMPLETED',
            'created_at': '2026-08-11T12:00:00Z',
            'operation': {'type': 'CREDIT', 'operation_id': 'it_1'},
        }).encode()
        event, _ = store_webhook(
            provider='infinia',
            raw_body=body,
            headers={
                'event': 'movement.created',
                'X-Idempotency-Key': 'evt_infinia_credit',
            },
        )

        process_webhook_event(event)

        operation.refresh_from_db()
        flow.refresh_from_db()
        self.assertEqual(operation.status, 'succeeded')
        self.assertEqual(operation.provider_operation_id, 'it_1')
        self.assertEqual(flow.status, 'succeeded')
        self.assertEqual(operation.ledger_entries.get().amount, Decimal('25.5'))

    def test_cobre_nested_completion_updates_known_operation(self):
        account = self._account(self._profile('cobre'), 'acc_cobre_payout')
        flow = MoneyFlow.objects.create(
            confio_account=self.confio_account,
            kind='withdraw',
            status='processing',
            source_asset='COP',
            source_amount=Decimal('50'),
            target_asset='COP',
        )
        operation = MoneyOperation.objects.create(
            money_flow=flow,
            provider='cobre',
            operation_type='payout',
            source_account=account,
            provider_operation_id='mm_payout_1',
            idempotency_key='cobre-payout-idempotency',
            status='processing',
            source_asset='COP',
            source_amount=Decimal('50'),
            target_asset='COP',
        )
        body = json.dumps({
            'id': 'evt_cobre_payout',
            'event_key': 'money_movement.completed',
            'content': {
                'id': 'mm_payout_1',
                'external_id': 'cobre-payout-idempotency',
                'amount': 5000,
                'currency': 'cop',
                'type': 'debit',
                'status': {'state': 'completed'},
                'created_at': '2026-08-11T12:00:00Z',
            },
        }).encode()
        event, _ = store_webhook(provider='cobre', raw_body=body, headers={})

        process_webhook_event(event)

        operation.refresh_from_db()
        flow.refresh_from_db()
        self.assertEqual(operation.status, 'succeeded')
        self.assertEqual(operation.provider_status, 'COMPLETED')
        self.assertEqual(flow.status, 'succeeded')
        self.assertEqual(LedgerEntry.objects.count(), 0)

        balance_body = json.dumps({
            'id': 'evt_cobre_payout_debit',
            'event_key': 'accounts.balance.debit',
            'content': {
                'id': 'trx_cobre_payout_debit',
                'account_id': 'acc_cobre_payout',
                'amount': -5000,
                'currency': 'cop',
                'date': '2026-08-11T12:00:01Z',
                'metadata': {
                    'money_movement_id': 'mm_payout_1',
                    'mm_external_id': 'cobre-payout-idempotency',
                },
                'current_balance': 10000,
                'credit_debit_type': 'debit',
            },
        }).encode()
        balance_event, _ = store_webhook(
            provider='cobre', raw_body=balance_body, headers={}
        )
        process_webhook_event(balance_event)

        entry = LedgerEntry.objects.get(provider_entry_id='trx_cobre_payout_debit')
        self.assertEqual(entry.operation_id, operation.id)
        self.assertEqual(entry.direction, 'debit')
        self.assertEqual(MoneyFlow.objects.count(), 1)

    def test_cobre_key_registration_activates_receiving_instruction(self):
        account = self._account(self._profile('cobre'), 'acc_cobre_key')
        instruction = FundingInstruction.objects.create(
            financial_account=account,
            provider_resource_id='key_1',
            kind='breb_key',
            status='pending',
        )
        body = json.dumps({
            'id': 'evt_cobre_key',
            'event_key': 'key.updated',
            'content': {
                'id': 'key_1',
                'source_id': 'acc_cobre_key',
                'key_value': '@persona',
                'connectivity': {'status': 'registered'},
            },
        }).encode()
        event, _ = store_webhook(provider='cobre', raw_body=body, headers={})

        process_webhook_event(event)

        instruction.refresh_from_db()
        self.assertEqual(instruction.status, 'active')
        self.assertEqual(instruction.display_value, '@persona')

    def test_client_request_id_makes_payment_intent_idempotent(self):
        account = self._account(self._profile('cobre'), 'acc_idempotent')
        request_id = 'b8ce72d8-d973-4102-8709-2cf2450f4506'

        first = create_money_operation(
            confio_account=self.confio_account,
            provider='cobre',
            operation_type='payout',
            source_asset='COP',
            source_amount='25',
            source_account=account,
            external_destination={'key': '@persona'},
            client_request_id=request_id,
        )
        second = create_money_operation(
            confio_account=self.confio_account,
            provider='cobre',
            operation_type='payout',
            source_asset='COP',
            source_amount='25',
            source_account=account,
            external_destination={'key': '@persona'},
            client_request_id=request_id,
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(len(first.idempotency_key), 36)
        self.assertEqual(MoneyFlow.objects.count(), 1)
        with self.assertRaises(PaymentAccountError):
            create_money_operation(
                confio_account=self.confio_account,
                provider='cobre',
                operation_type='payout',
                source_asset='COP',
                source_amount='26',
                source_account=account,
                external_destination={'key': '@persona'},
                client_request_id=request_id,
            )
