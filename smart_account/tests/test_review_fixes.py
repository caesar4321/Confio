"""Review fixes (2026-11-20): reconciler isolation, cancelClaim on personal
batches, buy-rule gates at run time, consumed-action expiry, unknown
residence, expiry returns with the flag off, ClaimExecuted to a closed
account, CONFIO in the sale order, SponsorBscBatch context paths."""
import json
import time
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from cusd_plus import sponsor_7702
from cusd_plus.sponsor_7702 import PolicyError
from smart_account import abi, automation, reconcile, relay_policy, services
from smart_account.models import (
    SmartAccount, SmartAccountBeneficiary, SmartAccountClaim, SmartAccountEvent, SmartAccountPreparedAction,
    SmartAccountRule, SmartAccountRuleRun,
)

from .base import CUSD, FACTORY, SWAP_ROUTER, USDT, VAULT, SmartAccountTestCase, WAD, new_address
from .test_tasks import RelayHarness

CONFIO = '0x' + 'cf' * 20


def _word(value) -> str:
    if isinstance(value, str):
        return value.lower().replace('0x', '').rjust(64, '0')
    return format(int(value), 'x').rjust(64, '0')


def _mint_calls(user_addr, amount=5 * WAD):
    approve = {'to': USDT, 'value': '0', 'data': '0x' + sponsor_7702.SEL_APPROVE + _word(VAULT) + _word(amount)}
    mint = {'to': VAULT, 'value': '0', 'data': '0x' + sponsor_7702.SEL_SUBSCRIBE_AND_MINT
            + _word(amount) + _word(0) + _word(user_addr)}
    return [approve, mint]


class _ClaimPending(SmartAccountTestCase):
    """An owner with an account on which a beneficiary's claim is pending."""

    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.heir = self.make_user('heir')
        self.account = self.make_account(self.owner)
        self.row = SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=90 * 86400, state='active', designated_at=timezone.now(),
            accepted_at=timezone.now())
        self.claim = SmartAccountClaim.objects.create(
            beneficiary_row=self.row, initiated_at=timezone.now(), initiated_tx='0x' + '01' * 32,
            executable_at=timezone.now() + timedelta(days=90))
        self.cancel = abi.call(self.account.contract_address, abi.encode_call('cancelClaim'))


# ── 1. reconciler isolation ─────────────────────────────────────────────

class ReconcilerIsolationTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.heir = self.make_user('heir')
        self.index = 0

    def emit(self, name, args, address, block=None):
        self.index += 1
        return SmartAccountEvent.objects.create(
            address=address.lower(), tx_hash='0x' + format(self.index, 'x').rjust(64, '0'), log_index=self.index,
            name=name, args=args, block_number=block or (1000 + self.index), block_time=timezone.now())

    def _real_account_with_beneficiary(self):
        account = self.make_account(self.owner)
        SmartAccountBeneficiary.objects.create(
            smart_account=account, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=90 * 86400, state='active', designated_at=timezone.now(),
            accepted_at=timezone.now())
        return account

    def test_rowless_account_events_never_block_a_real_accounts_claim(self):
        rogue_owner, rogue = '0x' + '66' * 20, new_address()
        self.emit('AccountCreated', {'owner': rogue_owner, 'account': rogue}, FACTORY)
        for _ in range(600):
            self.emit('Withdrawn', {'token': VAULT, 'to': rogue_owner, 'amount': '1'}, rogue)
        account = self._real_account_with_beneficiary()
        claim_event = self.emit('ClaimInitiated', {'beneficiary': self.heir.wallet, 'executableAt': '1900000000'},
                                account.contract_address)
        out = reconcile.apply_pending()
        self.assertEqual(out['failed'], 0)
        claim_event.refresh_from_db()
        self.assertIsNotNone(claim_event.applied_at)
        self.assertTrue(SmartAccountClaim.objects.filter(beneficiary_row__smart_account=account,
                                                         state='pending').exists())
        self.assertFalse(SmartAccount.all_objects.filter(contract_address=rogue).exists())
        # The rogue account's events stay stored-but-unapplied and are never selected again.
        self.assertEqual(SmartAccountEvent.objects.filter(address=rogue, applied_at__isnull=True).count(), 600)
        self.assertEqual(list(reconcile._pending_events(set(), set())), [])

    def test_one_accounts_failing_event_does_not_hold_back_another_account(self):
        stuck = self.make_account(self.owner)
        # A rule the chain read cannot return (unreadable): raises every time.
        self.emit('RuleCreated', {'id': '99', 'kind': '0'}, stuck.contract_address)
        for _ in range(600):
            self.emit('Withdrawn', {'token': VAULT, 'to': self.owner.wallet, 'amount': '1'}, stuck.contract_address)
        other_owner = self.make_user('other')
        other = self.make_account(other_owner)
        SmartAccountBeneficiary.objects.create(
            smart_account=other, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=90 * 86400, state='active', designated_at=timezone.now(),
            accepted_at=timezone.now())
        event = self.emit('ClaimInitiated', {'beneficiary': self.heir.wallet, 'executableAt': '1900000000'},
                          other.contract_address)
        out = reconcile.apply_pending()
        self.assertEqual(out['failed'], 1)
        event.refresh_from_db()
        self.assertIsNotNone(event.applied_at)
        # Per-account order holds: nothing after the stuck event was applied.
        self.assertEqual(SmartAccountEvent.objects.filter(
            address=stuck.contract_address, applied_at__isnull=False).count(), 0)

    def _log(self, address, name, args, index):
        return {'address': address, 'blockNumber': hex(1500), 'logIndex': hex(index),
                'transactionHash': '0x' + format(index, 'x').rjust(64, '0'), '_decoded': (name, args)}

    def test_scan_stores_logs_only_of_accounts_created_by_a_confio_owner(self):
        rogue, real = new_address(), new_address()
        factory_logs = [
            self._log(FACTORY, 'AccountCreated', {'owner': '0x' + '66' * 20, 'account': rogue}, 1),
            self._log(FACTORY, 'AccountCreated', {'owner': self.owner.wallet, 'account': real}, 2),
        ]
        account_logs = [
            self._log(rogue, 'Withdrawn', {'token': VAULT, 'to': '0x' + '66' * 20, 'amount': '1'}, 3),
            self._log(real, 'Subscribed', {'plan': '2', 'feeUsd': '1', 'paidUntil': '1900000000'}, 4),
        ]
        calls = []

        def get_logs(addresses, _from, _to):
            calls.append(list(addresses))
            # A node would return only the asked addresses; return both to
            # prove _store_logs filters by itself.
            return factory_logs if len(calls) == 1 else account_logs
        with mock.patch('smart_account.chain.finalized_block', return_value=2000), \
                mock.patch('smart_account.chain.get_logs', side_effect=get_logs), \
                mock.patch('smart_account.chain.block_time', return_value=(timezone.now(), '0x' + '0b' * 32)), \
                mock.patch('smart_account.abi.decode_log', side_effect=lambda log, factory: log['_decoded']), \
                override_settings(SMART_ACCOUNT_START_BLOCK=1000):
            reconcile.scan_events()
        self.assertEqual(calls[1], [real])           # the rogue account's logs are never even asked for
        stored = set(SmartAccountEvent.objects.values_list('address', 'name'))
        self.assertIn((real, 'Subscribed'), stored)
        self.assertNotIn((rogue, 'Withdrawn'), stored)


# ── 7. ClaimExecuted to a closed or unknown account ─────────────────────

