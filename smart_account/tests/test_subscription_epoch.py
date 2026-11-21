"""Subscription epochs (spec 4.4, 4.6, 4.8; invariants 9 and 22): every
subscribe starts a new epoch, rules of an earlier one are dead, the
beneficiary is cleared; cancelRule works in every state but Inherited; the
billing jobs convert USDT first and treat DollarsCover as "no sale needed"."""
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase
from django.utils import timezone
from eth_utils import keccak

from cusd_plus import sponsor_7702
from smart_account import abi, automation, chain, relay_policy, services
from smart_account.models import (
    SmartAccount, SmartAccountBeneficiary, SmartAccountClaim, SmartAccountForcedSale, SmartAccountRule,
    SmartAccountStandingAuthorization,
)

from . import test_tasks
from .base import USDT, VAULT, WAD, SmartAccountTestCase
from . import test_reconcile

CONTRACTS = Path(__file__).resolve().parents[2] / 'contracts' / 'smart_account'


# ── ABI ─────────────────────────────────────────────────────────────────

class EpochAbiTests(SimpleTestCase):
    def setUp(self):
        self.interface = (CONTRACTS / 'interfaces' / 'IConfioSmartAccount.sol').read_text()
        self.source = (CONTRACTS / 'ConfioSmartAccount.sol').read_text()

    def _struct(self, name):
        body = re.search(r'struct\s+%s\s*\{(.*?)\}' % name, self.interface, re.S).group(1)
        body = re.sub(r'///[^\n]*', '', body)
        types = [line.split()[0] for line in body.split(';') if line.strip()]
        return '(' + ','.join('uint8' if t in ('RuleKind', 'Frequency', 'Plan') else t for t in types) + ')'

    def test_rule_tuples_match_the_interface_structs(self):
        self.assertEqual(abi.RULE_ABI, self._struct('Rule'))
        self.assertEqual(abi.RULE_INPUT_ABI, self._struct('RuleInput'))
        self.assertTrue(abi.RULE_ABI.endswith('uint64,uint64)'))  # nextRunAt, epoch

    def test_subscription_epoch_view_is_read_with_the_interface_type(self):
        self.assertIn('function subscriptionEpoch() external view returns (uint64);', self.interface)
        self.assertEqual(dict(chain._ACCOUNT_VIEWS)['subscriptionEpoch'], 'uint64')

    def test_every_named_error_exists_in_the_contract(self):
        declared = set(re.findall(r'error\s+(\w+)\(\);', self.source))
        self.assertEqual(set(abi.ACCOUNT_ERRORS) - declared, set())
        for name in ('IsInherited', 'DollarsCover', 'BadRule'):
            self.assertIn(name, abi.ACCOUNT_ERRORS)
            self.assertIn(name, abi.ERROR_MESSAGES)

    def test_revert_error_reads_the_selector_from_a_node_message(self):
        sel = keccak(text='DollarsCover()')[:4].hex()
        self.assertEqual(abi.revert_error(f"{{'code': 3, 'message': 'execution reverted', 'data': '0x{sel}'}}"),
                         'DollarsCover')
        self.assertEqual(abi.revert_error('0x' + keccak(text='IsInherited()')[:4].hex()), 'IsInherited')
        self.assertIsNone(abi.revert_error('execution reverted'))
        self.assertIsNone(abi.revert_error('0xdeadbeef'))

    def test_account_rule_decodes_the_epoch(self):
        row = (2, 1, False, '0x' + '11' * 20, '0x' + '22' * 20, '0x' + '00' * 20, b'\x00' * 32, 25 * WAD, 77, 3)
        with mock.patch('smart_account.chain._view', return_value=[row]) as view:
            data = chain.account_rule('0x' + '33' * 20, 5)
        self.assertEqual(view.call_args[0][4], [abi.RULE_ABI])
        self.assertEqual((data['kind'], data['active'], data['next_run_at'], data['epoch']), ('buy', False, 77, 3))


# ── reconcile ───────────────────────────────────────────────────────────

