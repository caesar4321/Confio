"""Review round 4: cUSD+ sizing at the post-accrual pPlus (with pPlus
GROWING between the stored value, the call's own accrue() and inclusion),
rule edits keep their schedule, dropped relay transactions free their slot,
the USDT conversion floor, Face bound to the authorization/draft row, and
the stock rule minimum."""
from datetime import timedelta
from decimal import ROUND_CEILING, Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from eth_abi import decode

from smart_account import abi, automation, payouts, quotes, reconcile, services, tasks
from smart_account.models import (
    SmartAccount, SmartAccountBeneficiary, SmartAccountForcedSale, SmartAccountRelayTx, SmartAccountRule,
    SmartAccountRuleRun, SmartAccountStandingAuthorization,
)

from .base import CUSD, SWAP_ROUTER, USDT, VAULT, SmartAccountTestCase, WAD
# Module reference only: a TestCase bound to a name here is collected again.
from . import test_tasks

# The real window, captured before the suite-wide patch in base.py starts.
REAL_PLUS_PRICE_WINDOW = quotes.plus_price_window

BPS = 10_000
P_PLUS = 1_050_000_000_000_000_000          # stored pPlus
LAST = 1_100_000_000_000_000_000            # oracle at the last accrue()
LIVE = LAST + LAST * 50 // BPS              # oracle now: 0.5% not accrued yet
SHARE_BPS = 1_500
DAILY = Decimal(str(1.05 ** (1 / 365) - 1))
FACE_MESSAGE = 'Confirma que eres tú con tu rostro para continuar.'


def ceil_shares(amount_wei, p_plus):
    return (amount_wei * WAD + p_plus - 1) // p_plus


def contract_p_plus(oracle_at_inclusion):
    """CusdPlusVault.accrue() from the stored baseline, as executeRule /
    forcedSale / collectFee run it before converting."""
    return quotes.apply_growth(P_PLUS, LAST, oracle_at_inclusion, SHARE_BPS)


def inclusion_oracles():
    """Mined at once, a minute later, and at the end of the relay horizon."""
    out = []
    for seconds in (0, 60, quotes.RELAY_HORIZON_SECONDS):
        grown = Decimal(LIVE) * (1 + DAILY * Decimal(seconds) / Decimal(86_400))
        out.append(int(grown.to_integral_value(rounding=ROUND_CEILING)))
    return out


