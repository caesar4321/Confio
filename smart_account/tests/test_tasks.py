"""Relayer path and tasks: idempotency under a double run and a crash
between sign and broadcast; fail-closed on RPC and quote failures (10.3)."""
import itertools
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from smart_account import abi, automation, quotes, relayer, tasks
from smart_account.assets import Asset
from smart_account.models import (
    SmartAccount, SmartAccountBeneficiary, SmartAccountClaim, SmartAccountForcedSale, SmartAccountRelayTx,
    SmartAccountRule, SmartAccountRuleRun,
)

from .base import CUSD, SWAP_ROUTER, USDT, VAULT, SmartAccountTestCase, WAD, own_nonce_lock

SPONSOR = '0x' + '5a' * 20


class RelayHarness(SmartAccountTestCase):
    """A stub node and a stub KMS signer around relayer.send_relayer_call."""

    def setUp(self):
        super().setUp()
        self.sent = []            # raw txs that reached eth_sendRawTransaction
        self.signed = []          # every tx the signer signed
        self.rows_at_broadcast = []
        self.broadcast_error = None
        self.simulate_error = None
        self.known_hashes = set()
        self.gas_price = 100_000_000
        counter = itertools.count(1)

        def sign(tx):
            n = next(counter)
            self.signed.append(tx)
            return f'0xraw{n}', '0x' + format(n, 'x').rjust(64, '0')

        signer = mock.Mock(address=SPONSOR)
        signer.sign_typed_transaction.side_effect = sign

        def rpc(method, params):
            if method == 'eth_call':
                if self.simulate_error:
                    raise RuntimeError(self.simulate_error)
                return '0x'
            if method == 'eth_gasPrice':
                return hex(self.gas_price)
            if method == 'eth_getTransactionCount':
                return hex(7)
            if method == 'eth_getBalance':
                return hex(10 ** 18)
            if method == 'eth_sendRawTransaction':
                # Durability: the row with the signed hash exists BEFORE this call.
                self.rows_at_broadcast.append(list(SmartAccountRelayTx.objects.values_list('status', flat=True)))
                if self.broadcast_error:
                    raise RuntimeError(self.broadcast_error)
                self.sent.append(params[0])
                return '0x'
            if method == 'eth_getTransactionByHash':
                return {'hash': params[0]} if params[0] in self.known_hashes else None
            if method == 'eth_getTransactionReceipt':
                return None
            raise AssertionError(method)

        for p in (
                mock.patch('blockchain.evm_kms_signer.get_bsc_sponsor_signer_from_settings', return_value=signer),
                mock.patch('smart_account.chain.rpc', side_effect=rpc),
                mock.patch('cusd_plus.sponsor_7702.acquire_sponsor_nonce_lock', side_effect=own_nonce_lock),
                mock.patch('cusd_plus.sponsor_7702.release_sponsor_nonce_lock'),
                mock.patch('smart_account.tasks.check_relay_tx.apply_async'),
                mock.patch('smart_account.tasks.reconcile_events.apply_async')):
            p.start()
            self.addCleanup(p.stop)
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner, paid_days=-1)
        self.address = self.account.contract_address
        self.paid_until = int(self.account.paid_until.timestamp())

    def due(self, dollars, fee=15 * WAD, billing=1, notice=0, sold_for=0):
        views = {'status': 1, 'billingStatus': billing, 'paidUntil': self.paid_until, 'feeUsd': fee,
                 'dollarsUsd': dollars, 'noticeStartedAt': notice, 'forcedSaleForPeriod': sold_for}
        for name, value in views.items():
            self.chain.views[(self.address, name)] = value


