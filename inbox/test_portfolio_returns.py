from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from cusd_plus.stock_month import Trade
from . import portfolio_returns as pr
from .models import PortfolioDailySnapshot
from .schema import Query, SetCommunityPortfolioHidden
from .test_community import APPROVE, CommunityTestBase, MockInfo, make_user

# 2026-10-22 15:00 UTC: "today" is the 22nd, the last complete day the 21st.
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=dt_timezone.utc)
D20, D21, D22 = date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)
WALLET = '0xabc'


def at(day, hour=12, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt_timezone.utc)


def trade(kind, units, usd, when, symbol='NVDAon', block=None):
    return Trade(symbol=symbol, kind=kind, units=Decimal(units), usd=None if usd is None else Decimal(usd),
                 when=when, block=block)


class TablePrices(pr.PriceBook):
    """Closes keyed by the boundary's UTC date: (symbol, D) prices 00:00 of D."""

    def __init__(self, table, block_times=None):
        super().__init__()
        self.table = table
        self.times = block_times or {}

    def close(self, kind, symbol, boundary, now):
        price = self.table.get((symbol, boundary.date()))
        if price is None:
            if now - boundary > pr.PRICE_GRACE:
                raise pr.Untrusted(pr.PRICE_MISSING)
            raise pr.Retry('no close')
        return price

    def block_time(self, block):
        return self.times.get(block)


class DietzTests(CommunityTestBase):
    def test_the_spec_fixture(self):
        # V0=$100, a $50 buy mid-day, V1=$160: (160-100-50)/(100+25) = 8%.
        gain, ret = pr.dietz(Decimal('100'), Decimal('160'), Decimal('50'))
        self.assertEqual((gain, ret * 100), (Decimal('10'), Decimal('8')))

    def test_a_base_under_a_dollar_is_a_flat_day(self):
        self.assertEqual(pr.dietz(Decimal('0'), Decimal('0.6'), Decimal('0.5')), (Decimal('0.1'), Decimal('0')))


