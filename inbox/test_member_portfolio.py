from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone

from cusd_plus.stock_month import Trade
from . import community, member_portfolio
from .models import CommunityFollow
from .schema import Query, SetCommunityPortfolioHidden
from .test_community import APPROVE, MockInfo, CommunityTestBase, make_user

NOW = timezone.now()


def trade(kind, units, usd, symbol='NVDAon', hours=0):
    return Trade(symbol=symbol, kind=kind, units=Decimal(units), usd=None if usd is None else Decimal(usd),
                 when=NOW - timedelta(hours=48) + timedelta(hours=hours))


MARKET = {
    'NVDAon': {'price': Decimal('120'), 'day_pct': Decimal('20'), 'ticker': 'NVDA', 'name': 'NVIDIA'},
    'TSLAon': {'price': Decimal('10'), 'day_pct': Decimal('0'), 'ticker': 'TSLA', 'name': 'Tesla'},
}


class WalkTradesTests(CommunityTestBase):
    def test_open_book_and_closed_episode(self):
        trades = [trade('stock_buy', '1', '100'), trade('stock_buy', '1', '140', hours=1),
                  trade('stock_buy', '1', '10', symbol='TSLAon', hours=2),
                  trade('stock_sell', '1', '15', symbol='TSLAon', hours=12)]
        books, closed, holds = member_portfolio.walk_trades(trades, NOW)
        self.assertEqual((books['NVDAon'].units, books['NVDAon'].cost), (Decimal('2'), Decimal('240')))
        self.assertEqual(closed[0][:4], ('TSLAon', Decimal('10'), Decimal('15'), Decimal('5')))
        self.assertIn(10 * 3600, [int(h) for h in holds])

    def test_an_unreadable_trade_poisons_books_opened_after_it(self):
        trades = [trade('stock_buy', '10', '1000', symbol='?7'), trade('stock_buy', '10', '1000', symbol='AAPLon', hours=1),
                  trade('stock_sell', '10', '1500', symbol='AAPLon', hours=2)]
        books, closed, _ = member_portfolio.walk_trades(trades, NOW)
        self.assertEqual(closed, [])
        self.assertFalse(books['AAPLon'].explained)

    def test_units_from_outside_make_the_book_unexplained(self):
        books, closed, _ = member_portfolio.walk_trades(
            [trade('stock_buy', '1', '100'), trade('stock_sell', '2', '250', hours=1)], NOW)
        self.assertFalse(books['NVDAon'].explained)
        self.assertEqual(closed, [])


class BuildPortfolioTests(CommunityTestBase):
    def build(self, user, trades, held, dollars=Decimal('50'), presale=(Decimal('1000'), Decimal('25'))):
        with patch.object(member_portfolio, 'personal_wallet', return_value='0xabc'), \
                patch('cusd_plus.stock_month.confirmed_trades', return_value=trades), \
                patch('cusd_plus.gm_holdings.complete_holdings',
                      return_value=None if held is None else (held, {})), \
                patch.object(member_portfolio, '_market', return_value=MARKET), \
                patch.object(member_portfolio, 'dollars_usd', return_value=dollars), \
                patch.object(member_portfolio, 'presale_totals', return_value=presale):
            return member_portfolio.build_portfolio(user)

    def test_value_pnl_invested_and_average_entry(self):
        p = self.build(make_user(), [trade('stock_buy', '1', '100'), trade('stock_buy', '1', '140', hours=1)],
                       {'NVDAon': Decimal('2')})
        [pos] = p.open_positions
        self.assertEqual((pos.value_usd, pos.invested_usd, pos.avg_entry_usd, pos.pnl_usd),
                         (Decimal('240'), Decimal('240'), Decimal('120'), Decimal('0')))
        self.assertEqual((p.stocks_usd, p.dollars_usd, p.total_usd), (Decimal('240'), Decimal('50'), Decimal('290')))
        self.assertEqual(p.stocks_change_24h_usd, Decimal('40'))
        self.assertEqual((p.presale_confio, p.presale_invested_usd, p.trade_count), (Decimal('1000'), Decimal('25'), 2))

    def test_a_position_from_outside_shows_value_without_pnl(self):
        p = self.build(make_user(), [trade('stock_buy', '1', '100')], {'NVDAon': Decimal('3')})
        [pos] = p.open_positions
        self.assertEqual(pos.value_usd, Decimal('360'))
        self.assertIsNone(pos.pnl_usd)
        self.assertIsNone(pos.invested_usd)

    def test_unknown_parts_stay_unknown(self):
        p = self.build(make_user(), None, None, dollars=None)
        self.assertIsNone(p.stocks_usd)
        self.assertIsNone(p.dollars_usd)
        self.assertIsNone(p.total_usd)
        self.assertIsNone(p.trade_count)
        self.assertIsNone(p.open_positions)
        self.assertIsNone(p.closed_positions)
        self.assertIsNone(p.avg_hold_seconds)

    def test_holding_time_is_rounded_to_the_hour(self):
        p = self.build(make_user(), [trade('stock_buy', '1', '100')], {'NVDAon': Decimal('1')})
        self.assertEqual(p.avg_hold_seconds % 3600, 0)