class SendRelayerCallTests(RelayHarness):
    def _send(self, source='period:1'):
        return relayer.send_relayer_call(self.account, abi.encode_call('collectFee'), 'smart_collect_fee', source)

    def test_plain_type_2_from_the_sponsor_with_the_row_written_before_broadcast(self):
        row, created = self._send()
        self.assertTrue(created)
        tx = self.signed[0]
        self.assertEqual((tx['type'], tx['nonce'], tx['value'], tx['to'].lower()), (2, 7, 0, self.address))
        self.assertEqual(tx['data'], abi.encode_call('collectFee'))
        self.assertEqual(tx['gas'], abi.RELAY_GAS['smart_collect_fee'])
        self.assertEqual(self.rows_at_broadcast, [['signed']])
        row.refresh_from_db()
        self.assertEqual((row.status, row.signed_tx_hash), ('sent', '0x' + '1'.rjust(64, '0')))

    def test_double_run_signs_and_sends_once(self):
        first, created = self._send()
        second, created_again = self._send()
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual((len(self.signed), len(self.sent)), (1, 1))

    def test_crash_between_sign_and_broadcast_leaves_a_signed_row_and_no_second_send(self):
        self.broadcast_error = 'connection reset'
        with self.assertRaises(RuntimeError):
            self._send()
        row = SmartAccountRelayTx.objects.get()
        self.assertEqual(row.status, 'signed')
        self.broadcast_error = None
        again, created = self._send()
        self.assertFalse(created)                       # the durable row is found, nothing is signed
        self.assertEqual((again.pk, len(self.signed), len(self.sent)), (row.pk, 1, 0))
        # The reconciler: the node never saw the hash -> dropped after the grace window ...
        SmartAccountRelayTx.objects.update(updated_at=timezone.now() - timedelta(minutes=10))
        self.assertEqual(tasks.reconcile_relay_txs()['dropped'], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, 'dropped')
        # ... which frees the slot: the next run sends a fresh transaction.
        _row, created = self._send()
        self.assertTrue(created)
        self.assertEqual(len(self.sent), 1)

    def test_a_signed_row_the_node_knows_is_promoted_not_dropped(self):
        self.broadcast_error = 'timeout after send'
        with self.assertRaises(RuntimeError):
            self._send()
        row = SmartAccountRelayTx.objects.get()
        self.known_hashes.add(row.signed_tx_hash)
        SmartAccountRelayTx.objects.update(updated_at=timezone.now() - timedelta(minutes=10))
        self.assertEqual(tasks.reconcile_relay_txs()['promoted'], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, 'sent')

    def test_simulation_revert_and_gas_price_cap_refuse_before_signing(self):
        self.simulate_error = 'execution reverted'
        with self.assertRaises(relayer.RelayError) as raised:
            self._send()
        self.assertEqual(raised.exception.code, 'simulation_reverted')
        self.simulate_error = None
        self.gas_price = 50_000_000_000
        with self.assertRaises(relayer.RelayError) as raised:
            self._send()
        self.assertEqual(raised.exception.code, 'gas_price_too_high')
        self.assertEqual((self.signed, SmartAccountRelayTx.objects.count()), ([], 0))

    def test_sponsor_lock_and_kind_are_required(self):
        with mock.patch('cusd_plus.sponsor_7702.acquire_sponsor_nonce_lock', return_value=None):
            with self.assertRaises(relayer.RelayError) as raised:
                self._send()
        self.assertEqual(raised.exception.code, 'sponsor_busy')
        with self.assertRaises(relayer.RelayError):
            relayer.send_relayer_call(self.account, '0x', 'subscribe', 'x')
        with override_settings(SMART_ACCOUNT_ENABLED=False):
            with self.assertRaises(relayer.RelayError) as raised:
                self._send()
            self.assertEqual(raised.exception.code, 'disabled')