class EpochReconcileTests(test_reconcile.ReconcileTests):
    """Reuses ReconcileTests' emit/apply/subscribe helpers; its own tests
    run there, not twice."""

    def resubscribe(self, tx, plan=2, days=365):
        paid_until = int((self.now + timedelta(days=days)).timestamp())
        self.emit('FeeCollected', {'plan': str(plan), 'feeUsd': str(14999 * 10 ** 16), 'cusdAmount': '0',
                                   'cusdPlusShares': str(140 * WAD), 'pPlus': str(WAD),
                                   'paidUntil': str(paid_until)}, tx=tx)
        self.emit('Subscribed', {'plan': str(plan), 'feeUsd': str(14999 * 10 ** 16),
                                 'paidUntil': str(paid_until)}, tx=tx)

    def _rule(self, account, onchain_id, epoch, **fields):
        authorization = SmartAccountStandingAuthorization.objects.create(
            kind='payout', user=self.owner, rail='x', amount_usd=Decimal('10'), frequency='weekly',
            binding_hash='h')
        values = dict(smart_account=account, onchain_id=onchain_id, state='onchain', kind='payout',
                      token_in=VAULT, amount=Decimal('10.00'), frequency='weekly', active=True, epoch=epoch,
                      scheduled_for=self.now + timedelta(days=1), standing_authorization=authorization)
        values.update(fields)
        return SmartAccountRule.objects.create(**values)

    def test_first_subscribe_sets_epoch_one(self):
        account = self.subscribe()
        self.assertEqual(account.subscription_epoch, 1)

    def test_resubscribe_kills_earlier_rules_and_clears_the_beneficiary(self):
        account = self.subscribe()
        old = self._rule(account, 1, 1)
        heir_row = SmartAccountBeneficiary.objects.create(
            smart_account=account, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=90 * 86400, state='active', accepted_at=self.now)
        claim = SmartAccountClaim.objects.create(
            beneficiary_row=heir_row, initiated_tx='0xc1', initiated_at=self.now,
            executable_at=self.now + timedelta(days=90), state='pending')
        # Same tx: BeneficiaryRemoved (lower log index) then Subscribed.
        self.emit('BeneficiaryRemoved', {'beneficiary': self.heir.wallet}, tx='0xbb')
        self.resubscribe('0xbb')
        self.apply()
        account.refresh_from_db()
        old.refresh_from_db()
        heir_row.refresh_from_db()
        claim.refresh_from_db()
        self.assertEqual(account.subscription_epoch, 2)
        self.assertEqual((old.active, old.state, old.deactivated_reason, old.scheduled_for),
                         (False, 'cancelled', 'subscription_ended', None))
        self.assertIsNotNone(SmartAccountStandingAuthorization.objects.get(pk=old.standing_authorization_id).revoked_at)
        self.assertEqual(heir_row.state, 'removed')
        self.assertEqual(claim.state, 'cancelled')
        self.ops_alert_mock.assert_not_called()   # the chain's own events cleared it

    def test_leftover_designation_is_cleared_and_alerted(self):
        account = self.subscribe()
        row = SmartAccountBeneficiary.objects.create(
            smart_account=account, beneficiary_user=self.heir, beneficiary_address=self.heir.wallet,
            challenge_window_seconds=90 * 86400, state='pending_acceptance')
        self.resubscribe('0xbc')
        self.apply()
        row.refresh_from_db()
        self.assertEqual(row.state, 'removed')
        self.assertTrue(any('Subscribed' in str(c) for c in self.ops_alert_mock.call_args_list))

    def test_replay_is_idempotent_and_never_moves_the_epoch_back(self):
        account = self.subscribe()
        self.resubscribe('0xbd')
        self.apply()
        new = self._rule(SmartAccount.objects.get(pk=account.pk), 2, 2)
        from smart_account.models import SmartAccountEvent
        SmartAccountEvent.objects.update(applied_at=None)
        self.apply()
        account.refresh_from_db()
        new.refresh_from_db()
        self.assertEqual(account.subscription_epoch, 2)
        self.assertTrue(new.active)   # a rule of the current epoch is untouched
        self.assertEqual(new.state, 'onchain')

    def test_new_rule_is_stored_with_the_chain_epoch(self):
        account = self.subscribe()
        self.resubscribe('0xbe')
        self.apply()
        self.chain.rules[(self.contract, 4)] = {
            'kind': 'buy', 'frequency': 'weekly', 'active': True, 'token_in': VAULT,
            'token_out': '0x' + '71' * 20, 'payee': abi.ZERO_ADDRESS, 'payout_ref': '0x' + '00' * 32,
            'amount_usd_wei': 25 * WAD, 'next_run_at': int(self.now.timestamp()), 'epoch': 2}
        self.emit('RuleCreated', {'id': '4', 'kind': '2'})
        with mock.patch('smart_account.reconcile._asset_key_for', return_value=''):
            self.apply()
        rule = SmartAccountRule.objects.get(smart_account=account, onchain_id=4)
        self.assertEqual((rule.epoch, rule.active, rule.state), (2, True, 'onchain'))

    def test_a_rule_the_chain_reports_from_an_earlier_epoch_is_mirrored_dead(self):
        account = self.subscribe()
        self.resubscribe('0xbf')
        self.apply()
        self.chain.rules[(self.contract, 3)] = {
            'kind': 'buy', 'frequency': 'weekly', 'active': False, 'token_in': VAULT,
            'token_out': '0x' + '71' * 20, 'payee': abi.ZERO_ADDRESS, 'payout_ref': '0x' + '00' * 32,
            'amount_usd_wei': 25 * WAD, 'next_run_at': int(self.now.timestamp()), 'epoch': 1}
        self.emit('RuleUpdated', {'id': '3'})
        with mock.patch('smart_account.reconcile._asset_key_for', return_value=''):
            self.apply()
        rule = SmartAccountRule.objects.get(smart_account=account, onchain_id=3)
        self.assertEqual((rule.epoch, rule.active, rule.state, rule.deactivated_reason),
                         (1, False, 'cancelled', 'subscription_ended'))


