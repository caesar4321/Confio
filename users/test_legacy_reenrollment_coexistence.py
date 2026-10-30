"""Legacy single-wallet API must not bypass whole-inventory reconciliation."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from eth_account import Account as EvmAccount
from eth_account.messages import encode_defunct

from users.models import Account, Business, RetiredWalletAddress, User
from users.web3auth_schema import (
    CompleteWalletReenrollmentMutation, PrepareWalletReenrollmentMutation,
    _issue_wallet_reenrollment_grant, _issue_wallet_reenrollment_preparation,
    _legacy_reenrollment_has_owned_siblings,
)


class LegacyReenrollmentCoexistenceTests(TestCase):
    def setUp(self):
        self.user = User(username='legacy-coexist', firebase_uid='legacy-coexist')
        User.objects.bulk_create([self.user])
        self.account = Account.objects.create(user=self.user, algorand_address='A' * 58,
            is_keyless_migrated=False)
        self.wallet = EvmAccount.from_key('0x' + '12' * 32)
        self.info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        self.auth_time = int(timezone.now().timestamp())
        self.inspection = {'eligible': True, 'status': 'eligible',
            'snapshot_round': 12345, 'sponsor_funding': 500000,
            'reason': 'sponsor_only_empty_wallet'}
        challenge, self.grant = _issue_wallet_reenrollment_grant(
            self.user, self.account, 'test-google-subject', self.auth_time, self.inspection)
        self.signature = self.wallet.sign_message(encode_defunct(text=challenge)).signature.hex()

    def complete(self, inspection=None):
        with patch('users.web3auth_schema._revalidate_wallet_reenrollment',
                   side_effect=inspection or (lambda *_: self.inspection)), patch(
                   'users.web3auth_schema._wallet_reenrollment_server_blocker', return_value=None):
            return CompleteWalletReenrollmentMutation.mutate(None, self.info,
                self.wallet.address, self.grant, self.signature)

    def prepare(self):
        token = _issue_wallet_reenrollment_preparation(
            self.user, self.account, 'test-google-subject', self.auth_time)
        return PrepareWalletReenrollmentMutation.mutate(None, self.info, token)

    def assert_unchanged(self):
        self.account.refresh_from_db()
        self.assertEqual(self.account.algorand_address, 'A' * 58)
        self.assertIsNone(self.account.bsc_address)
        self.assertFalse(RetiredWalletAddress.objects.filter(account=self.account).exists())

    def test_sole_primary_account_remains_supported(self):
        self.assertTrue(self.complete().success)
        self.account.refresh_from_db()
        self.assertEqual(self.account.bsc_address.lower(), self.wallet.address.lower())

    def test_other_owners_retired_target_is_reserved(self):
        owner = User(username='former-owner', firebase_uid='former-owner')
        User.objects.bulk_create([owner])
        old = Account.objects.create(user=owner)
        RetiredWalletAddress.objects.create(user=owner, account=old, chain='bsc',
            address=self.wallet.address)
        self.assertFalse(self.complete().success)
        self.assert_unchanged()

    def test_soft_deleted_account_target_remains_reserved(self):
        owner = User(username='deleted-owner', firebase_uid='deleted-owner')
        User.objects.bulk_create([owner])
        old = Account.objects.create(user=owner, bsc_address=self.wallet.address)
        old.soft_delete()
        self.assertFalse(self.complete().success)
        self.assert_unchanged()

    def test_owned_sibling_blocks_preparation_before_chain_inspection(self):
        Account.objects.create(user=self.user, account_index=2)
        with patch('users.web3auth_schema._inspect_wallet_reenrollment') as inspection:
            result = self.prepare()
        self.assertFalse(result.success)
        self.assertIn('todas tus billeteras', result.error)
        inspection.assert_not_called()

    def test_owned_sibling_blocks_completion(self):
        business = Business.objects.create(name='Owned test business')
        Account.objects.create(user=self.user, account_type='business', business=business)
        self.assertFalse(self.complete().success)
        self.assert_unchanged()

    def test_sibling_created_during_slow_inspection_blocks_locked_completion(self):
        def inspection(*_):
            Account.objects.create(user=self.user, account_index=2)
            return self.inspection
        result = self.complete(inspection)
        self.assertFalse(result.success)
        self.assertIn('todas tus billeteras', result.error)
        self.assert_unchanged()

    def test_sibling_created_during_preparation_does_not_receive_grant(self):
        def inspection(*_):
            Account.objects.create(user=self.user, account_index=2)
            return self.inspection
        with patch('users.web3auth_schema._inspect_wallet_reenrollment', side_effect=inspection):
            result = self.prepare()
        self.assertFalse(result.success)
        self.assertIsNone(result.wallet_reenrollment_grant)

    def test_employee_only_business_does_not_count_as_owned_sibling(self):
        from users.models_employee import BusinessEmployee
        owner = User(username='employer', firebase_uid='employer')
        User.objects.bulk_create([owner])
        business = Business.objects.create(name='Employer test business')
        Account.objects.create(user=owner, account_type='business', business=business)
        BusinessEmployee.objects.create(user=self.user, business=business, role='admin')
        self.assertFalse(_legacy_reenrollment_has_owned_siblings(self.account))
        self.assertTrue(self.complete().success)

    def test_deleted_sibling_does_not_block_current_sole_primary(self):
        sibling = Account.objects.create(user=self.user, account_index=2)
        sibling.soft_delete()
        self.assertFalse(_legacy_reenrollment_has_owned_siblings(self.account))
        self.assertTrue(self.complete().success)

    def test_retirement_insert_race_rechecks_owner_for_both_chains(self):
        owner = User(username='racing-owner', firebase_uid='racing-owner')
        User.objects.bulk_create([owner])
        foreign_account = Account.objects.create(user=owner)
        old_bsc = '0x' + '34' * 20
        self.account.bsc_address = old_bsc
        self.account.save(update_fields=['bsc_address'])
        challenge, self.grant = _issue_wallet_reenrollment_grant(
            self.user, self.account, 'test-google-subject', self.auth_time, self.inspection)
        self.signature = self.wallet.sign_message(encode_defunct(text=challenge)).signature.hex()
        real_get_or_create = RetiredWalletAddress.objects.get_or_create

        for conflict_chain in ('algorand', 'bsc'):
            with self.subTest(chain=conflict_chain):
                def raced_get_or_create(**kwargs):
                    if kwargs['chain'] == conflict_chain:
                        # Simulate a concurrent winner between exists() and
                        # get_or_create(). For BSC the Algo row was inserted
                        # first, and must roll back with the failed transition.
                        return SimpleNamespace(account_id=foreign_account.pk), False
                    return real_get_or_create(**kwargs)

                with patch.object(RetiredWalletAddress.objects, 'get_or_create',
                                  side_effect=raced_get_or_create), patch(
                        'users.web3auth_schema._inspect_stale_bsc_reenrollment',
                        return_value={'eligible': True}), patch(
                        'users.web3auth_schema._stale_bsc_server_blocker', return_value=None):
                    self.assertFalse(self.complete().success)
                self.account.refresh_from_db()
                self.assertEqual(self.account.algorand_address, 'A' * 58)
                self.assertEqual(self.account.bsc_address, old_bsc)
                self.assertFalse(RetiredWalletAddress.objects.filter(account=self.account).exists())


class ProviderNeutralReenrollmentOfferTests(TestCase):
    ADDRESS = 'M' * 58

    def login(self, provider, identities):
        from django.test import override_settings
        from users.web3auth_schema import Web3AuthLoginMutation
        user = User.objects.create_user(
            username=f'offer-{provider}', firebase_uid=f'offer-{provider}', email=f'{provider}@example.com')
        Account.objects.create(user=user, account_type='personal', account_index=0, algorand_address=self.ADDRESS,
                               wallet_reenrollment_assessment={
                                   'version': 2, 'status': 'eligible', 'eligible': True,
                                   'reason': 'never_funded_wallet', 'snapshot_round': 100, 'sponsor_funding': 0,
                                   'old_algorand_address': self.ADDRESS, 'old_bsc_address': ''})
        claims = {'uid': user.firebase_uid, 'email': user.email, 'auth_time': int(timezone.now().timestamp()),
                  'firebase': {'sign_in_provider': provider, 'identities': identities}}
        with override_settings(APP_CHECK_ENFORCE=False), \
                patch('firebase_admin.auth.verify_id_token', return_value=claims), \
                patch('security.login_restrictions.login_is_restricted', return_value=False):
            return Web3AuthLoginMutation.mutate(
                None, SimpleNamespace(context=SimpleNamespace(META={}, headers={})), firebase_id_token='token')

    def test_apple_gets_the_same_offer_as_google(self):
        # protects=a proven-unused wallet is replaceable whichever provider signs in; fails_when=the offer is tied to Google again; no_claim=the assessment itself
        result = self.login('apple.com', {'apple.com': ['apple-sub']})
        self.assertTrue(result.wallet_reenrollment_allowed)
        self.assertTrue(result.wallet_reenrollment_grant)

    def test_a_token_with_no_provider_identity_gets_none(self):
        # protects=the grant always binds a provider subject; fails_when=another sign-in method reaches the offer; no_claim=login itself
        result = self.login('password', {})
        self.assertFalse(result.wallet_reenrollment_allowed)

    def test_a_grant_signed_before_the_rename_still_verifies(self):
        # protects=sign-ins in flight during the deploy; fails_when=completion rejects a valid Google grant after the app dropped its session; no_claim=grant expiry
        from django.core import signing
        from users import web3auth_schema as schema
        now = int(timezone.now().timestamp())
        user = User.objects.create_user(username='old-grant', firebase_uid='old-grant')
        account = Account.objects.create(user=user, account_type='personal', account_index=0, algorand_address=self.ADDRESS)
        token = signing.dumps({'version': 1, 'user_id': user.id, 'account_id': account.id,
                               'old_algorand_address': self.ADDRESS, 'old_bsc_address': '',
                               'google_subject': 'google-sub', 'google_auth_time': now, 'nonce': 'n'},
                              salt=schema.WALLET_REENROLLMENT_PREPARATION_SALT)
        self.assertIsNotNone(schema._verify_wallet_reenrollment_preparation(token, user, account))
