"""Futuros in Comunidad: episodes from the ledger, daily equity, the Liga's
ledger rows, the investor profile and share cards."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from cusd_plus import perps_portfolio
from cusd_plus.perps_portfolio import Episode

T0 = timezone.now() - timedelta(days=3)


def _episode(**kw):
    fields = dict(position_id=7, coin='BTC', ticker='BTC', side='long', leverage=5, state='open',
                  put_in=[(T0, Decimal('20.18'), 100)], returned=None, credited=Decimal('19.9'),
                  entry_px=Decimal('100000'), size_signed=Decimal('0.00099'), closed_at=None,
                  settled_equity=None, liquidated=False, filled_at=T0)
    fields.update(kw)
    return Episode(**fields)


class EquityTests(SimpleTestCase):
    def test_open_episode_marks_to_the_price(self):
        ep = _episode()
        self.assertEqual(perps_portfolio.equity_at(ep, T0 - timedelta(hours=1), lambda c: Decimal(1)), 0)
        at = T0 + timedelta(hours=1)
        self.assertEqual(perps_portfolio.equity_at(ep, at, lambda c: Decimal('110000')),
                         Decimal('19.9') + Decimal('0.00099') * 10000)
        short = _episode(side='short', size_signed=Decimal('-0.00099'))
        self.assertEqual(perps_portfolio.equity_at(short, at, lambda c: Decimal('110000')),
                         Decimal('19.9') - Decimal('9.9'))
        # A move past the margin floors at zero (liquidated by then).
        self.assertEqual(perps_portfolio.equity_at(short, at, lambda c: Decimal('200000')), 0)

    def test_margin_added_later_never_values_an_earlier_day(self):
        added = T0 + timedelta(days=1)
        ep = _episode(credited=Decimal('29.9'), credited_initial=Decimal('19.9'),
                      credit_events=[(added, Decimal('10'))])
        flat = lambda c: Decimal('100000')  # noqa: E731 — price at entry: equity = margin
        self.assertEqual(perps_portfolio.equity_at(ep, T0 + timedelta(hours=1), flat), Decimal('19.9'))
        self.assertEqual(perps_portfolio.equity_at(ep, added + timedelta(hours=1), flat), Decimal('29.9'))

    def test_partial_close_values_later_days_with_the_smaller_size(self):
        half = T0 + timedelta(days=1)
        ep = _episode(size_signed=Decimal('1'), credited=Decimal('20000'),
                      size_events=[(half, Decimal('0.5'), Decimal('0'), None)])
        up = lambda c: Decimal('110000')  # noqa: E731
        self.assertEqual(perps_portfolio.equity_at(ep, T0 + timedelta(hours=1), up), Decimal('30000'))
        self.assertEqual(perps_portfolio.equity_at(ep, half + timedelta(hours=1), up), Decimal('25000'))

    def test_exposure_starts_at_the_fill_not_at_funding(self):
        filled = T0 + timedelta(days=1)
        ep = _episode(filled_at=filled)
        far = lambda c: Decimal('200000')  # noqa: E731
        self.assertEqual(perps_portfolio.equity_at(ep, T0 + timedelta(hours=2), far), Decimal('19.9'),
                         'funded, not yet open: just its margin')
        self.assertGreater(perps_portfolio.equity_at(ep, filled + timedelta(hours=1), far), Decimal('19.9'))

    def test_closed_then_returned(self):
        closed_at = T0 + timedelta(days=1)
        back = T0 + timedelta(days=1, hours=1)
        ep = _episode(closed_at=closed_at, settled_equity=Decimal('23.3'), returned=(back, Decimal('22.95'), 120))
        self.assertEqual(perps_portfolio.equity_at(ep, closed_at + timedelta(minutes=5), None), Decimal('23.3'))
        # Half-open, as the ledger: at the return's own instant it is still valued
        # (the flow belongs to the next window); right after, it is gone.
        self.assertEqual(perps_portfolio.equity_at(ep, back, None), Decimal('23.3'))
        self.assertEqual(perps_portfolio.equity_at(ep, back + timedelta(seconds=1), None), 0)

    def test_ledger_rows_are_flows_plus_a_close_marker(self):
        closed_at = T0 + timedelta(days=1)
        ep = _episode(closed_at=closed_at, settled_equity=Decimal('23.3'),
                      returned=(closed_at + timedelta(hours=1), Decimal('22.95'), 120))
        rows = perps_portfolio.ledger_trades([ep])
        # Flows, plus zero-flow markers (fill, the bridge's credit, the close).
        self.assertEqual([r.kind for r in rows], ['perps_buy', 'perps_mark', 'perps_mark', 'perps_close', 'perps_sell'])
        self.assertEqual((rows[0].usd, rows[0].block, rows[4].usd), (Decimal('20.18'), 100, Decimal('22.95')))
        self.assertEqual((rows[1].usd, rows[2].usd, rows[3].usd), (0, 0, 0), 'markers move no money')
        self.assertEqual(ep.label, 'BTC · Largo 5x')


class LigaTests(SimpleTestCase):
    def test_value_and_flows_include_perps(self):
        from inbox import portfolio_returns as pr

        ep = _episode()
        ledger = pr.Ledger(stocks=[], crypto=[], perps=[ep], perps_rows=perps_portfolio.ledger_trades([ep]))
        prices = mock.Mock()
        prices.close.return_value = Decimal('110000')
        when = T0 + timedelta(hours=2)
        value = pr.value_at(ledger, when, timezone.now(), prices)
        self.assertEqual(value, Decimal('19.9') + Decimal('9.9'))
        prices.close.assert_called_with('perp', 'BTC', when, mock.ANY)
        flow = pr._flows(ledger, T0 - timedelta(minutes=1), T0 + timedelta(minutes=1))
        self.assertEqual(flow, Decimal('20.18'))
        self.assertIn(ledger.perps_rows[0], ledger.all)


class ShareTests(SimpleTestCase):
    def test_headlines(self):
        from inbox.activity_share import activity_headline

        with mock.patch('users.number_format.format_amount', side_effect=lambda v, trim=False: str(v)):
            self.assertEqual(activity_headline({'kind': 'perps_open', 'name': 'BTC · Corto 5x',
                                                'amount_usd': '20.18'}), 'Abrió BTC · Corto 5x · US$20.18')
            self.assertEqual(activity_headline({'kind': 'perps_close', 'name': 'BTC · Corto 5x',
                                                'amount_usd': '22.95', 'pnl_pct': '13.73'}),
                             'Cerró BTC · Corto 5x · US$22.95 · +13.73%')

    def test_old_builds_get_the_stock_twin_with_the_full_label(self):
        from inbox.schema import build_activity_type

        public = {'kind': 'perps_open', 'ticker': 'BTC', 'name': 'BTC · Corto 5x', 'amount_usd': '20.18'}
        with mock.patch('inbox.activity_share.activity_headline', return_value=''):
            old = build_activity_type(public, public, {'HTTP_X_CONFIO_VERSION': '5.2.4'})
        self.assertEqual((old.kind, old.ticker), ('stock_buy', 'BTC · Corto 5x'))


class EpisodesFromLedgerTests(TestCase):
    def test_needs_exact_settlement_rows(self):
        from blockchain.models import PerpMarket, PerpPosition, SponsoredBatch
        from users.models import User
        from users.models_unified import UnifiedTransactionTable

        user = User.objects.create(username='perpsep', firebase_uid='perpsep')
        wallet = '0x' + '55' * 20
        market = PerpMarket.objects.create(coin='BTC', dex='', asset_id=0, sz_decimals=5, max_leverage=40,
                                           collateral='USDC', synced_at=timezone.now())
        batch = SponsoredBatch.objects.create(user=user, user_bsc_address=wallet, kind='perps_open',
                                              calls_json='[]', num_calls=3, tx_hash='0x' + '01' * 32,
                                              status='confirmed', gas_limit=1, max_fee_wei=1, block_number=10)
        PerpPosition.objects.create(user=user, wallet=wallet, market=market, side='long', leverage=5,
                                    margin_usd=Decimal('20'), state='open', open_batch=batch,
                                    credited_usdc=Decimal('19.9'), entry_avg_px=Decimal('100000'),
                                    size=Decimal('0.00099'), opened_at=timezone.now())
        with self.assertRaises(perps_portfolio.PerpsLedgerUnknown):
            perps_portfolio.episodes(wallet)
        UnifiedTransactionTable.objects.create(
            sponsored_batch=batch, transaction_type='send', amount='20.18', token_type='CUSD_BSC',
            amount_denomination='USD_VALUE', status='CONFIRMED', transaction_hash=batch.tx_hash,
            transaction_date=batch.created_at, sender_type='user', counterparty_type='user')
        eps = perps_portfolio.episodes(wallet)
        self.assertEqual(len(eps), 1)
        self.assertEqual((eps[0].invested, eps[0].size_signed), (Decimal('20.18'), Decimal('0.00099')))


class PerpsMonthTests(SimpleTestCase):
    """Tu mes "Futuros": the month in the member's own money (margin in,
    dollars back), never the leveraged exposure."""

    def _run(self, eps, start, end, now, live=None, closes=None, in_flight=False, topup_bridging=False,
             landed=None):
        from cusd_plus import perps_month

        prices = mock.Mock()
        prices._series.side_effect = lambda kind, coin: sorted((closes or {}).items())
        prices.block_time.side_effect = lambda block: landed
        flight = mock.Mock()
        flight.exists.return_value = in_flight
        topups = mock.Mock()
        topups.filter.return_value.exists.return_value = topup_bridging
        with mock.patch('cusd_plus.perps_portfolio.episodes', return_value=eps), \
                mock.patch('blockchain.models.PerpMarginChange.objects', topups), \
                mock.patch('cusd_plus.perps_portfolio.batches_in_flight', return_value=flight), \
                mock.patch('cusd_plus.perps_portfolio.live_marks', return_value=live or {}), \
                mock.patch('inbox.portfolio_returns.PriceBook', return_value=prices), \
                mock.patch('inbox.portfolio_returns._settled_episode', side_effect=lambda ep, _p: ep):
            return perps_month.perps_month('0xabc', start, end, now)

    def test_opened_this_month_at_10x_counts_the_margin_not_the_exposure(self):
        start, end = T0 - timedelta(days=1), T0 + timedelta(days=30)
        ep = _episode(leverage=10, size_signed=Decimal('0.00199'), credited=Decimal('19.9'))
        result = self._run([ep], start, end, now=T0 + timedelta(days=1), live={'BTC': Decimal('110000')})
        self.assertEqual(result.state, 'gain')
        self.assertEqual(result.bought, Decimal('20.18'), 'the margin that left, never 10x of it')
        self.assertEqual(result.value_start, 0)
        self.assertEqual(result.value_end, Decimal('19.9') + Decimal('0.00199') * 10000)
        self.assertEqual(result.gain, result.value_end - Decimal('20.18'))

    def test_a_past_month_closes_at_the_perps_daily_close_and_counts_money_back(self):
        start = T0 - timedelta(days=1)
        end = T0 + timedelta(days=2)
        closed = T0 + timedelta(days=1)
        back = (closed + timedelta(hours=1), Decimal('22.95'), 120)
        ep = _episode(closed_at=closed, settled_equity=Decimal('23.3'), returned=back)
        result = self._run([ep], start, end, now=end + timedelta(days=5), closes={start: Decimal('100000')})
        self.assertEqual((result.bought, result.sold), (Decimal('20.18'), Decimal('22.95')))
        self.assertEqual(result.gain, Decimal('0') - 0 - Decimal('20.18') + Decimal('22.95'))

    def test_a_local_month_boundary_uses_the_last_utc_close_before_it(self):
        from datetime import datetime, timezone as tz
        start = datetime(2026, 10, 1, 4, tzinfo=tz.utc)          # Bolivia's midnight
        end = datetime(2026, 11, 1, 4, tzinfo=tz.utc)
        ep = _episode(put_in=[(start - timedelta(days=10), Decimal('20.18'), 100)],
                      filled_at=start - timedelta(days=10))
        closes = {datetime(2026, 10, 1, tzinfo=tz.utc): Decimal('100000'),
                  datetime(2026, 11, 1, tzinfo=tz.utc): Decimal('110000')}
        result = self._run([ep], start, end, now=end + timedelta(days=2), closes=closes)
        self.assertEqual(result.state, 'gain')
        self.assertEqual(result.value_start, Decimal('19.9'))
        self.assertEqual(result.gain, Decimal('0.00099') * 10000)

    def test_a_batch_recorded_before_local_midnight_counts_where_it_landed(self):
        from datetime import datetime, timezone as tz
        start = datetime(2026, 10, 1, 4, tzinfo=tz.utc)
        end = datetime(2026, 11, 1, 4, tzinfo=tz.utc)
        recorded = end - timedelta(minutes=1)
        ep = _episode(put_in=[(recorded, Decimal('20.18'), 100)], filled_at=end + timedelta(minutes=2))
        closes = {datetime(2026, 11, 1, tzinfo=tz.utc): Decimal('100000')}
        result = self._run([ep], start, end, now=end + timedelta(days=2), closes=closes,
                           landed=end + timedelta(minutes=1))
        self.assertEqual(result.state, 'none', "November's margin, not October's")

    def test_money_on_the_wire_is_settling_and_nothing_held_is_none(self):
        start, end = T0 - timedelta(days=1), T0 + timedelta(days=30)
        self.assertEqual(self._run([_episode(state='bridging')], start, end, T0).state, 'settling')
        self.assertEqual(self._run([_episode()], start, end, T0, in_flight=True).state, 'settling')
        self.assertEqual(self._run([], start, end, T0).state, 'none')
        # A first open on the wire (no episode yet) and a top-up on the bridge settle too.
        self.assertEqual(self._run([], start, end, T0, in_flight=True).state, 'settling')
        self.assertEqual(self._run([_episode()], start, end, T0, topup_bridging=True).state, 'settling')