class ClaimExecutedFallbackTests(_ClaimPending):
    def _emit(self, new_owner):
        return SmartAccountEvent.objects.create(
            address=self.account.contract_address, tx_hash='0x' + 'e1' * 32, log_index=1, name='ClaimExecuted',
            args={'previousOwner': self.owner.wallet, 'newOwner': new_owner}, block_number=1001,
            block_time=timezone.now())

    def test_closed_personal_account_still_receives_the_account(self):
        from users.models import Account
        Account.objects.filter(user=self.heir, account_type='personal').update(deleted_at=timezone.now())
        event = self._emit(self.heir.wallet)
        later = SmartAccountEvent.objects.create(
            address=self.account.contract_address, tx_hash='0x' + 'e2' * 32, log_index=2, name='Withdrawn',
            args={'token': VAULT, 'to': self.heir.wallet, 'amount': '1'}, block_number=1002,
            block_time=timezone.now())
        self.assertEqual(reconcile.apply_pending()['failed'], 0)
        for row in (event, later):
            row.refresh_from_db()
            self.assertIsNotNone(row.applied_at)
        self.account.refresh_from_db()
        self.assertEqual((self.account.owner_user, self.account.status), (self.heir, 'inherited'))
        self.assertTrue(self.ops_alert_mock.called)

    def test_unknown_wallet_is_recorded_alerted_and_never_blocks(self):
        event = self._emit('0x' + '99' * 20)
        self.assertEqual(reconcile.apply_pending()['failed'], 0)
        event.refresh_from_db()
        self.assertIsNotNone(event.applied_at)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.state, 'executed')
        self.assertTrue(self.ops_alert_mock.called)


# ── 2. cancelClaim on personal batches ──────────────────────────────────

class CancelClaimHelperTests(_ClaimPending):
    def test_appended_only_for_the_owners_own_key_while_a_claim_is_pending(self):
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, self.owner.wallet), [self.cancel])
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, '0x' + '42' * 20), [])  # business key
        self.claim.delete()
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, self.owner.wallet), [])
        self.chain.views[(self.account.contract_address, 'claimStartedAt')] = 1_700_000_000
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, self.owner.wallet), [self.cancel])
        self.chain.fail.add('account_view')    # unknown: the protective no-op rides along
        self.assertEqual(relay_policy.pending_cancel_claim_calls(self.owner, self.owner.wallet), [self.cancel])

    def test_claim_alert_carries_the_contract_address(self):
        from smart_account import schema
        alert = schema.Query.resolve_smart_account_claim_alert(None, self.info(self.owner))
        self.assertEqual(alert.contract_address, self.account.contract_address.lower())


class SendWithCancelClaimTests(_ClaimPending):
    """send/bsc_flow.submit_bsc_send: the stored batch with and without the
    trailing cancelClaim passes the byte-exact rebuild; a foreign or a second
    cancelClaim is refused."""

    def setUp(self):
        super().setUp()
        self.recipient = '0x' + '7e' * 20
        self.transfer = {'to': CUSD, 'value': '0',
                         'data': '0x' + sponsor_7702.SEL_TRANSFER + _word(self.recipient) + _word(5 * WAD)}

    def _submit(self, calls):
        from send import bsc_flow
        send_tx = SimpleNamespace(
            id=91, pk=91, sender_user_id=self.owner.pk, sender_business_id=None, status='PENDING',
            recipient_user_id=None, recipient_business_id=None, idempotency_key='', amount=Decimal('5'),
            token_type='CUSD', sender_address=self.owner.wallet, recipient_address=self.recipient,
            bsc_calls_json=json.dumps({'kind': 'send_cusd', 'calls': calls, 'token': CUSD,
                                       'recipient': self.recipient, 'units': str(5 * WAD)}))
        seen = []

        def broadcast(user, addr, calls_, *args, **kwargs):
            seen.append(calls_)
            raise PolicyError('reached_broadcast')
        with mock.patch('send.bsc_flow._send_step_up', return_value=''), \
                mock.patch('send.bsc_flow._send_face_terms', return_value={}), \
                mock.patch('cusd_plus.sponsor_7702.recover_intent_signer', return_value=self.owner.wallet), \
                mock.patch('cusd_plus.sponsor_7702.is_delegated', return_value=True), \
                mock.patch('cusd_plus.sponsor_7702.send_sponsored_batch', side_effect=broadcast):
            out = bsc_flow.submit_bsc_send(self.owner, send_tx, 0, int(time.time()) + 600, '0x' + '00' * 65)
        return out, seen

    def test_send_with_and_without_the_trailing_cancel_claim(self):
        for calls in ([self.transfer], [self.transfer, self.cancel]):
            out, seen = self._submit(calls)
            self.assertEqual(out['error'], 'reached_broadcast', calls)
            self.assertEqual(seen, [calls])       # signed and broadcast with ALL calls

    def test_foreign_or_second_cancel_claim_is_refused(self):
        stranger = self.make_user('stranger')
        foreign = self.make_account(stranger)
        foreign_cancel = abi.call(foreign.contract_address, abi.encode_call('cancelClaim'))
        for calls in ([self.transfer, foreign_cancel], [self.transfer, self.cancel, self.cancel],
                      [self.cancel, self.transfer]):
            out, seen = self._submit(calls)
            self.assertEqual(out['error'], 'claim_cancel_not_allowed')
            self.assertEqual(seen, [])


