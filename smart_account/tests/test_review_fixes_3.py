"""Review round 3: beneficiary mirror convergence, Face for send rules and
designations, stock-buy share sizing, forced-sale gas, buy-rule review cap."""
import time
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from eth_abi import decode as abi_decode, encode as abi_encode

from smart_account import abi, automation, payouts, quotes, relay_policy, relayer, services
from smart_account.assets import Asset
from smart_account.models import (
    SmartAccountBeneficiary, SmartAccountClaim, SmartAccountPreparedAction, SmartAccountRelayTx,
    SmartAccountRule, SmartAccountStandingAuthorization,
)

from .base import STOCK_ROUTER, VAULT, SmartAccountTestCase, WAD, new_address
# Module references only: a TestCase bound to a name in this module is
# collected (and run) again here.
from . import test_reconcile, test_tasks

FACE_MESSAGE = 'Confirma que eres tú con tu rostro para continuar.'


class _Events(SmartAccountTestCase):
    """The event helpers of test_reconcile.ReconcileTests (borrowed, not
    inherited, so its tests do not run twice)."""
    emit = test_reconcile.ReconcileTests.emit
    apply = test_reconcile.ReconcileTests.apply
    subscribe = test_reconcile.ReconcileTests.subscribe
    _name = test_reconcile.ReconcileTests._name

    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.heir = self.make_user('heir')
        self.contract = new_address()
        self.block = 1000
        self.index = 0
        self.now = timezone.now().replace(microsecond=0)


# ── 1. the chain is the truth for beneficiary events ────────────────────

class BeneficiaryConvergenceTests(_Events):
    def _accepted(self, hours=2):
        return self.emit('BeneficiaryAccepted', {'beneficiary': self.heir.wallet,
                                                 'challengeWindow': str(180 * 86400)},
                         when=self.now + timedelta(hours=hours))

    def _claim(self):
        executable = int((self.now + timedelta(days=180)).timestamp())
        return self.emit('ClaimInitiated', {'beneficiary': self.heir.wallet, 'executableAt': str(executable)},
                         tx='0xc1', when=self.now + timedelta(hours=3))

    def test_decline_after_accept_mined_then_claim_is_mirrored_and_the_owner_told(self):
        account = self.subscribe()
        self._name(account)
        self.apply()
        row = SmartAccountBeneficiary.objects.get()
        # The heir signed acceptBeneficiary (mined, not mirrored yet) and then
        # declined in the app: nothing on chain or in the mirror stopped it.
        services.decline_designation(self.viewer(self.heir), row.designation_id)
        row.refresh_from_db()
        self.assertEqual(row.state, 'declined')
        self._accepted()
        claim_event = self._claim()
        later = self.emit('PlanChanged', {'nextPlan': '1'})
        with mock.patch('smart_account.notifications.claim_initiated_owner') as told_owner, \
                mock.patch('smart_account.notifications.claim_initiated_beneficiary'):
            self.apply()
        row.refresh_from_db()
        self.assertEqual((row.state, row.accepted_at, row.declined_at),
                         ('active', self.now + timedelta(hours=2), None))
        claim = SmartAccountClaim.objects.get()
        self.assertEqual((claim.state, claim.beneficiary_row_id, claim.initiated_tx), ('pending', row.pk, '0xc1'))
        told_owner.assert_called_once_with(claim)
        claim_event.refresh_from_db()
        later.refresh_from_db()
        self.assertIsNotNone(later.applied_at)          # the account's later events are not blocked
        self.assertTrue(self.ops_alert_mock.called)     # ops hears about the revival
        # Every batch the owner signs now carries cancelClaim.
        calls = services.with_cancel_claim(self.owner, [])
        self.assertEqual(calls, [abi.call(account.contract_address, abi.encode_call('cancelClaim'))])

    def test_a_lapsed_row_is_revived_by_its_mined_acceptance(self):
        account = self.subscribe()
        self._name(account)
        self.apply()
        SmartAccountBeneficiary.objects.update(state='lapsed')
        self._accepted()
        self.apply()
        self.assertEqual(SmartAccountBeneficiary.objects.get().state, 'active')

    def test_acceptance_with_no_row_at_all_repairs_the_mirror_and_alerts(self):
        self.subscribe()
        self._accepted()
        self._claim()
        with mock.patch('smart_account.notifications.claim_initiated_owner') as told_owner, \
                mock.patch('smart_account.notifications.claim_initiated_beneficiary'):
            self.apply()
        row = SmartAccountBeneficiary.objects.get()
        self.assertEqual((row.state, row.beneficiary_user, row.challenge_window_seconds),
                         ('active', self.heir, 180 * 86400))
        self.assertEqual(SmartAccountClaim.objects.get().beneficiary_row, row)
        told_owner.assert_called_once()
        self.assertTrue(self.ops_alert_mock.called)

    def test_claim_by_a_beneficiary_the_mirror_had_removed_is_repaired_not_stuck(self):
        account = self.subscribe()
        self._name(account)
        self._accepted()
        self.apply()
        SmartAccountBeneficiary.objects.update(state='removed', removed_at=timezone.now())
        self._claim()
        with mock.patch('smart_account.notifications.claim_initiated_owner') as told_owner, \
                mock.patch('smart_account.notifications.claim_initiated_beneficiary'):
            self.apply()
        row = SmartAccountBeneficiary.objects.get()
        self.assertEqual((row.state, row.removed_at), ('active', None))
        self.assertEqual(SmartAccountClaim.objects.get().state, 'pending')
        told_owner.assert_called_once()

    def test_claim_by_an_address_with_no_confio_user_applies_and_alerts(self):
        account = self.subscribe()
        stranger = new_address()
        self.emit('ClaimInitiated', {'beneficiary': stranger, 'executableAt': '1900000000'})
        later = self.emit('PlanChanged', {'nextPlan': '1'})
        self.apply()
        later.refresh_from_db()
        self.assertIsNotNone(later.applied_at)
        self.assertFalse(SmartAccountClaim.objects.exists())
        self.assertTrue(self.ops_alert_mock.called)
        # The owner is still protected: the chain read decides cancelClaim.
        self.chain.views[(account.contract_address, 'claimStartedAt')] = 1
        self.assertEqual(len(services.with_cancel_claim(self.owner, [])), 1)