class PortfolioVisibilityTests(CommunityTestBase):
    def published_member(self, **kwargs):
        member = make_user(**kwargs)
        item = self.post(member)
        with patch('inbox.community.enqueue_follower_notifications'):
            self.run_review(item, APPROVE)
        return member

    def portfolio(self, viewer, member):
        empty = member_portfolio.Portfolio(None, None, None, None, None, None, 0, None, None)
        with patch.object(member_portfolio, 'build_portfolio', return_value=empty):
            return Query().resolve_community_member_portfolio(MockInfo(viewer), str(member.id))

    def test_hoy_is_the_members_own_day_not_the_markets(self):
        member, viewer = self.published_member(), make_user()
        built = member_portfolio.Portfolio(None, None, None, Decimal('14.70'), None, None, 0, None, None)
        with patch.object(member_portfolio, 'build_portfolio', return_value=built), \
                patch.object(member_portfolio, 'personal_wallet', return_value='0xabc'), \
                patch('inbox.portfolio_returns.today_gain', return_value=Decimal('-17.354')) as today:
            result = Query().resolve_community_member_portfolio(MockInfo(viewer), str(member.id))
        self.assertEqual(result.stocks_change_24h_usd, '-17.35')
        today.assert_called_once_with('0xabc')

    def test_public_by_default_and_hidden_by_the_members_own_switch(self):
        member = self.published_member()
        viewer = make_user()
        self.assertIsNotNone(self.portfolio(viewer, member))
        SetCommunityPortfolioHidden.mutate(None, MockInfo(member), hidden=True)
        self.assertIsNone(self.portfolio(viewer, member))
        own = self.portfolio(member, member)
        self.assertTrue(own.is_self and own.hidden)

    def test_the_profile_never_returns_an_email_derived_username(self):
        member = self.published_member()
        member.username = community._generated_username_bases(member)[0]
        member.save(update_fields=['username'])
        profile = Query().resolve_community_member_profile(MockInfo(make_user()), str(member.id))
        self.assertEqual(profile.username, community.pseudonym(member))

    def test_only_reachable_members(self):
        self.assertIsNone(self.portfolio(make_user(), make_user()))

    def test_a_blocked_member_sees_nothing(self):
        member = self.published_member()
        viewer = make_user()
        from .models import CommunityBlock

        CommunityBlock.objects.create(blocker=member, blocked=viewer)
        self.assertIsNone(self.portfolio(viewer, member))

    def test_followers_who_are_not_verified_have_no_asset_profile(self):
        member = self.published_member()
        fan = make_user(verified=False)
        CommunityFollow.objects.create(follower=fan, followed=member)
        self.assertIsNone(self.portfolio(member, fan))