class _GrowingVault:
    """cUSD+ whose pPlus grows: stored < accrued now < accrued at inclusion."""

    def growing_vault(self):
        patches = [
            mock.patch('cusd_plus.vault.p_plus_wad', return_value=P_PLUS),
            mock.patch('cusd_plus.vault.last_oracle_price_wad', return_value=LAST),
            mock.patch('cusd_plus.vault.current_oracle_price_wad', return_value=LIVE),
            mock.patch('cusd_plus.vault.confio_yield_share_bps', return_value=SHARE_BPS),
            mock.patch('cusd_plus.vault.usdy_daily_rate', return_value=float(DAILY)),
            mock.patch('cusd_plus.vault.rate_oracle_address', return_value='0x' + '0a' * 20),
            mock.patch('smart_account.quotes.plus_price_window', side_effect=REAL_PLUS_PRICE_WINDOW),
            mock.patch('smart_account.chain.p_plus_wad', return_value=P_PLUS),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # The premise: accrual moves pPlus above the stored value.
        assert contract_p_plus(LIVE) > P_PLUS


def _send_rule(case, *, amount='25.00', frequency='weekly', token_in=VAULT, onchain_id=4):
    """An on-chain send rule with its Face-confirmed authorization, due now."""
    from smart_account.models import SmartAccountStandingAuthorization as Authorization
    payee = case.make_user('payee')
    slot = timezone.now().replace(microsecond=0) - timedelta(minutes=3)
    authorization = Authorization.objects.create(
        kind='send', user=case.account.owner_user, payee_address=payee.wallet.lower(), rail='',
        amount_usd=Decimal(amount), frequency=frequency, face_action_key='out:' + 'f' * 64,
        binding_hash=payouts.send_binding_hash(case.address, payee.wallet, Decimal(amount), frequency))
    rule = SmartAccountRule.objects.create(
        smart_account=case.account, onchain_id=onchain_id, state='onchain', kind='send', token_in=token_in,
        payee_address=payee.wallet, payee_user=payee, amount=Decimal(amount), frequency=frequency,
        next_run_at=slot, scheduled_for=slot, active=True, standing_authorization=authorization)
    case.chain.views[(case.address, 'status')] = 1
    case.chain.views[(case.address, 'billingStatus')] = 0
    case.chain.rules[(case.address, onchain_id)] = {
        'kind': 'send', 'frequency': frequency, 'active': True, 'payee': payee.wallet.lower(),
        'amount_usd_wei': int(Decimal(amount) * WAD), 'next_run_at': int(slot.timestamp())}
    return rule, slot


# ── 1. cUSD+ sized at the post-accrual pPlus ────────────────────────────

class GrowingPPlusRuleTests(_GrowingVault, test_tasks.RelayHarness):
    def setUp(self):
        super().setUp()
        SmartAccount.objects.update(paid_until=timezone.now() + timedelta(days=20))
        self.account.refresh_from_db()
        self.growing_vault()
        self.fund(VAULT, self.address, 500 * WAD)

    def _crypto_buy_rule(self, amount='25.00'):
        rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=7, state='onchain', kind='buy', token_in=VAULT,
            token_out='0x' + '71' * 20, amount=Decimal(amount), frequency='weekly', active=True)
        built = []

        def buy(token, dollar, amount_in):
            built.append(amount_in)
            return {'call': {'to': SWAP_ROUTER, 'value': '0', 'data': '0x1234'}, 'token': '0x' + '71' * 20,
                    'max_in': amount_in, 'min_out': 1}
        for p in (mock.patch('cusd_plus.crypto_catalog.by_address', return_value=mock.Mock()),
                  mock.patch('smart_account.assets.is_feed_token', return_value=True),
                  mock.patch('cusd_plus.crypto_risk.trading_ready', return_value=True),
                  mock.patch('cusd_plus.crypto_risk.buy_enabled', return_value=True),
                  mock.patch('smart_account.quotes.crypto_buy_call', side_effect=buy)):
            p.start()
            self.addCleanup(p.stop)
        return rule, built

    def test_crypto_buy_amount_in_stays_inside_the_contracts_post_accrual_limit(self):
        rule, built = self._crypto_buy_rule()
        amount_wei = 25 * WAD
        automation.build_rule_call(rule)
        amount_in = built[0]
        for oracle in inclusion_oracles():
            limit = ceil_shares(amount_wei, contract_p_plus(oracle))   # what the router may pull
            self.assertLessEqual(amount_in, limit, oracle)
            self.assertGreater(amount_in, limit * (BPS - 10) // BPS, oracle)   # a few bps, not more
        # The old sizing, from the stored pPlus, exceeds the allowance: every run reverted.
        old = amount_wei * WAD // P_PLUS
        self.assertGreater(old, ceil_shares(amount_wei, contract_p_plus(LIVE)))

    def test_same_dollar_send_floor_is_below_what_the_contract_transfers(self):
        rule, _slot = _send_rule(self)
        with mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True):
            self.assertEqual(automation.run_rules()['sent'], 1)
        _dollar, min_out = decode(['uint8', 'uint256'], abi.decode_call(self.signed[0]['data'])[1][1])
        for oracle in inclusion_oracles():
            transferred = ceil_shares(25 * WAD, contract_p_plus(oracle))
            self.assertLessEqual(min_out, transferred)
        self.assertGreaterEqual(min_out, ceil_shares(25 * WAD, contract_p_plus(inclusion_oracles()[-1])) * 998 // 1000)

    def test_wrap_send_floor_is_below_the_shares_minted_at_inclusion(self):
        rule, _slot = _send_rule(self, token_in=CUSD)
        self.fund(CUSD, self.address, 500 * WAD)
        with mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True):
            self.assertEqual(automation.run_rules()['sent'], 1)
        _dollar, min_out = decode(['uint8', 'uint256'], abi.decode_call(self.signed[0]['data'])[1][1])
        for oracle in inclusion_oracles():
            self.assertLess(min_out, 25 * WAD * WAD // contract_p_plus(oracle))

    def test_stock_buy_share_limit_is_the_post_accrual_one(self):
        rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=8, state='onchain', kind='buy', token_in=VAULT,
            token_out='0x' + '73' * 20, amount=Decimal('25.00'), frequency='weekly', active=True)
        seen = []

        def stock_buy(symbol, notional, share_limit):
            seen.append(share_limit)
            return {'call': {'to': '0x' + '51' * 20, 'value': '0', 'data': '0x1234'}, 'min_out': 1}
        with mock.patch('cusd_plus.crypto_catalog.by_address', return_value=None), \
                mock.patch('smart_account.assets.stock_by_address', return_value=('AAPLon', {})), \
                override_settings(CUSD_PLUS_STOCK_TRADING_ENABLED=True), \
                mock.patch('cusd_plus.eligibility.check_stock_buy_eligibility', return_value=True), \
                mock.patch('cusd_plus.complex_products.factor_for_symbol', return_value=None), \
                mock.patch('smart_account.quotes.stock_buy_notional', return_value=Decimal('24.50')), \
                mock.patch('smart_account.quotes.stock_buy_call', side_effect=stock_buy):
            automation.build_rule_call(rule)
        for oracle in inclusion_oracles():
            self.assertLessEqual(seen[0], ceil_shares(25 * WAD, contract_p_plus(oracle)))

    def test_balance_check_covers_the_largest_limit(self):
        rule, built = self._crypto_buy_rule()
        most = ceil_shares(25 * WAD, contract_p_plus(LIVE))
        self.fund(VAULT, self.address, most - 1)
        with self.assertRaises(automation.RuleSkip):
            automation.build_rule_call(rule)
        self.fund(VAULT, self.address, most)
        automation.build_rule_call(rule)
        self.assertEqual(len(built), 1)


