"""Relay policy for account batches (spec 7.4, 10.3)."""
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from cusd_plus import sponsor_7702
from cusd_plus.sponsor_7702 import PolicyError
from smart_account import abi, relay_policy, services
from smart_account.models import (
    SmartAccountBeneficiary, SmartAccountClaim, SmartAccountPreparedAction,
)

from .base import CUSD, USDT, VAULT, SmartAccountTestCase, WAD


def _user_word(addr):
    return addr.lower().replace('0x', '').rjust(64, '0')


class PreparedBatchPolicyTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.fund(VAULT, self.owner.wallet, 500 * WAD)
        self.batch = services.prepare_deposit(
            self.viewer(self.owner), [{'asset_key': 'cusd_plus', 'units': str(100 * WAD)}])

    def _validate(self, calls, user=None, request_id=None, addr=None):
        user = user or self.owner
        return sponsor_7702.validate_policy(calls, user, addr or user.wallet, request_id=request_id)

    def _code(self, *args, **kwargs):
        with self.assertRaises(PolicyError) as raised:
            self._validate(*args, **kwargs)
        return raised.exception.code

    def test_prepared_batch_is_accepted_by_request_id_with_the_attempt_suffix(self):
        self._validate(self.batch.calls, request_id=self.batch.request_id + '_a0')
        self._validate(self.batch.calls, request_id=self.batch.request_id + '_a1')
        self._validate(self.batch.calls)  # and by its bytes alone

    def test_mismatched_batch_is_refused(self):
        other = [abi.transfer_call(VAULT, self.account.contract_address, 101 * WAD)]
        self.assertEqual(self._code(other, request_id=self.batch.request_id + '_a0'), 'smart_action_mismatch')
        self.assertEqual(self._code(other), 'smart_action_not_prepared')

    def test_extra_call_is_refused(self):
        extra = self.batch.calls + [abi.call(self.account.contract_address, abi.encode_call('cancelSubscription'))]
        self.assertEqual(self._code(extra, request_id=self.batch.request_id), 'smart_action_mismatch')

    def test_expired_action_is_refused(self):
        SmartAccountPreparedAction.objects.filter(request_id=self.batch.request_id).update(
            expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self._code(self.batch.calls, request_id=self.batch.request_id), 'smart_action_expired')

    def test_consumed_action_is_refused_unless_its_batch_did_nothing(self):
        from blockchain.models import SponsoredBatch
        batch = SponsoredBatch.objects.create(
            user=self.owner, user_bsc_address=self.owner.wallet, kind='smart_deposit', num_calls=1,
            calls_json='[]', tx_hash='0x' + 'ab' * 32, gas_limit=1, max_fee_wei='1', status='sent',
            client_request_id=self.batch.request_id + '_a0')
        action = SmartAccountPreparedAction.objects.get(request_id=self.batch.request_id)
        relay_policy.consume(action, batch)
        # A fresh attempt while the first is on the wire: refused.
        self.assertEqual(self._code(self.batch.calls, request_id=self.batch.request_id + '_a1'),
                         'smart_action_consumed')
        # The exact replay of the recorded request is let through to the replay lookup.
        self._validate(self.batch.calls, request_id=self.batch.request_id + '_a0')
        # A mined no-op needs a retry with a fresh delegate nonce.
        SponsoredBatch.objects.filter(pk=batch.pk).update(status='noop_failed')
        self._validate(self.batch.calls, request_id=self.batch.request_id + '_a1')

    def test_another_users_prepared_action_is_not_mine(self):
        stranger = self.make_user('stranger')
        self.assertEqual(self._code(self.batch.calls, user=stranger, request_id=self.batch.request_id),
                         'smart_action_not_prepared')

    def test_batch_signed_by_another_key_is_refused(self):
        self.assertEqual(self._code(self.batch.calls, request_id=self.batch.request_id, addr='0x' + '99' * 20),
                         'smart_action_not_prepared')

    def test_call_to_an_account_not_registered_to_the_signer_is_refused(self):
        other = self.make_user('other')
        foreign = self.make_account(other)
        calls = [abi.call(foreign.contract_address, abi.encode_call('withdraw', VAULT, 1))]
        self.assertEqual(self._code(calls), 'smart_action_not_prepared')
        # Even with a stored row naming it (a wrong row must not widen anything).
        SmartAccountPreparedAction.objects.create(
            request_id='sa-' + 'f' * 32, user=self.owner, signer_address=self.owner.wallet,
            target_address=foreign.contract_address, kind='smart_withdraw', calls=calls,
            calls_hash=services.calls_hash(calls), expires_at=timezone.now() + timedelta(minutes=5))
        self.assertEqual(self._code(calls, request_id='sa-' + 'f' * 32), 'smart_account_not_registered')

    def test_deposit_to_someone_elses_account_is_refused(self):
        other = self.make_user('other')
        foreign = self.make_account(other)
        calls = [abi.transfer_call(VAULT, foreign.contract_address, WAD)]
        self.assertEqual(self._code(calls), 'smart_action_not_prepared')
        SmartAccountPreparedAction.objects.create(
            request_id='sa-' + 'e' * 32, user=self.owner, signer_address=self.owner.wallet,
            target_address=self.account.contract_address, kind='smart_deposit', calls=calls,
            calls_hash=services.calls_hash(calls), expires_at=timezone.now() + timedelta(minutes=5))
        self.assertEqual(self._code(calls, request_id='sa-' + 'e' * 32), 'deposit_recipient_not_allowed')

    def test_selector_outside_the_kinds_allowlist_is_refused(self):
        calls = [abi.call(self.account.contract_address, abi.encode_call('removeBeneficiary'))]
        SmartAccountPreparedAction.objects.create(
            request_id='sa-' + 'd' * 32, user=self.owner, signer_address=self.owner.wallet,
            target_address=self.account.contract_address, kind='smart_withdraw', calls=calls,
            calls_hash=services.calls_hash(calls), expires_at=timezone.now() + timedelta(minutes=5))
        self.assertEqual(self._code(calls, request_id='sa-' + 'd' * 32), 'selector_not_allowed')

    def test_unprepared_designation_is_never_relayed(self):
        calls = [abi.call(self.account.contract_address,
                          abi.encode_call('setBeneficiary', '0x' + '77' * 20, 90 * 86400))]
        self.assertEqual(self._code(calls), 'smart_action_not_prepared')

    def test_value_is_refused(self):
        calls = [dict(self.batch.calls[0], value='1')]
        self.assertEqual(self._code(calls, request_id=self.batch.request_id), 'smart_action_mismatch')

    def test_kind_comes_from_the_prepared_action(self):
        action = relay_policy.validate_batch(self.batch.calls, self.owner, self.owner.wallet, self.batch.request_id)
        self.assertEqual(action.kind, 'smart_deposit')
        self.assertIn(action.kind, abi.BATCH_KINDS_NOT_OUTGOING)


class CancelClaimTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.heir = self.make_user('heir')
        self.account = self.make_account(self.owner)
        self.fund(VAULT, self.owner.wallet, 500 * WAD)
        row = SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=90 * 86400, state='active', designated_at=timezone.now(),
            accepted_at=timezone.now())
        self.claim = SmartAccountClaim.objects.create(
            beneficiary_row=row, initiated_at=timezone.now(), initiated_tx='0x' + '01' * 32,
            executable_at=timezone.now() + timedelta(days=90))
        self.cancel = abi.call(self.account.contract_address, abi.encode_call('cancelClaim'))

    def test_every_prepared_batch_carries_cancel_claim_while_a_claim_is_pending(self):
        viewer = self.viewer(self.owner)
        for batch in (
                services.prepare_deposit(viewer, [{'asset_key': 'cusd_plus', 'units': '5'}]),
                services.prepare_cancel(viewer),
                services.prepare_plan_change(viewer, 'monthly'),
                services.prepare_claim_cancel(viewer)):
            self.assertEqual(batch.calls.count(self.cancel), 1, batch.kind)
            sponsor_7702.validate_policy(batch.calls, self.owner, self.owner.wallet, request_id=batch.request_id)

    def test_policy_refuses_an_owner_batch_without_it(self):
        from smart_account.models import SmartAccountPreparedAction
        calls = [abi.transfer_call(VAULT, self.account.contract_address, 5)]
        SmartAccountPreparedAction.objects.create(
            request_id='sa-' + 'c' * 32, user=self.owner, signer_address=self.owner.wallet,
            target_address=self.account.contract_address, kind='smart_deposit', calls=calls,
            calls_hash=services.calls_hash(calls), expires_at=timezone.now() + timedelta(minutes=5))
        with self.assertRaises(PolicyError) as raised:
            sponsor_7702.validate_policy(calls, self.owner, self.owner.wallet, request_id='sa-' + 'c' * 32)
        self.assertEqual(raised.exception.code, 'claim_cancel_required')

    def test_not_appended_once_the_claim_is_gone(self):
        self.claim.state = 'cancelled'
        self.claim.save()
        batch = services.prepare_cancel(self.viewer(self.owner))
        self.assertNotIn(self.cancel, batch.calls)

    def test_chain_says_pending_before_the_mirror_does(self):
        self.claim.delete()
        self.chain.views[(self.account.contract_address, 'claimStartedAt')] = 1_700_000_000
        batch = services.prepare_cancel(self.viewer(self.owner))
        self.assertIn(self.cancel, batch.calls)

    def test_unreadable_chain_fails_the_prepare(self):
        self.claim.delete()
        self.chain.fail.add('account_view')
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_cancel(self.viewer(self.owner))
        self.assertEqual(raised.exception.code, 'chain_unavailable')

    def test_personal_wallet_batch_may_end_with_cancel_claim(self):
        mint = {'to': VAULT, 'value': '0', 'data': '0x' + sponsor_7702.SEL_SUBSCRIBE_AND_MINT
                + format(5 * WAD, 'x').rjust(64, '0') + '0' * 64 + _user_word(self.owner.wallet)}
        approve = {'to': USDT, 'value': '0', 'data': '0x' + sponsor_7702.SEL_APPROVE
                   + _user_word(VAULT) + format(5 * WAD, 'x').rjust(64, '0')}
        sponsor_7702.validate_policy([approve, mint, self.cancel], self.owner, self.owner.wallet)
        self.assertEqual(sponsor_7702.classify_calls_kind([approve, mint, self.cancel]), 'subscribe')
        # ... but only on the signer's OWN account, and only as the last call.
        stranger = self.make_user('stranger')
        with self.assertRaises(PolicyError):
            sponsor_7702.validate_policy([approve, mint, self.cancel], stranger, stranger.wallet)
        with self.assertRaises(PolicyError):
            sponsor_7702.validate_policy([self.cancel, approve, mint], self.owner, self.owner.wallet)

    def test_generic_batches_are_not_required_to_carry_it_by_default(self):
        mint = {'to': VAULT, 'value': '0', 'data': '0x' + sponsor_7702.SEL_SUBSCRIBE_AND_MINT
                + format(5 * WAD, 'x').rjust(64, '0') + '0' * 64 + _user_word(self.owner.wallet)}
        sponsor_7702.validate_policy([mint], self.owner, self.owner.wallet)
        with override_settings(SMART_ACCOUNT_REQUIRE_CANCEL_CLAIM=True):
            with self.assertRaises(PolicyError) as raised:
                sponsor_7702.validate_policy([mint], self.owner, self.owner.wallet)
            self.assertEqual(raised.exception.code, 'claim_cancel_required')
            sponsor_7702.validate_policy([mint, self.cancel], self.owner, self.owner.wallet)


