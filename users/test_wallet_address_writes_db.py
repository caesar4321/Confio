"""Database regression coverage for legacy writers versus reconciliation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from time import monotonic, sleep
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from users.models import Account, RetiredWalletAddress, User
from users.wallet_address_writes import (
    WalletRegistrationChanged, persist_legacy_wallet_fields,
)


class LegacyWalletWriteDatabaseTests(TransactionTestCase):
    def setUp(self):
        self.user = User(username='wallet-write-test', firebase_uid='wallet-write-test')
        User.objects.bulk_create([self.user])
        self.account = Account.objects.create(
            user=self.user, account_type='personal', account_index=0,
            algorand_address='A' * 58, is_keyless_migrated=False)

    def test_bsc_only_account_cannot_get_an_algorand_address(self):
        Account.objects.filter(pk=self.account.pk).update(
            algorand_address=None, bsc_address='0x' + '1' * 40,
            is_keyless_migrated=True)
        self.account.refresh_from_db()
        with self.assertRaises(WalletRegistrationChanged):
            persist_legacy_wallet_fields(self.account, algorand_address='B' * 58)
        self.account.refresh_from_db()
        self.assertIsNone(self.account.algorand_address)

    def test_retired_address_cannot_be_registered(self):
        RetiredWalletAddress.objects.create(
            account=self.account, user=self.user, chain='algorand', address='B' * 58)
        with self.assertRaises(WalletRegistrationChanged):
            persist_legacy_wallet_fields(self.account, algorand_address='B' * 58)
        self.account.refresh_from_db()
        self.assertEqual(self.account.algorand_address, 'A' * 58)

    def test_stale_snapshot_cannot_restore_previous_wallet(self):
        Account.objects.filter(pk=self.account.pk).update(
            algorand_address=None, bsc_address='0x' + '1' * 40,
            is_keyless_migrated=True)
        with self.assertRaises(WalletRegistrationChanged):
            persist_legacy_wallet_fields(self.account, algorand_address='A' * 58)

    def test_legacy_mutation_rejects_retired_address_before_account_creation(self):
        from users.web3auth_schema import UpdateAlgorandAddressMutation

        RetiredWalletAddress.objects.create(
            account=self.account, user=self.user, chain='algorand', address='B' * 58)
        newcomer = User(username='new-wallet-user', firebase_uid='new-wallet-user')
        User.objects.bulk_create([newcomer])
        info = SimpleNamespace(context=SimpleNamespace(user=newcomer))
        result = UpdateAlgorandAddressMutation.mutate(None, info, 'B' * 58)
        self.assertFalse(result.success)
        self.assertFalse(Account.objects.filter(user=newcomer).exists())

    def wait_for_database_lock(self, worker_pid):
        deadline = monotonic() + 5
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_stat_clear_snapshot()')
                cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s', [worker_pid])
                row = cursor.fetchone()
            if row and row[0] == 'Lock':
                return
            sleep(0.01)
        self.fail('Worker did not wait for the owner row lock')

    @skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks')
    def test_account_creation_waits_for_owner_inventory_lock(self):
        started = Event()
        worker_pid = []

        def create_sibling():
            try:
                with connections['default'].cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    worker_pid.append(cursor.fetchone()[0])
                started.set()
                return Account.objects.create(user_id=self.user.pk, account_index=2).pk
            finally:
                connections['default'].close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=self.user.pk)
                future = executor.submit(create_sibling)
                self.assertTrue(started.wait(5))
                self.wait_for_database_lock(worker_pid[0])
                self.assertFalse(Account.objects.filter(user=self.user, account_index=2).exists())
            self.assertTrue(Account.objects.filter(pk=future.result(timeout=5)).exists())

    @skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks')
    def test_reconciliation_waits_for_creation_then_rejects_changed_inventory(self):
        from eth_account import Account as EvmAccount
        from eth_account.messages import encode_defunct
        from users.wallet_reconciliation import PrepareWalletReconciliation, CompleteWalletReconciliation

        wallet = EvmAccount.from_key('0x' + '12' * 32)
        info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        identity = {'uid': self.user.firebase_uid, 'auth_time': timezone.now().timestamp(),
                    'firebase': {'sign_in_provider': 'google.com'}}
        with patch('firebase_admin.auth.verify_id_token', return_value=identity):
            proof = PrepareWalletReconciliation.mutate(None, info, 'test-token', wallet.address)
        signature = wallet.sign_message(encode_defunct(text=proof.challenge)).signature.hex()
        started = Event()
        worker_pid = []

        def complete():
            try:
                with connections['default'].cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    worker_pid.append(cursor.fetchone()[0])
                started.set()
                return CompleteWalletReconciliation.mutate(None, info, proof.grant, signature)
            finally:
                connections['default'].close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                Account.objects.create(user=self.user, account_index=2)
                future = executor.submit(complete)
                self.assertTrue(started.wait(5))
                self.wait_for_database_lock(worker_pid[0])
            result = future.result(timeout=5)
            self.assertFalse(result.success)
            self.assertIn('Accounts changed', result.error)
        self.account.refresh_from_db()
        self.assertEqual(self.account.algorand_address, 'A' * 58)

    @skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks')
    def test_inflight_legacy_writer_waits_then_rejects_new_generation(self):
        started = Event()
        worker_pid = []

        def legacy_write():
            try:
                with connections['default'].cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    worker_pid.append(cursor.fetchone()[0])
                started.set()
                try:
                    persist_legacy_wallet_fields(self.account, algorand_address='A' * 58)
                except WalletRegistrationChanged:
                    return 'rejected'
                return 'overwritten'
            finally:
                connections['default'].close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                locked = Account.objects.select_for_update().get(pk=self.account.pk)
                locked.algorand_address = None
                locked.bsc_address = '0x' + '1' * 40
                locked.is_keyless_migrated = True
                locked.save(update_fields=['algorand_address', 'bsc_address', 'is_keyless_migrated'])
                future = executor.submit(legacy_write)
                self.assertTrue(started.wait(5))
                deadline = monotonic() + 5
                blocked = False
                while monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_stat_clear_snapshot()')
                        cursor.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s', worker_pid)
                        row = cursor.fetchone()
                    if row and row[0] == 'Lock':
                        blocked = True
                        break
                    sleep(0.01)
                self.assertTrue(blocked, 'Writer did not wait for the wallet row lock')
            self.assertEqual(future.result(timeout=5), 'rejected')
        self.account.refresh_from_db()
        self.assertIsNone(self.account.algorand_address)
        self.assertEqual(self.account.bsc_address, '0x' + '1' * 40)
