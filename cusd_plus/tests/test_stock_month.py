"""Tu mes "Tus acciones": the month's stock result net of the user's own money."""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from cusd_plus import stock_month as sm

UTC = dt_tz.utc
OCT_START = datetime(2026, 10, 1, tzinfo=UTC)
NOV_START = datetime(2026, 11, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
ADDR = '0x' + 'aa' * 20
DAY_MS = 24 * 3600 * 1000


def market(**prices):
    return [{'primaryMarket': {'symbol': f'{t}on', 'price': str(p)},
             'underlyingMarket': {'ticker': t, 'name': f'{t} Inc.'}} for t, p in prices.items()]


def candle(day: datetime, close):
    """A daily candle opening on `day` (closes 24h later)."""
    return {'timestamp': day.timestamp() * 1000, 'close': close}


def trade(symbol, kind, units, usd, when):
    return sm.Trade(symbol=symbol, kind=kind, units=Decimal(units),
                    usd=None if usd is None else Decimal(usd), when=when)


class StockMonthTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.trades = []
        self.chain = {}
        self.pending = False
        self.market = market(NVDA=110, AAPL=200)
        self.candles = {
            'NVDAon': [candle(datetime(2026, 9, 30, tzinfo=UTC), '100'),
                       candle(datetime(2026, 10, 31, tzinfo=UTC), '120')],
            'AAPLon': [candle(datetime(2026, 9, 30, tzinfo=UTC), '200'),
                       candle(datetime(2026, 10, 31, tzinfo=UTC), '210')],
        }
        patches = [
            mock.patch.object(sm, 'confirmed_trades', side_effect=lambda _a: self.trades),
            mock.patch.object(sm, 'pending_trade_exists', side_effect=lambda _a: self.pending),
            mock.patch('cusd_plus.gm_holdings.holdings_units', side_effect=self.scan),
            mock.patch('cusd_plus.gm_api.all_market', side_effect=lambda: self.market),
            mock.patch('cusd_plus.gm_api.ohlc', side_effect=lambda s, _r: self.candles.get(s, [])),
            mock.patch('cusd_plus.schema._display_name', side_effect=lambda n: n.replace(' Inc.', '')),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def scan(self, _address, *, allow_stale=True, require_complete=False):
        self.assertTrue(require_complete)                     # a total never from a partial or stale scan
        return self.chain

    def run_month(self, start=OCT_START, end=NOV_START, now=NOW):
        return sm.stock_month(ADDR, start, end, now)

    def test_purchase_is_not_a_gain(self):
        # Held 1 NVDA on the 1st (US$100); bought 1 more for US$105 on the 10th; NVDA now US$110.
        self.trades = [trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC)),
                       trade('NVDAon', 'stock_buy', '1', '105', datetime(2026, 10, 10, tzinfo=UTC))]
        self.chain = {'NVDAon': 2.0}
        r = self.run_month()
        self.assertEqual(r.state, 'gain')
        self.assertEqual(r.value_start, Decimal('100'))
        self.assertEqual(r.value_end, Decimal('220'))
        self.assertEqual(r.bought, Decimal('105'))
        self.assertEqual(r.gain, Decimal('15'))               # 220 − 100 − 105
        self.assertEqual(r.gain_pct.quantize(Decimal('0.01')), Decimal('7.32'))
        self.assertEqual((r.top.ticker, r.top.change_pct), ('NVDA', Decimal('10')))
        self.assertEqual(r.top.name, 'NVDA')

    def test_sale_is_not_a_loss_and_sold_out_month_still_counts(self):
        self.trades = [trade('AAPLon', 'stock_buy', '1', '190', datetime(2026, 9, 5, tzinfo=UTC)),
                       trade('AAPLon', 'stock_sell', '1', '204', datetime(2026, 10, 15, tzinfo=UTC))]
        self.chain = {}
        r = self.run_month()
        self.assertEqual(r.state, 'gain')
        self.assertEqual(r.value_end, Decimal('0'))
        self.assertEqual(r.gain, Decimal('4'))                # 0 − 200 − 0 + 204
        self.assertEqual(r.holdings, 0)
        self.assertIsNone(r.top)

    def test_down_month_is_a_negative_gain(self):
        self.market = market(NVDA=90)
        self.trades = [trade('NVDAon', 'stock_buy', '2', '190', datetime(2026, 9, 5, tzinfo=UTC))]
        self.chain = {'NVDAon': 2.0}
        r = self.run_month()
        self.assertEqual(r.gain, Decimal('-20'))
        self.assertEqual(r.top.change_pct, Decimal('-10'))

    def test_past_month_ends_at_the_last_close(self):
        self.trades = [trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC)),
                       trade('NVDAon', 'stock_sell', '1', '130', datetime(2026, 11, 3, tzinfo=UTC))]
        self.chain = {}
        r = self.run_month(now=datetime(2026, 11, 10, tzinfo=UTC))
        self.assertEqual(r.state, 'gain')
        self.assertEqual(r.value_end, Decimal('120'))         # Oct 31 close; the November sale is outside
        self.assertEqual(r.gain, Decimal('20'))

    def test_stocks_from_outside_confio_show_value_only(self):
        self.trades = [trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC))]
        self.chain = {'NVDAon': 3.0}                          # 2 arrived from elsewhere
        r = self.run_month()
        self.assertEqual(r.state, 'value_only')
        self.assertEqual(r.value_end, Decimal('330'))
        self.assertIsNone(r.gain)
        self.assertEqual(r.top.ticker, 'NVDA')
        # A past month can't be reconstructed at all.
        self.assertIsNone(self.run_month(start=datetime(2026, 9, 1, tzinfo=UTC), end=OCT_START))

    def test_missing_settlement_row_never_guesses(self):
        self.trades = [trade('NVDAon', 'stock_buy', '1', None, datetime(2026, 10, 5, tzinfo=UTC))]
        self.chain = {'NVDAon': 1.0}
        self.assertEqual(self.run_month().state, 'value_only')

    def test_trade_settling_shows_today_value_not_value_only(self):
        # The receipt landed (chain has the units) but finality hasn't confirmed the batch.
        self.trades = [trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC))]
        self.chain = {'NVDAon': 2.0}
        self.pending = True
        r = self.run_month()
        self.assertEqual(r.state, 'settling')
        self.assertEqual(r.value_end, Decimal('220'))
        self.assertIsNone(r.gain)
        self.assertEqual(r.top.ticker, 'NVDA')
        # A past month can't be reconstructed while the ledger disagrees.
        self.assertIsNone(self.run_month(start=datetime(2026, 9, 1, tzinfo=UTC), end=OCT_START))

    def test_candle_fetch_failure_is_a_missing_price(self):
        self.trades = [trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC))]
        self.chain = {'NVDAon': 3.0}                          # value_only: the mover is optional
        with mock.patch('cusd_plus.gm_api.ohlc', side_effect=RuntimeError('ondo down')):
            r = self.run_month()
        self.assertEqual(r.state, 'value_only')
        self.assertIsNone(r.top)

    def test_no_stocks_is_none_state_and_unknown_scan_is_none(self):
        self.assertEqual(self.run_month().state, 'none')
        self.chain = None
        self.assertIsNone(self.run_month())

    def test_past_month_before_first_purchase_never_invites_a_holder(self):
        self.trades = [trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 10, 5, tzinfo=UTC))]
        self.chain = {'NVDAon': 1.0}
        self.assertIsNone(self.run_month(start=datetime(2026, 9, 1, tzinfo=UTC), end=OCT_START))
        self.chain, self.trades = {}, []
        self.assertEqual(self.run_month(start=datetime(2026, 9, 1, tzinfo=UTC), end=OCT_START).state, 'none')

    def test_missing_boundary_price_hides_the_card(self):
        self.trades = [trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC))]
        self.chain = {'NVDAon': 1.0}
        self.candles['NVDAon'] = [candle(datetime(2026, 9, 10, tzinfo=UTC), '100')]   # 3 weeks stale
        self.assertIsNone(self.run_month())

    def test_ledger_tolerates_float_dust_but_not_real_differences(self):
        ledger = {'NVDAon': Decimal('0.123456789')}
        self.assertTrue(sm.ledger_explains_chain(ledger, {'NVDAon': Decimal('0.1234567890000001')}))
        self.assertFalse(sm.ledger_explains_chain(ledger, {'NVDAon': Decimal('0.1235')}))
        self.assertFalse(sm.ledger_explains_chain({'NVDAon': Decimal('-1')}, {}))

    def test_close_before_uses_the_candle_closed_by_the_boundary(self):
        caracas_start = OCT_START + timedelta(hours=4)        # 00:00 in Caracas
        self.candles['NVDAon'] = [candle(datetime(2026, 9, 30, tzinfo=UTC), '100'),
                                  candle(datetime(2026, 10, 1, tzinfo=UTC), '104')]
        with mock.patch('django.utils.timezone.now', return_value=NOW):
            self.assertEqual(sm.close_before('NVDAon', caracas_start), Decimal('100'))


