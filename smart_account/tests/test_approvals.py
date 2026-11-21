"""Factory approvals for designations and acceptances (audit fix to
decision 26), the relayer allowlist, and the app's submission path for
prepared batches (request id suffix, intent id, fee-referral arm)."""
import time
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from cusd_plus import sponsor_7702
from cusd_plus.sponsor_7702 import PolicyError
from smart_account import abi, relay_policy, relayer, services
from smart_account.models import (
    SmartAccountBeneficiary, SmartAccountPreparedAction, SmartAccountRelayTx,
)

from .base import FACTORY, VAULT, WAD
from .test_tasks import RelayHarness


class ApprovalTests(RelayHarness):
    mock_approvals = False

    def setUp(self):
        super().setUp()
        self.heir = self.make_user('heir')
        self.approved = {}          # (kind, account, beneficiary[, window]) -> expiry
        self.receipt_status = '0x1'

        def designation_until(account, beneficiary, window):
            return self.approved.get(('d', account.lower(), beneficiary.lower(), int(window)), 0)

        def acceptance_until(account, beneficiary):
            return self.approved.get(('a', account.lower(), beneficiary.lower()), 0)

        def receipt(tx_hash):
            if self.receipt_status is None:
                return None
            # The factory records the approval when its transaction mines.
            tx = self.signed[-1]
            name, args = abi.decode_call(tx['data'])
            if self.receipt_status == '0x1':
                expiry = int(time.time()) + 3600
                if name == 'approveDesignation':
                    self.approved[('d', args[0].lower(), args[1].lower(), int(args[2]))] = expiry
                else:
                    self.approved[('a', args[0].lower(), args[1].lower())] = expiry
            return {'status': self.receipt_status, 'blockNumber': '0x1', 'blockHash': '0x' + '00' * 32}

        for p in (mock.patch('smart_account.chain.designation_approved_until', side_effect=designation_until),
                  mock.patch('smart_account.chain.acceptance_approved_until', side_effect=acceptance_until),
                  mock.patch('smart_account.chain.receipt', side_effect=receipt),
                  mock.patch('smart_account.approvals.time.sleep')):
            p.start()
            self.addCleanup(p.stop)

    def _designate(self, **kwargs):
        args = dict(beneficiary_handle='heir', window_days=180, disclosure_accepted=True)
        args.update(kwargs)
        return services.prepare_designation(self.viewer(self.owner), **args)

    def _code(self, fn, *args, **kwargs):
        with self.assertRaises(services.PrepareError) as raised:
            fn(*args, **kwargs)
        return raised.exception.code

    def test_designation_is_approved_on_the_factory_before_the_batch_is_returned(self):
        batch = self._designate()
        self.assertEqual(len(self.signed), 1)
        tx = self.signed[0]
        self.assertEqual(tx['to'].lower(), FACTORY)
        name, args = abi.decode_call(tx['data'])
        self.assertEqual((name, args[0].lower(), args[1].lower(), args[2]),
                         ('approveDesignation', self.address, self.heir.wallet, 180 * 86400))
        row = SmartAccountRelayTx.objects.get()
        self.assertEqual((row.kind, row.smart_account_id), ('smart_designation_approval', self.account.pk))
        # The batch the owner signs is the designation itself, unchanged.
        name, args = abi.decode_call(batch.calls[0]['data'])
        self.assertEqual((name, args[0].lower(), args[1]), ('setBeneficiary', self.heir.wallet, 180 * 86400))
        self.assertEqual(len(batch.calls), 1)

    def test_a_failed_check_sends_no_approval(self):
        self.unverified.add(self.heir.pk)
        self.assertEqual(self._code(self._designate), 'beneficiary_unverified')
        self.unverified.clear()
        self.assertEqual(self._code(self._designate, disclosure_accepted=False), 'disclosure_required')
        self.chain.inheritance = False
        self.assertEqual(self._code(self._designate), 'beneficiary_disabled')
        self.assertEqual((self.signed, SmartAccountRelayTx.objects.count()), ([], 0))

    def test_a_reverted_approval_returns_an_error_and_no_batch(self):
        self.receipt_status = '0x0'
        self.assertEqual(self._code(self._designate), 'approval_failed')
        self.assertFalse(SmartAccountPreparedAction.objects.filter(kind='smart_beneficiary').exists())
        # Only the inert draft the Face grant is bound to stays (a retry
        # reuses it and the same grant); nothing is pending or shown.
        self.assertEqual(list(SmartAccountBeneficiary.objects.values_list('state', flat=True)), ['draft'])
        draft = SmartAccountBeneficiary.objects.get()
        self.receipt_status = '0x1'
        self.approved.clear()
        batch = self._designate()
        action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
        self.assertEqual(action.payload['beneficiary_pk'], draft.pk)
        self.assertEqual(SmartAccountBeneficiary.objects.count(), 1)

    @override_settings(SMART_ACCOUNT_APPROVAL_WAIT_SECONDS=0)
    def test_an_approval_not_yet_mined_returns_no_batch_and_a_retry_reuses_it(self):
        self.receipt_status = None
        self.assertEqual(self._code(self._designate), 'approval_pending')
        self.assertFalse(SmartAccountPreparedAction.objects.filter(kind='smart_beneficiary').exists())
        self.receipt_status = '0x1'
        batch = self._designate()
        self.assertTrue(batch.request_id)
        self.assertEqual(len(self.signed), 1)       # the same approval, not a second one

    def test_relay_refusal_returns_an_error_and_no_batch(self):
        self.simulate_error = 'execution reverted: relayer paused'
        self.assertEqual(self._code(self._designate), 'approval_failed')
        self.assertFalse(SmartAccountPreparedAction.objects.filter(kind='smart_beneficiary').exists())

    def test_unreadable_approval_state_fails_closed(self):
        with mock.patch('smart_account.chain.designation_approved_until', side_effect=RuntimeError('rpc down')):
            self.assertEqual(self._code(self._designate), 'chain_unavailable')
        self.assertEqual(self.signed, [])

    def test_a_live_approval_is_not_sent_again(self):
        self.approved[('d', self.address, self.heir.wallet, 180 * 86400)] = int(time.time()) + 3000
        self._designate()
        self.assertEqual(self.signed, [])

    def test_window_change_is_approved_for_the_new_window(self):
        SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=180 * 86400, state='active', designated_at=timezone.now(),
            accepted_at=timezone.now())
        services.prepare_window_change(self.viewer(self.owner), 365)
        name, args = abi.decode_call(self.signed[0]['data'])
        self.assertEqual((name, args[2]), ('approveDesignation', 365 * 86400))

    def test_acceptance_is_approved_for_the_named_wallet(self):
        row = SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=180 * 86400, state='pending_acceptance', designated_at=timezone.now(),
            expires_at=timezone.now() + timezone.timedelta(days=30), verified_at_designation=True)
        # Checks are re-run first: a failure sends nothing.
        self.residence[self.heir.pk] = 'us_resident'
        self.assertEqual(self._code(services.prepare_acceptance, self.viewer(self.heir), str(row.designation_id)),
                         'beneficiary_ineligible')
        self.assertEqual(self.signed, [])
        self.residence.clear()
        batch = services.prepare_acceptance(self.viewer(self.heir), str(row.designation_id))
        tx = self.signed[0]
        self.assertEqual(tx['to'].lower(), FACTORY)
        name, args = abi.decode_call(tx['data'])
        self.assertEqual((name, args[0].lower(), args[1].lower()),
                         ('approveAcceptance', self.address, self.heir.wallet))
        self.assertEqual(abi.decode_call(batch.calls[0]['data'])[0], 'acceptBeneficiary')
        self.assertEqual(SmartAccountRelayTx.objects.get().kind, 'smart_acceptance_approval')

    def test_a_reverted_acceptance_approval_returns_no_batch(self):
        row = SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=180 * 86400, state='pending_acceptance', designated_at=timezone.now(),
            expires_at=timezone.now() + timezone.timedelta(days=30), verified_at_designation=True)
        self.receipt_status = '0x0'
        self.assertEqual(self._code(services.prepare_acceptance, self.viewer(self.heir), str(row.designation_id)),
                         'approval_failed')
        self.assertFalse(SmartAccountPreparedAction.objects.filter(kind='smart_beneficiary').exists())
        row.refresh_from_db()
        self.assertIsNone(row.acceptance_checked_at)