class ExistingKindsStillValidateTests(SmartAccountTestCase):
    """The new branch must not change what the existing branches accept."""

    def setUp(self):
        super().setUp()
        self.user = self.make_user('plain')
        self.word = _user_word(self.user.wallet)

    def _call(self, to, selector, *words):
        return {'to': to, 'value': '0', 'data': '0x' + selector + ''.join(words)}

    def test_savings_kinds(self):
        amount = format(5 * WAD, 'x').rjust(64, '0')
        zero = '0' * 64
        cases = {
            'subscribe': [self._call(USDT, sponsor_7702.SEL_APPROVE, _user_word(VAULT), amount),
                          self._call(VAULT, sponsor_7702.SEL_SUBSCRIBE_AND_MINT, amount, zero, self.word)],
            'redeem': [self._call(VAULT, sponsor_7702.SEL_REDEEM_TO_USDT, amount, zero, self.word)],
            'wrap_cusd': [self._call(CUSD, sponsor_7702.SEL_APPROVE, _user_word(VAULT), amount),
                          self._call(VAULT, sponsor_7702.SEL_WRAP_CUSD, amount, zero, self.word)],
            'unwrap_to_cusd': [self._call(VAULT, sponsor_7702.SEL_UNWRAP_TO_CUSD, amount, zero, self.word)],
            'mint_cusd': [self._call(USDT, sponsor_7702.SEL_APPROVE, _user_word(CUSD), amount),
                          self._call(CUSD, sponsor_7702.SEL_CUSD_MINT, amount, zero, self.word)],
        }
        for kind, calls in cases.items():
            sponsor_7702.validate_policy(calls, self.user, self.user.wallet)
            self.assertEqual(sponsor_7702.classify_calls_kind(calls), kind)

    def test_existing_refusals_are_unchanged(self):
        amount = format(5 * WAD, 'x').rjust(64, '0')
        stranger = _user_word('0x' + '66' * 20)
        with self.assertRaises(PolicyError) as raised:
            sponsor_7702.validate_policy(
                [self._call(VAULT, sponsor_7702.SEL_SUBSCRIBE_AND_MINT, amount, '0' * 64, stranger)],
                self.user, self.user.wallet)
        self.assertEqual(raised.exception.code, 'mint_recipient_not_allowed')
        with self.assertRaises(PolicyError) as raised:
            sponsor_7702.validate_policy([self._call('0x' + '12' * 20, 'deadbeef')], self.user, self.user.wallet)
        self.assertEqual(raised.exception.code, 'destination_not_allowed')

    def test_gas_budget_knows_the_account_selectors(self):
        account = '0x' + '31' * 20
        calls = [abi.call(account, abi.encode_call('subscribe', 2, 1))]
        with override_settings(CUSD_PLUS_7702_GAS_LIMIT=5_000_000):
            self.assertGreater(sponsor_7702.gas_budget(calls, 0), 300_000)

    def test_trade_is_fee_bearing_for_the_referral_arm(self):
        from cusd_plus import fee_referral
        account = '0x' + '31' * 20
        trade = abi.call(account, abi.encode_call('trade', VAULT, b'\x00', VAULT, CUSD, 1, 1))
        self.assertTrue(fee_referral.has_fee_bearing_call([trade]))