class PriceBookTests(CommunityTestBase):
    def book(self, series):
        book = pr.PriceBook()
        for ref in pr.MARKET_REFERENCES:     # no network: a test sets the ones it needs
            book._candles[('stock', ref)] = None
        book._candles[('stock', 'NVDAon')] = series
        return book

    def test_a_close_exactly_at_the_boundary_is_final(self):
        book = self.book([(at(D21, 0), Decimal('100'))])
        self.assertEqual(book.close('stock', 'NVDAon', at(D21, 0), NOW), Decimal('100'))

    def test_a_delayed_candle_is_retried_not_carried(self):
        # Yesterday's candle (closing at 00:00 of the 22nd) hasn't arrived yet.
        book = self.book([(at(D21, 0), Decimal('100'))])
        with self.assertRaises(pr.Retry):
            book.close('stock', 'NVDAon', at(D22, 0), NOW)

    def test_a_market_closure_carries_the_last_close_once_the_feed_moved_on(self):
        # Friday's close covers Saturday and Sunday once Monday's candle is in,
        # and the broad market had no session either.
        sat, sun, mon, tue = date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 19), date(2026, 10, 20)
        book = self.book([(at(sat, 0), Decimal('100')), (at(tue, 0), Decimal('110'))])
        book._candles[('stock', 'SPYon')] = [(at(sat, 0), Decimal('500')), (at(tue, 0), Decimal('505'))]
        self.assertEqual(book.close('stock', 'NVDAon', at(sun, 0), NOW), Decimal('100'))
        self.assertEqual(book.close('stock', 'NVDAon', at(mon, 0), NOW), Decimal('100'))

    def test_a_settled_no_trade_gap_carries_the_last_close(self):
        # PBRon had no weekend candles while the references traded; two days
        # on, its own feed has moved past and the gap is still there.
        sat, sun, mon, tue = date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12), date(2026, 10, 13)
        book = self.book([(at(sat, 0), Decimal('26')), (at(tue, 0), Decimal('26.4'))])
        book._candles[('stock', 'SPYon')] = [(at(d, 0), Decimal('500')) for d in (sat, sun, mon, tue)]
        self.assertEqual(book.close('stock', 'NVDAon', at(sun, 0), NOW), Decimal('26'))
        self.assertEqual(book.close('stock', 'NVDAon', at(mon, 0), NOW), Decimal('26'))

    def test_an_untraded_weekend_day_is_final_once_the_market_feed_is_past_it(self):
        # PBRon: no Saturday candle, SPYon has its Saturday candle, and it's
        # Sunday morning: nobody traded PBRon on Saturday, Friday's close holds.
        sat, sun = date(2026, 10, 24), date(2026, 10, 25)
        book = self.book([(at(sat, 0), Decimal('26'))])
        book._candles[('stock', 'SPYon')] = [(at(sat, 0), Decimal('500')), (at(sun, 0), Decimal('501'))]
        self.assertEqual(book.close('stock', 'NVDAon', at(sun, 0), at(sun, 6)), Decimal('26'))
        # Shown, but provisional: the token's own candle may still come.
        self.assertTrue(book.provisional)
        # Past the price grace with still no candle of its own: unknown, not provisional.
        late = PriceBookTests.book(self, [(at(sat, 0), Decimal('26'))])
        late._candles[('stock', 'SPYon')] = [(at(sat, 0), Decimal('500')), (at(sun, 0), Decimal('501'))]
        with self.assertRaises(pr.Untrusted):
            late.close('stock', 'NVDAon', at(sun, 0), at(sun, 0) + pr.PRICE_GRACE + timedelta(hours=1))
        # Too soon after midnight: maybe just late.
        with self.assertRaises(pr.Retry):
            book.close('stock', 'NVDAon', at(sun, 0), at(sun, 2))

    def test_an_untraded_weekend_needs_the_market_feed_past_it(self):
        sat, sun = date(2026, 10, 24), date(2026, 10, 25)
        book = self.book([(at(sat, 0), Decimal('26'))])
        book._candles[('stock', 'SPYon')] = [(at(sat, 0), Decimal('500'))]     # feed not past Saturday
        with self.assertRaises(pr.Retry):
            book.close('stock', 'NVDAon', at(sun, 0), at(sun, 6))

    def test_a_weekday_gap_never_counts_as_an_untraded_weekend(self):
        mon, tue = date(2026, 10, 26), date(2026, 10, 27)
        book = self.book([(at(mon, 0), Decimal('26'))])                  # Sunday close, Monday missing
        book._candles[('stock', 'SPYon')] = [(at(mon, 0), Decimal('500')), (at(tue, 0), Decimal('501'))]
        with self.assertRaises(pr.Retry):
            book.close('stock', 'NVDAon', at(tue, 0), at(tue, 6))

    def test_a_fresh_gap_in_this_symbol_is_retried(self):
        # The 21st's candle is missing but only a day has passed: maybe late.
        now = at(D22, 23)
        book = self.book([(at(D20, 0), Decimal('100')), (at(D22, 0), Decimal('110'))])
        book._candles[('stock', 'SPYon')] = [(at(d, 0), Decimal('500')) for d in (D20, D21, D22)]
        with self.assertRaises(pr.Retry):
            book.close('stock', 'NVDAon', at(D21, 0), now)

    def test_a_gap_its_own_feed_has_not_moved_past_is_not_settled(self):
        book = self.book([(at(date(2026, 10, 10), 0), Decimal('100'))])
        with self.assertRaises(pr.Untrusted):
            book.close('stock', 'NVDAon', at(date(2026, 10, 12), 0), NOW)

    def test_a_gap_only_in_this_symbol_is_not_a_closure(self):
        book = self.book([(at(D20, 0), Decimal('100')), (at(D22, 0), Decimal('110'))])
        book._candles[('stock', 'SPYon')] = [(at(D20, 0), Decimal('500')), (at(D21, 0), Decimal('501')),
                                             (at(D22, 0), Decimal('502'))]
        with self.assertRaises(pr.Retry):
            book.close('stock', 'NVDAon', at(D21, 0), NOW)

    def test_without_a_reference_nothing_is_a_closure(self):
        book = self.book([(at(D20, 0), Decimal('100')), (at(D22, 0), Decimal('110'))])
        for ref in pr.MARKET_REFERENCES:
            book._candles[('stock', ref)] = None
        with self.assertRaises(pr.Retry):
            book.close('stock', 'NVDAon', at(D21, 0), NOW)

    def test_a_reference_never_vouches_for_its_own_gap(self):
        book = self.book([])
        book._candles[('stock', 'SPYon')] = [(at(D20, 0), Decimal('100')), (at(D22, 0), Decimal('120'))]
        book._candles[('stock', 'IVVon')] = [(at(D20, 0), Decimal('1')), (at(D21, 0), Decimal('1')),
                                             (at(D22, 0), Decimal('1'))]
        with self.assertRaises(pr.Retry):
            book.close('stock', 'SPYon', at(D21, 0), NOW)

    def test_one_reference_that_traded_in_the_gap_proves_the_market_was_open(self):
        book = self.book([(at(D20, 0), Decimal('100')), (at(D22, 0), Decimal('110'))])
        book._candles[('stock', 'SPYon')] = [(at(D20, 0), Decimal('500')), (at(D22, 0), Decimal('502'))]
        book._candles[('stock', 'IVVon')] = [(at(D20, 0), Decimal('1')), (at(D21, 0), Decimal('1')),
                                             (at(D22, 0), Decimal('1'))]
        with self.assertRaises(pr.Retry):
            book.close('stock', 'NVDAon', at(D21, 0), NOW)

    def test_a_lagging_reference_that_traded_in_the_gap_still_proves_it_open(self):
        book = self.book([(at(D20, 0), Decimal('100')), (at(D22, 0), Decimal('110'))])
        book._candles[('stock', 'SPYon')] = [(at(D20, 0), Decimal('500')), (at(D22, 0), Decimal('502'))]
        book._candles[('stock', 'IVVon')] = [(at(D20, 0), Decimal('1')), (at(D21, 0), Decimal('1'))]
        with self.assertRaises(pr.Retry):
            book.close('stock', 'NVDAon', at(D21, 0), NOW)

    def test_bitcoin_never_carries_across_a_gap(self):
        book = pr.PriceBook()
        book._candles[('crypto', 'BTC')] = [(at(D20, 0), Decimal('1')), (at(D22, 0), Decimal('2'))]
        with self.assertRaises(pr.Retry):
            book.close('crypto', 'BTC', at(D21, 0), NOW)

    def test_a_forming_candle_does_not_count_as_moving_on(self):
        book = self.book([(at(D21, 0), Decimal('100')), (at(D22, 0) + timedelta(days=1), Decimal('1'))])
        with self.assertRaises(pr.Retry):
            book.close('stock', 'NVDAon', at(D22, 0), NOW)

    def test_a_close_that_never_arrives_becomes_unknown(self):
        book = self.book([(at(date(2026, 10, 1), 0), Decimal('100'))])
        with self.assertRaises(pr.Untrusted):
            book.close('stock', 'NVDAon', at(date(2026, 10, 10), 0), NOW)

    def test_a_forming_stock_candle_is_dropped_when_fetched(self):
        fetched = pr.timezone.now()
        rows = [{'timestamp': (fetched - timedelta(days=2)).timestamp() * 1000, 'close': '100'},
                {'timestamp': (fetched - timedelta(days=1, seconds=-60)).timestamp() * 1000, 'close': '105'}]
        with patch('cusd_plus.gm_api.ohlc', return_value=rows):
            series = pr.PriceBook._fetch('stock', 'NVDAon')
        self.assertEqual([price for _, price in series], [Decimal('100')])

    def test_a_dead_feed_is_fetched_once_per_run(self):
        book = pr.PriceBook()
        with patch.object(pr.PriceBook, '_fetch', side_effect=RuntimeError('timeout')) as fetch:
            for day in (D20, D21):
                with self.assertRaises(pr.Retry):
                    book.close('stock', 'NVDAon', at(day, 0), NOW)
        self.assertEqual(fetch.call_count, 1)