# ReconcileTests' own test methods are not re-run under this subclass.
for _name in [n for n in vars(test_reconcile.ReconcileTests) if n.startswith('test_')]:
    if _name not in vars(EpochReconcileTests):
        setattr(EpochReconcileTests, _name, None)


# ── rules never run outside their epoch ─────────────────────────────────

class EpochRuleRunTests(test_tasks.RelayHarness):
    def _rule(self, epoch):
        slot = timezone.now() - timedelta(minutes=1)
        rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=9, state='onchain', kind='buy', token_in=VAULT,
            token_out='0x' + '71' * 20, amount=Decimal('25.00'), frequency='weekly', active=True,
            next_run_at=slot, scheduled_for=slot, epoch=epoch)
        self.chain.rules[(self.address, 9)] = {
            'kind': 'buy', 'frequency': 'weekly', 'active': True, 'token_in': VAULT,
            'token_out': '0x' + '71' * 20, 'payee': abi.ZERO_ADDRESS, 'payout_ref': '0x' + '00' * 32,
            'amount_usd_wei': 25 * WAD, 'next_run_at': 0, 'epoch': epoch}
        return rule

    def test_a_rule_of_an_earlier_epoch_is_not_due_and_never_built(self):
        SmartAccount.objects.filter(pk=self.account.pk).update(subscription_epoch=2, paid_until=timezone.now()
                                                               + timedelta(days=10), billing_status='current')
        rule = self._rule(1)
        self.assertNotIn(rule.pk, [r.pk for r in automation.due_rules()])
        out = {'sent': 0, 'skipped': 0, 'waiting': 0, 'errors': 0}
        rule = SmartAccountRule.objects.select_related('smart_account').get(pk=rule.pk)
        with mock.patch('smart_account.automation.build_rule_call') as build:
            automation._run_rule(rule, out)
        build.assert_not_called()
        self.assertEqual(out['skipped'], 1)
        self.assertEqual(self.signed, [])

    def test_a_rule_of_the_current_epoch_is_due(self):
        SmartAccount.objects.filter(pk=self.account.pk).update(subscription_epoch=2, paid_until=timezone.now()
                                                               + timedelta(days=10), billing_status='current')
        rule = self._rule(2)
        self.assertIn(rule.pk, [r.pk for r in automation.due_rules()])


# ── USDT first, DollarsCover is "no sale needed" ────────────────────────

DOLLARS_COVER = '0x' + keccak(text='DollarsCover()')[:4].hex()