class TradePolicyTests(SmartAccountTestCase):
    def test_trade_arguments_must_be_what_the_wrapped_router_call_implies(self):
        owner = self.make_user('owner')
        account = self.make_account(owner)
        params = {'kind': 'crypto_buy', 'venue': '0x' + '52' * 20, 'token_in': VAULT,
                  'token_out': '0x' + '71' * 20, 'max_in': 100, 'min_out': 9, 'action': {'dollar': 0}}
        with mock.patch('smart_account.services.trade_parameters', return_value=params), \
                mock.patch('smart_account.services.trade_gate', return_value=None):
            batch = services.prepare_trade(self.viewer(owner), 'crypto', '0x' + 'ab' * 40)
            sponsor_7702.validate_policy(batch.calls, owner, owner.wallet, request_id=batch.request_id)
        # The live requote at submit time now implies a tighter floor: refused.
        tighter = dict(params, min_out=10)
        with mock.patch('smart_account.services.trade_parameters', return_value=tighter):
            with self.assertRaises(PolicyError) as raised:
                sponsor_7702.validate_policy(batch.calls, owner, owner.wallet, request_id=batch.request_id)
        self.assertEqual(raised.exception.code, 'bad_smart_trade')
        # A router call the existing decoders refuse is refused here too.
        with mock.patch('smart_account.services.trade_parameters', side_effect=PolicyError('route_not_allowed')):
            with self.assertRaises(PolicyError) as raised:
                sponsor_7702.validate_policy(batch.calls, owner, owner.wallet, request_id=batch.request_id)
        self.assertEqual(raised.exception.code, 'route_not_allowed')