class ReclaimWithCancelClaimTests(_ClaimPending):
    """A domain flow that rebuilds its calls at submit (invite reclaim):
    the signature decides whether the trailing cancelClaim was signed."""

    def _submit(self, signed_calls):
        from send import invite_bsc_flow
        invite = SimpleNamespace(pk=10 ** 9, inviter_user_id=self.owner.pk, status='pending',
                                 inviter_address=self.owner.wallet, invitation_id='ab' * 32)

        def digest(calls, *args):
            return json.dumps(calls, sort_keys=True).encode()
        expected = json.dumps(signed_calls, sort_keys=True).encode()
        with override_settings(BSC_INVITE_ESCROW_ADDRESS='0x' + 'e5' * 20), \
                mock.patch('send.invite_bsc_flow._escrow', return_value='0x' + 'e5' * 20), \
                mock.patch('cusd_plus.sponsor_7702.intent_digest', side_effect=digest), \
                mock.patch('cusd_plus.sponsor_7702.recover_intent_signer',
                           side_effect=lambda d, s: self.owner.wallet if d == expected else '0x' + '00' * 20), \
                mock.patch('cusd_plus.sponsor_7702.is_delegated', return_value=True):
            return invite_bsc_flow.submit_reclaim(self.owner, invite, 0, int(time.time()) + 600, '0x' + '00' * 65)

    def test_reclaim_with_and_without_the_trailing_cancel_claim(self):
        from send import invite_bsc_flow
        with mock.patch('send.invite_bsc_flow._escrow', return_value='0x' + 'e5' * 20):
            base = invite_bsc_flow.build_reclaim_calls('0x' + 'ab' * 32)
        # Past the signature check the row CAS fails (no such invite row): the
        # error proves the signature matched.
        for calls in (base, base + [self.cancel]):
            self.assertEqual(self._submit(calls)['error'], 'invite_not_reclaimable')
        stranger = self.make_user('stranger')
        foreign = abi.call(self.make_account(stranger).contract_address, abi.encode_call('cancelClaim'))
        self.assertEqual(self._submit(base + [foreign])['error'], 'bad_intent_signature')
        self.assertEqual(self._submit(base + [self.cancel, self.cancel])['error'], 'bad_intent_signature')


