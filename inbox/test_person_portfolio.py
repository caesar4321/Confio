"""One sleeve per person: the personal wallet plus every Cuenta inteligente
(inbox/person_wallets.py, inbox/account_trades.py), summed for the
portfolio, Rentabilidad and the Liga; moves between their own addresses are
never flows."""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone

from smart_account.models import SmartAccount, SmartAccountEvent
from users.models import Account

from . import account_trades, member_portfolio, person_wallets
from . import portfolio_returns as pr
from . import rolling_returns as rr
from .models import PortfolioDailySnapshot, SmartAccountTrade
from .test_community import CommunityTestBase, make_user
from .test_portfolio_returns import NOW, D20, D21, TablePrices, at, trade

PERSONAL = '0x' + 'a1' * 20
ACCT = '0x' + 'b2' * 20
OLD = '0x' + 'c3' * 20
NVDA = '0x' + 'd4' * 20
CUSD = '0x' + 'e5' * 20
PLUS = '0x' + 'f6' * 20
USDT = '0x' + '17' * 20
CONFIO = '0x' + '28' * 20
WEI = 10 ** 18
MARKET = {'NVDAon': {'price': Decimal('120'), 'day_pct': Decimal('0'), 'ticker': 'NVDA', 'name': 'NVIDIA'}}


class PersonBase(CommunityTestBase):
    def setUp(self):
        super().setUp()
        for target, value in (('smart_account.chain.cusd_address', CUSD),
                              ('smart_account.chain.cusd_plus_address', PLUS),
                              ('smart_account.chain.usdt_address', USDT),
                              ('smart_account.chain.confio_address', CONFIO),
                              ('cusd_plus.gm_holdings.registry', {'NVDAon': {'address': NVDA, 'decimals': 18}}),
                              ('cusd_plus.gm_holdings._fallback_registry', {}),
                              ('cusd_plus.crypto_catalog.by_address', None)):
            p = patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.user = make_user()
        Account.objects.filter(user=self.user, account_type='personal').update(bsc_address=PERSONAL)
        self.n = 0

    def account(self, address=ACCT, *, deleted=False, status='active'):
        personal = Account.objects.get(user=self.user, account_type='personal')
        return SmartAccount.all_objects.create(
            owner_user=self.user, owner_account=personal, contract_address=address, status=status,
            deleted_at=timezone.now() if deleted else None)

    def event(self, address, name, args, when):
        self.n += 1
        return SmartAccountEvent.objects.create(
            address=address, tx_hash='0x%064x' % self.n, log_index=0, name=name,
            args={k: str(v) for k, v in args.items()}, block_number=1000 + self.n, block_time=when)

    def buy(self, address, units, usd, when, token_in=CUSD):
        return self.event(address, 'Traded', {'venue': USDT, 'tokenIn': token_in, 'tokenOut': NVDA,
                                              'amountIn': int(usd) * WEI, 'amountOut': int(units) * WEI}, when)


