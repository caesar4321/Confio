"""Wallet registration regressions using real database writes and signatures."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from eth_account import Account as EvmAccount
from eth_account.messages import encode_defunct

from users.models import Account, Business, RetiredWalletAddress, User
from users.schema import UpdateAccountBscAddress, UpdateAccountAlgorandAddress
from users.web3auth_schema import UpdateAlgorandAddressMutation
from users.wallet_reconciliation import (
    PrepareWalletReconciliation, CompleteWalletReconciliation, wallet_challenge,
)


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
        # This forces the stale snapshot without relying on thread timing.
        original_filter = RetiredWalletAddress.objects.filter

        def reconcile_before_history_check(*args, **kwargs):
            with patch.object(RetiredWalletAddress.objects, 'filter', original_filter):
                self.assertTrue(self.complete().success)
            return original_filter(*args, **kwargs)

        with patch('users.jwt_context.get_jwt_business_context_with_validation', return_value={
            'account_type': 'personal', 'account_index': 0,
        }), patch.object(RetiredWalletAddress.objects, 'filter', side_effect=reconcile_before_history_check):
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