@override_settings(CUSD_PLUS_7702_ENABLED=True, BSC_CHAIN_ID=56)
class SponsorBscBatchTests(_ClaimPending):
    """The generic rail (cusd_plus.schema.SponsorBscBatch.mutate)."""

    def setUp(self):
        super().setUp()
        self.broadcasts = []

        def broadcast(user, addr, calls, *args, **kwargs):
            self.broadcasts.append({'addr': addr, 'calls': calls, 'kind': args[4], 'kwargs': kwargs})
            return '0x' + 'ab' * 32, SimpleNamespace(executed_early=None)
        self.face = mock.patch('cusd_plus.face_step_up.claim_external_outflow', return_value='')
        patches = [
            mock.patch('cusd_plus.sponsor_7702.delegate_address', return_value='0x' + 'de' * 20),
            mock.patch('cusd_plus.sponsor_7702.is_delegated', return_value=True),
            mock.patch('cusd_plus.sponsor_7702.send_sponsored_batch', side_effect=broadcast),
            mock.patch('cusd_plus.eligibility.check_savings_mint_eligibility', return_value=True),
            mock.patch('cusd_plus.vault.is_safe_mint_amount', return_value=True),
            mock.patch('security.geo.review_cap_exceeded_wei', return_value=False),
            mock.patch('cusd_plus.tasks.record_savings_mint'),
            mock.patch('payment_accounts.infinia_fee_collection.mint_policy_calls',
                       side_effect=lambda calls, *a, **k: calls),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.face_mock = self.face.start()
        self.addCleanup(self.face.stop)

    def mutate(self, calls, user=None, info=None, request_id=None, signer=None):
        from cusd_plus.schema import SponsorBscBatch
        user = user or self.owner
        gql = [mock.Mock(to=c['to'], value_wei=c['value'], data=c['data']) for c in calls]
        with mock.patch('cusd_plus.sponsor_7702.recover_intent_signer', return_value=signer or user.wallet):
            return SponsorBscBatch.mutate(None, info or self.info(user), gql, '0', str(int(time.time()) + 600),
                                          '0x' + '00' * 65, None, request_id)

    def test_savings_mint_with_and_without_the_trailing_cancel_claim(self):
        for calls in (_mint_calls(self.owner.wallet), _mint_calls(self.owner.wallet) + [self.cancel]):
            res = self.mutate(calls)
            self.assertTrue(res.success, res.error)
            self.assertEqual(self.broadcasts[-1]['calls'], calls)
            self.assertEqual(self.broadcasts[-1]['kind'], 'subscribe')   # intent kind unchanged

    def test_foreign_or_second_cancel_claim_is_refused(self):
        stranger = self.make_user('stranger')
        foreign = abi.call(self.make_account(stranger).contract_address, abi.encode_call('cancelClaim'))
        for calls in (_mint_calls(self.owner.wallet) + [foreign],
                      _mint_calls(self.owner.wallet) + [self.cancel, self.cancel]):
            res = self.mutate(calls)
            self.assertFalse(res.success)
            # A specific code (never simulation_reverted): the app drops only the cancel.
            self.assertEqual(res.error, 'claim_cancel_not_allowed')
        self.assertEqual(self.broadcasts, [])

    def _arm(self):
        from cusd_plus import fee_referral
        arm = fee_referral.ReferralArm(referrer_user_id=self.heir.pk, referrer_address='0x' + '3e' * 20,
                                       share_bps=5000)
        return (fee_referral.arm_call(arm),
                [mock.patch('cusd_plus.fee_referral.eligible_arm', return_value=arm),
                 mock.patch('cusd_plus.fee_referral.onchain_ready', return_value=True)])

    def test_armed_four_call_batch_with_trailing_cancel_claim_is_six_calls_and_keeps_the_arm(self):
        amount = 5 * WAD
        four = [
            {'to': USDT, 'value': '0', 'data': '0x' + sponsor_7702.SEL_APPROVE + _word(VAULT) + _word(amount)},
            {'to': USDT, 'value': '0', 'data': '0x' + sponsor_7702.SEL_APPROVE + _word(CUSD) + _word(amount)},
            {'to': CUSD, 'value': '0', 'data': '0x' + sponsor_7702.SEL_APPROVE + _word(VAULT) + _word(amount)},
            _mint_calls(self.owner.wallet, amount)[1],
        ]
        arm, patches = self._arm()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        for calls in ([arm] + four, [arm] + four + [self.cancel]):
            res = self.mutate(calls)
            self.assertTrue(res.success, (len(calls), res.error))
            self.assertEqual(self.broadcasts[-1]['calls'], calls)       # arm first, cancel last
            self.assertEqual(self.broadcasts[-1]['kind'], 'subscribe')
        # Seven calls (a second cancel) are over the cap; an arm with a foreign
        # cancel gets the specific refusal, not a revert.
        self.assertEqual(self.mutate([arm] + four + [self.cancel, self.cancel]).error, 'bad_batch_size')
        stranger = self.make_user('stranger')
        foreign = abi.call(self.make_account(stranger).contract_address, abi.encode_call('cancelClaim'))
        self.assertEqual(self.mutate([arm] + _mint_calls(self.owner.wallet) + [foreign]).error,
                         'claim_cancel_not_allowed')
        # Signed by a key that does not own the account (business context): refused the same way.
        business = '0x' + '42' * 20
        with mock.patch('cusd_plus.schema._active_bsc_address', return_value=business):
            self.assertEqual(self.mutate(_mint_calls(business) + [self.cancel], signer=business).error,
                             'claim_cancel_not_allowed')

    def test_smart_context_refuses_a_personal_wallet_batch(self):
        res = self.mutate(_mint_calls(self.owner.wallet), info=self.info(self.owner, 'smart', 0))
        self.assertEqual(res.error, 'smart_context_not_supported')
        self.assertEqual(self.broadcasts, [])

    def _business_ctx(self, permitted):
        def ctx(info, required_permission=None, allow_smart=False):
            base = {'account_type': 'business', 'account_index': 0, 'business_id': '5'}
            if required_permission == 'send_funds' and not permitted:
                return None       # an employee without the permission
            return base
        return mock.patch('users.jwt_context.get_jwt_business_context_with_validation', side_effect=ctx)

    def test_prepared_account_batch_from_business_and_employee_contexts(self):
        for permitted in (True, False):      # business owner, employee without send_funds
            batch = services.prepare_claim_cancel(self.viewer(self.owner))
            with self._business_ctx(permitted):
                res = self.mutate(batch.calls, request_id=batch.request_id + '_a0')
            self.assertTrue(res.success, (permitted, res.error))
            sent = self.broadcasts[-1]
            self.assertEqual(sent['addr'], self.owner.wallet)                 # the personal signer
            self.assertEqual(sent['kind'], 'smart_claim')
            self.face_mock.assert_not_called()                                 # Face skipped
        # Without a prepared action the same employee is refused before anything.
        with self._business_ctx(False):
            self.assertEqual(self.mutate(_mint_calls(self.owner.wallet)).error, 'permission_denied')

    def test_consumed_action_replay_returns_the_recorded_transaction(self):
        from blockchain.models import SponsoredBatch
        batch = services.prepare_claim_cancel(self.viewer(self.owner))
        request_id = batch.request_id + '_a0'
        recorded = SponsoredBatch.objects.create(
            user=self.owner, user_bsc_address=self.owner.wallet, kind='smart_claim', num_calls=len(batch.calls),
            calls_json=json.dumps(batch.calls), tx_hash='0x' + 'cd' * 32, gas_limit=1, max_fee_wei='1',
            status='sent', client_request_id=request_id)
        relay_policy.consume(SmartAccountPreparedAction.objects.get(request_id=batch.request_id), recorded)
        SmartAccountPreparedAction.objects.filter(request_id=batch.request_id).update(
            expires_at=timezone.now() - timedelta(minutes=1))
        with mock.patch('cusd_plus.sponsor_7702.batch_matches_calls', return_value=True), \
                mock.patch('cusd_plus.sponsor_7702.batch_execution_hint', return_value=None):
            res = self.mutate(batch.calls, request_id=request_id)
        self.assertEqual((res.success, res.tx_hash), (True, recorded.tx_hash))
        self.assertEqual(self.broadcasts, [])
        # A fresh attempt id is not a replay: refused.
        self.assertEqual(self.mutate(batch.calls, request_id=batch.request_id + '_a1').error,
                         'smart_action_consumed')


# ── 4. consumed + failed + expired ──────────────────────────────────────

class ConsumedExpiryTests(SmartAccountTestCase):
    def test_retry_after_a_failed_batch_needs_an_unexpired_action(self):
        from blockchain.models import SponsoredBatch
        owner = self.make_user('owner')
        account = self.make_account(owner)
        batch = services.prepare_cancel(self.viewer(owner))
        recorded = SponsoredBatch.objects.create(
            user=owner, user_bsc_address=owner.wallet, kind='smart_cancel', num_calls=1, calls_json='[]',
            tx_hash='0x' + 'ab' * 32, gas_limit=1, max_fee_wei='1', status='reverted',
            client_request_id=batch.request_id + '_a0')
        action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
        relay_policy.consume(action, recorded)
        relay_policy.validate_batch(batch.calls, owner, owner.wallet, batch.request_id + '_a1')
        SmartAccountPreparedAction.objects.filter(pk=action.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(PolicyError) as raised:
            relay_policy.validate_batch(batch.calls, owner, owner.wallet, batch.request_id + '_a1')
        self.assertEqual(raised.exception.code, 'smart_action_expired')
        # The exact replay of the recorded request still reaches the replay lookup.
        relay_policy.validate_batch(batch.calls, owner, owner.wallet, batch.request_id + '_a0')
        self.assertIsNotNone(account)


# ── 5. unknown residence ────────────────────────────────────────────────

class ResidenceUnknownTests(SmartAccountTestCase):
    def test_unknown_country_is_not_eligible(self):
        heir = self.make_user('heir')
        with mock.patch('security.geo.country_of', return_value=''), \
                mock.patch('security.geo.residence_country_for', return_value=None):
            self.assertEqual(self.real_residence_check(heir), 'unknown')
        owner = self.make_user('owner')
        self.residence[heir.pk] = 'unknown'
        with self.assertRaises(services.PrepareError) as raised:
            services.beneficiary_checks(owner, heir)
        self.assertEqual(raised.exception.code, 'beneficiary_residence_unknown')


# ── 3, 6, 8. automation ─────────────────────────────────────────────────

class BuyRuleGateTests(RelayHarness):
    def setUp(self):
        super().setUp()
        SmartAccount.objects.update(paid_until=timezone.now() + timedelta(days=20))
        self.account.refresh_from_db()
        self.slot = timezone.now().replace(microsecond=0) - timedelta(minutes=3)
        self.rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=4, state='onchain', kind='buy', token_in=VAULT,
            token_out='0x' + '71' * 20, amount=Decimal('25.00'), frequency='weekly',
            next_run_at=self.slot, scheduled_for=self.slot, active=True)
        self.chain.views[(self.address, 'status')] = 1
        self.chain.views[(self.address, 'billingStatus')] = 0
        self.chain.rules[(self.address, 4)] = {'active': True, 'next_run_at': int(self.slot.timestamp())}
        self.fund(VAULT, self.address, 500 * WAD)

    def _run(self):
        with mock.patch('smart_account.notifications.rule_run') as told:
            out = automation.run_rules()
        return out, told

    def test_crypto_buy_skipped_and_told_when_buying_is_no_longer_allowed(self):
        with mock.patch('cusd_plus.crypto_catalog.by_address', return_value=mock.Mock()), \
                mock.patch('smart_account.assets.is_feed_token', return_value=True), \
                mock.patch('cusd_plus.crypto_risk.trading_ready', return_value=True), \
                mock.patch('cusd_plus.crypto_risk.buy_enabled', return_value=False) as gate, \
                mock.patch('smart_account.quotes.crypto_buy_call') as quote:
            out, told = self._run()
        gate.assert_called_once_with(self.owner, {})
        quote.assert_not_called()
        self.assertEqual((out['skipped'], self.signed), (1, []))
        told.assert_called_once()
        run = SmartAccountRuleRun.objects.get()
        self.assertEqual((run.status, run.error), ('skipped', 'trade_not_available'))

    @override_settings(CUSD_PLUS_STOCK_TRADING_ENABLED=True)
    def test_stock_buy_reruns_the_country_overlay_without_request_meta(self):
        with mock.patch('cusd_plus.crypto_catalog.by_address', return_value=None), \
                mock.patch('smart_account.assets.stock_by_address', return_value=('AAPLon', {})), \
                mock.patch('cusd_plus.eligibility.check_stock_buy_eligibility', return_value=False) as gate, \
                mock.patch('smart_account.quotes.stock_buy_call') as quote:
            out, told = self._run()
        gate.assert_called_once_with(self.owner, {})
        quote.assert_not_called()
        self.assertEqual((out['skipped'], self.signed), (1, []))
        told.assert_called_once()


class ReturnWithFlagOffTests(RelayHarness):
    @override_settings(SMART_ACCOUNT_ENABLED=False)
    def test_expired_assets_are_returned_with_the_feature_flag_off(self):
        SmartAccount.objects.update(cancel_requested_at=timezone.now() - timedelta(days=40))
        self.chain.views[(self.address, 'status')] = 3
        self.fund(CUSD, self.address, 2 * WAD)
        out = automation.return_expired()
        self.assertEqual(out['sent'], 1)
        self.assertEqual(self.signed[0]['data'], abi.encode_call('returnAsset', CUSD))
        # Nothing else the relayer does runs with the flag off.
        with self.assertRaises(Exception):
            from smart_account import relayer
            relayer.send_relayer_call(self.account, abi.encode_call('collectFee'), 'smart_collect_fee', 'x')
        with override_settings(SMART_ACCOUNT_FACTORY_ADDRESS=''):
            self.assertEqual(automation.return_expired(), {'skipped': 'disabled'})


@override_settings(BSC_CONFIO_TOKEN_ADDRESS=CONFIO)
class ConfioSaleOrderTests(RelayHarness):
    VENUE, REF = SWAP_ROUTER, '0x' + 'fe' * 20

    def setUp(self):
        super().setUp()
        self.fund(CONFIO, self.address, 1000 * WAD)
        self.fund(VAULT, self.address, 3 * WAD)

    def latch(self):
        self.chain.views[(self.address, 'confioSaleVenue')] = self.VENUE
        self.chain.views[(self.address, 'confioSalePriceRef')] = self.REF

    def test_confio_is_not_a_fee_source_until_latched_then_joins_by_value(self):
        self.assertEqual(automation.sale_candidates(self.account), [])
        self.latch()
        with mock.patch('smart_account.chain.feed_price_usd', return_value=Decimal('0.50')) as feed:
            candidates = automation.sale_candidates(self.account)
        feed.assert_called_once_with(self.REF, mock.ANY)
        self.assertEqual([(a.key, a.value_usd) for a in candidates], [('confio', Decimal('500'))])
        self.account.refresh_from_db()
        self.assertTrue(self.account.confio_sale_latched)
        # A stale reference leaves it unpriced: not planned (the contract would refuse it).
        with mock.patch('smart_account.chain.feed_price_usd', return_value=None):
            self.assertEqual(automation.sale_candidates(self.account), [])

    def test_largest_first_order_puts_confio_ahead_and_its_leg_uses_the_latched_venue(self):
        self.latch()
        built = {'call': {'data': '0x' + 'ab' * 8}, 'token': CONFIO, 'max_in': 40 * WAD,
                 'expected_dollars_wei': 16 * WAD}
        with mock.patch('smart_account.chain.feed_price_usd', return_value=Decimal('0.50')), \
                mock.patch('cusd_plus.crypto_policy.live_fee_bps', return_value=90), \
                mock.patch('smart_account.quotes.confio_sell_call', return_value=built) as confio_quote, \
                mock.patch('smart_account.quotes.crypto_sell_call') as crypto_quote:
            legs = automation.plan_forced_sale(self.account, 15 * WAD, abi.DOLLAR_PLUS)
        confio_quote.assert_called_once()
        crypto_quote.assert_not_called()
        self.assertEqual([(leg['asset_key'], leg['venue']) for leg in legs], [('confio', self.VENUE)])
        self.assertIn('confio', abi.RELAY_GAS_SALE_LEG)
