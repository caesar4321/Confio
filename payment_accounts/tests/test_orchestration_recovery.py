"""Provider lookup races must not undo newer webhook facts or resubmit them."""
from datetime import timedelta
from unittest import mock
import uuid

from django.test import TestCase
from django.utils import timezone

from payment_accounts.models import MoneyOperation
from payment_accounts.tasks import reconcile_operations

from threading import Event, Thread
from django.db import connections, connection, transaction
from django.test import TransactionTestCase
from payment_accounts.models import CobreJourney, FinancialAccount, LedgerEntry, MoneyFlow, ProviderProfile
from payment_accounts.cobre_journeys import observe_refund
from payment_accounts.services import PaymentAccountError, submit_money_operation
from users.models import User, Account

class ReconciliationRaceTests(TestCase):
    def operation(self, provider='infinia', hours=1):
        row = MoneyOperation.objects.create(provider=provider, operation_type='payout',
            source_asset='USD_STABLE', source_amount='10', status='submitted',
            idempotency_key=str(uuid.uuid4()), submitted_at=timezone.now()-timedelta(hours=hours))
        MoneyOperation.objects.filter(pk=row.pk).update(updated_at=timezone.now()-timedelta(hours=1))
        return row

    def run_lookup_race(self, row, changes):
        def lookup(_):
            MoneyOperation.objects.filter(pk=row.pk).update(**changes)
            return None
        with mock.patch('payment_accounts.tasks.get_provider') as provider, mock.patch(
                'payment_accounts.tasks.submit_money_operation') as submit:
            provider.return_value.retrieve_operation_by_idempotency.side_effect = lookup
            self.assertEqual(reconcile_operations(), 0)
            submit.assert_not_called()
        row.refresh_from_db()
        for field, value in changes.items():
            self.assertEqual(getattr(row, field), value)

    def test_missing_lookup_does_not_overwrite_new_terminal_webhook(self):
        for status in ('succeeded', 'failed', 'reversed', 'needs_review'):
            with self.subTest(status=status):
                self.run_lookup_race(self.operation(), {'status': status})

    def test_expired_lookup_does_not_reopen_webhook_success(self):
        self.run_lookup_race(self.operation('cobre', hours=25), {'status': 'succeeded'})

    def test_missing_lookup_does_not_resubmit_new_provider_id(self):
        self.run_lookup_race(self.operation(), {'provider_operation_id': 'just-bound-id'})

    def test_missing_lookup_does_not_resubmit_changed_instruction(self):
        self.run_lookup_race(self.operation(), {'external_destination': {'destination': 'changed'}})

    def test_unchanged_missing_operation_retries_same_identity(self):
        row = self.operation()
        with mock.patch('payment_accounts.tasks.get_provider') as provider, mock.patch(
                'payment_accounts.tasks.submit_money_operation') as submit:
            provider.return_value.retrieve_operation_by_idempotency.return_value = None
            self.assertEqual(reconcile_operations(), 1)
            self.assertEqual(submit.call_args.args[0].pk, row.pk)
            self.assertEqual(submit.call_args.args[0].idempotency_key, row.idempotency_key)
        row.refresh_from_db()
        self.assertEqual(row.status, 'unknown')

    def test_unchanged_expired_operation_is_not_resubmitted(self):
        row = self.operation('cobre', hours=25)
        with mock.patch('payment_accounts.tasks.get_provider') as provider, mock.patch(
                'payment_accounts.tasks.submit_money_operation') as submit:
            provider.return_value.retrieve_operation_by_idempotency.return_value = None
            reconcile_operations()
            submit.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, 'needs_review')


class SubmissionRefundLockTests(TransactionTestCase):
    def test_refund_commits_while_retry_waits_for_journey_then_blocks_submission(self):
        """Exercise real PG locks, including deferred LedgerEntry foreign keys.

        Pause submission after its operation lock, immediately before its journey
        lock. A refund must be able to update the journey and account, reference
        that operation, and COMMIT. Submission must then observe the refund stop.
        """
        user = User.objects.create_user(username='refund-lock', firebase_uid='refund-lock')
        owner = Account.objects.create(user=user, account_type='personal', bsc_address='0x'+'11'*20)
        profile = ProviderProfile.objects.create(confio_account=owner, provider='cobre',
            owner_type='individual', status='active')
        accounts = [FinancialAccount.objects.create(provider_profile=profile,
            provider_account_id=asset, asset=asset, country='COL' if asset == 'COP' else 'XXX',
            status='active', ownership_structure='omnibus_subledger') for asset in ('COP', 'USD_STABLE', 'COPCO')]
        flow = MoneyFlow.objects.create(confio_account=owner, kind='fund', source_asset='COP',
            source_amount='10', target_asset='USDT_BSC', metadata={'orchestrator': 'cobre'})
        op = MoneyOperation.objects.create(provider='cobre', money_flow=flow,
            operation_type='internal_transfer', source_account=accounts[0], destination_account=accounts[2],
            source_asset='COP', source_amount='10', status='unknown',
            idempotency_key=str(uuid.uuid4()), provider_operation_id='refund-lock-movement')
        journey = CobreJourney.objects.create(confio_account=owner, money_flow=flow,
            request_id=uuid.uuid4(), direction='to_wallet', stage='converting_cop',
            local_account=accounts[0], crypto_account=accounts[1], copco_account=accounts[2],
            ramp_operation=op, minimum_fx_output='1', wallet_address=owner.bsc_address)
        at_journey, refund_finished = Event(), Event()
        errors = []
        original_lock = CobreJourney.objects.select_for_update

        def pause_before_journey(*args, **kwargs):
            at_journey.set()
            if not refund_finished.wait(10):
                raise AssertionError('Refund did not finish while submission was paused')
            return original_lock(*args, **kwargs)

        def retry():
            try:
                submit_money_operation(op)
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        with mock.patch.object(CobreJourney.objects, 'select_for_update', side_effect=pause_before_journey), mock.patch(
                'payment_accounts.services.get_provider') as provider:
            worker = Thread(target=retry, daemon=True)
            worker.start()
            try:
                self.assertTrue(at_journey.wait(10), 'Submission did not reach its journey lock')
                with transaction.atomic():
                    # A bad lock order fails quickly instead of hanging the suite.
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '2s'")
                    entry = LedgerEntry.objects.create(provider='cobre', provider_entry_id='refund-lock-entry',
                        operation=op, financial_account=accounts[0], direction='credit', asset='COP', amount='10',
                        occurred_at=timezone.now(), provider_data={'content': {'metadata': {
                            'money_movement_id': op.provider_operation_id}}})
                    observe_refund(entry)
                    FinancialAccount.objects.filter(pk=accounts[0].pk).update(current_balance='10')
                # Leaving atomic also verifies deferred FK locks can be acquired.
            finally:
                refund_finished.set()
                worker.join(10)
            self.assertFalse(worker.is_alive(), 'Submission remained blocked after refund committed')
            provider.assert_not_called()
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], PaymentAccountError)
        self.assertIn('does not allow further submissions', str(errors[0]))
        journey.refresh_from_db()
        self.assertEqual(journey.stage, 'needs_review')
        op.refresh_from_db()
        self.assertEqual(op.status, 'unknown')
