from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from . import portfolio_returns as pr
from . import rolling_returns as rr
from .models import PortfolioValueSnapshot
from .test_community import CommunityTestBase, make_user
from .test_portfolio_returns import NOW, WALLET, trade

START = NOW - timedelta(hours=24)
OLD = trade('stock_buy', '1', '100', NOW - timedelta(days=3))


def ledger(*stocks):
    return pr.Ledger(stocks=list(stocks), crypto=[])


class RollingTests(CommunityTestBase):
    def setUp(self):
        super().setUp()
        self.user = make_user()

    def snap(self, at, value, on=None, marks=None):
        PortfolioValueSnapshot.objects.create(user=self.user, wallet=WALLET, at=at, value_usd=Decimal(value),
                                              other_usd=Decimal(value), perps_marks=marks or {},
                                              ledger_sig=rr.flow_signature(on or ledger(OLD), at))

    def rolling(self, stocks, value_now, with_points=False, raises=None):
        with patch.object(rr, 'trusted_ledger', return_value=ledger(*stocks), side_effect=raises), \
                patch.object(rr, 'live_value', return_value=Decimal(value_now)):
            return rr.rolling(WALLET, NOW, with_points=with_points)

    def test_a_buy_in_the_last_24_hours_is_money_put_in_not_a_gain(self):
        self.snap(START - timedelta(minutes=4), '110')
        buy = trade('stock_buy', '1', '12', NOW - timedelta(hours=2), symbol='TSLAon')
        r = self.rolling([OLD, buy], '125')
        self.assertEqual(r.gain, Decimal('3'))                    # 125 - 110 - 12
        self.assertEqual(r.capital, Decimal('116'))               # 110 + 12 / 2
        self.assertEqual(r.pct, Decimal('3') / Decimal('116') * 100)

    def test_a_sale_is_money_taken_out(self):
        self.snap(START, '110')
        sale = trade('stock_sell', '1', '108', NOW - timedelta(hours=3))
        r = self.rolling([OLD, sale], '0')
        self.assertEqual((r.gain, r.capital), (Decimal('-2'), Decimal('110')))

    def test_a_first_trade_inside_the_window_starts_from_nothing(self):
        r = self.rolling([trade('stock_buy', '1', '100', NOW - timedelta(hours=5))], '104')
        self.assertEqual((r.gain, r.value_start), (Decimal('4'), Decimal('0')))

    def test_no_snapshot_near_24_hours_ago_is_unknown(self):
        self.snap(START + timedelta(minutes=5), '110')            # too recent
        self.snap(START - timedelta(minutes=45), '110')           # too old
        self.assertIsNone(self.rolling([OLD], '111'))

    def test_a_snapshot_on_another_ledger_is_unknown(self):
        self.snap(START, '110')
        late = trade('stock_buy', '1', '50', START - timedelta(hours=1), symbol='TSLAon')
        self.assertIsNone(self.rolling([OLD, late], '170'))

    def test_anything_unknown_is_unknown(self):
        self.snap(START, '110')
        self.assertIsNone(self.rolling([OLD], '111', raises=pr.Retry('trade on the wire')))
        self.assertIsNone(self.rolling([OLD], '111', raises=pr.Untrusted(pr.OUTSIDE_UNITS)))

    def test_a_re_dated_futuros_marker_keeps_the_snapshot(self):
        mark = trade('perps_mark', '3', '0', START - timedelta(hours=2), symbol='perp:1')
        self.snap(START, '110', on=ledger(OLD, mark))
        moved = trade('perps_mark', '4', '0', NOW - timedelta(hours=1), symbol='perp:1')   # the day's last cost
        self.assertEqual(self.rolling([OLD, moved], '111').gain, Decimal('1'))

    def test_futuros_costs_synced_after_a_snapshot_count_before_it(self):
        # Taken at $100 of stocks + $100 of Futuros; a $5 funding payment from
        # before it synced later: the start is re-valued at the stored marks.
        self.snap(START, '100', marks={'BTC': '100'})
        with patch.object(rr, '_perps_value', return_value=Decimal('95')) as perps:
            r = self.rolling([OLD], '195')
        self.assertEqual((r.value_start, r.gain), (Decimal('195'), Decimal('0')))
        self.assertEqual(perps.call_args.args[1:], (START, {'BTC': '100'}))

    def test_points_from_the_snapshots_end_at_now(self):
        self.snap(START, '100')
        self.snap(NOW - timedelta(hours=12), '105')
        self.snap(NOW - timedelta(hours=6), '999', on=ledger())   # another ledger: skipped
        r = self.rolling([OLD], '110', with_points=True)
        self.assertEqual([p for _, p in r.points], [Decimal('0'), Decimal('5'), Decimal('10')])
        self.assertEqual((r.points[0][0], r.points[-1][0]), (START, NOW))


class SnapshotTests(CommunityTestBase):
    def test_a_snapshot_is_written_only_when_the_value_is_known(self):
        user = make_user()
        with patch.object(rr, 'trusted_ledger', return_value=ledger(OLD)), \
                patch.object(rr, 'live_value', return_value=Decimal('123.4567891')):
            self.assertTrue(rr.snapshot_wallet(user, WALLET, NOW, pr.PriceBook()))
        snap = PortfolioValueSnapshot.objects.get(wallet=WALLET)
        self.assertEqual((snap.value_usd, snap.other_usd, snap.perps_marks, snap.ledger_sig),
                         (Decimal('123.456789'), Decimal('123.456789'), {}, rr.flow_signature(ledger(OLD), NOW)))
        with patch.object(rr, 'trusted_ledger', side_effect=pr.Retry('trade on the wire')):
            self.assertFalse(rr.snapshot_wallet(user, WALLET, NOW, pr.PriceBook()))
        with patch.object(rr, 'trusted_ledger', return_value=ledger()):
            self.assertFalse(rr.snapshot_wallet(user, WALLET, NOW, pr.PriceBook()))
        self.assertEqual(PortfolioValueSnapshot.objects.count(), 1)

    def test_old_snapshots_are_pruned(self):
        from django.utils import timezone

        user = make_user()
        old = PortfolioValueSnapshot.objects.create(user=user, wallet=WALLET, at=timezone.now() - timedelta(days=4),
                                                    value_usd=Decimal('1'), other_usd=Decimal('1'), ledger_sig='x')
        with patch.object(rr, 'wallets_to_snapshot', return_value=[]):
            rr.snapshot_all(budget_seconds=60)
        self.assertFalse(PortfolioValueSnapshot.objects.filter(id=old.id).exists())