class BillingTaskTests(RelayHarness):
    def test_tasks_are_no_ops_unless_enabled_and_configured(self):
        self.due(20 * WAD)
        # Exits and protective work (expiry returns, resolving relay rows,
        # mirroring events, claim notices) need only the factory: switching
        # the flag off must never trap assets or hide a claim.
        exits = (tasks.return_expired, tasks.reconcile_relay_txs, tasks.reconcile_events, tasks.claim_notices)
        for settings in (dict(SMART_ACCOUNT_ENABLED=False), dict(SMART_ACCOUNT_FACTORY_ADDRESS='')):
            with override_settings(**settings):
                for task in (tasks.collect_due_fees, tasks.start_payment_notices, tasks.run_forced_sales,
                             tasks.convert_usdt, tasks.run_rules, tasks.return_expired, tasks.claim_notices,
                             tasks.sync_entitlements, tasks.latch_confio_sale, tasks.reconcile_events,
                             tasks.reconcile_relay_txs):
                    if task in exits and settings.get('SMART_ACCOUNT_FACTORY_ADDRESS') != '':
                        continue
                    self.assertEqual(task(), {'skipped': 'disabled'}, task.name)
        self.assertEqual(self.signed, [])

    def test_collect_fee_once_per_period_under_a_double_run(self):
        self.due(20 * WAD)
        self.assertEqual(automation.collect_due_fees()['sent'], 1)
        self.assertEqual(automation.collect_due_fees()['sent'], 0)
        self.assertEqual(len(self.sent), 1)
        row = SmartAccountRelayTx.objects.get()
        self.assertEqual((row.kind, row.source_id), ('smart_collect_fee', f'period:{self.paid_until}'))
        # The mirror is untouched: only the FeeCollected event moves it.
        self.account.refresh_from_db()
        self.assertEqual(int(self.account.paid_until.timestamp()), self.paid_until)

    def test_short_dollars_start_a_notice_instead_and_tell_the_owner_daily(self):
        self.due(3 * WAD)
        self.assertEqual(automation.collect_due_fees()['short'], 1)
        self.assertEqual(self.sent, [])
        with mock.patch('smart_account.notifications.fee_due') as told:
            out = automation.start_payment_notices()
            self.assertEqual((out['sent'], out['notified']), (1, 1))
            automation.start_payment_notices()
            self.assertEqual(told.call_count, 1)                      # not twice the same day
            SmartAccount.objects.update(last_due_notice_at=timezone.now() - timedelta(days=1, minutes=5))
            automation.start_payment_notices()
            self.assertEqual(told.call_count, 2)
        self.assertEqual(SmartAccountRelayTx.objects.filter(kind='smart_payment_notice').count(), 1)
        self.assertEqual(self.signed[0]['data'], abi.encode_call('startPaymentNotice'))

    def test_rpc_failure_leaves_state_unchanged_and_is_reported(self):
        self.due(20 * WAD)
        self.chain.fail.add('account_view')
        out = automation.collect_due_fees()
        self.assertEqual((out['errors'], out['sent']), (1, 0))
        self.assertEqual((self.signed, SmartAccountRelayTx.objects.count()), ([], 0))
        self.assertTrue(self.ops_alert_mock.called)
        self.chain.fail.clear()
        self.assertEqual(automation.collect_due_fees()['sent'], 1)   # retried on the next run

    def test_nothing_is_sent_while_the_relayer_is_paused_or_the_mirror_is_ahead(self):
        self.due(20 * WAD)
        self.chain.paused = True
        self.assertEqual(automation.collect_due_fees(), {'skipped': 'relayer_paused'})
        self.chain.paused = False
        self.due(20 * WAD, billing=0)        # the chain says Current
        self.assertEqual(automation.collect_due_fees()['sent'], 0)
        self.assertEqual(self.sent, [])

    def test_a_cancelled_or_inherited_account_is_never_charged(self):
        self.due(20 * WAD)
        SmartAccount.objects.update(cancel_requested_at=timezone.now())
        self.assertEqual(automation.collect_due_fees(), {'sent': 0, 'short': 0, 'skipped': 0, 'errors': 0})
        SmartAccount.objects.update(cancel_requested_at=None, inherited_at=timezone.now())
        self.assertEqual(automation.collect_due_fees()['sent'], 0)

    def test_convert_usdt_reads_the_balance_fresh_and_keys_each_occurrence(self):
        SmartAccount.objects.update(paid_until=timezone.now() + timedelta(days=5))
        self.chain.views[(self.address, 'status')] = 1
        self.assertEqual(automation.convert_usdt()['sent'], 0)
        self.fund(USDT, self.address, 40 * WAD)
        with mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=False):
            self.assertEqual(automation.convert_usdt()['sent'], 1)
            self.assertEqual(automation.convert_usdt()['sent'], 0)
        name, args = abi.decode_call(self.signed[0]['data'])
        self.assertEqual((name, args[0]), ('convertUsdt', abi.DOLLAR))
        self.assertEqual(args[1], 40 * WAD * (10_000 - 90 - 30) // 10_000)   # above the contract's floor
        self.assertEqual(int(args[2], 16), 0)                                # no referral arm by default
        SmartAccountRelayTx.objects.update(status='confirmed')
        with mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True):
            self.assertEqual(automation.convert_usdt()['sent'], 1)           # a later arrival converts again
        self.assertEqual(abi.decode_call(self.signed[1]['data'])[1][0], abi.DOLLAR_PLUS)
        self.assertEqual(sorted(SmartAccountRelayTx.objects.values_list('source_id', flat=True)), ['usdt:0', 'usdt:1'])