class ComputeDayTests(CommunityTestBase):
    def day(self, stocks, table, crypto=(), day=D21):
        ledger = pr.Ledger(stocks=list(stocks), crypto=list(crypto))
        return pr.compute_day(ledger, day, NOW, TablePrices(table))

    def test_a_deposit_is_never_a_gain(self):
        # Held 1 NVDA at $100; bought 1 more for $100 at mid-day; closed at $100.
        d = self.day([trade('stock_buy', '1', '100', at(D20)), trade('stock_buy', '1', '100', at(D21))],
                     {('NVDAon', D21): Decimal('100'), ('NVDAon', D22): Decimal('100')})
        self.assertEqual((d.value_start, d.value_end, d.net_flow, d.gain, d.daily_return),
                         (Decimal('100'), Decimal('200'), Decimal('100'), Decimal('0'), Decimal('0')))

    def test_price_move_with_a_sale(self):
        # 2 units at $100 → sold 1 for $110 → closed at $120: gain = 120 - 200 + 110 = 30.
        d = self.day([trade('stock_buy', '2', '200', at(D20)), trade('stock_sell', '1', '110', at(D21))],
                     {('NVDAon', D21): Decimal('100'), ('NVDAon', D22): Decimal('120')})
        self.assertEqual(d.gain, Decimal('30'))
        self.assertEqual(d.daily_return, Decimal('30') / Decimal('145'))

    def test_a_trade_without_its_settlement_is_untrusted(self):
        with self.assertRaises(pr.Untrusted) as ctx:
            self.day([trade('stock_buy', '1', None, at(D21))],
                     {('NVDAon', D21): Decimal('100'), ('NVDAon', D22): Decimal('100')})
        self.assertEqual(ctx.exception.reason, pr.MISSING_SETTLEMENT)

    def test_a_small_real_bitcoin_holding_is_kept(self):
        crypto = [trade('crypto_buy', '0.000001', '0.1', at(D20), symbol='BTC')]
        d = self.day([], {('BTC', D21): Decimal('100000'), ('BTC', D22): Decimal('100000')}, crypto=crypto)
        self.assertEqual((d.value_start, d.value_end, d.gain), (Decimal('0.1'), Decimal('0.1'), Decimal('0')))

    def test_a_sell_all_rounding_overshoot_is_zero(self):
        stocks = [trade('stock_buy', '1', '100', at(D20)), trade('stock_sell', '1.0000000001', '100', at(D20, 13))]
        d = self.day(stocks, {})
        self.assertEqual((d.value_start, d.value_end), (Decimal('0'), Decimal('0')))

    def test_a_small_residual_stays_and_can_be_sold_later(self):
        crypto = [trade('crypto_buy', '1', '100000', at(D20, 1), symbol='BTC'),
                  trade('crypto_sell', '0.9999995', '99999.95', at(D20, 2), symbol='BTC'),
                  trade('crypto_buy', '0.001', '100', at(D20, 3), symbol='BTC'),
                  trade('crypto_sell', '0.0010005', '100.05', at(D20, 4), symbol='BTC')]
        d = self.day([], {}, crypto=crypto)
        self.assertEqual(d.value_end, Decimal('0'))

    def test_past_turnover_never_erases_a_new_small_position(self):
        crypto = [trade('crypto_buy', '100', '6000000', at(D20, 1), symbol='BTC'),
                  trade('crypto_sell', '100', '6000000', at(D20, 2), symbol='BTC'),
                  trade('crypto_buy', '0.0001', '10', at(D20, 3), symbol='BTC')]
        d = self.day([], {('BTC', D21): Decimal('100000'), ('BTC', D22): Decimal('100000')}, crypto=crypto)
        self.assertEqual((d.value_end, d.gain), (Decimal('10'), Decimal('0')))

    def test_a_day_that_has_not_ended_is_refused(self):
        with self.assertRaises(ValueError):
            self.day([], {}, day=D22)