class CryptoPortfolioTests(CommunityTestBase):
    """Bitcoin & gold join the investor profile: value, P&L, closed trades,
    total, today's change and trade count; their ledger never poisons stocks."""

    def build(self, crypto_trades, crypto_held, prices=None, day=None, stock_trades=None, stock_held=None):
        from types import SimpleNamespace

        prices = {'BTCB': Decimal('80000'), 'XAUT': Decimal('4000')} if prices is None else prices
        day = day or {'BTCB': 10.0, 'XAUT': 0.0}
        rows = [{'token': SimpleNamespace(symbol=s), 'day_change_pct': d} for s, d in day.items()]
        with patch.object(member_portfolio, 'personal_wallet', return_value='0xabc'), \
                patch('cusd_plus.stock_month.confirmed_trades', return_value=stock_trades or []), \
                patch('cusd_plus.gm_holdings.complete_holdings', return_value=(stock_held or {}, {})), \
                patch.object(member_portfolio, '_market', return_value=MARKET), \
                patch.object(member_portfolio, 'dollars_usd', return_value=Decimal('50')), \
                patch.object(member_portfolio, 'presale_totals', return_value=(Decimal('0'), Decimal('0'))), \
                patch('cusd_plus.crypto_month.confirmed_trades', return_value=crypto_trades), \
                patch('cusd_plus.crypto_holdings.holdings_snapshot',
                      return_value=None if crypto_held is None else (crypto_held, None)) as self.snap, \
                patch('cusd_plus.crypto_month._live_prices', return_value=prices), \
                patch('cusd_plus.crypto_prices.market_rows', return_value=rows):
            return member_portfolio.build_portfolio(make_user())

    def test_bitcoin_and_gold_count_everywhere(self):
        crypto = [trade('crypto_buy', '0.001', '70', symbol='BTCB'),
                  trade('crypto_buy', '0.01', '41', symbol='XAUT', hours=1),
                  trade('crypto_sell', '0.01', '39', symbol='XAUT', hours=2)]
        p = self.build(crypto, {'BTCB': 10 ** 15})  # 0.001 BTC (18 decimals) still held
        [btc] = p.open_positions
        self.assertEqual((btc.ticker, btc.name, btc.value_usd), ('BTC', 'Bitcoin', Decimal('80')))
        self.assertEqual((btc.invested_usd, btc.pnl_usd), (Decimal('70'), Decimal('10')))
        [gold] = p.closed_positions
        self.assertEqual((gold.ticker, gold.name, gold.pnl_usd), ('XAUT', 'Oro', Decimal('-2')))
        self.assertEqual(p.crypto_usd, Decimal('80'))
        self.assertEqual(p.total_usd, Decimal('130'))  # 50 dollars + 0 stocks + 80 bitcoin
        self.assertEqual(p.stocks_change_24h_usd.quantize(Decimal('0.01')), Decimal('7.27'))  # 80 - 80/1.1
        self.assertEqual(p.trade_count, 3)

    def test_unpriced_crypto_makes_the_total_unknown_not_lower(self):
        p = self.build([trade('crypto_buy', '0.001', '70', symbol='BTCB')], {'BTCB': 10 ** 15}, prices={})
        self.assertIsNone(p.crypto_usd)
        self.assertIsNone(p.total_usd)
        self.assertIsNone(p.open_positions[0].value_usd)

    def test_only_a_fresh_holdings_read_is_trusted(self):
        p = self.build([trade('crypto_buy', '0.001', '70', symbol='BTCB')], None)
        self.assertEqual(self.snap.call_args.kwargs, {'allow_last_known': False})
        self.assertIsNone(p.crypto_usd)
        self.assertIsNone(p.total_usd)
        self.assertIsNone(p.open_positions)

    def test_an_unreadable_swap_never_poisons_a_stock(self):
        stocks = [trade('stock_buy', '1', '100'), trade('stock_sell', '1', '130', hours=3)]
        p = self.build([trade('crypto_buy', '0', None, symbol='?9')], {}, stock_trades=stocks)
        [nvda] = p.closed_positions
        self.assertEqual((nvda.ticker, nvda.pnl_usd), ('NVDA', Decimal('30')))

    def test_a_member_who_never_swapped_costs_no_scan(self):
        with patch('cusd_plus.crypto_holdings.holdings_snapshot') as scan:
            part = member_portfolio.crypto_part('0x' + '1' * 40, NOW)
        scan.assert_not_called()
        self.assertEqual((part.total, part.open_positions), (Decimal('0'), []))