class ForcedSaleTests(RelayHarness):
    def setUp(self):
        super().setUp()
        self.due(5 * WAD, fee=150 * WAD, billing=3, notice=self.paid_until + 10)
        SmartAccount.objects.update(notice_started_at=timezone.now() - timedelta(days=8))
        self.btc = Asset('crypto:BTCB', 'crypto', 'BTC', 'Bitcoin', '0x' + '71' * 20, 2 * 10 ** 15, 18,
                         Decimal('120'), True)
        self.gold = Asset('crypto:XAUT', 'crypto', 'XAUT', 'Tether Gold', '0x' + '72' * 20, 25_000, 6,
                          Decimal('100'), True)
        self.token = mock.Mock()

        def sell(token, dollar, amount_in):
            value = Decimal(amount_in) / Decimal(self.current.units) * self.current.value_usd
            net = int(value * Decimal('0.991') * WAD)
            return {'call': {'to': SWAP_ROUTER, 'value': '0', 'data': '0x1234'}, 'token': self.current.address,
                    'max_in': amount_in, 'expected_dollars_wei': net}

        def by_address(address, include_unlisted=False):
            self.current = self.btc if address == self.btc.address else self.gold
            return self.token

        for p in (mock.patch('smart_account.quotes.crypto_sell_call', side_effect=sell),
                  mock.patch('cusd_plus.crypto_catalog.by_address', side_effect=by_address),
                  mock.patch('cusd_plus.crypto_policy.live_fee_bps', return_value=90),
                  mock.patch('smart_account.automation._account_dollar', return_value=abi.DOLLAR_PLUS)):
            p.start()
            self.addCleanup(p.stop)

    def test_target_sits_inside_the_contracts_cap(self):
        for shortfall in (WAD // 10, 15 * WAD, 145 * WAD):
            target, cap = automation.forced_sale_target_wei(shortfall)
            self.assertEqual(cap, shortfall + shortfall * 500 // 10_000 + WAD)
            self.assertTrue(shortfall < target < cap)

    def test_two_legs_when_no_single_holding_covers_the_fee(self):
        with mock.patch('smart_account.automation.sale_candidates', return_value=[self.btc, self.gold]):
            out = automation.run_forced_sales()
        self.assertEqual(out['sent'], 1)
        name, args = abi.decode_call(self.signed[0]['data'])
        legs, min_out = args[0], args[1]
        self.assertEqual(name, 'forcedSale')
        self.assertEqual([leg[1].lower() for leg in legs], [self.btc.address, self.gold.address])  # largest first
        self.assertEqual(min_out, 145 * WAD)                 # the shortfall
        self.assertEqual(self.signed[0]['gas'], abi.RELAY_GAS_SALE_BASE + 2 * abi.RELAY_GAS_SALE_LEG['crypto'])
        sale = SmartAccountForcedSale.objects.get()
        self.assertEqual((sale.status, sale.attempts, sale.legs.count()), ('sent', 1, 2))
        # A second run while it is on the wire: no new quote, no second sale.
        with mock.patch('smart_account.automation.sale_candidates') as candidates:
            self.assertEqual(automation.run_forced_sales()['sent'], 0)
            candidates.assert_not_called()
        self.assertEqual(len(self.sent), 1)

    def test_holdings_that_do_not_cover_the_fee_sell_nothing_and_return_nothing(self):
        small = Asset('crypto:BTCB', 'crypto', 'BTC', 'Bitcoin', self.btc.address, 10 ** 15, 18, Decimal('40'), True)
        with mock.patch('smart_account.automation.sale_candidates', return_value=[small]):
            out = automation.run_forced_sales()
        self.assertEqual((out['unsellable'], out['sent']), (1, 0))
        self.assertEqual(self.sent, [])
        self.assertFalse(SmartAccountRelayTx.objects.filter(kind='smart_return').exists())
        sale = SmartAccountForcedSale.objects.get()
        self.assertEqual((sale.status, sale.attempts), ('failed', 1))

    def test_quote_failure_is_recorded_and_retried_and_a_closed_market_is_not_an_attempt(self):
        with mock.patch('smart_account.automation.sale_candidates', return_value=[self.btc, self.gold]):
            with mock.patch('smart_account.quotes.crypto_sell_call',
                            side_effect=quotes.QuoteUnavailable('crypto_quote_unavailable')):
                self.assertEqual(automation.run_forced_sales()['errors'], 1)
            sale = SmartAccountForcedSale.objects.get()
            self.assertEqual((sale.status, sale.attempts), ('failed', 1))
            self.assertEqual(self.sent, [])
            with mock.patch('smart_account.quotes.crypto_sell_call',
                            side_effect=quotes.QuoteUnavailable('market_closed', retry_later=True)):
                self.assertEqual(automation.run_forced_sales()['waiting'], 1)
            sale.refresh_from_db()
            self.assertEqual(sale.attempts, 1)
            self.assertEqual(automation.run_forced_sales()['sent'], 1)   # a later retry succeeds

    def test_no_sale_before_the_notice_ends_or_twice_for_one_period(self):
        with mock.patch('smart_account.automation.sale_candidates', return_value=[self.btc, self.gold]):
            self.due(5 * WAD, fee=150 * WAD, billing=2, notice=self.paid_until + 10)
            self.assertEqual(automation.run_forced_sales()['sent'], 0)
            self.due(5 * WAD, fee=150 * WAD, billing=3, notice=self.paid_until + 10, sold_for=self.paid_until)
            self.assertEqual(automation.run_forced_sales()['sent'], 0)
            self.due(200 * WAD, fee=150 * WAD, billing=3, notice=self.paid_until + 10)
            self.assertEqual(automation.run_forced_sales()['sent'], 0)   # dollars cover: collectFee's job
        self.assertEqual(self.sent, [])

    def test_reverted_sale_is_recorded_as_failed(self):
        with mock.patch('smart_account.automation.sale_candidates', return_value=[self.btc, self.gold]):
            automation.run_forced_sales()
        row = SmartAccountRelayTx.objects.get()
        row.status = 'reverted'
        row.save()
        automation.on_relay_tx_final(row)
        self.assertEqual(SmartAccountForcedSale.objects.get().status, 'failed')


class RuleTaskTests(RelayHarness):
    def setUp(self):
        super().setUp()
        SmartAccount.objects.update(paid_until=timezone.now() + timedelta(days=20))
        self.account.refresh_from_db()
        self.payee = self.make_user('payee')
        self.slot = timezone.now().replace(microsecond=0) - timedelta(minutes=3)
        self.rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=4, state='onchain', kind='send', token_in=VAULT,
            payee_address=self.payee.wallet, payee_user=self.payee, amount=Decimal('25.00'), frequency='weekly',
            next_run_at=self.slot, scheduled_for=self.slot, active=True)
        self.chain.views[(self.address, 'status')] = 1
        self.chain.views[(self.address, 'billingStatus')] = 0
        self.chain.rules[(self.address, 4)] = {
            'kind': 'send', 'frequency': 'weekly', 'active': True, 'payee': self.payee.wallet.lower(),
            'amount_usd_wei': 25 * WAD, 'next_run_at': int(self.slot.timestamp())}
        # The owner's Face-confirmed consent for exactly this rule.
        from smart_account import payouts
        from smart_account.models import SmartAccountStandingAuthorization
        self.authorization = SmartAccountStandingAuthorization.objects.create(
            kind='send', user=self.account.owner_user, payee_address=self.payee.wallet.lower(), rail='',
            amount_usd=Decimal('25.00'), frequency='weekly', face_action_key='out:' + 'f' * 64,
            binding_hash=payouts.send_binding_hash(self.address, self.payee.wallet, Decimal('25.00'), 'weekly'))
        SmartAccountRule.objects.filter(pk=self.rule.pk).update(standing_authorization=self.authorization)
        self.rule.refresh_from_db()
        self.fund(VAULT, self.address, 500 * WAD)
        eligible = mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True)
        eligible.start()
        self.addCleanup(eligible.stop)

    def test_send_rule_runs_once_per_slot(self):
        self.assertEqual(automation.run_rules()['sent'], 1)
        self.assertEqual(automation.run_rules()['sent'], 0)
        self.assertEqual(len(self.sent), 1)
        name, args = abi.decode_call(self.signed[0]['data'])
        self.assertEqual((name, args[0]), ('executeRule', 4))
        self.assertEqual(args[1], abi.send_rule_data(abi.DOLLAR_PLUS, 25 * WAD * 999 // 1000))
        run = SmartAccountRuleRun.objects.get()
        self.assertEqual((run.status, run.scheduled_for), ('sent', self.slot))
        row = SmartAccountRelayTx.objects.get()
        self.assertEqual(row.source_id, f'rule:{self.rule.pk}:{int(self.slot.timestamp())}')

    def test_payee_in_the_other_dollar_gets_the_fee_free_conversion(self):
        with mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=False):
            automation.run_rules()
        args = abi.decode_call(self.signed[0]['data'])[1]
        self.assertEqual(args[1], abi.send_rule_data(abi.DOLLAR, 25 * WAD * 995 // 1000))

    def test_rpc_failure_changes_nothing(self):
        self.chain.fail.add('account_view')
        out = automation.run_rules()
        self.assertEqual((out['errors'], out['sent']), (1, 0))
        self.assertEqual(self.signed, [])
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.scheduled_for, self.slot)
        self.chain.fail.clear()
        self.assertEqual(automation.run_rules()['sent'], 1)

    def test_not_run_while_payment_is_due_or_before_the_contracts_gap(self):
        self.chain.views[(self.address, 'billingStatus')] = 1
        self.assertEqual(automation.run_rules()['sent'], 0)
        self.chain.views[(self.address, 'billingStatus')] = 0
        self.chain.rules[(self.address, 4)]['next_run_at'] = int(timezone.now().timestamp()) + 3600
        self.assertEqual(automation.run_rules()['waiting'], 1)
        self.assertEqual(self.signed, [])

    def test_insufficient_balance_is_skipped_and_told_once(self):
        self.fund(VAULT, self.address, WAD)
        with mock.patch('smart_account.notifications.rule_run') as told:
            self.assertEqual(automation.run_rules()['skipped'], 1)
            automation.run_rules()
            self.assertEqual(told.call_count, 1)
        self.assertEqual(SmartAccountRuleRun.objects.get().status, 'skipped')
        self.assertEqual(self.signed, [])

    def test_payee_wallet_change_deactivates_the_rule(self):
        from users.models import Account
        Account.objects.filter(user=self.payee, account_type='personal').update(bsc_address='0x' + '8c' * 20)
        automation.run_rules()
        self.rule.refresh_from_db()
        self.assertEqual((self.rule.active, self.rule.deactivated_reason), (False, 'payee_wallet_changed'))
        self.assertEqual(self.signed, [])

    def test_quote_failure_on_a_buy_rule_sends_nothing(self):
        SmartAccountRule.objects.filter(pk=self.rule.pk).update(kind='buy', token_out='0x' + '71' * 20,
                                                                payee_address='', payee_user=None)
        with mock.patch('cusd_plus.crypto_catalog.by_address', return_value=mock.Mock()), \
                mock.patch('smart_account.assets.is_feed_token', return_value=True), \
                mock.patch('cusd_plus.crypto_risk.trading_ready', return_value=True), \
                mock.patch('cusd_plus.crypto_risk.buy_enabled', return_value=True), \
                mock.patch('smart_account.quotes.crypto_buy_call',
                           side_effect=quotes.QuoteUnavailable('crypto_quote_unavailable')):
            out = automation.run_rules()
        self.assertEqual(out['errors'], 1)
        self.assertEqual((self.signed, SmartAccountRelayTx.objects.count()), ([], 0))
        self.assertEqual(SmartAccountRuleRun.objects.get().status, 'failed')

    def test_closed_market_waits_for_the_next_session(self):
        SmartAccountRule.objects.filter(pk=self.rule.pk).update(kind='buy', token_out='0x' + '73' * 20,
                                                                payee_address='', payee_user=None)
        with mock.patch('cusd_plus.crypto_catalog.by_address', return_value=None), \
                mock.patch('smart_account.assets.stock_by_address', return_value=('AAPLon', {})), \
                override_settings(CUSD_PLUS_STOCK_TRADING_ENABLED=True), \
                mock.patch('cusd_plus.eligibility.check_stock_buy_eligibility', return_value=True), \
                mock.patch('smart_account.quotes.stock_buy_notional', return_value=Decimal('24.50')), \
                mock.patch('smart_account.quotes.stock_buy_call',
                           side_effect=quotes.QuoteUnavailable('market_closed', retry_later=True)):
            self.assertEqual(automation.run_rules()['waiting'], 1)
        self.assertEqual(SmartAccountRuleRun.objects.get().status, 'pending')
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.scheduled_for, self.slot)   # same slot, tried again next tick

    def test_calendar_schedule_never_catches_up_missed_runs(self):
        start = timezone.now().replace(microsecond=0) - timedelta(days=40)
        self.rule.scheduled_for, self.rule.next_run_at = start, start
        automation.schedule_next(self.rule)
        self.assertGreater(self.rule.scheduled_for, timezone.now())
        self.assertLessEqual(self.rule.scheduled_for, timezone.now() + timedelta(days=7))
        jan31 = timezone.now().replace(year=2027, month=1, day=31)
        self.assertEqual(automation.next_slot('monthly', jan31).day, 28)


class ReturnAndNoticeTests(RelayHarness):
    def test_return_per_token_and_a_failing_token_does_not_block_the_others(self):
        SmartAccount.objects.update(cancel_requested_at=timezone.now() - timedelta(days=40))
        self.chain.views[(self.address, 'status')] = 3
        self.fund(VAULT, self.address, 5 * WAD)
        self.fund(CUSD, self.address, 2 * WAD)
        original = relayer.simulate

        def simulate(sponsor, to, calldata, gas):
            if VAULT[2:] in calldata:
                raise relayer.RelayError('simulation_reverted', 'vault paused')
            return original(sponsor, to, calldata, gas)
        with mock.patch('smart_account.relayer.simulate', side_effect=simulate):
            out = automation.return_expired()
        self.assertEqual((out['sent'], out['errors']), (1, 1))
        self.assertEqual(self.signed[0]['data'], abi.encode_call('returnAsset', CUSD))
        out = automation.return_expired()                      # cUSD is on the wire; cUSD+ is retried
        self.assertEqual((out['sent'], out['skipped']), (1, 1))
        self.assertEqual(self.signed[1]['data'], abi.encode_call('returnAsset', VAULT))

    def test_nothing_is_returned_without_a_signed_cancellation(self):
        self.due(0)
        self.fund(VAULT, self.address, 5 * WAD)
        automation.return_expired()
        self.assertEqual(self.signed, [])

    def test_owner_is_told_once_when_the_account_is_empty(self):
        SmartAccount.objects.update(cancel_requested_at=timezone.now() - timedelta(days=40))
        self.chain.views[(self.address, 'status')] = 3
        with mock.patch('smart_account.notifications.assets_returned') as told:
            automation.return_expired()
            automation.return_expired()
        told.assert_called_once()

    def test_claim_notices_rise_near_the_end_and_never_repeat_within_the_interval(self):
        self.assertEqual(automation.claim_notice_interval(timedelta(days=90)), timedelta(days=7))
        self.assertEqual(automation.claim_notice_interval(timedelta(days=20)), timedelta(days=3))
        self.assertEqual(automation.claim_notice_interval(timedelta(days=2)), timedelta(days=1))
        heir = self.make_user('heir')
        row = SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=heir, beneficiary_address=heir.wallet,
            challenge_window_seconds=90 * 86400, state='active', designated_at=timezone.now())
        claim = SmartAccountClaim.objects.create(
            beneficiary_row=row, initiated_at=timezone.now() - timedelta(days=8), initiated_tx='0x' + '09' * 32,
            executable_at=timezone.now() + timedelta(days=82),
            last_owner_notice_at=timezone.now() - timedelta(days=8))
        with mock.patch('smart_account.notifications.claim_initiated_owner') as owner_told, \
                mock.patch('smart_account.notifications.claim_executable') as heir_told:
            self.assertEqual(automation.claim_notices()['owner_notices'], 1)
            self.assertEqual(automation.claim_notices()['owner_notices'], 0)
            SmartAccountClaim.objects.filter(pk=claim.pk).update(executable_at=timezone.now() - timedelta(minutes=1))
            self.assertEqual(automation.claim_notices()['executable'], 1)
            self.assertEqual(automation.claim_notices()['executable'], 0)
        self.assertEqual((owner_told.call_count, heir_told.call_count), (1, 1))

    def test_beneficiary_wallet_change_is_detected_and_a_pending_designation_lapses(self):
        from users.models import Account
        heir = self.make_user('heir')
        other = self.make_user('other')
        active = SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=heir, beneficiary_address=heir.wallet,
            challenge_window_seconds=90 * 86400, state='active', designated_at=timezone.now())
        pending = SmartAccountBeneficiary.objects.create(
            smart_account=self.account, beneficiary_user=other, beneficiary_address=other.wallet,
            challenge_window_seconds=90 * 86400, state='pending_acceptance', designated_at=timezone.now(),
            expires_at=timezone.now() - timedelta(minutes=1))
        Account.objects.filter(user=heir, account_type='personal').update(bsc_address='0x' + '8d' * 20)
        with mock.patch('smart_account.notifications.beneficiary_address_changed') as told:
            out = automation.claim_notices()
        self.assertEqual((out['stale'], out['lapsed']), (1, 1))
        told.assert_called_once()
        active.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual((active.state, pending.state), ('stale_address', 'lapsed'))


