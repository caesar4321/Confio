"""Offline service tests with real signatures, mocked DB and Firebase boundaries.

Run: myvenv/bin/python -m unittest tests.test_wallet_reconciliation
No production settings, database, keys, Firebase or RPC access.
"""
import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

# Import framework modules before temporarily substituting the model module;
# restoring sys.modules must not leave two different Graphene type identities.
import graphene
from django.db import transaction

from django.conf import settings
if not settings.configured:
    settings.configure(SECRET_KEY='offline-wallet-reconciliation-tests', USE_TZ=True)

from django.core import signing
from django.utils import timezone
from eth_account import Account as EvmAccount
from eth_account.messages import encode_defunct


class WalletReconciliationTests(TestCase):
    def setUp(self):
        fake_models = MagicMock()
        spec = importlib.util.spec_from_file_location(
            'users._reconciliation_test_subject',
            Path(__file__).resolve().parents[1] / 'users/wallet_reconciliation.py')
        self.service = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'users.models': fake_models}):
            spec.loader.exec_module(self.service)
        self.user = SimpleNamespace(pk=7, firebase_uid='test-firebase', is_active=True, is_authenticated=True)
        self.info = SimpleNamespace(context=SimpleNamespace(user=self.user))
        self.wallet = EvmAccount.from_key('0x' + '12' * 32)
        self.account = SimpleNamespace(pk=9, algorand_address='OLD-ALGO',
            bsc_address='0x' + '34' * 20, is_keyless_migrated=False, save=MagicMock(),
            account_type='personal', account_index=0, business_id=None)
        self.service.owned_accounts = MagicMock(return_value=[self.account])
        self.service.User.objects.select_for_update.return_value.get.return_value = self.user
        self.service.Account.all_objects.filter.return_value.exclude.return_value.exists.return_value = False
        self.service.RetiredWalletAddress.objects.filter.return_value.exclude.return_value.exists.return_value = False
        self.service.RetiredWalletAddress.normalize_address.side_effect = lambda chain, addr: addr
        self.service.RetiredWalletAddress.objects.get_or_create.return_value = (SimpleNamespace(account_id=9), True)
        self.identity = {'uid': self.user.firebase_uid, 'auth_time': timezone.now().timestamp(),
                         'firebase': {'sign_in_provider': 'google.com'}}
        self.stack = []
        for target, value in [
            ('firebase_admin.auth.verify_id_token', MagicMock(return_value=self.identity)),
            ('django.db.transaction.atomic', MagicMock(side_effect=lambda: nullcontext())),
            ('django.db.transaction.on_commit', MagicMock()),
        ]:
            p = patch(target, value); p.start(); self.stack.append(p)
            self.addCleanup(p.stop)

    def prepare(self):
        return self.service.PrepareWalletReconciliation.mutate(
            None, self.info, 'firebase-token', self.wallet.address)

    def signature(self, prepared, wallet=None):
        return (wallet or self.wallet).sign_message(
            encode_defunct(text=prepared.challenge)).signature.hex()

    def complete(self, prepared, signature=None):
        return self.service.CompleteWalletReconciliation.mutate(
            None, self.info, prepared.grant, signature or self.signature(prepared))

    def test_google_reconciles_without_balance_checks_and_keeps_old_addresses(self):
        proof = self.prepare()
        result = self.complete(proof)
        self.assertTrue(result.success)
        self.assertIsNone(self.account.algorand_address)
        self.assertEqual(self.account.bsc_address, self.wallet.address.lower())
        retired = self.service.RetiredWalletAddress.objects.get_or_create.call_args_list
        self.assertEqual([c.kwargs['chain'] for c in retired], ['algorand', 'bsc'])
        self.account.save.assert_called_once_with(update_fields=[
            'algorand_address', 'bsc_address', 'is_keyless_migrated'])

    def test_apple_uses_same_authorization(self):
        self.identity['firebase']['sign_in_provider'] = 'apple.com'
        self.assertTrue(self.complete(self.prepare()).success)

    def test_lost_response_is_idempotent(self):
        proof = self.prepare()
        self.assertTrue(self.complete(proof).success)
        self.assertTrue(self.complete(proof).success)
        self.account.save.assert_called_once()

    def test_competing_registration_invalidates_old_grant(self):
        proof = self.prepare()
        self.account.bsc_address = '0x' + '56' * 20
        self.assertFalse(self.complete(proof).success)
        self.account.save.assert_not_called()

    def test_wrong_signer_fails_even_on_idempotent_path(self):
        proof = self.prepare()
        self.complete(proof)
        wrong = self.signature(proof, EvmAccount.from_key('0x' + '78' * 32))
        self.assertFalse(self.complete(proof, wrong).success)

    def test_other_active_owner_is_rejected(self):
        self.service.Account.all_objects.filter.return_value.exclude.return_value.exists.return_value = True
        self.assertFalse(self.complete(self.prepare()).success)
        self.account.save.assert_not_called()

    def test_other_historical_owner_is_rejected(self):
        self.service.RetiredWalletAddress.objects.filter.return_value.exclude.return_value.exists.return_value = True
        self.assertFalse(self.complete(self.prepare()).success)
        self.account.save.assert_not_called()

    def test_audit_conflict_does_not_save_registration(self):
        self.service.RetiredWalletAddress.objects.get_or_create.return_value = (SimpleNamespace(account_id=88), False)
        self.assertFalse(self.complete(self.prepare()).success)
        self.account.save.assert_not_called()

    def test_stale_authentication_cannot_prepare(self):
        self.identity['auth_time'] -= 601
        self.assertFalse(self.prepare().success)

    def test_wrong_firebase_identity_cannot_prepare(self):
        self.identity['uid'] = 'another-user'
        self.assertFalse(self.prepare().success)

    def test_password_login_cannot_prepare(self):
        self.identity['firebase']['sign_in_provider'] = 'password'
        self.assertFalse(self.prepare().success)

    def test_revoked_identity_cannot_prepare(self):
        with patch('firebase_admin.auth.verify_id_token', side_effect=ValueError('revoked')):
            self.assertFalse(self.prepare().success)

    def test_another_user_cannot_replay(self):
        proof = self.prepare()
        self.user.pk = 8
        self.assertFalse(self.complete(proof).success)

    def test_expired_grant_fails(self):
        proof = self.prepare()
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 601):
            self.assertFalse(self.complete(proof).success)

    def test_tampered_grant_fails(self):
        proof = self.prepare(); proof.grant += 'tampered'
        self.assertFalse(self.complete(proof).success)

    def test_zero_address_rejected(self):
        self.assertFalse(self.service.PrepareWalletReconciliation.mutate(
            None, self.info, 'firebase-token', '0x' + '00' * 20).success)

    def test_signed_grant_binds_replacement_and_old_anchors(self):
        proof = self.prepare()
        payload = signing.loads(proof.grant, salt=self.service.SALT)
        self.assertEqual(payload['replacement'], self.wallet.address.lower())
        self.assertEqual(payload['inventory'][0]['anchors'], ['OLD-ALGO', '0x' + '34' * 20])

    def sibling_proof(self):
        self.sibling = SimpleNamespace(pk=10, account_type='business', account_index=3,
            business_id=91, algorand_address='OLD-BUSINESS', bsc_address=None,
            is_keyless_migrated=False, save=MagicMock())
        self.sibling_wallet = EvmAccount.from_key('0x' + '56' * 32)
        self.service.owned_accounts.return_value = [self.account, self.sibling]
        self.service.RetiredWalletAddress.objects.get_or_create.side_effect = (
            lambda **kwargs: (SimpleNamespace(account_id=kwargs['defaults']['account'].pk), True))
        proof = self.prepare()
        wallets = []
        for account, wallet in [(self.account, self.wallet), (self.sibling, self.sibling_wallet)]:
            address = wallet.address.lower()
            wallets.append({'account_id': str(account.pk), 'bsc_address': address,
                'signature': wallet.sign_message(encode_defunct(text=self.service.wallet_challenge(
                    proof.challenge, str(account.pk), address))).signature.hex()})
        return proof, wallets

    def complete_inventory(self, proof, wallets):
        return self.service.CompleteWalletReconciliation.mutate(
            None, self.info, proof.grant, self.signature(proof), wallets=wallets)

    def test_inventory_only_prepare_does_not_issue_grant(self):
        result = self.service.PrepareWalletReconciliation.mutate(None, self.info, 'token')
        self.assertTrue(result.success)
        self.assertIsNone(result.grant)
        self.assertEqual(result.accounts[0]['account_id'], '9')
        self.assertFalse(result.accounts[0]['is_keyless_migrated'])

    def test_all_owned_wallets_are_reconciled_and_retry_is_idempotent(self):
        proof, wallets = self.sibling_proof()
        self.assertTrue(self.complete_inventory(proof, wallets).success)
        self.assertTrue(self.complete_inventory(proof, wallets).success)
        self.assertEqual(self.sibling.bsc_address, self.sibling_wallet.address.lower())
        self.assertIsNone(self.sibling.algorand_address)
        self.account.save.assert_called_once()
        self.sibling.save.assert_called_once()

    def test_single_proof_cannot_partially_reconcile_siblings(self):
        proof, _ = self.sibling_proof()
        self.assertFalse(self.complete(proof).success)
        self.account.save.assert_not_called()

    def test_omitted_sibling_proof_is_rejected(self):
        proof, wallets = self.sibling_proof()
        self.assertFalse(self.complete_inventory(proof, wallets[:1]).success)
        self.account.save.assert_not_called()

    def test_duplicate_account_proof_is_rejected(self):
        proof, wallets = self.sibling_proof()
        self.assertFalse(self.complete_inventory(proof, [wallets[0], wallets[0]]).success)

    def test_wrong_sibling_signer_is_rejected(self):
        proof, wallets = self.sibling_proof()
        wallets[1]['signature'] = wallets[0]['signature']
        self.assertFalse(self.complete_inventory(proof, wallets).success)
        self.account.save.assert_not_called()

    def test_unowned_account_proof_is_rejected(self):
        proof, wallets = self.sibling_proof()
        wallets[1]['account_id'] = '99'
        self.assertFalse(self.complete_inventory(proof, wallets).success)

    def test_changed_sibling_anchor_rejects_entire_transition(self):
        proof, wallets = self.sibling_proof()
        self.sibling.algorand_address = 'CHANGED'
        self.assertFalse(self.complete_inventory(proof, wallets).success)
        self.account.save.assert_not_called()

    def test_changed_sibling_context_rejects_entire_transition(self):
        proof, wallets = self.sibling_proof()
        self.sibling.account_index += 1
        self.assertFalse(self.complete_inventory(proof, wallets).success)
        self.account.save.assert_not_called()

    def test_missing_sibling_rejects_entire_transition(self):
        proof, wallets = self.sibling_proof()
        self.service.owned_accounts.return_value = [self.account]
        self.assertFalse(self.complete_inventory(proof, wallets).success)

    def test_v1_grant_is_rejected_even_with_valid_signature(self):
        proof = self.prepare()
        payload = signing.loads(proof.grant, salt=self.service.SALT)
        payload['version'] = 1
        proof.grant = signing.dumps(payload, salt=self.service.SALT)
        proof.challenge = self.service.challenge(payload)
        self.assertFalse(self.complete(proof).success)

    def test_duplicate_target_addresses_are_rejected(self):
        proof, wallets = self.sibling_proof()
        wallets[1]['bsc_address'] = self.wallet.address.lower()
        wallets[1]['signature'] = self.wallet.sign_message(encode_defunct(
            text=self.service.wallet_challenge(proof.challenge, '10', self.wallet.address))).signature.hex()
        self.assertFalse(self.complete_inventory(proof, wallets).success)
        self.account.save.assert_not_called()

    def test_inventory_graphql_contract(self):
        proof, wallets = self.sibling_proof()
        class Query(graphene.ObjectType):
            ok = graphene.Boolean()
        class Mutation(graphene.ObjectType):
            prepare_wallet_reconciliation = self.service.PrepareWalletReconciliation.Field()
            complete_wallet_reconciliation = self.service.CompleteWalletReconciliation.Field()
        schema = graphene.Schema(query=Query, mutation=Mutation)
        result = schema.execute('''mutation($token: String!) {
          prepareWalletReconciliation(firebaseIdToken: $token) {
            success grant accounts { accountId accountType accountIndex businessId
              algorandAddress bscAddress isKeylessMigrated }
          }
        }''', variable_values={'token': 'firebase-token'}, context_value=self.info.context)
        self.assertIsNone(result.errors)
        result = schema.execute('''mutation($grant: String!, $signature: String!,
            $wallets: [WalletReconciliationProofInput!]!) {
          completeWalletReconciliation(grant: $grant, signature: $signature, wallets: $wallets) {
            success accounts { accountId bscAddress isKeylessMigrated }
          }
        }''', variable_values={'grant': proof.grant, 'signature': self.signature(proof),
            'wallets': [{'accountId': item['account_id'], 'bscAddress': item['bsc_address'],
                         'signature': item['signature']} for item in wallets]},
            context_value=self.info.context)
        self.assertIsNone(result.errors)
        self.assertTrue(result.data['completeWalletReconciliation']['success'])
        self.assertEqual(len(result.data['completeWalletReconciliation']['accounts']), 2)

    def test_graphql_contract_matches_mobile(self):
        import graphene
        class Query(graphene.ObjectType):
            ok = graphene.Boolean()
        class Mutation(graphene.ObjectType):
            prepare_wallet_reconciliation = self.service.PrepareWalletReconciliation.Field()
            complete_wallet_reconciliation = self.service.CompleteWalletReconciliation.Field()
        schema = graphene.Schema(query=Query, mutation=Mutation)
        result = schema.execute('''mutation($token: String!, $address: String!) {
          prepareWalletReconciliation(firebaseIdToken: $token, bscAddress: $address) {
            success error grant challenge
          }
        }''', variable_values={'token': 'firebase-token', 'address': self.wallet.address},
            context_value=self.info.context)
        self.assertIsNone(result.errors)
        prepared = SimpleNamespace(**result.data['prepareWalletReconciliation'])
        result = schema.execute('''mutation($grant: String!, $signature: String!) {
          completeWalletReconciliation(grant: $grant, signature: $signature) {
            success error bscAddress
          }
        }''', variable_values={'grant': prepared.grant, 'signature': self.signature(prepared)},
            context_value=self.info.context)
        self.assertIsNone(result.errors)
        self.assertTrue(result.data['completeWalletReconciliation']['success'])


class RetiredBalanceVisibilityTests(TestCase):
    def test_retired_algorand_balances_are_not_served_from_account_cache(self):
        spec = importlib.util.spec_from_file_location(
            'blockchain._balance_service_test_subject',
            Path(__file__).resolve().parents[1] / 'blockchain/balance_service.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {
            'users.models': MagicMock(), 'blockchain.models': MagicMock(),
            'blockchain.algorand_client': MagicMock(),
        }):
            spec.loader.exec_module(module)
        account = SimpleNamespace(id=9, algorand_address=None)
        with patch.object(module.cache, 'get', side_effect=AssertionError('Must not read old cache')):
            for refresh in (False, True):
                balances = module.BalanceService.get_all_balances(account, force_refresh=refresh)
                self.assertEqual(set(balances), {'algo', 'cusd', 'confio', 'usdc', 'confio_presale'})
                self.assertTrue(all(b['amount'] == 0 and b['available'] == 0 for b in balances.values()))
                self.assertEqual(module.BalanceService.get_balance(account, force_refresh=refresh)['amount'], 0)
            self.assertIsNone(module.BalanceService._get_cached_balance(account, 'CUSD'))