class TotalReturnTests(CommunityTestBase):
    def total(self, trades, held, market=MARKET):
        with patch.object(member_portfolio, 'personal_wallet', return_value='0xabc'), \
                patch('cusd_plus.stock_month.confirmed_trades', return_value=trades), \
                patch('cusd_plus.gm_holdings.complete_holdings', return_value=(held, {})), \
                patch.object(member_portfolio, '_market', return_value=market), \
                patch.object(member_portfolio, 'dollars_usd', return_value=Decimal('0')), \
                patch.object(member_portfolio, 'presale_totals', return_value=(Decimal('0'), Decimal('0'))):
            return member_portfolio.total_return(make_user())

    def test_realized_plus_open_value_on_everything_bought(self):
        # Bought NVDA $100 + $140 (now 2 × $120 = $240), TSLA $10 sold for $15.
        result = self.total([trade('stock_buy', '1', '100'), trade('stock_buy', '1', '140', hours=1),
                             trade('stock_buy', '1', '10', symbol='TSLAon', hours=2),
                             trade('stock_sell', '1', '15', symbol='TSLAon', hours=3)],
                            {'NVDAon': Decimal('2')})
        self.assertEqual((result.gain_usd, result.invested_usd), (Decimal('5'), Decimal('250')))
        self.assertEqual(result.pct, Decimal('2'))
        self.assertEqual(result.since, timezone.localdate(NOW - timedelta(hours=48)))

    def test_a_partial_sale_counts_its_proceeds(self):
        # 2 NVDA for $200, 1 sold for $150, 1 left worth $120: +$70 on $200.
        result = self.total([trade('stock_buy', '2', '200'), trade('stock_sell', '1', '150', hours=1)],
                            {'NVDAon': Decimal('1')})
        self.assertEqual((result.gain_usd, result.pct), (Decimal('70'), Decimal('35')))

    def test_anything_unexplained_is_unknown(self):
        # Units from outside, a trade without a price, an open book not held.
        self.assertIsNone(self.total([trade('stock_buy', '1', '100')], {'NVDAon': Decimal('3')}))
        self.assertIsNone(self.total([trade('stock_buy', '1', None)], {'NVDAon': Decimal('1')}))
        self.assertIsNone(self.total([trade('stock_buy', '1', '100')], {}))
        self.assertIsNone(self.total([], {}))

    def test_an_outside_sale_in_a_closed_episode_still_makes_it_unknown(self):
        # Sold a unit from outside, then bought and sold one in Confío.
        self.assertIsNone(self.total([trade('stock_sell', '1', '100'), trade('stock_buy', '1', '100', hours=1),
                                      trade('stock_sell', '1', '120', hours=2)], {}))

    def test_holdings_are_valued_against_the_same_ledger_snapshot(self):
        calls = []

        def ledger(wallet):
            calls.append(wallet)
            return [trade('stock_buy', '1', '100')]
        with patch.object(member_portfolio, 'personal_wallet', return_value='0xabc'), \
                patch('cusd_plus.stock_month.confirmed_trades', side_effect=ledger), \
                patch('cusd_plus.gm_holdings.complete_holdings', return_value=({'NVDAon': Decimal('1')}, {})), \
                patch.object(member_portfolio, '_market', return_value=MARKET), \
                patch.object(member_portfolio, 'dollars_usd', return_value=Decimal('0')), \
                patch.object(member_portfolio, 'presale_totals', return_value=(Decimal('0'), Decimal('0'))):
            member_portfolio.total_return(make_user())
        self.assertEqual(len(calls), 1)

    def test_an_explained_dust_leftover_does_not_blank_the_total(self):
        # 1 NVDA for $100, 0.9999 sold for $110, 0.0001 left (worth $0.012 → kept;
        # make it dust by pricing at $50): Total still counts the sale.
        market = dict(MARKET, NVDAon={**MARKET['NVDAon'], 'price': Decimal('50')})
        result = self.total([trade('stock_buy', '1', '100'), trade('stock_sell', '0.9999', '110', hours=1)],
                            {'NVDAon': Decimal('0.0001')}, market=market)
        self.assertIsNotNone(result)
        self.assertEqual(result.gain_usd, Decimal('10'))     # the $0.005 leftover adds nothing