class NotificationTests(SmartAccountTestCase):
    def test_notifications_go_through_the_service_in_spanish_with_a_route(self):
        from notifications.models import Notification
        from smart_account import notifications
        owner, heir = self.make_user('owner'), self.make_user('heir')
        account = self.make_account(owner)
        row = SmartAccountBeneficiary.objects.create(
            smart_account=account, beneficiary_user=heir, beneficiary_address=heir.wallet,
            challenge_window_seconds=180 * 86400, state='pending_acceptance', designated_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30))
        notifications.beneficiary_named(row)
        note = Notification.objects.get(user=heir)
        self.assertIn('te nombró beneficiario', note.message)
        self.assertEqual((note.data['screen'], note.data['designationId']),
                         ('BeneficiaryInvite', str(row.designation_id)))
        claim = SmartAccountClaim.objects.create(
            beneficiary_row=row, initiated_at=timezone.now(), initiated_tx='0x' + '0a' * 32,
            executable_at=timezone.now() + timedelta(days=180))
        notifications.claim_initiated_owner(claim)
        note = Notification.objects.filter(user=owner).latest('id')
        self.assertEqual((note.notification_type, note.data['screen']), ('SECURITY_ALERT', 'BeneficiaryStatus'))

    def test_a_failing_notification_never_breaks_the_caller(self):
        from smart_account import notifications
        self.assertIsNone(notifications.safe(mock.Mock(side_effect=RuntimeError('fcm down'), __name__='x')))