class LoadLedgerTests(CommunityTestBase):
    def load(self, stocks, crypto=(), times=None):
        with patch('cusd_plus.stock_month.confirmed_trades', return_value=list(stocks)), \
                patch('cusd_plus.crypto_month.confirmed_trades', return_value=list(crypto)):
            return pr.load_ledger(WALLET, TablePrices({}, times))

    def test_selling_inventory_that_came_from_outside_is_untrusted_even_if_it_nets_out(self):
        # Receive 1 from outside, sell it, buy it back, send it out: ledger and chain both end at 0.
        with self.assertRaises(pr.Untrusted):
            self.load([trade('stock_sell', '1', '110', at(D20, 10)), trade('stock_buy', '1', '100', at(D20, 11))])

    def test_a_trade_recorded_before_midnight_takes_its_blocks_day(self):
        late = trade('stock_buy', '1', '100', at(D20, 23, 59), block=7)
        ledger = self.load([late], times={7: at(D21, 0, 1)})
        self.assertEqual(ledger.stocks[0].when, at(D21, 0, 1))

    def test_a_near_midnight_trade_without_a_block_time_is_retried(self):
        with self.assertRaises(pr.Retry):
            self.load([trade('stock_buy', '1', '100', at(D20, 23, 59), block=7)])

    def test_an_unreadable_trade_is_untrusted(self):
        with self.assertRaises(pr.Untrusted):
            self.load([trade('stock_buy', '0', None, at(D20), symbol='?9')])