class UsdtFirstBillingTests(test_tasks.RelayHarness):
    def setUp(self):
        super().setUp()
        p = mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=False)
        p.start()
        self.addCleanup(p.stop)

    def names(self):
        return [abi.decode_call(tx['data'])[0] for tx in self.signed]

    def test_collect_converts_usdt_that_covers_the_gap(self):
        self.due(10 * WAD)                       # US$5 short of the US$15 fee
        self.fund(USDT, self.address, 6 * WAD)   # ~US$5.95 net of 0.9%
        out = automation.collect_due_fees()
        self.assertEqual((out['short'], out.get('covered'), out['errors']), (0, 1, 0))
        self.assertEqual(self.names(), ['convertUsdt'])

    def test_dust_usdt_short_of_the_gap_does_not_block(self):
        self.due(10 * WAD)
        self.fund(USDT, self.address, WAD)        # far below the gap
        out = automation.start_payment_notices()
        self.assertEqual(out['sent'], 1)
        self.assertEqual(self.names(), ['startPaymentNotice'])

    def test_notice_is_not_started_while_usdt_covers_and_no_fee_due_message(self):
        self.due(14 * WAD)
        self.fund(USDT, self.address, 2 * WAD)
        with mock.patch('smart_account.notifications.fee_due') as fee_due:
            out = automation.start_payment_notices()
        self.assertEqual((out['sent'], out['errors'], out.get('covered')), (0, 0, 1))
        self.assertEqual(self.names(), ['convertUsdt'])
        fee_due.assert_not_called()

    def test_sub_floor_usdt_is_minted_as_cusd_for_the_fee(self):
        self.due(14 * WAD + WAD // 2)
        self.fund(USDT, self.address, 9 * WAD // 10)   # under the cUSD+ safe-mint floor
        automation.collect_due_fees()
        name, args = abi.decode_call(self.signed[0]['data'])
        self.assertEqual((name, args[0]), ('convertUsdt', abi.DOLLAR))

    def test_notice_revert_dollars_cover_is_not_an_error(self):
        self.due(10 * WAD)
        self.simulate_error = f"execution reverted: {DOLLARS_COVER}"
        out = automation.start_payment_notices()
        self.assertEqual((out['errors'], out.get('covered')), (0, 1))
        self.assertFalse(any('start_payment_notices' in str(c) for c in self.ops_alert_mock.call_args_list))

    def _sale_due(self):
        self.due(10 * WAD, billing=3, notice=self.paid_until + 10)
        SmartAccount.objects.update(notice_started_at=timezone.now() - timedelta(days=8))

    def _leg(self, account, shortfall, dollar, cap_shortfall=None):
        return [{'venue': '0x' + '52' * 20, 'token': '0x' + '71' * 20, 'max_in': 1, 'data': '0x1234',
                 'asset_key': 'crypto:BTCB', 'kind': 'crypto', 'expected_dollars_wei': shortfall,
                 'quote_ref': ''}]

    def test_forced_sale_converts_usdt_instead_of_selling(self):
        self._sale_due()
        self.fund(USDT, self.address, 6 * WAD)
        with mock.patch('smart_account.automation.plan_forced_sale') as plan:
            out = automation.run_forced_sales()
        plan.assert_not_called()
        self.assertEqual((out['sent'], out['errors'], out.get('covered')), (0, 0, 1))
        self.assertEqual(self.names(), ['convertUsdt'])

    def test_forced_sale_revert_dollars_cover_is_no_sale_and_no_failure(self):
        self._sale_due()
        self.simulate_error = f"{{'message': 'execution reverted', 'data': '{DOLLARS_COVER}'}}"
        with mock.patch('smart_account.automation.plan_forced_sale', side_effect=self._leg), \
                mock.patch('smart_account.automation._account_dollar', return_value=abi.DOLLAR):
            for _ in range(6):
                out = automation.run_forced_sales()
                self.assertEqual((out['errors'], out.get('covered')), (0, 1))
        sale = SmartAccountForcedSale.objects.get()
        self.assertEqual((sale.status, sale.attempts, sale.last_error), ('pending', 0, ''))
        self.assertEqual(sale.legs.count(), 0)
        self.ops_alert_mock.assert_not_called()

    def test_other_sale_reverts_still_fail(self):
        self._sale_due()
        self.simulate_error = 'execution reverted: 0x' + keccak(text='DollarsShort()')[:4].hex()
        with mock.patch('smart_account.automation.plan_forced_sale', side_effect=self._leg), \
                mock.patch('smart_account.automation._account_dollar', return_value=abi.DOLLAR):
            out = automation.run_forced_sales()
        self.assertEqual(out['errors'], 1)
        self.assertEqual(SmartAccountForcedSale.objects.get().status, 'failed')


# ── prepares and the relay ──────────────────────────────────────────────

class EpochPrepareTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')

    def _onchain_rule(self, account, epoch, onchain_id=7):
        return SmartAccountRule.objects.create(
            smart_account=account, onchain_id=onchain_id, state='onchain', kind='buy', token_in=VAULT,
            token_out='0x' + '71' * 20, amount=Decimal('25.00'), frequency='weekly', active=True, epoch=epoch)

    def test_cancel_rule_is_prepared_and_relayed_in_any_owned_state(self):
        for status, extra in (('expired', {}), ('active', {'billing_status': 'payment_due'}),
                              ('cancel_pending', {'cancel_requested_at': timezone.now()})):
            with self.subTest(status=status):
                user = self.make_user(f'o_{status}')
                account = self.make_account(user, status=status, subscription_epoch=1, **extra)
                rule = self._onchain_rule(account, 1)
                batch = services.prepare_cancel_rule(self.viewer(user), str(rule.internal_id))
                action = relay_policy.validate_batch(batch.calls, user, user.wallet, batch.request_id)
                self.assertEqual(action.kind, 'smart_rule_cancel')

    def test_cancel_of_an_earlier_epoch_rule_is_refused(self):
        account = self.make_account(self.owner, subscription_epoch=2)
        rule = self._onchain_rule(account, 1)
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_cancel_rule(self.viewer(self.owner), str(rule.internal_id))
        self.assertEqual(raised.exception.code, 'rule_not_found')

    def test_relay_refuses_a_cancel_once_the_epoch_moved_on(self):
        account = self.make_account(self.owner, subscription_epoch=1)
        rule = self._onchain_rule(account, 1)
        batch = services.prepare_cancel_rule(self.viewer(self.owner), str(rule.internal_id))
        SmartAccount.objects.filter(pk=account.pk).update(subscription_epoch=2)
        with self.assertRaises(sponsor_7702.PolicyError) as raised:
            relay_policy.validate_batch(batch.calls, self.owner, self.owner.wallet, batch.request_id)
        self.assertEqual(raised.exception.code, 'rule_epoch_changed')

    def test_edit_of_an_earlier_epoch_rule_is_refused(self):
        account = self.make_account(self.owner, subscription_epoch=2)
        rule = self._onchain_rule(account, 1)
        with self.assertRaises(services.PrepareError) as raised:
            services._existing_rule(account, str(rule.internal_id), 'buy')
        self.assertEqual(raised.exception.code, 'rule_not_found')

    def test_a_create_prepared_in_an_earlier_epoch_is_not_relayed(self):
        account = self.make_account(self.owner, subscription_epoch=1)
        rule_tuple = abi.rule_input('buy', 'weekly', VAULT, token_out='0x' + '71' * 20, amount_usd_wei=25 * WAD)
        batch = services._rule_batch(self.viewer(self.owner), account, None, dict(
            kind='buy', token_in=VAULT, token_out='0x' + '71' * 20, amount=Decimal('25.00'), frequency='weekly'),
            rule_tuple, ['x'])
        draft = SmartAccountRule.all_objects.get(state='draft', smart_account=account)
        self.assertEqual(draft.epoch, 1)
        relay_policy.validate_batch(batch.calls, self.owner, self.owner.wallet, batch.request_id)
        SmartAccount.objects.filter(pk=account.pk).update(subscription_epoch=2)
        with self.assertRaises(sponsor_7702.PolicyError) as raised:
            relay_policy.validate_batch(batch.calls, self.owner, self.owner.wallet, batch.request_id)
        self.assertEqual(raised.exception.code, 'rule_epoch_changed')

    def _subscribe_summary(self, account):
        self.fund(VAULT, self.owner.wallet, 500 * WAD)
        batch = services.prepare_subscribe(self.viewer(self.owner), 'annual',
                                           [{'asset_key': 'cusd_plus', 'units': str(200 * WAD)}], True)
        return batch.summary

    def test_resubscribe_after_expiry_says_rules_and_beneficiary_do_not_come_back(self):
        account = self.make_account(self.owner, status='expired', subscription_epoch=1,
                                    paid_until=timezone.now() - timedelta(days=3))
        summary = self._subscribe_summary(account)
        self.assertIn('Tus reglas y tu beneficiario anteriores no vuelven: créalos de nuevo.', summary)
        self.assertEqual(summary[-1], services.RESUBSCRIBE_NOTE)

    def test_first_subscribe_has_no_resubscribe_note(self):
        summary = self._subscribe_summary(None)
        self.assertNotIn(services.RESUBSCRIBE_NOTE, summary)
