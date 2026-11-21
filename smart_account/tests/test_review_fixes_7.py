"""Review round 7: chain truth over a lagging mirror (spec 6.5).

1. A ClaimExecuted the mirror has not applied yet: the previous owner's
   batches must not carry account.cancelClaim() (it reverts NotOwner) nor be
   refused for lacking it. An unreadable chain keeps the protective no-op
   but never requires it.
2. Subscribe from a wallet whose clone the factory still maps: owner() and
   inherited() decide, not the mirror. Still the signer's: subscribed in
   place. Inherited or owned by someone else: a new account one generation
   on (decision 33)."""
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from smart_account import abi, offer, relay_policy, services
from smart_account.models import SmartAccountPreparedAction

from .base import BUILD, FACTORY, VAULT, WAD, SmartAccountTestCase
from .test_review_fixes import _ClaimPending


class MirrorLagsClaimExecutedTests(_ClaimPending):
    def setUp(self):
        super().setUp()
        self.reconcile = mock.patch('smart_account.tasks.reconcile_events.apply_async')
        self.reconcile_mock = self.reconcile.start()
        self.addCleanup(self.reconcile.stop)

    def executed_on_chain(self):
        # Mirror: still active, claim still pending. Chain: the heir owns it.
        self.chain.views[(self.account.contract_address, 'inherited')] = True
        self.chain.views[(self.account.contract_address, 'owner')] = self.heir.wallet

    def prepared(self, calls, request_id='sa-' + 'd' * 32):
        SmartAccountPreparedAction.objects.create(
            request_id=request_id, user=self.owner, signer_address=self.owner.wallet,
            target_address=self.account.contract_address, kind='smart_deposit', calls=calls,
            calls_hash=services.calls_hash(calls), expires_at=timezone.now() + timedelta(minutes=5))
        return request_id

    def deposit_calls(self):
        from smart_account import abi
        return [abi.transfer_call(VAULT, self.account.contract_address, 5)]

    def test_inherited_on_chain_appends_nothing_and_accepts_the_batch(self):
        self.executed_on_chain()
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, self.owner.wallet), [])
        self.assertIsNone(services.claim_pending_on_own_account(self.owner))
        self.assertEqual(services.with_cancel_claim(self.owner, self.deposit_calls()), self.deposit_calls())
        calls = self.deposit_calls()
        action = relay_policy.validate_batch(calls, self.owner, self.owner.wallet, self.prepared(calls))
        self.assertEqual(action.request_id, 'sa-' + 'd' * 32)
        self.assertTrue(self.ops_alert_mock.called)
        self.assertTrue(self.reconcile_mock.called)

    def test_owner_changed_without_inherited_flag_also_skips(self):
        self.chain.views[(self.account.contract_address, 'owner')] = self.heir.wallet
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, self.owner.wallet), [])
        calls = self.deposit_calls()
        relay_policy.validate_batch(calls, self.owner, self.owner.wallet, self.prepared(calls))

    def test_chain_not_yet_mirrored_claim_on_inherited_account_skips(self):
        # Mirror has no pending claim, chain has claimStartedAt but is inherited.
        self.claim.delete()
        self.chain.views[(self.account.contract_address, 'claimStartedAt')] = 1_700_000_000
        self.executed_on_chain()
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, self.owner.wallet), [])
        self.assertIsNone(services.claim_pending_on_own_account(self.owner))

    def test_unreadable_chain_appends_but_never_requires(self):
        self.chain.fail.add('account_view')
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, self.owner.wallet), [self.cancel])
        self.assertEqual(services.claim_pending_on_own_account(self.owner), self.account)
        self.assertIn(self.cancel, services.with_cancel_claim(self.owner, self.deposit_calls()))
        calls = self.deposit_calls()
        relay_policy.validate_batch(calls, self.owner, self.owner.wallet, self.prepared(calls))
        self.assertFalse(self.reconcile_mock.called)

    def test_still_owner_on_chain_still_requires_it(self):
        from cusd_plus.sponsor_7702 import PolicyError
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, self.owner.wallet), [self.cancel])
        calls = self.deposit_calls()
        with self.assertRaises(PolicyError) as raised:
            relay_policy.validate_batch(calls, self.owner, self.owner.wallet, self.prepared(calls))
        self.assertEqual(raised.exception.code, 'claim_cancel_required')
        self.assertFalse(self.reconcile_mock.called)

    def test_generic_requirement_follows_the_chain(self):
        with override_settings(SMART_ACCOUNT_REQUIRE_CANCEL_CLAIM=True):
            self.executed_on_chain()
            relay_policy.require_cancel_claim_generic([], self.owner, self.owner.wallet)
            self.chain.fail.add('account_view')
            relay_policy.require_cancel_claim_generic([], self.owner, self.owner.wallet)


class SubscribeChainTruthTests(SmartAccountTestCase):
    """No own row, factory.accountOf(signer) is set: the clone's owner() and
    inherited() decide."""

    def setUp(self):
        super().setUp()
        self.previous = self.make_user('previous')
        self.heir = self.make_user('heir')
        self.fund(VAULT, self.previous.wallet, 500 * WAD)
        self.clone = '0x' + 'cd' * 20
        self.chain.accounts[self.previous.wallet] = self.clone
        self.chain.views[(self.clone, 'owner')] = self.previous.wallet

    def block(self):
        return offer.subscribe_block(self.previous, personal_context=True, meta=BUILD)

    def prepare(self):
        return services.prepare_subscribe(self.viewer(self.previous), 'annual',
                                          [{'asset_key': 'cusd_plus', 'units': str(200 * WAD)}], True)

    def assert_reopens(self):
        self.assertIsNone(self.block())
        batch = self.prepare()
        new = self.chain.predict_address_at(self.previous.wallet, 1)
        self.assertEqual(batch.calls[0], abi.call(FACTORY, abi.encode_call('createAccount')))
        self.assertEqual(batch.calls[-1]['to'], new)
        self.assertNotIn(self.chain.account_of(self.previous.wallet), [c['to'] for c in batch.calls])

    def assert_refused(self, code):
        self.assertEqual(self.block(), code)
        with self.assertRaises(services.PrepareError) as raised:
            self.prepare()
        self.assertEqual(raised.exception.code, code)
        self.assertFalse(SmartAccountPreparedAction.objects.exists())

    def test_inherited_on_chain_with_no_mirror_row_reopens(self):
        self.chain.views[(self.clone, 'inherited')] = True
        self.chain.views[(self.clone, 'owner')] = self.heir.wallet
        self.assert_reopens()

    def test_owner_changed_on_chain_reopens(self):
        self.chain.views[(self.clone, 'owner')] = self.heir.wallet
        self.assert_reopens()

    def test_mirror_lags_a_claim_on_an_unknown_wallet_row(self):
        # Mirror row for the clone belongs to someone else and is not marked
        # inherited yet; the chain says inherited.
        other = self.make_user('other')
        row = self.make_account(other, index=1)
        self.chain.accounts[self.previous.wallet] = row.contract_address
        self.chain.views[(row.contract_address, 'inherited')] = True
        self.assert_reopens()

    def test_unreadable_owner_fails_closed(self):
        self.chain.fail.add('account_view')
        self.assert_refused('chain_unavailable')

    def test_still_the_signers_clone_subscribes(self):
        self.assertIsNone(self.block())
        batch = self.prepare()
        self.assertEqual(batch.calls[-1]['to'], self.clone)
