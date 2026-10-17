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