class TodayGainTests(CommunityTestBase):
    """Hoy = value now - yesterday's stored close - money put in today."""
    OLD = trade('stock_buy', '1', '100', at(D20, 10))

    def gain(self, stocks, value_now, chain=None, times=None):
        with patch('cusd_plus.stock_month.confirmed_trades', return_value=stocks), \
                patch('cusd_plus.crypto_month.confirmed_trades', return_value=[]), \
                patch.object(pr, 'in_flight', return_value=False), \
                patch.object(pr, 'check_chain', side_effect=chain), \
                patch.object(pr, 'live_value', return_value=Decimal(value_now)):
            return pr.today_gain(WALLET, now=NOW, prices=TablePrices({}, times))

    def stored(self, stocks, value_end, trusted=True, provisional=False):
        sig = pr.Ledger(stocks=stocks, crypto=[]).signature(pr.day_start(D22))
        PortfolioDailySnapshot.objects.create(
            user=make_user(), wallet=WALLET, day=D21, value_end_usd=None if value_end is None else Decimal(value_end),
            ledger_trusted=trusted, ledger_sig=pr.provisional_sig(sig) if provisional else sig)

    def test_a_same_day_buy_is_money_put_in_not_a_gain(self):
        stocks = [self.OLD, trade('stock_buy', '1', '12', at(D22, 10), symbol='TSLAon')]
        self.stored([self.OLD], '110')
        # 125 now - 110 at last night's close - 12 put in today.
        self.assertEqual(self.gain(stocks, '125'), Decimal('3'))

    def test_a_same_day_sale_is_money_taken_out(self):
        stocks = [self.OLD, trade('stock_sell', '1', '108', at(D22, 10))]
        self.stored([self.OLD], '110')
        self.assertEqual(self.gain(stocks, '0'), Decimal('-2'))

    def test_a_provisional_weekend_close_is_shown(self):
        self.stored([self.OLD], '110', provisional=True)
        self.assertEqual(self.gain([self.OLD], '111'), Decimal('1'))

    def test_a_first_trade_today_starts_from_zero(self):
        self.assertEqual(self.gain([trade('stock_buy', '1', '100', at(D22, 10))], '104'), Decimal('4'))

    def test_no_stored_close_or_an_untrusted_one_is_unknown(self):
        self.assertIsNone(self.gain([self.OLD], '111'))
        self.stored([self.OLD], None, trusted=False)
        self.assertIsNone(self.gain([self.OLD], '111'))

    def test_a_close_stored_on_another_ledger_is_unknown(self):
        # A trade confirmed after the night's run: the stored close missed it.
        self.stored([self.OLD], '110')
        late = trade('stock_buy', '1', '50', at(D21, 9), symbol='TSLAon')
        self.assertIsNone(self.gain([self.OLD, late], '170'))

    def test_a_trade_before_midnight_counts_on_its_blocks_day(self):
        late = trade('stock_buy', '1', '20', at(D21, 23, 50), block=7)
        self.stored([self.OLD], '110')                          # the night's run saw it land after midnight
        self.assertEqual(self.gain([self.OLD, late], '135', times={7: at(D22, 0, 2)}), Decimal('5'))
        self.assertIsNone(self.gain([self.OLD, late], '135'))   # block time unknown: no guess

    def test_a_block_time_is_read_once_then_cached(self):
        landed = at(D22, 0, 2)
        with patch('cusd_plus.fee_ledger.block_time', return_value=landed) as rpc:
            self.assertEqual(pr.PriceBook().block_time(987654321), landed)
            self.assertEqual(pr.PriceBook().block_time(987654321), landed)
        self.assertEqual(rpc.call_count, 1)

    def test_a_profile_never_waits_on_the_rpc_for_a_block_time(self):
        with patch('cusd_plus.fee_ledger.block_time') as rpc:
            self.assertIsNone(pr.CachedBlockTimes().block_time(987654322))
        rpc.assert_not_called()

    def test_units_from_outside_are_unknown(self):
        self.stored([self.OLD], '110')

        def outside(wallet, ledger):
            raise pr.Untrusted(pr.OUTSIDE_UNITS)

        self.assertIsNone(self.gain([self.OLD], '300', chain=outside))