class GrowingPPlusBillingTests(_GrowingVault, test_tasks.RelayHarness):
    def setUp(self):
        super().setUp()
        self.growing_vault()

    def test_fee_is_collected_when_the_accrued_dollars_cover_it(self):
        # Stored pPlus says short by a little; after accrue() it covers.
        shares = 100 * WAD
        fee = shares * P_PLUS // WAD + WAD // 10
        self.assertGreaterEqual(shares * contract_p_plus(LIVE) // WAD, fee)
        self.fund(VAULT, self.address, shares)
        self.due(shares * P_PLUS // WAD, fee=fee)
        out = automation.collect_due_fees()
        self.assertEqual((out['sent'], out['short']), (1, 0))
        # ... and no payment notice is started (it would revert DollarsCover).
        self.assertEqual(automation.start_payment_notices()['sent'], 0)

    def test_forced_sale_is_sized_on_the_post_accrual_shortfall(self):
        shares, cusd, fee = 40 * WAD, 3 * WAD, 150 * WAD
        self.fund(VAULT, self.address, shares)
        self.fund(CUSD, self.address, cusd)
        self.due(cusd + shares * P_PLUS // WAD, fee=fee, billing=3, notice=self.paid_until + 10)
        SmartAccount.objects.update(notice_started_at=timezone.now() - timedelta(days=8))
        planned = []

        def plan(account, shortfall, dollar, cap_shortfall=None):
            planned.append((shortfall, cap_shortfall))
            return [{'venue': SWAP_ROUTER, 'token': '0x' + '71' * 20, 'max_in': 1, 'data': '0x1234',
                     'asset_key': 'crypto:BTCB', 'kind': 'crypto', 'expected_dollars_wei': shortfall,
                     'quote_ref': ''}]
        with mock.patch('smart_account.automation.plan_forced_sale', side_effect=plan), \
                mock.patch('smart_account.automation._account_dollar', return_value=abi.DOLLAR_PLUS):
            self.assertEqual(automation.run_forced_sales()['sent'], 1)
        shortfall, floor = planned[0]
        min_out = abi.decode_call(self.signed[0]['data'])[1][1]
        stored_shortfall = fee - cusd - shares * P_PLUS // WAD
        for oracle in inclusion_oracles():
            contract_shortfall = fee - (cusd + shares * contract_p_plus(oracle) // WAD)
            self.assertLessEqual(min_out, contract_shortfall)       # never asks more than the contract's
            self.assertGreaterEqual(shortfall, contract_shortfall)  # the plan covers it
            self.assertLessEqual(floor, contract_shortfall)         # the cap is the tightest one
        self.assertEqual(min_out, floor)
        self.assertLess(shortfall, stored_shortfall)                # not the stored-pPlus figure
        _target, cap = automation.forced_sale_target_wei(shortfall, floor)
        self.assertEqual(cap, floor + floor * 500 // BPS + WAD)


# ── 2. an edited rule keeps its schedule ────────────────────────────────

class RuleEditScheduleTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.address = self.account.contract_address
        self.fund(VAULT, self.address, 500 * WAD)
        self.token = '0x' + '6a' * 20
        for p in (mock.patch('smart_account.assets.resolve_asset_key', return_value=('stock', 'AAPLon', self.token, 18)),
                  mock.patch('smart_account.services._stock_buy_allowed', return_value=True),
                  mock.patch('cusd_plus.complex_products.factor_for_symbol', return_value=None),
                  mock.patch('smart_account.services._require_stock_minimum'),
                  mock.patch('security.geo.review_cap_exceeded', return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        # A monthly rule that ran on "the 1st" (14 days ago): the contract's
        # next run is 28 days after that run, the calendar slot a month after.
        now = timezone.now().replace(microsecond=0)
        self.paid_on = now - timedelta(days=14)
        self.chain_next = self.paid_on + timedelta(days=28)
        self.calendar_next = automation.next_slot('monthly', self.paid_on)
        self.rule = SmartAccountRule.objects.create(
            smart_account=self.account, onchain_id=3, state='onchain', kind='buy', token_in=VAULT,
            token_out=self.token, asset_key='stock:AAPLon', amount=Decimal('50.00'), frequency='monthly',
            active=True, next_run_at=self.chain_next, scheduled_for=self.calendar_next)
        self.chain.rules[(self.address, 3)] = {
            'kind': 'buy', 'frequency': 'monthly', 'active': True, 'token_in': VAULT, 'token_out': self.token,
            'payee': abi.ZERO_ADDRESS, 'payout_ref': '0x' + '00' * 32, 'amount_usd_wei': 50 * WAD,
            'next_run_at': int(self.chain_next.timestamp())}

    def _edit(self, amount='80.00'):
        batch = services.prepare_buy_rule(self.viewer(self.owner), str(self.rule.internal_id), 'stock:AAPLon',
                                          amount, 'monthly')
        name, args = abi.decode_call(batch.calls[0]['data'])
        self.assertEqual((name, args[0]), ('updateRule', 3))
        return args[1][7]   # firstRunAt

    def _store(self, first_run_at, now):
        """ConfioSmartAccount._storeRule, then the RuleUpdated event mirrored."""
        stored = dict(self.chain.rules[(self.address, 3)])
        stored.update(next_run_at=max(first_run_at, int(now.timestamp())), amount_usd_wei=80 * WAD)
        self.chain.rules[(self.address, 3)] = stored
        event = SimpleNamespace(args={'id': 3}, tx_hash='0x' + 'e1' * 32, block_time=now, block_number=1)
        reconcile._rule_updated(self.account, event)
        self.rule.refresh_from_db()

    def test_monthly_rule_paid_on_the_1st_and_edited_on_the_15th_waits_for_its_next_date(self):
        first_run_at = self._edit()
        self.assertEqual(first_run_at, int(self.calendar_next.timestamp()))   # never 0 (= "now")
        now = timezone.now()
        self._store(first_run_at, now)
        self.assertEqual(self.rule.next_run_at, self.calendar_next)
        self.assertEqual(self.rule.scheduled_for, self.calendar_next)
        self.assertNotIn(self.rule.pk, [r.pk for r in automation.due_rules()])
        # Not due a day before the date; due on it.
        with mock.patch('django.utils.timezone.now', return_value=self.calendar_next - timedelta(days=1)):
            self.assertNotIn(self.rule.pk, [r.pk for r in automation.due_rules()])
        with mock.patch('django.utils.timezone.now', return_value=self.calendar_next + timedelta(minutes=1)):
            self.assertIn(self.rule.pk, [r.pk for r in automation.due_rules()])

    def test_the_chains_next_run_wins_when_it_is_later_than_the_mirror(self):
        later = self.calendar_next + timedelta(days=3)
        self.chain.rules[(self.address, 3)]['next_run_at'] = int(later.timestamp())
        self.assertEqual(self._edit(), int(later.timestamp()))

    def test_a_cancelled_rule_on_chain_is_not_edited(self):
        self.chain.rules[(self.address, 3)]['active'] = False
        with self.assertRaises(services.PrepareError) as raised:
            self._edit()
        self.assertEqual(raised.exception.code, 'rule_not_found')

    def test_unreadable_chain_refuses_the_edit(self):
        self.chain.fail.add('account_rule')
        with self.assertRaises(services.PrepareError) as raised:
            self._edit()
        self.assertEqual(raised.exception.code, 'chain_unavailable')

    def test_an_edit_prepared_before_a_run_and_signed_after_it_does_not_run_again(self):
        first_run_at = self._edit()
        # The rule runs in between: the mirror's slot moves on a month.
        later_slot = automation.next_slot('monthly', self.calendar_next)
        SmartAccountRule.objects.filter(pk=self.rule.pk).update(scheduled_for=later_slot)
        self.rule.refresh_from_db()
        signed_at = self.calendar_next + timedelta(hours=1)
        with mock.patch('django.utils.timezone.now', return_value=signed_at):
            self._store(first_run_at, signed_at)   # nextRunAt falls back to "now" on chain
            self.assertEqual(self.rule.scheduled_for, later_slot)
            self.assertNotIn(self.rule.pk, [r.pk for r in automation.due_rules()])

    def test_a_new_rule_still_starts_now(self):
        batch = services.prepare_buy_rule(self.viewer(self.owner), None, 'stock:AAPLon', '30.00', 'weekly')
        name, args = abi.decode_call(batch.calls[0]['data'])
        self.assertEqual((name, args[0][7]), ('createRule', 0))


# ── 3. a sent relay transaction that can never be mined ─────────────────

@override_settings(BSC_SPONSOR_ADDRESS=test_tasks.SPONSOR)
class DroppedSentTxTests(test_tasks.RelayHarness):
    def setUp(self):
        super().setUp()
        self.mined_nonce = 7         # the row is signed with pending nonce 7
        self.receipts = {}
        from smart_account import chain
        inner = chain.rpc.side_effect

        def rpc(method, params):
            if method == 'eth_getTransactionCount' and params[1] == 'latest':
                return hex(self.mined_nonce)
            if method == 'eth_getTransactionReceipt':
                return self.receipts.get(params[0])
            return inner(method, params)
        p = mock.patch('smart_account.chain.rpc', side_effect=rpc)
        p.start()
        self.addCleanup(p.stop)
        finalized = mock.patch('cusd_plus.tasks._finalized_block_number', return_value=0)
        finalized.start()
        self.addCleanup(finalized.stop)

    def _age(self, minutes=30):
        SmartAccountRelayTx.objects.update(created_at=timezone.now() - timedelta(minutes=minutes),
                                           updated_at=timezone.now() - timedelta(minutes=minutes))

    def test_fee_period_is_released_and_collected_again(self):
        self.due(20 * WAD)
        self.assertEqual(automation.collect_due_fees()['sent'], 1)
        row = SmartAccountRelayTx.objects.get()
        self.assertEqual((row.status, row.sponsor_nonce), ('sent', 7))
        self._age()
        self.assertEqual(tasks.reconcile_relay_txs()['dropped'], 0)   # nonce 7 not mined past yet
        self.mined_nonce = 8                                          # another tx took nonce 7
        self.assertEqual(tasks.reconcile_relay_txs()['dropped'], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, 'dropped')
        self.assertEqual(automation.collect_due_fees()['sent'], 1)    # the period is retried
        self.assertEqual(len(self.sent), 2)

    def test_a_young_row_or_one_with_a_receipt_is_never_dropped(self):
        self.due(20 * WAD)
        automation.collect_due_fees()
        row = SmartAccountRelayTx.objects.get()
        self.mined_nonce = 8
        SmartAccountRelayTx.objects.update(updated_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(tasks.reconcile_relay_txs()['dropped'], 0)   # inside the grace period
        self._age()
        self.receipts[row.signed_tx_hash] = {'blockNumber': '0x10', 'blockHash': '0x' + 'aa' * 32, 'status': '0x1'}
        self.assertEqual(tasks.reconcile_relay_txs()['dropped'], 0)   # mined, not final yet
        row.refresh_from_db()
        self.assertEqual(row.status, 'sent')

    def test_without_a_configured_sponsor_nothing_is_dropped(self):
        self.due(20 * WAD)
        automation.collect_due_fees()
        self._age()
        self.mined_nonce = 8
        with override_settings(BSC_SPONSOR_ADDRESS=None):
            self.assertEqual(tasks.reconcile_relay_txs()['dropped'], 0)

    def test_forced_sale_is_released_and_retried(self):
        self.due(5 * WAD, fee=150 * WAD, billing=3, notice=self.paid_until + 10)
        SmartAccount.objects.update(notice_started_at=timezone.now() - timedelta(days=8))
        legs = [{'venue': SWAP_ROUTER, 'token': '0x' + '71' * 20, 'max_in': 1, 'data': '0x1234',
                 'asset_key': 'crypto:BTCB', 'kind': 'crypto', 'expected_dollars_wei': 146 * WAD, 'quote_ref': ''}]
        with mock.patch('smart_account.automation.plan_forced_sale', return_value=legs), \
                mock.patch('smart_account.automation._account_dollar', return_value=abi.DOLLAR_PLUS):
            self.assertEqual(automation.run_forced_sales()['sent'], 1)
            self.assertEqual(automation.run_forced_sales()['sent'], 0)    # on the wire
            self._age()
            self.mined_nonce = 8
            self.assertEqual(tasks.reconcile_relay_txs()['dropped'], 1)
            sale = SmartAccountForcedSale.objects.get()
            self.assertEqual(sale.status, 'failed')
            self.assertEqual(automation.run_forced_sales()['sent'], 1)    # retried
        self.assertEqual(len(self.sent), 2)

    def test_rule_slot_is_released_and_retried(self):
        SmartAccount.objects.update(paid_until=timezone.now() + timedelta(days=20))
        self.account.refresh_from_db()
        self.fund(VAULT, self.address, 500 * WAD)
        rule, slot = _send_rule(self)
        with mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True):
            self.assertEqual(automation.run_rules()['sent'], 1)
            self.assertEqual(automation.run_rules()['sent'], 0)
            self._age()
            self.mined_nonce = 8
            self.assertEqual(tasks.reconcile_relay_txs()['dropped'], 1)
            run = SmartAccountRuleRun.objects.get()
            self.assertEqual(run.status, 'failed')
            self.assertEqual(automation.run_rules()['sent'], 1)           # same slot, sent again
        self.assertEqual(SmartAccountRuleRun.objects.get().scheduled_for, slot)
        self.assertEqual(len(self.sent), 2)


# ── 4. USDT below the personal path's minimum stays USDT ────────────────

class ConvertUsdtFloorTests(test_tasks.RelayHarness):
    def test_balances_below_the_safe_mint_minimum_are_skipped(self):
        from cusd_plus import vault
        SmartAccount.objects.update(paid_until=timezone.now() + timedelta(days=5))
        self.chain.views[(self.address, 'status')] = 1
        with mock.patch('cusd_plus.eligibility.is_ondo_eligible', return_value=True):
            for balance in (1, WAD, vault.MIN_SAFE_MINT_WEI - 1):
                self.fund(USDT, self.address, balance)
                out = automation.convert_usdt()
                self.assertEqual((out['sent'], out['skipped']), (0, 1), balance)
            self.assertEqual(self.signed, [])
            self.fund(USDT, self.address, vault.MIN_SAFE_MINT_WEI)
            self.assertEqual(automation.convert_usdt()['sent'], 1)


# ── 5. a fresh Face per rule and per designation ────────────────────────

class _CountingFace:
    """step_up applies; `grants` fresh checks; a consumed key may be
    re-claimed (security.face_step_up's exact-retry rule)."""

    def face(self):
        self.grants, self.consumed = 0, []

        def step_up(user, purpose, *, action_key=None, consume=False, **kwargs):
            if action_key in self.consumed:
                return ''
            if self.grants <= 0:
                return FACE_MESSAGE
            self.grants -= 1
            self.consumed.append(action_key)
            return ''
        for p in (mock.patch('security.face_step_up.step_up_applies', return_value=True),
                  mock.patch('security.face_step_up.require_face_step_up', side_effect=step_up)):
            p.start()
            self.addCleanup(p.stop)


class FaceNonceTests(_CountingFace, SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.payee = self.make_user('payee')
        self.heir = self.make_user('heir')
        self.account = self.make_account(self.owner)
        self.fund(VAULT, self.account.contract_address, 500 * WAD)
        self.face()

    def _send(self):
        return services.prepare_send_rule(self.viewer(self.owner), None, 'payee', '25.00', 'weekly')

    def test_recreating_a_cancelled_identical_send_rule_needs_a_new_face(self):
        self.grants = 1
        self._send()
        first = SmartAccountStandingAuthorization.objects.get()
        # It reaches the chain and is cancelled (reconcile revokes the grant's authorization).
        SmartAccountRule.objects.update(state='cancelled')
        SmartAccountStandingAuthorization.objects.update(revoked_at=timezone.now(), revoked_reason='rule_cancelled')
        with self.assertRaises(services.PrepareError) as raised:
            self._send()
        self.assertEqual(raised.exception.code, 'face_required')
        self.assertEqual(SmartAccountStandingAuthorization.objects.count(), 1)   # refused: no new row
        self.grants = 1
        self._send()
        second = SmartAccountStandingAuthorization.objects.exclude(pk=first.pk).get()
        self.assertNotEqual(second.face_action_key, first.face_action_key)
        self.assertEqual(second.binding_hash, first.binding_hash)            # same terms, new grant

    def test_an_identical_rule_that_is_still_on_chain_needs_a_new_face(self):
        self.grants = 1
        self._send()
        SmartAccountRule.objects.update(state='onchain', onchain_id=1, active=True)
        with self.assertRaises(services.PrepareError):
            self._send()

    def test_an_exact_retry_of_the_same_draft_reuses_the_grant(self):
        self.grants = 1
        first = self._send()
        second = self._send()                  # e.g. the response was lost: no new check
        self.assertNotEqual(first.request_id, second.request_id)
        self.assertEqual(SmartAccountStandingAuthorization.objects.count(), 1)
        self.assertEqual(self.grants, 0)
        self.assertEqual(len(self.consumed), 1)

    def test_renaming_a_removed_beneficiary_needs_a_new_face(self):
        self.grants = 1
        services.prepare_designation(self.viewer(self.owner), 'heir', 180, True)
        row = SmartAccountBeneficiary.objects.get()
        first_key = self.consumed[0]
        # An exact retry while it is still the same draft: same grant.
        services.prepare_designation(self.viewer(self.owner), 'heir', 180, True)
        self.assertEqual((SmartAccountBeneficiary.objects.count(), len(self.consumed)), (1, 1))
        # Signed, accepted, then removed: naming the same person again is a new designation.
        SmartAccountBeneficiary.objects.filter(pk=row.pk).update(state='removed', removed_at=timezone.now())
        with self.assertRaises(services.PrepareError) as raised:
            services.prepare_designation(self.viewer(self.owner), 'heir', 180, True)
        self.assertEqual(raised.exception.code, 'face_required')
        self.assertEqual(SmartAccountBeneficiary.objects.count(), 1)
        self.grants = 1
        services.prepare_designation(self.viewer(self.owner), 'heir', 180, True)
        self.assertEqual(SmartAccountBeneficiary.objects.count(), 2)
        self.assertEqual(len(self.consumed), 2)
        self.assertNotEqual(self.consumed[1], first_key)


# ── 6. the stock rule minimum ───────────────────────────────────────────

class StockRuleMinimumTests(SmartAccountTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user('owner')
        self.account = self.make_account(self.owner)
        self.fund(VAULT, self.account.contract_address, 500 * WAD)
        from cusd_plus import stock_fees
        for p in (mock.patch('smart_account.assets.resolve_asset_key',
                             return_value=('stock', 'AAPLon', '0x' + '6a' * 20, 18)),
                  mock.patch('smart_account.services._stock_buy_allowed', return_value=True),
                  mock.patch('cusd_plus.complex_products.factor_for_symbol', return_value=None),
                  mock.patch('security.geo.review_cap_exceeded', return_value=False),
                  mock.patch('smart_account.quotes._stock_fee', return_value=(30, stock_fees.MODE_PERIMETER)),
                  mock.patch('cusd_plus.stock_fees.exit_buffer_bps', return_value=5)):
            p.start()
            self.addCleanup(p.stop)

    def _prepare(self, amount):
        return services.prepare_buy_rule(self.viewer(self.owner), None, 'stock:AAPLon', amount, 'monthly')

    def test_a_rule_below_the_order_minimum_is_refused_with_the_minimum(self):
        minimum = quotes.min_stock_rule_amount()
        self.assertEqual(minimum, Decimal('1.01'))   # 1.00 / (1 - 0.30% - 0.05% - 0.10%), up to the cent
        self.assertLess(quotes.stock_buy_notional(Decimal('1.00')), quotes.MIN_STOCK_ORDER_USD)
        with self.assertRaises(services.PrepareError) as raised:
            self._prepare('1.00')
        self.assertEqual(raised.exception.code, 'stock_below_minimum')
        self.assertEqual(raised.exception.message,
                         'El monto mínimo para comprar acciones automáticamente es US$1.01.')
        self.assertFalse(SmartAccountRule.objects.exists())
        self._prepare(str(minimum))
        self.assertTrue(SmartAccountRule.objects.exists())

    def test_the_minimum_follows_the_live_fee(self):
        with mock.patch('smart_account.quotes._stock_fee', return_value=(200, 'perimeter')):
            minimum = quotes.min_stock_rule_amount()
            self.assertGreaterEqual(quotes.stock_buy_notional(minimum), quotes.MIN_STOCK_ORDER_USD)
            self.assertLess(quotes.stock_buy_notional(minimum - Decimal('0.01')), quotes.MIN_STOCK_ORDER_USD)
            with self.assertRaises(services.PrepareError) as raised:
                self._prepare(str(minimum - Decimal('0.01')))
            self.assertIn(services.usd_text(minimum), raised.exception.message)

    def test_an_unreadable_fee_policy_refuses(self):
        with mock.patch('smart_account.quotes._stock_fee',
                        side_effect=quotes.QuoteUnavailable('stock_fee_policy_unavailable')):
            with self.assertRaises(services.PrepareError) as raised:
                self._prepare('50.00')
        self.assertEqual(raised.exception.code, 'trade_not_available')