class StockMonthResolverTests(SimpleTestCase):
    """Gating: unknown hides, 'none' shows only when buying is offered."""

    def resolve(self, result, *, surfaces=True, can_buy=True):
        from types import SimpleNamespace
        from zoneinfo import ZoneInfo
        from users import cashflow_schema
        account = SimpleNamespace(id=1, bsc_address=ADDR)
        info = SimpleNamespace(context=SimpleNamespace(META={}))
        ctx = (object(), account, 'personal', None, ZoneInfo('UTC'))
        with mock.patch.object(cashflow_schema, '_summary_context', return_value=ctx), \
             mock.patch('cusd_plus.schema._stock_surfaces_enabled', return_value=surfaces), \
             mock.patch('cusd_plus.eligibility.stock_buy_overlay_allows', return_value=can_buy), \
             mock.patch('cusd_plus.stock_month.stock_month', return_value=result):
            return cashflow_schema.MonthSummaryQuery().resolve_stock_month(info, 2026, 10)

    def test_gain_is_serialized_with_cents(self):
        r = sm.StockMonth(state='gain', value_end=Decimal('220'), value_start=Decimal('100'),
                          bought=Decimal('105'), sold=Decimal('0'), gain=Decimal('15'),
                          gain_pct=Decimal('7.3170'), holdings=1,
                          top=sm.Mover(ticker='NVDA', name='NVIDIA', change_pct=Decimal('10')))
        out = self.resolve(r, can_buy=False)
        self.assertEqual((out.state, out.gain_usd, out.gain_pct, out.value_usd), ('gain', '15.00', '7.32', '220.00'))
        self.assertEqual(out.top_mover.change_pct, '10.00')
        self.assertFalse(out.can_buy)

    def test_gain_adds_up_from_the_cents_shown(self):
        r = sm.StockMonth(state='gain', value_end=Decimal('100.004'), value_start=Decimal('50.005'),
                          bought=Decimal('0'), sold=Decimal('0'), gain=Decimal('49.999'), holdings=1)
        out = self.resolve(r)
        self.assertEqual((out.value_usd, out.value_start_usd, out.gain_usd), ('100.00', '50.01', '49.99'))

    def test_none_needs_buying_and_unknown_or_gated_is_null(self):
        self.assertTrue(self.resolve(sm.StockMonth(state='none')).can_buy)
        self.assertIsNone(self.resolve(sm.StockMonth(state='none'), can_buy=False))
        self.assertIsNone(self.resolve(None))
        self.assertIsNone(self.resolve(sm.StockMonth(state='gain'), surfaces=False))


class FreshHoldingsTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()

    def test_failed_scan_uses_last_known_only_when_stale_is_allowed(self):
        from cusd_plus import gm_holdings
        holder = '0x' + '88' * 20
        cache.set(f'gm_hold_last:{holder}', {'TSLAon': 1.0}, 60)
        with mock.patch.object(gm_holdings, 'registry', return_value={'TSLAon': {'address': '0x' + '11' * 20}}), \
             mock.patch.object(gm_holdings, '_scan', side_effect=TimeoutError('node down')), \
             self.assertLogs('cusd_plus.gm_holdings', level='WARNING'):
            self.assertEqual(gm_holdings.holdings_units(holder), {'TSLAon': 1.0})
            self.assertIsNone(gm_holdings.holdings_units(holder, allow_stale=False))

    def test_complete_mode_never_serves_a_partial_or_stale_scan(self):
        from cusd_plus import gm_holdings
        holder = '0x' + '99' * 20
        reg = {'TSLAon': {'address': '0x' + '11' * 20}}
        cache.set(f'gm_hold:{holder}', {'TSLAon': 1.0}, 30)       # a partial scan from another screen
        cache.set(f'gm_hold_last:{holder}', {'TSLAon': 1.0}, 60)
        with mock.patch.object(gm_holdings, 'registry', return_value=reg), \
             mock.patch.object(gm_holdings, '_scan', side_effect=RuntimeError('GM balanceOf failed')) as scan, \
             self.assertLogs('cusd_plus.gm_holdings', level='WARNING'):
            self.assertIsNone(gm_holdings.holdings_units(holder, require_complete=True))
        self.assertTrue(scan.call_args.kwargs['require_complete'])
        with mock.patch.object(gm_holdings, 'registry', return_value=reg), \
             mock.patch.object(gm_holdings, '_scan', return_value={'TSLAon': 2.0}):
            self.assertEqual(gm_holdings.holdings_units(holder, require_complete=True), {'TSLAon': 2.0})
        self.assertEqual(cache.get(f'gm_hold:{holder}'), {'TSLAon': 2.0})   # also the best answer for others
        gm_holdings.invalidate_holdings(holder)
        self.assertIsNone(cache.get(f'gm_hold_full:{holder}'))
        self.assertIsNone(cache.get(f'gm_hold:{holder}'))


class ConfirmedTradesCacheTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()

    def run_read(self, sig, decoded):
        qs = mock.MagicMock()
        qs.aggregate.return_value = sig
        with mock.patch('blockchain.models.SponsoredBatch') as model, \
             mock.patch.object(sm, '_decode_trades', return_value=decoded) as decode:
            model.objects.filter.return_value = qs
            return sm.confirmed_trades(ADDR), decode.call_count

    def test_decodes_once_until_the_ledger_changes(self):
        t0 = datetime(2026, 10, 1, tzinfo=UTC)
        sig = {'n': 1, 'last': 7, 'touched': t0, 'rows': 1, 'rows_touched': t0}
        one = [trade('NVDAon', 'stock_buy', '1', '95', t0)]
        self.assertEqual(self.run_read(sig, one), (one, 1))
        self.assertEqual(self.run_read(sig, one), (one, 0))                       # cached
        self.assertEqual(self.run_read({**sig, 'rows_touched': t0 + timedelta(seconds=1)}, one)[1], 1)  # amount re-synced
        self.assertEqual(self.run_read({**sig, 'n': 2, 'last': 8}, one)[1], 1)    # a new confirmation

    def test_no_trades_skips_decoding_and_unreadable_ones_are_not_cached(self):
        self.assertEqual(self.run_read({'n': 0}, []), ([], 0))
        t0 = datetime(2026, 10, 1, tzinfo=UTC)
        sig = {'n': 1, 'last': 9, 'touched': t0, 'rows': 0, 'rows_touched': None}
        bad = [trade('?9', 'stock_buy', '0', None, t0)]
        self.run_read(sig, bad)
        self.assertEqual(self.run_read(sig, bad)[1], 1)