class SyncWalletTests(CommunityTestBase):
    STOCKS = [trade('stock_buy', '1', '100', at(D20, 10))]
    TABLE = {('NVDAon', date(2026, 10, d)): Decimal(100 + d) for d in range(15, 24)}

    def sync(self, user, stocks=None, chain=None, **kwargs):
        chain = chain or (lambda wallet, ledger: None)
        with patch('cusd_plus.stock_month.confirmed_trades', return_value=self.STOCKS if stocks is None else stocks), \
                patch('cusd_plus.crypto_month.confirmed_trades', return_value=[]), \
                patch.object(pr, 'in_flight', return_value=False), \
                patch.object(pr, 'check_chain', side_effect=chain):
            return pr.sync_wallet(user, WALLET, now=NOW, prices=TablePrices(self.TABLE), **kwargs)

    def test_days_from_the_first_trade_and_a_rerun_changes_nothing(self):
        user = make_user()
        self.assertEqual(self.sync(user), {'written': 2, 'unchanged': 0, 'retry': 0})
        rows = list(PortfolioDailySnapshot.objects.filter(wallet=WALLET).order_by('day'))
        self.assertEqual([r.day for r in rows], [D20, D21])
        # The 20th: bought at $100, closed at $121 (the close at 00:00 of the 21st).
        self.assertEqual((rows[0].value_start_usd, rows[0].value_end_usd, rows[0].net_flow_usd),
                         (Decimal('0'), Decimal('121'), Decimal('100')))
        self.assertEqual(rows[1].daily_return, (Decimal('1') / Decimal('121')).quantize(Decimal('1e-10')))
        self.assertEqual(self.sync(user), {'written': 0, 'unchanged': 2, 'retry': 0})
        self.assertEqual(self.sync(user, recompute=True), {'written': 0, 'unchanged': 2, 'retry': 0})

    def test_a_provisional_close_keeps_its_day_open_until_settled(self):
        user = make_user()
        prices = TablePrices(self.TABLE)
        original = TablePrices.close

        def close(book, kind, symbol, boundary, now):
            if boundary.date() == date(2026, 10, 22):     # the 21st's end: carried, not proven
                book.provisional = True
            return original(book, kind, symbol, boundary, now)

        with patch.object(TablePrices, 'close', close):
            with patch('cusd_plus.stock_month.confirmed_trades', return_value=self.STOCKS), \
                    patch('cusd_plus.crypto_month.confirmed_trades', return_value=[]), \
                    patch.object(pr, 'in_flight', return_value=False), \
                    patch.object(pr, 'check_chain', return_value=None):
                pr.sync_wallet(user, WALLET, now=NOW, prices=prices)
        self.assertTrue(PortfolioDailySnapshot.objects.get(day=D21).ledger_sig.endswith('p'))
        # The next run (a real close now) recomputes and settles it.
        self.assertEqual(self.sync(user), {'written': 1, 'unchanged': 1, 'retry': 0})
        self.assertFalse(PortfolioDailySnapshot.objects.get(day=D21).ledger_sig.endswith('p'))
        self.assertEqual(self.sync(user), {'written': 0, 'unchanged': 2, 'retry': 0})

    def test_a_late_confirmed_trade_reopens_only_the_days_it_touches(self):
        user = make_user()
        self.sync(user)
        late = self.STOCKS + [trade('stock_buy', '1', '121', at(D21, 9))]
        counts = self.sync(user, stocks=late)
        self.assertEqual(counts, {'written': 1, 'unchanged': 1, 'retry': 0})
        self.assertEqual(PortfolioDailySnapshot.objects.get(day=D21).net_flow_usd, Decimal('121'))

    def test_units_from_outside_store_unknown_days(self):
        def outside(wallet, ledger):
            raise pr.Untrusted(pr.OUTSIDE_UNITS)
        self.sync(make_user(), chain=outside)
        rows = PortfolioDailySnapshot.objects.filter(wallet=WALLET)
        self.assertEqual(rows.count(), 2)
        self.assertTrue(all(not r.ledger_trusted and r.daily_return is None
                            and r.untrusted_reason == pr.OUTSIDE_UNITS for r in rows))

    def test_a_failed_scan_writes_nothing(self):
        def scan_failed(wallet, ledger):
            raise pr.Retry('holdings unreadable')
        self.assertEqual(self.sync(make_user(), chain=scan_failed)['retry'], 1)
        self.assertFalse(PortfolioDailySnapshot.objects.exists())

    def test_proven_days_stay_proven_and_open_days_are_retried(self):
        user = make_user()
        self.sync(user)
        PortfolioDailySnapshot.objects.filter(day=D21).update(ledger_trusted=False, daily_return=None,
                                                              untrusted_reason=pr.PRICE_MISSING)
        def outside(wallet, ledger):
            raise pr.Untrusted(pr.OUTSIDE_UNITS)
        self.sync(user, chain=outside)
        self.assertTrue(PortfolioDailySnapshot.objects.get(day=D20).ledger_trusted)
        self.assertEqual(PortfolioDailySnapshot.objects.get(day=D21).untrusted_reason, pr.OUTSIDE_UNITS)

    def test_an_unreadable_trade_makes_every_open_day_unknown(self):
        self.sync(make_user(), stocks=[trade('stock_buy', '0', None, at(D20), symbol='?9')], days=3)
        self.assertEqual(
            set(PortfolioDailySnapshot.objects.values_list('untrusted_reason', flat=True)), {pr.UNREADABLE_TRADE})

    def test_no_trades_no_rows(self):
        self.assertEqual(self.sync(make_user(), stocks=[]), {'written': 0, 'unchanged': 0, 'retry': 0})

    def test_a_trade_on_the_wire_writes_nothing(self):
        with patch.object(pr, 'in_flight', return_value=True):
            self.assertEqual(pr.sync_wallet(make_user(), WALLET, now=NOW)['retry'], 1)