class RelayerAllowlistTests(RelayHarness):
    def _code(self, calldata, kind):
        with self.assertRaises(relayer.RelayError) as raised:
            relayer.send_relayer_call(self.account, calldata, kind, 'x')
        return raised.exception.code

    def test_each_kind_signs_only_its_one_function(self):
        self.assertEqual(self._code(abi.encode_call('startPaymentNotice'), 'smart_collect_fee'), 'call_not_allowed')
        self.assertEqual(self._code(abi.encode_call('withdraw', VAULT, 1), 'smart_return'), 'call_not_allowed')
        self.assertEqual(self._code('0xdeadbeef', 'smart_collect_fee'), 'call_not_allowed')
        self.assertEqual(self._code(abi.encode_call('collectFee') + '00', 'smart_collect_fee'), 'bad_calldata')
        # Owner functions are never relayer calls, whatever the kind says.
        self.assertEqual(self._code(abi.encode_call('cancelSubscription'), 'smart_collect_fee'), 'call_not_allowed')
        self.assertEqual(self._code(abi.encode_call('createAccount'), 'smart_designation_approval'),
                         'call_not_allowed')
        self.assertEqual(self.signed, [])

    def test_factory_approvals_go_to_the_factory_and_name_only_this_account(self):
        other = self.make_account(self.make_user('other'))
        beneficiary = '0x' + '77' * 20
        self.assertEqual(self._code(abi.encode_call('approveDesignation', other.contract_address, beneficiary, 1),
                                    'smart_designation_approval'), 'call_not_allowed')
        self.assertEqual(self._code(abi.encode_call('approveAcceptance', other.contract_address, beneficiary),
                                    'smart_acceptance_approval'), 'call_not_allowed')
        row, created = relayer.send_relayer_call(
            self.account, abi.encode_call('approveAcceptance', self.address, beneficiary),
            'smart_acceptance_approval', 'y')
        self.assertTrue(created)
        self.assertEqual(self.signed[0]['to'].lower(), FACTORY)
        self.assertEqual(self.signed[0]['gas'], abi.RELAY_GAS['smart_acceptance_approval'])
        # An account call never goes to the factory, and vice versa.
        relayer.send_relayer_call(self.account, abi.encode_call('collectFee'), 'smart_collect_fee', 'z')
        self.assertEqual(self.signed[1]['to'].lower(), self.address)

    def test_an_approval_is_not_a_balance_change(self):
        from smart_account import inflight
        relayer.send_relayer_call(self.account, abi.encode_call('approveAcceptance', self.address, '0x' + '77' * 20),
                                  'smart_acceptance_approval', 'y')
        self.assertFalse(inflight.address_in_flight(self.address))
        relayer.send_relayer_call(self.account, abi.encode_call('collectFee'), 'smart_collect_fee', 'z')
        self.assertTrue(inflight.address_in_flight(self.address))

    def test_a_user_batch_can_never_carry_a_factory_approval(self):
        calls = [abi.call(FACTORY, abi.encode_call('approveDesignation', self.address, '0x' + '77' * 20, 1))]
        with self.assertRaises(PolicyError) as raised:
            sponsor_7702.validate_policy(calls, self.owner, self.owner.wallet)
        self.assertEqual(raised.exception.code, 'smart_action_not_prepared')
        SmartAccountPreparedAction.objects.create(
            request_id='sa-' + 'c' * 32, user=self.owner, signer_address=self.owner.wallet,
            target_address=self.address, kind='smart_beneficiary', calls=calls,
            calls_hash=services.calls_hash(calls), expires_at=timezone.now() + timezone.timedelta(minutes=5))
        with self.assertRaises(PolicyError) as raised:
            sponsor_7702.validate_policy(calls, self.owner, self.owner.wallet, request_id='sa-' + 'c' * 32)
        self.assertEqual(raised.exception.code, 'selector_not_allowed')