class DeclineGuardTests(_Events):
    def setUp(self):
        super().setUp()
        self.account = self.subscribe()
        self._name(self.account)
        self.apply()
        self.row = SmartAccountBeneficiary.objects.get()

    def _decline(self):
        with self.assertRaises(services.PrepareError) as raised:
            services.decline_designation(self.viewer(self.heir), self.row.designation_id)
        self.row.refresh_from_db()
        self.assertEqual(self.row.state, 'pending_acceptance')
        return raised.exception.code

    def test_refused_within_an_hour_of_an_acceptance_check(self):
        SmartAccountBeneficiary.objects.update(acceptance_checked_at=timezone.now() - timedelta(minutes=59))
        self.assertEqual(self._decline(), 'designation_acceptance_in_progress')
        SmartAccountBeneficiary.objects.update(acceptance_checked_at=timezone.now() - timedelta(minutes=61))
        self.assertEqual(services.decline_designation(self.viewer(self.heir), self.row.designation_id).state,
                         'declined')

    def test_refused_while_an_acceptance_approval_is_live(self):
        SmartAccountRelayTx.objects.create(
            smart_account=self.account, kind='smart_acceptance_approval',
            source_id=f'acceptance:{self.heir.wallet}:1', calldata='0x', signed_tx_hash='0x' + 'ab' * 32,
            status='confirmed')
        self.assertEqual(self._decline(), 'designation_acceptance_in_progress')

    def test_refused_when_the_chain_already_names_the_signer(self):
        self.chain.views[(self.account.contract_address, 'beneficiary')] = self.heir.wallet
        self.assertEqual(self._decline(), 'designation_already_accepted')

    def test_unreadable_chain_refuses(self):
        self.chain.fail.add('account_view')
        self.assertEqual(self._decline(), 'chain_unavailable')


# ── 2. Face for send rules and designations ─────────────────────────────