class CheckChainTests(CommunityTestBase):
    LEDGER = pr.Ledger(stocks=[trade('stock_buy', '2', '200', at(D20), block=100)], crypto=[])

    def check(self, chain, blocks=None, crypto=({}, 50)):
        with patch('cusd_plus.gm_holdings.complete_holdings', return_value=(chain, blocks or {'NVDAon': 120})), \
                patch('cusd_plus.crypto_holdings.holdings_snapshot', return_value=crypto):
            return pr.check_chain(WALLET, self.LEDGER)

    def test_the_ledger_explains_the_chain(self):
        self.assertIsNone(self.check({'NVDAon': '2'}))

    def test_a_sell_all_overshoot_matches_an_empty_chain(self):
        ledger = pr.Ledger(stocks=[trade('stock_buy', '1', '100', at(D20, 1), block=100),
                                   trade('stock_sell', '1.0000000001', '100', at(D20, 2), block=101)], crypto=[])
        with patch('cusd_plus.gm_holdings.complete_holdings', return_value=({}, {'NVDAon': 120})), \
                patch('cusd_plus.crypto_holdings.holdings_snapshot', return_value=({}, 50)):
            self.assertIsNone(pr.check_chain(WALLET, ledger))

    def test_units_from_outside(self):
        with self.assertRaises(pr.Untrusted):
            self.check({'NVDAon': '3'})
        with self.assertRaises(pr.Untrusted):
            self.check({'NVDAon': '2', 'TSLAon': '1'})

    def test_a_lagging_node_or_failed_scan_is_retried(self):
        with self.assertRaises(pr.Retry):
            self.check({}, blocks={'NVDAon': 90})
        with self.assertRaises(pr.Retry):
            self.check({'NVDAon': '2'}, crypto=None)


