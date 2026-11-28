"""Wallet registration regressions using real database writes and signatures."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.db import close_old_connections, connection
from django.utils import timezone
from eth_account import Account as EvmAccount
from eth_account.messages import encode_defunct

from users.models import Account, Business, RetiredWalletAddress, User
from users.schema import UpdateAccountBscAddress, UpdateAccountAlgorandAddress
from users.web3auth_schema import UpdateAlgorandAddressMutation
from users.wallet_reconciliation import (
    PrepareWalletReconciliation, CompleteWalletReconciliation, wallet_challenge,
)


class RecoveryReservationConcurrencyTests(TransactionTestCase):
    def test_competing_connections_get_the_same_reservation(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        user = User.objects.create_user(username='concurrent-recovery', firebase_uid='concurrent-recovery')
        Account.objects.create(user=user, account_type='personal', account_index=0,
                               bsc_address='0x' + '56' * 20, is_keyless_migrated=True)
        identity = {'uid': user.firebase_uid, 'auth_time': timezone.now().timestamp(),
                    'firebase': {'sign_in_provider': 'google.com'}}
        barrier = Barrier(2)

        def reserve(proposal):
            close_old_connections()
            try:
                caller = User.objects.get(pk=user.pk)
                info = SimpleNamespace(context=SimpleNamespace(user=caller))
                barrier.wait(timeout=10)
                result = PrepareWalletReconciliation.mutate(None, info, 'fresh-token', recovery_file_ids=proposal)
                return result.success, result.recovery_file_ids
            finally:
                connection.close()

        proposals = [['first-payload-id', 'first-manifest-id'], ['second-payload-id', 'second-manifest-id']]
        with patch('firebase_admin.auth.verify_id_token', return_value=identity), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, proposals))
        self.assertTrue(all(success for success, _ in results))
        self.assertEqual(results[0][1], results[1][1])
        self.assertIn(results[0][1], proposals)
        user.refresh_from_db()
        self.assertEqual(user.wallet_recovery_drive_ids, results[0][1])


class WalletReconciliationDatabaseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='wallet-audit', firebase_uid='wallet-audit')
        self.old_address = '0x' + '34' * 20
        self.wallet = EvmAccount.from_key('0x' + '12' * 32)
        self.account = Account.objects.create(
            user=self.user, account_type='personal', account_index=0,
            bsc_address=self.old_address, is_keyless_migrated=True,
        )
        self.info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        identity = {'uid': self.user.firebase_uid, 'auth_time': timezone.now().timestamp(),
                    'firebase': {'sign_in_provider': 'google.com'}}
        with patch('firebase_admin.auth.verify_id_token', return_value=identity):
            self.proof = PrepareWalletReconciliation.mutate(
                None, self.info, 'test-token', self.wallet.address)
        self.signature = self.wallet.sign_message(
            encode_defunct(text=self.proof.challenge)).signature.hex()

    def complete(self):
        return CompleteWalletReconciliation.mutate(None, self.info, self.proof.grant, self.signature)

    def reserve(self, ids, provider='google.com', uid=None, age=0):
        identity = {'uid': uid or self.user.firebase_uid,
                    'auth_time': timezone.now().timestamp() - age,
                    'firebase': {'sign_in_provider': provider}}
        with patch('firebase_admin.auth.verify_id_token', return_value=identity):
            return PrepareWalletReconciliation.mutate(None, self.info, 'fresh-token', recovery_file_ids=ids)

    def test_recovery_reservation_is_durable_and_first_writer_wins(self):
        self.assertEqual(self.reserve([]).recovery_file_ids, [])
        first = ['drive-payload-first', 'drive-manifest-first']
        self.assertEqual(self.reserve(first).recovery_file_ids, first)
        # A second device carries a stale User instance and different proposed
        # IDs. The locked database row, not that stale object, decides.
        self.assertEqual(self.reserve(['drive-payload-second', 'drive-manifest-second']).recovery_file_ids, first)
        self.assertEqual(self.reserve([]).recovery_file_ids, first)
        self.account.refresh_from_db()
        self.assertEqual(self.account.bsc_address, self.old_address)

    def test_recovery_reservation_rejects_wrong_or_stale_identity_and_apple(self):
        ids = ['drive-payload-first', 'drive-manifest-first']
        for kwargs in ({'uid': 'other'}, {'age': 601}, {'provider': 'apple.com'}):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(self.reserve(ids, **kwargs).success)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_recovery_drive_ids, [])

    def test_recovery_reservation_rejects_invalid_ids(self):
        for ids in (['x'], ['identical-id', 'identical-id'], ['invalid/id', 'valid-manifest-id'], ['valid-first-id', 'x']):
            with self.subTest(ids=ids):
                self.assertFalse(self.reserve(ids).success)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_recovery_drive_ids, [])

    def test_commit_keeps_history_and_retries_without_duplicate_audit_rows(self):
        self.assertTrue(self.complete().success)
        self.assertTrue(self.complete().success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.bsc_address, self.wallet.address.lower())
        self.assertEqual(RetiredWalletAddress.objects.filter(account=self.account).count(), 1)
        self.assertTrue(RetiredWalletAddress.is_retired('bsc', self.old_address))

    def test_save_failure_rolls_back_retirement(self):
        with patch.object(Account, 'save', side_effect=RuntimeError('test write failure')):
            self.assertFalse(self.complete().success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.bsc_address, self.old_address)
        self.assertFalse(RetiredWalletAddress.objects.filter(account=self.account).exists())

    def test_background_registration_cannot_undo_committed_reconciliation(self):
        # Reconcile after registration read its Account and before its write.
        # This forces the stale snapshot without relying on thread timing:
        # the address lock is the step every registration takes before it.
        def reconcile_before_the_check(*args, **kwargs):
            self.assertTrue(self.complete().success)

        with patch('users.jwt_context.get_jwt_business_context_with_validation', return_value={
            'account_type': 'personal', 'account_index': 0,
        }), patch('users.models.lock_bsc_address', side_effect=reconcile_before_the_check):
            result = UpdateAccountBscAddress.mutate(None, self.info, self.old_address)
        self.assertFalse(result.success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.bsc_address, self.wallet.address.lower())

    def test_retired_algorand_address_cannot_be_reactivated_by_legacy_updates(self):
        from algosdk.encoding import encode_address
        address = encode_address(b'a' * 32)
        RetiredWalletAddress.objects.create(
            chain='algorand', address=address, account=self.account, user=self.user)
        with patch('users.jwt_context.get_jwt_business_context_with_validation', return_value={
            'account_type': 'personal', 'account_index': 0,
        }):
            for mutation in (UpdateAccountAlgorandAddress, UpdateAlgorandAddressMutation):
                with self.subTest(mutation=mutation.__name__):
                    result = mutation.mutate(None, self.info, address)
                    self.assertFalse(result.success)
        self.account.refresh_from_db()
        self.assertIsNone(self.account.algorand_address)

    def test_stale_algorand_updates_cannot_overwrite_reconciled_bsc_address(self):
        from algosdk.encoding import encode_address
        address = encode_address(b'a' * 32)
        original_check = RetiredWalletAddress.is_retired

        def reconcile_before_write(*args):
            with patch.object(RetiredWalletAddress, 'is_retired', original_check):
                self.assertTrue(self.complete().success)
            return False

        for mutation in (UpdateAccountAlgorandAddress, UpdateAlgorandAddressMutation):
            with self.subTest(mutation=mutation.__name__):
                Account.objects.filter(pk=self.account.pk).update(bsc_address=self.old_address)
                with patch('users.jwt_context.get_jwt_business_context_with_validation', return_value={
                    'account_type': 'personal', 'account_index': 0,
                }), patch.object(RetiredWalletAddress, 'is_retired', side_effect=reconcile_before_write):
                    result = mutation.mutate(None, self.info, address)
                self.assertFalse(result.success)
                self.account.refresh_from_db()
                self.assertEqual(self.account.bsc_address, self.wallet.address.lower())
                self.assertIsNone(self.account.algorand_address)


class OwnedWalletInventoryDatabaseTests(TestCase):
    """Full owner inventory, including secondary personal and business contexts."""
    def setUp(self):
        WalletReconciliationDatabaseTests.setUp(self)
        business = Business.objects.create(name='Owner wallet test')
        self.secondary = Account.objects.create(user=self.user, account_type='personal',
            account_index=2, algorand_address='S' * 58)
        self.business = Account.objects.create(user=self.user, account_type='business',
            account_index=4, business=business, bsc_address='0x' + '67' * 20)
        self.targets = {
            self.account.pk: self.wallet,
            self.secondary.pk: EvmAccount.from_key('0x' + '56' * 32),
            self.business.pk: EvmAccount.from_key('0x' + '78' * 32),
        }
        identity = {'uid': self.user.firebase_uid, 'auth_time': timezone.now().timestamp(),
                    'firebase': {'sign_in_provider': 'google.com'}}
        with patch('firebase_admin.auth.verify_id_token', return_value=identity):
            self.proof = PrepareWalletReconciliation.mutate(
                None, self.info, 'test-token', self.wallet.address)
        self.signature = self.wallet.sign_message(
            encode_defunct(text=self.proof.challenge)).signature.hex()
        self.wallet_proofs = [
            {'account_id': str(pk), 'bsc_address': wallet.address,
             'signature': wallet.sign_message(encode_defunct(text=wallet_challenge(
                 self.proof.challenge, str(pk), wallet.address))).signature.hex()}
            for pk, wallet in self.targets.items()
        ]

    def complete(self):
        return CompleteWalletReconciliation.mutate(
            None, self.info, self.proof.grant, self.signature, wallets=self.wallet_proofs)

    def test_inventory_preserves_real_contexts_and_changes_all_owned_wallets(self):
        self.assertEqual([entry['account_id'] for entry in self.proof.accounts],
                         [str(pk) for pk in self.targets])
        business = self.proof.accounts[-1]
        self.assertEqual((business['account_type'], business['account_index'], business['business_id']),
                         ('business', 4, str(self.business.business_id)))
        self.assertTrue(self.complete().success)
        self.assertTrue(self.complete().success)
        for pk, wallet in self.targets.items():
            account = Account.objects.get(pk=pk)
            self.assertEqual(account.bsc_address, wallet.address.lower())
            self.assertIsNone(account.algorand_address)
            self.assertTrue(account.is_keyless_migrated)

    def test_single_account_protocol_is_rejected_with_siblings(self):
        result = CompleteWalletReconciliation.mutate(None, self.info, self.proof.grant, self.signature)
        self.assertFalse(result.success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.bsc_address, self.old_address)

    def test_later_account_save_failure_rolls_back_all_prior_accounts(self):
        original_save = Account.save

        def fail_business(instance, *args, **kwargs):
            if instance.pk == self.business.pk:
                raise RuntimeError('last account write fails')
            return original_save(instance, *args, **kwargs)

        with patch.object(Account, 'save', fail_business):
            self.assertFalse(self.complete().success)
        self.account.refresh_from_db()
        self.secondary.refresh_from_db()
        self.assertEqual(self.account.bsc_address, self.old_address)
        self.assertEqual(self.secondary.algorand_address, 'S' * 58)
        self.assertFalse(RetiredWalletAddress.objects.filter(user=self.user).exists())

    def test_added_context_invalidates_entire_grant(self):
        Account.objects.create(user=self.user, account_type='personal', account_index=8)
        self.assertFalse(self.complete().success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.bsc_address, self.old_address)

    def test_deleted_context_invalidates_entire_grant(self):
        self.secondary.soft_delete()
        self.assertFalse(self.complete().success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.bsc_address, self.old_address)

    def _smart_account(self, index=0):
        contract = '0x' + '9a' * 20
        return contract, Account.objects.create(user=self.user, account_type='smart',
            account_index=index, bsc_address=contract)

    def _sign_all_targets(self):
        self.signature = self.wallet.sign_message(
            encode_defunct(text=self.proof.challenge)).signature.hex()
        self.wallet_proofs = [
            {'account_id': str(pk), 'bsc_address': wallet.address,
             'signature': wallet.sign_message(encode_defunct(text=wallet_challenge(
                 self.proof.challenge, str(pk), wallet.address))).signature.hex()}
            for pk, wallet in self.targets.items()
        ]

    def _prepare(self, address=None, provider='google.com', **extra):
        identity = {'uid': self.user.firebase_uid, 'auth_time': timezone.now().timestamp(),
                    'firebase': {'sign_in_provider': provider}}
        with patch('firebase_admin.auth.verify_id_token', return_value=identity):
            return PrepareWalletReconciliation.mutate(
                None, self.info, 'test-token', address, **extra)

    def test_smart_account_is_left_out_of_the_inventory(self):
        # Listing a Cuenta inteligente locked its owner out of sign-in: the
        # app refuses an inventory with any type other than personal/business.
        _, smart = self._smart_account()
        for address in (None, self.old_address, self.wallet.address):
            result = self._prepare(address)
            self.assertTrue(result.success)
            self.assertNotIn(str(smart.pk), [item['account_id'] for item in result.accounts])
            self.assertNotIn('smart', [item['account_type'] for item in result.accounts])

    def test_smart_account_owner_gets_no_grant_to_replace_personal_wallet(self):
        # The contract's owner on chain is a personal wallet. The registered
        # address gets a grant as before; a different one gets the inventory
        # and no grant, so the app has nothing to commit.
        self._smart_account(index=1)  # an inherited account counts the same
        for provider in ('google.com', 'apple.com'):
            self.assertTrue(self._prepare(self.old_address, provider).grant)
            replacement = self._prepare(self.wallet.address, provider)
            self.assertTrue(replacement.success)
            self.assertIsNone(replacement.grant)
            self.assertIsNone(replacement.challenge)

    def test_grant_older_than_the_smart_account_cannot_replace_its_owner(self):
        # setUp's grant was issued before the Cuenta inteligente existed.
        contract, smart = self._smart_account()
        result = self.complete()
        self.assertFalse(result.success)
        self.assertEqual(result.error, 'A Cuenta inteligente blocks replacing a personal wallet')
        self.account.refresh_from_db()
        self.business.refresh_from_db()
        smart.refresh_from_db()
        self.assertEqual(self.account.bsc_address, self.old_address)
        self.assertEqual(self.business.bsc_address, '0x' + '67' * 20)
        self.assertEqual(smart.bsc_address, contract)
        self.assertFalse(RetiredWalletAddress.objects.filter(user=self.user).exists())

    def test_deleted_smart_account_does_not_block_a_replacement(self):
        _, smart = self._smart_account()
        smart.soft_delete()
        self.proof = self._prepare(self.wallet.address)
        self.assertTrue(self.proof.grant)
        self._sign_all_targets()
        self.assertTrue(self.complete().success)

    def test_smart_account_does_not_block_a_first_bsc_address(self):
        # Nothing to orphan: a personal wallet with no BSC address owns no contract.
        Account.objects.filter(pk=self.account.pk).update(
            bsc_address=None, algorand_address='P' * 58, is_keyless_migrated=False)
        self._smart_account()
        self.proof = self._prepare(self.wallet.address, 'apple.com')
        self.assertTrue(self.proof.grant)
        self._sign_all_targets()
        self.assertTrue(self.complete().success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.bsc_address, self.wallet.address.lower())

    def test_smart_account_owner_can_still_replace_other_wallets(self):
        # The personal wallet keeps its address; only the ones that cannot
        # own a contract change (a business, a personal with no BSC address).
        # Stored checksummed, offered lowercase: the match ignores case.
        self.assertNotEqual(self.wallet.address, self.wallet.address.lower())
        Account.objects.filter(pk=self.account.pk).update(bsc_address=self.wallet.address)
        contract, smart = self._smart_account()
        self.proof = self._prepare(self.wallet.address.lower())
        self.assertTrue(self.proof.grant)
        self._sign_all_targets()
        self.assertTrue(self.complete().success)
        self.assertTrue(self.complete().success)  # the retry after a lost response
        for row in (self.account, self.secondary, self.business, smart):
            row.refresh_from_db()
        self.assertEqual(self.account.bsc_address.lower(), self.wallet.address.lower())
        self.assertEqual(self.secondary.bsc_address, self.targets[self.secondary.pk].address.lower())
        self.assertIsNone(self.secondary.algorand_address)
        self.assertEqual(self.business.bsc_address, self.targets[self.business.pk].address.lower())
        self.assertEqual(smart.bsc_address, contract)

    def test_smart_account_owner_can_still_reserve_drive_ids(self):
        # The app reserves ids to upload the secret it already holds, too.
        self._smart_account()
        proposal = ['payload-file-id', 'manifest-file-id']
        self.assertEqual(self._prepare(recovery_file_ids=[]).recovery_file_ids, [])
        result = self._prepare(recovery_file_ids=proposal)
        self.assertTrue(result.success)
        self.assertEqual(result.recovery_file_ids, proposal)

    def test_smart_account_owner_cannot_replace_a_secondary_personal_wallet(self):
        # Wider than the one wallet that owns the contract, on purpose.
        Account.objects.filter(pk=self.account.pk).update(bsc_address=self.wallet.address)
        secondary_address = '0x' + 'ab' * 20
        Account.objects.filter(pk=self.secondary.pk).update(bsc_address=secondary_address)
        self._smart_account()
        self.proof = self._prepare(self.wallet.address)
        self.assertTrue(self.proof.grant)
        self._sign_all_targets()
        result = self.complete()
        self.assertFalse(result.success)
        self.assertEqual(result.error, 'A Cuenta inteligente blocks replacing a personal wallet')
        self.secondary.refresh_from_db()
        self.business.refresh_from_db()
        self.assertEqual(self.secondary.bsc_address, secondary_address)
        self.assertEqual(self.business.bsc_address, '0x' + '67' * 20)

    def test_employee_only_wallet_is_excluded_and_unchanged(self):
        from users.models_employee import BusinessEmployee
        other_user = User(username='another-owner', firebase_uid='another-owner')
        User.objects.bulk_create([other_user])
        other_business = Business.objects.create(name='Employer test')
        employer = Account.objects.create(user=other_user, business=other_business,
            account_type='business', account_index=1, bsc_address='0x' + '89' * 20)
        BusinessEmployee.objects.create(user=self.user, business=other_business, role='admin')
        identity = {'uid': self.user.firebase_uid, 'auth_time': timezone.now().timestamp(),
                    'firebase': {'sign_in_provider': 'apple.com'}}
        with patch('firebase_admin.auth.verify_id_token', return_value=identity):
            result = PrepareWalletReconciliation.mutate(None, self.info, 'test-token')
        self.assertNotIn(str(employer.pk), [item['account_id'] for item in result.accounts])
        self.assertTrue(self.complete().success)
        employer.refresh_from_db()
        self.assertEqual(employer.bsc_address, '0x' + '89' * 20)

    def test_sibling_target_cannot_claim_other_account_historical_address(self):
        other_user = User(username='historical-owner', firebase_uid='historical-owner')
        User.objects.bulk_create([other_user])
        other_account = Account.objects.create(user=other_user)
        RetiredWalletAddress.objects.create(account=other_account, user=other_user,
            chain='bsc', address=self.targets[self.business.pk].address)
        self.assertFalse(self.complete().success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.bsc_address, self.old_address)