class _Face:
    """Face applies to the owner; `grant` decides whether a check is there."""

    def face(self, grant=True):
        calls = []

        def step_up(user, purpose, *, action_key=None, consume=False, **kwargs):
            calls.append({'action_key': action_key, 'consume': consume})
            return '' if grant else FACE_MESSAGE
        patches = [mock.patch('security.face_step_up.step_up_applies', return_value=True),
                   mock.patch('security.face_step_up.require_face_step_up', side_effect=step_up)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return calls


class SendRuleFaceTests(_Face, SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.payee = self.make_user('payee')
        self.account = self.make_account(self.owner)
        self.fund(VAULT, self.account.contract_address, 500 * WAD)

    def test_without_a_face_check_no_rule_and_no_authorization(self):
        self.face(grant=False)
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_send_rule(self.viewer(self.owner), None, 'payee', '25.00', 'weekly')
        self.assertEqual(raised.exception.code, 'face_required')
        self.assertFalse(SmartAccountRule.objects.exists())
        self.assertFalse(SmartAccountStandingAuthorization.objects.exists())

    def test_the_grant_is_claimed_and_bound_to_payee_amount_and_frequency(self):
        calls = self.face()
        batch = services.prepare_send_rule(self.viewer(self.owner), None, 'payee', '25.00', 'weekly')
        authorization = SmartAccountStandingAuthorization.objects.get()
        self.assertEqual((authorization.kind, authorization.payee_address, authorization.amount_usd,
                          authorization.frequency, authorization.face_required),
                         ('send', self.payee.wallet, Decimal('25.00'), 'weekly', True))
        self.assertTrue(authorization.face_action_key.startswith('out:'))
        self.assertEqual(calls, [{'action_key': authorization.face_action_key, 'consume': True}])
        draft = SmartAccountRule.objects.get()
        self.assertEqual(draft.standing_authorization, authorization)
        self.assertEqual(authorization.binding_hash, payouts.send_binding_hash(
            self.account.contract_address, self.payee.wallet, Decimal('25.00'), 'weekly'))
        # Another amount is another grant.
        services.prepare_send_rule(self.viewer(self.owner), None, 'payee', '30.00', 'weekly')
        self.assertNotEqual(calls[1]['action_key'], calls[0]['action_key'])
        # Submit re-checks the same key (an exact retry, no new check).
        action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
        self.assertIsNone(relay_policy.face_refusal(action, self.owner))
        self.assertEqual(calls[-1], {'action_key': authorization.face_action_key, 'consume': True})
        SmartAccountStandingAuthorization.objects.filter(pk=authorization.pk).update(revoked_at=timezone.now())
        self.assertEqual(relay_policy.face_refusal(action, self.owner), FACE_MESSAGE)

    def test_submit_refuses_a_send_rule_draft_without_authorization(self):
        self.face()
        batch = services.prepare_send_rule(self.viewer(self.owner), None, 'payee', '25.00', 'weekly')
        SmartAccountRule.objects.update(standing_authorization=None)
        action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
        self.assertEqual(relay_policy.face_refusal(action, self.owner), FACE_MESSAGE)

    def test_kinds_where_money_stays_with_the_owner_ask_nothing(self):
        for kind in ('smart_subscribe', 'smart_deposit', 'smart_withdraw', 'smart_trade', 'smart_cancel',
                     'smart_claim', 'smart_inherited_withdraw', 'smart_beneficiary_remove'):
            self.assertIsNone(relay_policy.face_refusal(SimpleNamespace(kind=kind, payload={}, calls=[]),
                                                        self.owner), kind)
        acceptance = SimpleNamespace(kind='smart_beneficiary', payload={'beneficiary_pk': 1}, calls=[
            abi.call(self.account.contract_address, abi.encode_call('acceptBeneficiary'))])
        self.assertIsNone(relay_policy.face_refusal(acceptance, self.owner))


class DesignationFaceTests(_Face, SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.heir = self.make_user('heir')
        self.account = self.make_account(self.owner)

    def test_designation_needs_the_owners_face_before_any_approval(self):
        self.face(grant=False)
        with mock.patch('smart_account.approvals.ensure_designation') as approval:
            with self.assertRaises(services.PrepareError) as raised:
                services.prepare_designation(self.viewer(self.owner), 'heir', 180, True)
            approval.assert_not_called()
        self.assertEqual(raised.exception.code, 'face_required')
        self.assertFalse(SmartAccountBeneficiary.objects.exists())

    def test_the_grant_rides_in_the_prepared_payload_and_is_rechecked_at_submit(self):
        calls = self.face()
        batch = services.prepare_designation(self.viewer(self.owner), 'heir', 180, True)
        action = SmartAccountPreparedAction.objects.get(request_id=batch.request_id)
        self.assertTrue(action.payload['face_required'])
        self.assertEqual(action.payload['face_action_key'], calls[0]['action_key'])
        self.assertIsNone(relay_policy.face_refusal(action, self.owner))
        action.payload = {k: v for k, v in action.payload.items() if k != 'face_action_key'}
        self.assertEqual(relay_policy.face_refusal(action, self.owner), FACE_MESSAGE)


class SendRuleMirrorTests(_Events):
    def _rule(self, amount_wei):
        account = self.subscribe()
        payee = self.make_user('payee')
        self.fund(VAULT, account.contract_address, 500 * WAD)
        batch = services.prepare_send_rule(self.viewer(self.owner), None, 'payee', '25.00', 'weekly')
        from blockchain.models import SponsoredBatch
        sponsored = SponsoredBatch.objects.create(
            user=self.owner, user_bsc_address=self.owner.wallet, kind='smart_rule', num_calls=1,
            calls_json='[]', tx_hash='0xd1', gas_limit=1, max_fee_wei='1', status='confirmed')
        SmartAccountPreparedAction.objects.filter(request_id=batch.request_id).update(
            consumed=True, sponsored_batch=sponsored)
        self.chain.rules[(account.contract_address, 0)] = {
            'kind': 'send', 'frequency': 'weekly', 'active': True, 'token_in': VAULT,
            'token_out': abi.ZERO_ADDRESS, 'payee': payee.wallet, 'payout_ref': '0x' + '00' * 32,
            'amount_usd_wei': amount_wei, 'next_run_at': int(self.now.timestamp())}
        self.emit('RuleCreated', {'id': '0', 'kind': '0'}, tx='0xd1')
        self.apply()
        return SmartAccountRule.objects.get()

    def test_the_authorized_rule_is_active(self):
        rule = self._rule(25 * WAD)
        self.assertEqual((rule.active, rule.standing_authorization.kind), (True, 'send'))

    def test_an_on_chain_rule_that_differs_from_what_face_authorized_never_runs(self):
        rule = self._rule(2_500 * WAD)
        self.assertEqual((rule.active, rule.deactivated_reason, rule.standing_authorization),
                         (False, 'no_standing_authorization', None))


class SendRuleRunTests(test_tasks.RelayHarness):
    def setUp(self):
        super().setUp()
        from smart_account.models import SmartAccount
        SmartAccount.objects.update(paid_until=timezone.now() + timedelta(days=20))
        self.payee = self.make_user('payee')
        slot = timezone.now().replace(microsecond=0) - timedelta(minutes=3)
        self.authorization = SmartAccountStandingAuthorization.objects.create(
            kind='send', user=self.owner, payee_address=self.payee.wallet, rail='', amount_usd=Decimal('25.00'),
            frequency='weekly', face_action_key='out:' + 'f' * 64,
            binding_hash=payouts.send_binding_hash(self.address, self.payee.wallet, Decimal('25.00'), 'weekly'))
        self.rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=4, state='onchain', kind='send', token_in=VAULT,
            payee_address=self.payee.wallet, payee_user=self.payee, amount=Decimal('25.00'), frequency='weekly',
            next_run_at=slot, scheduled_for=slot, active=True, standing_authorization=self.authorization)
        self.chain.views[(self.address, 'status')] = 1
        self.chain.views[(self.address, 'billingStatus')] = 0
        self.chain.rules[(self.address, 4)] = {
            'kind': 'send', 'frequency': 'weekly', 'active': True, 'payee': self.payee.wallet,
            'amount_usd_wei': 25 * WAD, 'next_run_at': int(slot.timestamp())}
        self.fund(VAULT, self.address, 5_000 * WAD)
        p = mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def test_runs_while_the_authorization_matches_the_chain(self):
        self.assertEqual(automation.run_rules()['sent'], 1)

    def test_a_chain_rule_that_no_longer_matches_is_deactivated_and_not_sent(self):
        self.chain.rules[(self.address, 4)]['amount_usd_wei'] = 2_500 * WAD
        automation.run_rules()
        self.rule.refresh_from_db()
        self.assertEqual((self.rule.active, self.rule.deactivated_reason), (False, 'authorization_mismatch'))
        self.assertEqual(self.signed, [])

    def test_a_revoked_or_missing_authorization_never_runs(self):
        SmartAccountStandingAuthorization.objects.update(revoked_at=timezone.now())
        automation.run_rules()
        self.rule.refresh_from_db()
        self.assertEqual((self.rule.active, self.rule.deactivated_reason), (False, 'no_standing_authorization'))
        self.assertEqual(self.signed, [])


# ── 3. stock buys sized to the contract's one-cent excess window ────────

BPS = 10_000
P_PLUS = 1_031_234_567_890_123_456        # stored pPlus
LAST = 1_118_765_432_109_876_543          # vault.lastOraclePrice
LIVE = LAST + LAST * 3 // 1_000_000       # oracle now: 0.3 bps not accrued yet
SHARE_BPS = 1_500
EXIT_FEE_BPS = 20                         # cUSD.feeBps()
DAILY_5PCT = Decimal(str(1.05 ** (1 / 365) - 1))


def reference_redeem(shares, p_plus, last, oracle, share_bps, fee_bps):
    """CusdPlusVault.redeemToUsdt + CusdVault.settleSavingsExit, written out
    independently: accrue() then the two floors, then the ceil fee."""
    if oracle > last:
        growth = (oracle - last) * WAD // last
        kept = growth * (BPS - share_bps) // BPS
        p_plus = p_plus * (WAD + kept) // WAD
    usdy_out = shares * p_plus // oracle                # Math.mulDiv(shares, pPlus, p)
    gross = usdy_out * oracle // WAD                    # _imRedeem at the snapshot price
    fee = -(-gross * fee_bps // BPS) if gross and fee_bps else 0   # Math.mulDiv(.., Ceil)
    return gross - fee


class StockBuySizingTests(SmartAccountTestCase):
    def vault(self, *, daily=DAILY_5PCT, live=LIVE, rate_oracle=True):
        patches = [
            mock.patch('cusd_plus.vault.p_plus_wad', return_value=P_PLUS),
            mock.patch('cusd_plus.vault.last_oracle_price_wad', return_value=LAST),
            mock.patch('cusd_plus.vault.current_oracle_price_wad', return_value=live),
            mock.patch('cusd_plus.vault.confio_yield_share_bps', return_value=SHARE_BPS),
            mock.patch('cusd_plus.vault.usdy_daily_rate', return_value=float(daily)),
            mock.patch('cusd_plus.vault.rate_oracle_address', return_value='0x' + '0a' * 20 if rate_oracle else None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_redemption_covers_the_spend_and_stays_under_a_cent_at_quote_and_at_inclusion(self):
        self.vault()
        now = int(time.time())
        expiration = now + 60
        late = LIVE + int(Decimal(LIVE) * DAILY_5PCT * Decimal(120) / Decimal(86_400))   # two minutes later
        for dollars in (10, 100, 1_000, 10_000):
            spend = dollars * WAD
            shares = quotes.size_buy_shares(spend, exit_fee_bps=EXIT_FEE_BPS, expiration=expiration, now=now)
            for oracle in (LIVE, late):
                net = reference_redeem(shares, P_PLUS, LAST, oracle, SHARE_BPS, EXIT_FEE_BPS)
                self.assertGreaterEqual(net, spend, (dollars, oracle))
                self.assertLess(net - spend, quotes.USDT_EXCESS_MAX, (dollars, oracle))
            # Minimal: one share less no longer covers the spend.
            self.assertLess(reference_redeem(shares - 1, P_PLUS, LAST, LIVE, SHARE_BPS, EXIT_FEE_BPS), spend)

    def test_the_old_exit_buffer_overshoots_the_window(self):
        # What stock_buy_call did before: gross for net, at the stored
        # price, plus the personal flow's 5 bps exit buffer.
        spend = 100 * WAD
        gross = (spend * BPS + (BPS - EXIT_FEE_BPS) - 1) // (BPS - EXIT_FEE_BPS)
        per_share = (WAD * P_PLUS // LAST) * LAST // WAD
        shares = (gross * WAD + per_share - 1) // per_share
        shares += (shares * 5 + BPS - 1) // BPS
        excess = reference_redeem(shares, P_PLUS, LAST, LIVE, SHARE_BPS, EXIT_FEE_BPS) - spend
        self.assertGreater(excess, quotes.USDT_EXCESS_MAX)

    def test_accrual_drift_over_the_quote_lifetime_refuses_and_retries_later(self):
        self.vault()
        now = int(time.time())
        far = now + 24 * 3600
        # $10,000 over a day of accrual leaves more than a cent: not sent.
        with self.assertRaises(quotes.QuoteUnavailable) as raised:
            quotes.size_buy_shares(10_000 * WAD, exit_fee_bps=EXIT_FEE_BPS, expiration=far, now=now)
        self.assertEqual((raised.exception.code, raised.exception.retry_later), ('usdt_excess_window', True))
        # $10 over the same day stays inside the window.
        shares = quotes.size_buy_shares(10 * WAD, exit_fee_bps=EXIT_FEE_BPS, expiration=far, now=now)
        late = LIVE + int(Decimal(LIVE) * DAILY_5PCT)
        self.assertLess(reference_redeem(shares, P_PLUS, LAST, late, SHARE_BPS, EXIT_FEE_BPS) - 10 * WAD,
                        quotes.USDT_EXCESS_MAX)

    def test_without_a_rate_oracle_a_high_rate_is_assumed(self):
        self.vault(daily=Decimal(0), rate_oracle=False)
        now = int(time.time())
        with self.assertRaises(quotes.QuoteUnavailable):
            quotes.size_buy_shares(10_000 * WAD, exit_fee_bps=EXIT_FEE_BPS, expiration=now + 3600, now=now)

    def test_a_price_the_vault_guard_would_refuse_is_not_quoted(self):
        self.vault(live=LAST - 1)
        with self.assertRaises(quotes.QuoteUnavailable) as raised:
            quotes.size_buy_shares(10 * WAD, exit_fee_bps=EXIT_FEE_BPS, expiration=None)
        self.assertTrue(raised.exception.retry_later)

    def _router_call(self, shares, spend, expiration):
        from cusd_plus import sponsor_7702
        quote = (56, 7, b'\x01' * 32, '0x' + '6a' * 20, 2 * WAD, spend // 2, expiration, 0, b'\x00' * 32)
        encoded = abi_encode([sponsor_7702.GM_QUOTE_ABI, 'bytes', 'uint256', 'uint256', 'uint256', 'uint256'],
                             [quote, b'\x02' * 65, shares, spend, spend, 20])
        return {'to': STOCK_ROUTER, 'value': '0', 'data': '0x' + sponsor_7702.SEL_STOCK_BUY + encoded.hex()}

    def test_an_account_trade_is_resized_with_everything_else_kept(self):
        from cusd_plus import sponsor_7702
        expiration = int(time.time()) + 90
        call = self._router_call(10 ** 30, 100 * WAD, expiration)
        with mock.patch('smart_account.quotes.size_buy_shares', return_value=123) as sized:
            out = quotes.resize_stock_buy_call(call)
        sized.assert_called_once_with(100 * WAD, exit_fee_bps=90, expiration=expiration)  # live cUSD fee
        types = [sponsor_7702.GM_QUOTE_ABI, 'bytes', 'uint256', 'uint256', 'uint256', 'uint256']
        before = abi_decode(types, bytes.fromhex(call['data'][10:]))
        after = abi_decode(types, bytes.fromhex(out['data'][10:]))
        self.assertEqual(after[2], 123)
        self.assertEqual((after[0], after[1], after[3:]), (before[0], before[1], before[3:]))

    def test_rule_buy_uses_the_exact_sizing_not_the_buffer(self):
        from cusd_plus import stock_fees
        quote = {'notional_wei': str(100 * WAD), 'chain_id': 56, 'attestation_id': 7, 'user_id': '0x' + '01' * 32,
                 'asset_address': '0x' + '6a' * 20, 'price': str(2 * WAD), 'token_amount': str(50 * WAD),
                 'expiration': int(time.time()) + 60, 'side': 0, 'additional_data_hex': '0x' + '00' * 32,
                 'signature_hex': '0x' + '02' * 65, 'attestation_id_str': '7'}
        with mock.patch('smart_account.quotes._stock_fee', return_value=(20, stock_fees.MODE_PERIMETER)), \
                mock.patch('smart_account.quotes._binding_quote', return_value=quote), \
                mock.patch('smart_account.quotes._checked_stock', return_value={'asset': '0x' + '6a' * 20}), \
                mock.patch('smart_account.quotes.size_buy_shares', return_value=456) as sized:
            built = quotes.stock_buy_call('AAPLon', Decimal('100'), share_limit=10 ** 30)
        sized.assert_called_once_with(100 * WAD, exit_fee_bps=90, expiration=quote['expiration'])
        self.assertEqual(built['max_in'], 456)
        with mock.patch('smart_account.quotes._stock_fee', return_value=(20, stock_fees.MODE_PERIMETER)), \
                mock.patch('smart_account.quotes._binding_quote', return_value=quote), \
                mock.patch('smart_account.quotes.size_buy_shares', return_value=456):
            with self.assertRaises(quotes.QuoteUnavailable):
                quotes.stock_buy_call('AAPLon', Decimal('100'), share_limit=455)


# ── 4. forced sales with three and four legs ────────────────────────────

class ForcedSaleGasTests(test_tasks.RelayHarness):
    def setUp(self):
        super().setUp()
        from smart_account.models import SmartAccount
        self.due(5 * WAD, fee=150 * WAD, billing=3, notice=self.paid_until + 10)
        SmartAccount.objects.update(notice_started_at=timezone.now() - timedelta(days=8))
        self.tokens = {}

        def stock_sell(symbol, notional):
            return {'call': {'to': STOCK_ROUTER, 'value': '0', 'data': '0x5678'}, 'token': self.tokens[symbol],
                    'max_in': 1, 'expected_dollars_wei': int(Decimal(notional) * Decimal('0.991') * WAD)}
        for p in (mock.patch('smart_account.quotes.stock_sell_call', side_effect=stock_sell),
                  mock.patch('cusd_plus.crypto_policy.live_fee_bps', return_value=90),
                  mock.patch('smart_account.automation._account_dollar', return_value=abi.DOLLAR_PLUS)):
            p.start()
            self.addCleanup(p.stop)

    def stock(self, symbol, value):
        address = new_address()
        self.tokens[symbol] = address
        return Asset(f'stock:{symbol}', 'stock', symbol, symbol, address, 10 * WAD, 18, Decimal(value), True)

    def _sell(self, candidates):
        with mock.patch('smart_account.automation.sale_candidates', return_value=candidates):
            out = automation.run_forced_sales()
        return out

    def test_the_cap_covers_every_leg_at_the_largest_budget_well_under_a_block(self):
        cap = relayer.max_relay_gas('smart_forced_sale')
        self.assertEqual(cap, abi.RELAY_GAS_SALE_BASE + abi.MAX_SALE_LEGS * max(abi.RELAY_GAS_SALE_LEG.values()))
        self.assertLess(cap, 20_000_000)
        self.assertEqual(relayer.max_relay_gas('smart_execute_rule'), relayer.MAX_RELAY_GAS)

    def test_three_stock_legs_are_sent(self):
        out = self._sell([self.stock('A', 60), self.stock('B', 60), self.stock('C', 60)])
        self.assertEqual(out['sent'], 1)
        legs = abi.decode_call(self.signed[0]['data'])[1][0]
        self.assertEqual(len(legs), 3)
        self.assertEqual(self.signed[0]['gas'], abi.RELAY_GAS_SALE_BASE + 3 * abi.RELAY_GAS_SALE_LEG['stock'])
        self.assertGreater(self.signed[0]['gas'], relayer.MAX_RELAY_GAS)   # what used to fail forever

    def test_four_stock_legs_are_sent(self):
        out = self._sell([self.stock(s, 45) for s in 'ABCD'])
        self.assertEqual(out['sent'], 1)
        legs = abi.decode_call(self.signed[0]['data'])[1][0]
        self.assertEqual(len(legs), 4)
        self.assertEqual(self.signed[0]['gas'], abi.RELAY_GAS_SALE_BASE + 4 * abi.RELAY_GAS_SALE_LEG['stock'])

    def test_a_leg_over_the_gas_budget_is_skipped_for_a_cheaper_one(self):
        budget = abi.RELAY_GAS_SALE_BASE + 2 * abi.RELAY_GAS_SALE_LEG['stock'] + abi.RELAY_GAS_SALE_LEG['crypto']
        btc = Asset('crypto:BTCB', 'crypto', 'BTC', 'Bitcoin', '0x' + '71' * 20, 10 ** 15, 18, Decimal('40'), True)

        def crypto_sell(token, dollar, amount_in):
            value = Decimal(amount_in) / Decimal(btc.units) * btc.value_usd
            return {'call': {'to': '0x' + '52' * 20, 'value': '0', 'data': '0x1234'}, 'token': btc.address,
                    'max_in': amount_in, 'expected_dollars_wei': int(value * Decimal('0.991') * WAD)}
        with mock.patch.dict(relayer.MAX_RELAY_GAS_BY_KIND, {'smart_forced_sale': budget}), \
                mock.patch('cusd_plus.crypto_catalog.by_address', return_value=mock.Mock()), \
                mock.patch('smart_account.quotes.crypto_sell_call', side_effect=crypto_sell):
            out = self._sell([self.stock('A', 70), self.stock('B', 60), self.stock('C', 50), btc])
        self.assertEqual(out['sent'], 1)
        legs = abi.decode_call(self.signed[0]['data'])[1][0]
        self.assertEqual([leg[1].lower() for leg in legs], [self.tokens['A'], self.tokens['B'], btc.address])
        self.assertEqual(self.signed[0]['gas'], budget)


# ── 5. the store-review amount cap on buy rules ─────────────────────────

class BuyRuleReviewCapTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.fund(VAULT, self.account.contract_address, 500 * WAD)
        self.token = '0x' + '6a' * 20
        for p in (mock.patch('smart_account.assets.resolve_asset_key', return_value=('stock', 'AAPLon', self.token, 18)),
                  mock.patch('smart_account.services._stock_buy_allowed', return_value=True),
                  mock.patch('cusd_plus.complex_products.factor_for_symbol', return_value=None)):
            p.start()
            self.addCleanup(p.stop)

    def test_prepare_refuses_above_the_cap(self):
        with mock.patch('security.geo.review_cap_exceeded', return_value=True) as cap:
            with self.assertRaises(services.PrepareError) as raised:
                services.prepare_buy_rule(self.viewer(self.owner), None, 'stock:AAPLon', '600.00', 'monthly')
        self.assertEqual(raised.exception.code, 'review_amount_cap')
        cap.assert_called_once_with(self.owner, Decimal('600.00'))
        self.assertFalse(SmartAccountRule.objects.exists())
        with mock.patch('security.geo.review_cap_exceeded', return_value=False):
            services.prepare_buy_rule(self.viewer(self.owner), None, 'stock:AAPLon', '600.00', 'monthly')
        self.assertTrue(SmartAccountRule.objects.exists())

    @override_settings(CUSD_PLUS_STOCK_TRADING_ENABLED=True)
    def test_each_run_rechecks_the_cap(self):
        rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=1, state='onchain', kind='buy', token_in=VAULT,
            token_out=self.token, amount=Decimal('600.00'), frequency='monthly', active=True)
        with mock.patch('smart_account.assets.stock_by_address', return_value=('AAPLon', {})), \
                mock.patch('cusd_plus.eligibility.check_stock_buy_eligibility', return_value=True):
            with mock.patch('security.geo.review_cap_exceeded', return_value=True):
                self.assertEqual(automation.buy_rule_refusal(rule).code, 'review_amount_cap')
            with mock.patch('security.geo.review_cap_exceeded', return_value=False):
                self.assertIsNone(automation.buy_rule_refusal(rule))