class PeriodReturnTests(CommunityTestBase):
    LEDGER = pr.Ledger(stocks=[trade('stock_buy', '1', '100', at(date(2026, 9, 1)))], crypto=[])

    def row(self, user, day, ret, gain='1', trusted=True, ledger=None):
        PortfolioDailySnapshot.objects.create(
            user=user, wallet=WALLET, day=day, value_start_usd=Decimal('100'), value_end_usd=Decimal('0'),
            net_flow_usd=Decimal('0'), gain_usd=Decimal(gain) if trusted else None,
            daily_return=Decimal(ret) if trusted else None, ledger_trusted=trusted,
            untrusted_reason='' if trusted else pr.OUTSIDE_UNITS,
            ledger_sig=(ledger or self.LEDGER).signature(pr.day_start(day + pr.DAY)))

    def period(self, user, key, partial=None, ledger=None):
        with patch('inbox.member_portfolio.personal_wallet', return_value=WALLET), \
                patch.object(pr, 'load_ledger', return_value=ledger or self.LEDGER), \
                patch.object(pr, 'today_partial', return_value=partial):
            return pr.period_return(user, key, now=NOW)

    def partial(self, ret, gain='2'):
        return pr.Day(day=D22, value_start=Decimal('0'), value_end=Decimal('0'), net_flow=Decimal('0'),
                      gain=Decimal(gain), daily_return=Decimal(ret))

    def test_seven_days_chain_link_with_today(self):
        user = make_user()
        for n in range(7, 0, -1):
            self.row(user, D22 - timedelta(days=n), '0.01')
        p = self.period(user, '7d', self.partial('0.02'))
        self.assertEqual(p.pct, (Decimal('1.01') ** 7 * Decimal('1.02') - 1) * 100)
        self.assertEqual(p.gain_usd, Decimal('9'))
        self.assertEqual(len(p.points), 9)
        self.assertEqual(p.as_of, NOW)

    def test_one_unknown_day_makes_the_range_unknown(self):
        user = make_user()
        for n in range(7, 0, -1):
            self.row(user, D22 - timedelta(days=n), '0.01', trusted=n != 3)
        self.assertIsNone(self.period(user, '7d', self.partial('0')).pct)

    def test_a_day_never_snapshotted_is_unknown_not_flat(self):
        user = make_user()
        self.row(user, D22 - timedelta(days=1), '0.01')
        self.assertIsNone(self.period(user, '7d', self.partial('0')).pct)
        self.assertIsNone(self.period(make_user(), '7d', self.partial('0')).pct)

    def test_a_stale_row_is_unknown(self):
        user = make_user()
        for n in range(7, 0, -1):
            self.row(user, D22 - timedelta(days=n), '0.01')
        changed = pr.Ledger(stocks=self.LEDGER.stocks + [trade('stock_buy', '1', '5', at(D20))], crypto=[])
        self.assertIsNone(self.period(user, '7d', self.partial('0'), ledger=changed).pct)

    def test_days_before_the_first_trade_are_flat(self):
        user = make_user()
        recent = pr.Ledger(stocks=[trade('stock_buy', '1', '100', at(D20))], crypto=[])
        for day in (D20, D21):
            self.row(user, day, '0.1', ledger=recent)
        p = self.period(user, '30d', self.partial('0'), ledger=recent)
        self.assertEqual(p.pct, (Decimal('1.1') ** 2 - 1) * 100)

    def test_no_investments_is_unknown(self):
        self.assertIsNone(self.period(make_user(), '24h', self.partial('0'), ledger=pr.Ledger([], [])).pct)

    def test_without_a_live_day_24h_is_unknown_and_7d_stops_at_midnight(self):
        user = make_user()
        for n in range(7, 0, -1):
            self.row(user, D22 - timedelta(days=n), '0')
        self.assertIsNone(self.period(user, '24h').pct)
        p = self.period(user, '7d')
        self.assertEqual((p.pct, p.as_of), (Decimal('0'), pr.day_start(D22)))

    def test_24h_is_today_so_far(self):
        p = self.period(make_user(), '24h', self.partial('0.05', gain='5'))
        self.assertEqual((p.pct, p.gain_usd), (Decimal('5.00'), Decimal('5')))


class InvestorReturnsQueryTests(CommunityTestBase):
    def published_member(self):
        member = make_user()
        item = self.post(member)
        with patch('inbox.community.enqueue_follower_notifications'):
            self.run_review(item, APPROVE)
        return member

    def returns(self, viewer, member, key='7d'):
        result = pr.PeriodReturn(range_key=key, pct=Decimal('8'), gain_usd=Decimal('10'), as_of=NOW,
                                 points=[(NOW, Decimal('8'))])
        with patch.object(pr, 'period_return', return_value=result):
            return Query().resolve_investor_returns(MockInfo(viewer), str(member.id), key)

    def test_same_visibility_as_the_portfolio(self):
        member, viewer = self.published_member(), make_user()
        r = self.returns(viewer, member)
        self.assertEqual((r.pct, r.gain_usd, len(r.points)), ('8.00', '10.00', 1))
        self.assertIsNone(self.returns(viewer, member, key='1y'))
        SetCommunityPortfolioHidden.mutate(None, MockInfo(member), hidden=True)
        self.assertIsNone(self.returns(viewer, member))
        self.assertIsNotNone(self.returns(member, member))