class AccountTradesTests(PersonBase):
    def test_owner_buy_and_sell(self):
        self.account()
        self.buy(ACCT, 2, 200, at(D20))
        self.event(ACCT, 'Traded', {'venue': USDT, 'tokenIn': NVDA, 'tokenOut': CUSD,
                                    'amountIn': WEI, 'amountOut': 130 * WEI}, at(D21))
        stocks, crypto = account_trades.trades_of(ACCT)
        self.assertEqual([(t.kind, t.units, t.usd, t.source) for t in stocks],
                         [('stock_buy', Decimal(2), Decimal(200), ACCT), ('stock_sell', Decimal(1), Decimal(130), ACCT)])
        self.assertEqual(crypto, [])

    def test_a_hands_off_buy_counts_its_dollars_exactly_without_the_chain(self):
        self.event(ACCT, 'RelayTraded', {'id': 1, 'venue': USDT, 'tokenIn': PLUS, 'tokenOut': NVDA,
                                         'spent': 95 * WEI, 'got': WEI, 'usdCounted': 100 * WEI}, at(D20))
        [t], _ = account_trades.trades_of(ACCT)
        self.assertEqual((t.kind, t.usd), ('stock_buy', Decimal(100)))

    def test_a_dollar_plus_leg_waits_for_its_block_price(self):
        self.buy(ACCT, 1, 95, at(D20), token_in=PLUS)
        with self.assertRaises(account_trades.AccountTradesPending):
            account_trades.trades_of(ACCT)                       # a request never reads the chain
        with self.assertRaises(pr.Retry):                        # unknown for now, never a smaller ledger
            pr.load_ledger(PERSONAL, TablePrices({}), [PERSONAL, ACCT])
        with patch.object(account_trades, 'p_plus_at', return_value=105 * WEI // 100):
            [t], _ = account_trades.trades_of(ACCT, allow_rpc=True)
        self.assertEqual(t.usd, Decimal('99.75'))
        self.assertTrue(SmartAccountTrade.objects.filter(event__address=ACCT).exists())

    def test_a_forced_sale_is_a_sell_and_dollars_only_runs_are_no_trade(self):
        self.event(ACCT, 'ForcedSale', {'tokenIn': NVDA, 'amountIn': WEI, 'dollarsOut': 118 * WEI,
                                        'forPeriod': 0}, at(D20))
        self.event(ACCT, 'RuleExecuted', {'id': 3, 'tokenIn': CUSD, 'tokenOut': USDT,
                                          'amountIn': 10 * WEI, 'amountOut': 10 * WEI}, at(D20, 13))
        self.event(ACCT, 'ForcedSale', {'tokenIn': CONFIO, 'amountIn': WEI, 'dollarsOut': WEI,
                                        'forPeriod': 0}, at(D20, 14))
        stocks, crypto = account_trades.trades_of(ACCT)
        self.assertEqual([(t.kind, t.usd) for t in stocks], [('stock_sell', Decimal(118))])
        self.assertEqual(crypto, [])

    def test_an_unknown_token_is_unreadable_never_dropped(self):
        self.event(ACCT, 'Traded', {'venue': USDT, 'tokenIn': CUSD, 'tokenOut': '0x' + '39' * 20,
                                    'amountIn': WEI, 'amountOut': WEI}, at(D20))
        [t], _ = account_trades.trades_of(ACCT)
        self.assertTrue(t.symbol.startswith('?'))


class WalletsOfTests(PersonBase):
    def test_personal_wallet_and_every_own_generation(self):
        self.account(OLD, deleted=True)          # migrated: still the person's
        self.account(ACCT)
        self.account('0x' + '44' * 20, status='inherited')   # someone else's sleeve
        self.assertEqual(person_wallets.wallets_of(self.user), [PERSONAL, OLD, ACCT])
        self.assertEqual(person_wallets.addresses_for(PERSONAL), [PERSONAL, OLD, ACCT])
        self.assertEqual(person_wallets.addresses_for('0x' + '55' * 20), ['0x' + '55' * 20])

    def test_anything_moving_an_account_is_on_the_wire(self):
        with patch('smart_account.inflight.address_in_flight', return_value=True):
            self.assertTrue(pr.in_flight(PERSONAL, [PERSONAL, ACCT]))
            self.assertFalse(pr.in_flight(PERSONAL, [PERSONAL]))


class JointChainTests(PersonBase):
    """Holdings split over the person's addresses, explained by the joint ledger."""
    TABLE = {('NVDAon', date(2026, 10, d)): Decimal(100 + d) for d in range(15, 24)}

    def holdings(self, by_address):
        def scan(address, **kwargs):
            return {'NVDAon': by_address.get(address, '0')}, {'NVDAon': 10 ** 9}
        return patch('cusd_plus.gm_holdings.complete_holdings', side_effect=scan)

    def sync(self, personal_trades, by_address):
        with patch('cusd_plus.stock_month.confirmed_trades', return_value=personal_trades), \
                patch('cusd_plus.crypto_month.confirmed_trades', return_value=[]), \
                patch.object(pr, 'in_flight', return_value=False), \
                self.holdings(by_address), \
                patch('cusd_plus.crypto_holdings.holdings_snapshot', return_value=({}, 50)):
            return pr.sync_wallet(self.user, PERSONAL, days=2, now=NOW, prices=TablePrices(self.TABLE))

    def rows(self):
        return {r.day: r for r in PortfolioDailySnapshot.objects.filter(wallet=PERSONAL)}

    def test_stocks_in_both_wallets(self):
        self.account()
        self.buy(ACCT, 2, 200, at(D20, 11))
        self.sync([trade('stock_buy', '1', '100', at(D20, 10), block=5)], {PERSONAL: '1', ACCT: '2'})
        day20 = self.rows()[D20]
        self.assertTrue(day20.ledger_trusted)
        self.assertEqual((day20.net_flow_usd, day20.value_end_usd), (Decimal(300), Decimal(363)))

    def test_an_internal_transfer_is_not_a_return(self):
        # Bought 3 in the personal wallet on the 20th, moved 2 into the account on the 21st.
        self.account()
        self.sync([trade('stock_buy', '3', '300', at(D20, 10), block=5)], {PERSONAL: '1', ACCT: '2'})
        day21 = self.rows()[D21]
        self.assertTrue(day21.ledger_trusted)
        self.assertEqual((day21.net_flow_usd, day21.gain_usd), (Decimal(0), Decimal(3)))   # 3 x (122 - 121)

    def test_a_migration_is_not_counted(self):
        # Bought 2 in the old account; migrated to the new one: all of it sits there now.
        self.account(OLD, deleted=True)
        self.account(ACCT)
        self.buy(OLD, 2, 200, at(D20, 10))
        self.sync([], {OLD: '0', ACCT: '2'})
        rows = self.rows()
        self.assertTrue(rows[D21].ledger_trusted)
        self.assertEqual((rows[D20].net_flow_usd, rows[D21].net_flow_usd, rows[D21].gain_usd),
                         (Decimal(200), Decimal(0), Decimal(2)))

    def test_units_from_outside_are_still_untrusted_across_wallets(self):
        self.account()
        ledger = pr.Ledger(stocks=[trade('stock_buy', '3', '300', at(D20), block=5)], crypto=[],
                           wallets=[PERSONAL, ACCT])
        with self.holdings({PERSONAL: '1', ACCT: '3'}), \
                patch('cusd_plus.crypto_holdings.holdings_snapshot', return_value=({}, 50)):
            with self.assertRaises(pr.Untrusted):
                pr.check_chain(PERSONAL, ledger)

    def test_wallets_to_snapshot_includes_account_only_traders(self):
        self.account()
        self.buy(ACCT, 1, 100, at(D20))
        self.assertIn((self.user, PERSONAL), pr.wallets_to_snapshot())


class PersonPortfolioTests(PersonBase):
    """Profile: holdings, dollars, P&L and total return across both wallets."""

    def patches(self):
        when = timezone.now() - timedelta(hours=48)
        personal = [trade('stock_buy', '1', '100', when)]
        self.buy(ACCT, 2, 200, when + timedelta(hours=1))
        scans = {PERSONAL: ({'NVDAon': '1'}, {}), ACCT: ({'NVDAon': '2'}, {})}
        return [patch('cusd_plus.stock_month.confirmed_trades', return_value=personal),
                patch('cusd_plus.gm_holdings.complete_holdings', side_effect=lambda a, **k: scans[a]),
                patch.object(member_portfolio, '_market', return_value=MARKET),
                patch.object(member_portfolio, 'dollars_usd',
                             side_effect=lambda w: {PERSONAL: Decimal(50), ACCT: Decimal(25)}[w]),
                patch.object(member_portfolio, 'presale_totals', return_value=(Decimal(0), Decimal(0)))]

    def run_with(self, fn):
        self.account()
        ps = self.patches()
        for p in ps:
            p.start()
        try:
            return fn(self.user)
        finally:
            for p in ps:
                p.stop()

    def test_stocks_in_both_wallets(self):
        p = self.run_with(member_portfolio.build_portfolio)
        [nvda] = p.open_positions
        self.assertEqual((nvda.units, nvda.value_usd, nvda.invested_usd, nvda.pnl_usd),
                         (Decimal(3), Decimal(360), Decimal(300), Decimal(60)))
        self.assertEqual((p.dollars_usd, p.total_usd, p.trade_count), (Decimal(75), Decimal(435), 2))

    def test_total_return_combined(self):
        r = self.run_with(member_portfolio.total_return)
        self.assertEqual((r.gain_usd, r.invested_usd), (Decimal(60), Decimal(300)))


class LigaCombinedTests(PersonBase):
    def test_liga_pnl_spans_both_wallets(self):
        # Personal: 1 NVDA for $100; account: 2 for $200; now $120 each.
        self.account()
        self.buy(ACCT, 2, 200, NOW - timedelta(days=3))
        with patch('cusd_plus.stock_month.confirmed_trades',
                   return_value=[trade('stock_buy', '1', '100', NOW - timedelta(days=4))]), \
                patch('cusd_plus.crypto_month.confirmed_trades', return_value=[]), \
                patch.object(pr, 'in_flight', return_value=False), \
                patch.object(pr, 'check_chain', return_value=None), \
                patch.object(member_portfolio, '_market', return_value=MARKET):
            result = rr.results(PERSONAL, ['all'], NOW, TablePrices({}))['all']
        self.assertEqual((result.gain, result.capital), (Decimal(60), Decimal(300)))