class AppSubmissionTests(RelayHarness):
    """How apps/src/services/sponsored7702.executeSponsoredBatch submits a
    prepared batch: requestId + '_a0' (then '_a1'), intentId derived by its
    generic classifier, and optionally a leading fee-referral arm."""

    def setUp(self):
        super().setUp()
        self.fund(VAULT, self.owner.wallet, 500 * WAD)
        self.batch = services.prepare_deposit(
            self.viewer(self.owner), [{'asset_key': 'cusd_plus', 'units': str(100 * WAD)}])

    def test_attempt_suffix_is_stripped_for_the_lookup(self):
        self.assertEqual(relay_policy.base_request_id(self.batch.request_id + '_a1'), self.batch.request_id)
        self.assertIsNotNone(relay_policy.early_action(self.owner, self.batch.request_id + '_a0'))
        action = relay_policy.validate_batch(self.batch.calls, self.owner, self.owner.wallet,
                                             self.batch.request_id + '_a1')
        self.assertEqual(action.request_id, self.batch.request_id)

    def test_request_id_fits_the_sponsor_endpoint_format(self):
        from cusd_plus.schema import _SPONSOR_REQUEST_ID_RE
        self.assertTrue(_SPONSOR_REQUEST_ID_RE.fullmatch(self.batch.request_id + '_a0'))

    def test_intent_id_the_app_derives_is_accepted(self):
        # evmWallet.deriveIntentId knows no account selector: it signs `subscribe:<requestId>_a0`,
        # which the sponsor accepts for a prepared account batch (legacy_subscribe_intent).
        from eth_utils import keccak
        rid = self.batch.request_id + '_a0'
        self.assertEqual(sponsor_7702.intent_id_for('subscribe', client_request_id=rid),
                         keccak(text=f'subscribe:{rid}'))

    def test_a_leading_fee_referral_arm_keeps_the_byte_match(self):
        from cusd_plus import fee_referral
        arm = fee_referral.ReferralArm(referrer_user_id=1, referrer_address='0x' + '42' * 20, share_bps=2500)
        with mock.patch('cusd_plus.fee_referral._cusd_address', return_value='0x' + 'c1' * 20):
            armed = [fee_referral.arm_call(arm)] + self.batch.calls
            with mock.patch('cusd_plus.fee_referral.eligible_arm', return_value=arm), \
                    mock.patch('cusd_plus.fee_referral.onchain_ready', return_value=True), \
                    mock.patch('cusd_plus.fee_referral.has_fee_bearing_call', return_value=True):
                base = fee_referral.strip_arm(armed, self.owner, self.owner.wallet)
        self.assertEqual(base, self.batch.calls)
        _generic, is_account = relay_policy.split_generic(base, self.owner)
        self.assertTrue(is_account)
        relay_policy.validate_batch(base, self.owner, self.owner.wallet, self.batch.request_id + '_a0')
        # An arm anywhere but first is never stripped, so the batch no longer matches.
        with self.assertRaises(PolicyError):
            fee_referral.strip_arm(self.batch.calls + [armed[0]], self.owner, self.owner.wallet)
