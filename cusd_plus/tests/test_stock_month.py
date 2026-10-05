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
        self.pending = []
        self.market = market(NVDA=110, AAPL=200)
        self.candles = {
            'NVDAon': [candle(datetime(2026, 9, 30, tzinfo=UTC), '100'),
                       candle(datetime(2026, 10, 31, tzinfo=UTC), '120')],
            'AAPLon': [candle(datetime(2026, 9, 30, tzinfo=UTC), '200'),
                       candle(datetime(2026, 10, 31, tzinfo=UTC), '210')],
        }
        patches = [
            mock.patch.object(sm, 'confirmed_trades', side_effect=lambda _a: self.trades),
            mock.patch('cusd_plus.gm_holdings.registry', return_value={}),
            mock.patch.object(sm, 'pending_trades', side_effect=lambda _a: list(self.pending)),
            mock.patch('cusd_plus.gm_holdings.holdings_units', side_effect=self.scan),
            mock.patch('cusd_plus.gm_api.all_market', side_effect=lambda: self.market),
            mock.patch('cusd_plus.gm_api.ohlc', side_effect=lambda s, _r: self.candles.get(s, [])),
            mock.patch('cusd_plus.schema._display_name', side_effect=lambda n: n.replace(' Inc.', '')),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def scan(self, _address, *, require_complete=False):
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
        self.pending = [trade('NVDAon', 'stock_buy', '1', None, NOW - timedelta(minutes=1))]
        r = self.run_month()
        self.assertEqual(r.state, 'settling')
        self.assertEqual(r.value_end, Decimal('220'))
        self.assertIsNone(r.gain)
        self.assertEqual(r.top.ticker, 'NVDA')
        # A past month ends before the in-flight trade: the ledger plus that
        # trade explains the chain, so September stays exact.
        sept = self.run_month(start=datetime(2026, 9, 1, tzinfo=UTC), end=OCT_START)
        self.assertEqual(sept.state, 'gain')
        self.assertEqual(sept.value_end, Decimal('100'))      # 1 NVDA at the Sept 30 close
        # Unknown when a trade can't be explained at all (2 extra units).
        self.chain = {'NVDAon': 4.0}
        self.assertIsNone(self.run_month(start=datetime(2026, 9, 1, tzinfo=UTC), end=OCT_START))

    def test_holder_scan_lagging_a_pending_trade_is_settling_not_a_final_gain(self):
        # The app showed the receipt, but the scan still reads the pre-trade
        # chain, which the ledger (without the pending batch) still explains.
        self.trades = [trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC))]
        self.chain = {'NVDAon': 1.0}
        self.pending = [trade('NVDAon', 'stock_buy', '1', None, NOW - timedelta(minutes=1))]
        r = self.run_month()
        self.assertEqual(r.state, 'settling')
        self.assertIsNone(r.gain)
        # A past month ends before the in-flight trade and stays exact.
        self.assertEqual(self.run_month(start=datetime(2026, 9, 1, tzinfo=UTC), end=OCT_START).state, 'gain')

    def test_trade_confirming_between_the_two_reads_is_settling_never_value_only(self):
        # The batch turns 'confirmed' between the ledger and the in-flight
        # reads: whichever list is read first still sees it on the wire.
        old = trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC))
        new = trade('NVDAon', 'stock_buy', '1', '108', NOW - timedelta(minutes=1))
        reads = []

        def confirmed(_a):
            reads.append('ledger')
            return [old] if len(reads) == 1 else [old, new]

        def pending(_a):
            reads.append('pending')
            return [new] if len(reads) == 1 else []

        self.chain = {'NVDAon': 2.0}
        with mock.patch.object(sm, 'confirmed_trades', side_effect=confirmed), \
             mock.patch.object(sm, 'pending_trades', side_effect=pending):
            self.assertEqual(self.run_month().state, 'settling')

    def test_past_month_boundaries_of_a_symbol_share_one_task(self):
        # Start and end candles of one symbol are read one after the other in
        # the same task, so the second read hits gm_api's cache instead of a
        # concurrent duplicate request to Ondo.
        import threading
        threads = []

        def ohlc(symbol, _range):
            threads.append((symbol, threading.get_ident()))
            return self.candles.get(symbol, [])

        self.trades = [trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC))]
        self.chain = {'NVDAon': 1.0}
        with mock.patch('cusd_plus.gm_api.ohlc', side_effect=ohlc):
            r = self.run_month(now=datetime(2026, 11, 10, tzinfo=UTC))
        self.assertEqual(r.state, 'gain')
        nvda = [t for s, t in threads if s == 'NVDAon']
        self.assertEqual(len(nvda), 2)
        self.assertEqual(len(set(nvda)), 1)

    def test_first_purchase_not_yet_scanned_is_settling_never_an_invite(self):
        # Receipt shown; the scan lags the trade.
        self.pending = [trade('NVDAon', 'stock_buy', '1', None, NOW - timedelta(minutes=1))]
        self.assertEqual(self.run_month().state, 'settling')
        self.assertEqual(self.run_month(start=datetime(2026, 9, 1, tzinfo=UTC), end=OCT_START).state, 'none')

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

    def test_sold_out_with_an_unreadable_trade_is_value_only_not_an_invitation(self):
        self.trades = [trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC)),
                       trade('?7', 'stock_sell', '0', None, datetime(2026, 10, 15, tzinfo=UTC))]
        self.chain = {}
        r = self.run_month()
        self.assertEqual(r.state, 'value_only')
        self.assertEqual(r.value_end, Decimal('0'))

    def test_only_this_months_trades_need_their_settlement(self):
        # August's buy lost its history row: October is still exact (its own
        # dollars are known); August itself can't be.
        self.trades = [trade('NVDAon', 'stock_buy', '1', None, datetime(2026, 8, 5, tzinfo=UTC)),
                       trade('NVDAon', 'stock_buy', '1', '105', datetime(2026, 10, 10, tzinfo=UTC))]
        self.chain = {'NVDAon': 2.0}
        r = self.run_month()
        self.assertEqual(r.state, 'gain')
        self.assertEqual(r.gain, Decimal('15'))
        self.candles['NVDAon'].insert(0, candle(datetime(2026, 7, 31, tzinfo=UTC), '90'))
        self.candles['NVDAon'].insert(1, candle(datetime(2026, 8, 31, tzinfo=UTC), '95'))
        self.assertIsNone(self.run_month(start=datetime(2026, 8, 1, tzinfo=UTC), end=datetime(2026, 9, 1, tzinfo=UTC)))

    def test_an_unreadable_trade_anywhere_leaves_the_ledger_untrusted(self):
        self.trades = [trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC)),
                       trade('?3', 'stock_buy', '0', None, datetime(2026, 8, 5, tzinfo=UTC))]
        self.chain = {'NVDAon': 1.0}
        self.assertEqual(self.run_month().state, 'value_only')

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

    def resolve(self, result, *, surfaces=True, can_buy=True, trading=True):
        from types import SimpleNamespace
        from zoneinfo import ZoneInfo
        from users import cashflow_schema
        account = SimpleNamespace(id=1, bsc_address=ADDR)
        info = SimpleNamespace(context=SimpleNamespace(META={}))
        ctx = (object(), account, 'personal', None, ZoneInfo('UTC'))
        with mock.patch.object(cashflow_schema, '_summary_context', return_value=ctx), \
             mock.patch('cusd_plus.schema._stock_surfaces_enabled', return_value=surfaces), \
             mock.patch('cusd_plus.schema._stock_execution_ready', return_value=trading), \
             mock.patch('cusd_plus.eligibility.stock_buy_overlay_allows', return_value=can_buy), \
             mock.patch('cusd_plus.stock_month.stock_month', return_value=result):
            return cashflow_schema.MonthSummaryQuery().resolve_stock_month(info, 2026, 10)

    def test_gain_is_serialized_with_cents(self):
        r = sm.StockMonth(state='gain', value_end=Decimal('220'), value_start=Decimal('100'),
                          bought=Decimal('105'), sold=Decimal('0'), gain=Decimal('15'),
                          gain_pct=Decimal('7.3170'), holdings=1,
                          top=sm.Mover(ticker='NVDA', name='NVIDIA', change_pct=Decimal('10')))
        out = self.resolve(r)                                 # the buy overlay only matters for 'none'
        self.assertEqual((out.state, out.gain_usd, out.gain_pct, out.value_usd), ('gain', '15.00', '7.32', '220.00'))
        self.assertEqual(out.top_mover.change_pct, '10.00')
        self.assertFalse(out.can_buy)

    def test_gain_adds_up_from_the_cents_shown(self):
        r = sm.StockMonth(state='gain', value_end=Decimal('100.004'), value_start=Decimal('50.005'),
                          bought=Decimal('0'), sold=Decimal('0'), gain=Decimal('49.999'), holdings=1)
        out = self.resolve(r)
        self.assertEqual((out.value_usd, out.value_start_usd, out.gain_usd), ('100.00', '50.01', '49.99'))

    def test_percent_follows_the_cents_gain(self):
        # Raw gain −0.0099 on ~US$1 is −0.98%, but the cents shown net to 0.00:
        # the percent must not say "−1%" beside "+US$0.00".
        r = sm.StockMonth(state='gain', value_end=Decimal('1.005'), value_start=Decimal('1.0149'),
                          bought=Decimal('0'), sold=Decimal('0'), gain=Decimal('-0.0099'),
                          gain_pct=Decimal('-0.9755'), holdings=1)
        out = self.resolve(r)
        self.assertEqual((out.gain_usd, out.gain_pct), ('0.00', '0.00'))

    def test_none_needs_buying_and_unknown_or_gated_is_null(self):
        self.assertTrue(self.resolve(sm.StockMonth(state='none')).can_buy)
        self.assertIsNone(self.resolve(sm.StockMonth(state='none'), can_buy=False))
        self.assertIsNone(self.resolve(sm.StockMonth(state='none'), trading=False))   # never invite while trading is off
        self.assertIsNone(self.resolve(None))
        self.assertIsNone(self.resolve(sm.StockMonth(state='gain'), surfaces=False))


class FreshHoldingsTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()

    def test_failed_scan_uses_last_known_only_outside_complete_mode(self):
        from cusd_plus import gm_holdings
        holder = '0x' + '88' * 20
        cache.set(f'gm_hold_last:{holder}', {'TSLAon': 1.0}, 60)
        with mock.patch.object(gm_holdings, 'registry', return_value={'TSLAon': {'address': '0x' + '11' * 20}}), \
             mock.patch.object(gm_holdings, '_scan', side_effect=TimeoutError('node down')), \
             self.assertLogs('cusd_plus.gm_holdings', level='WARNING'):
            self.assertEqual(gm_holdings.holdings_units(holder), {'TSLAon': 1.0})
            self.assertIsNone(gm_holdings.holdings_units(holder, require_complete=True))

    def test_complete_mode_never_serves_a_partial_or_stale_scan(self):
        from cusd_plus import gm_holdings
        holder = '0x' + '99' * 20
        reg = {'TSLAon': {'address': '0x' + '11' * 20}}
        cache.set(f'gm_hold:{holder}', {'TSLAon': 1.0}, 30)       # a partial scan from another screen
        cache.set(f'gm_hold_last:{holder}', {'TSLAon': 1.0}, 60)
        for patch in (mock.patch.object(gm_holdings, 'registry_entry', return_value=(reg, True)),
                      mock.patch.object(gm_holdings, '_fallback_registry', return_value={})):
            patch.start()
            self.addCleanup(patch.stop)
        with mock.patch.object(gm_holdings, 'registry', return_value=reg), \
             mock.patch.object(gm_holdings, '_scan', side_effect=RuntimeError('GM balanceOf failed')) as scan, \
             self.assertLogs('cusd_plus.gm_holdings', level='WARNING'):
            self.assertIsNone(gm_holdings.holdings_units(holder, require_complete=True))
        self.assertIn('failures', scan.call_args.kwargs)
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


class HoldingsWarmupTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()

    def test_warmup_fills_the_complete_scan_and_never_raises(self):
        from cusd_plus import tasks
        with mock.patch('cusd_plus.gm_holdings.holdings_units') as scan:
            tasks.warm_gm_holdings(ADDR)
        scan.assert_called_once_with(ADDR, require_complete=True)
        with mock.patch('cusd_plus.gm_holdings.holdings_units', side_effect=RuntimeError('rpc down')), \
             self.assertLogs('cusd_plus.tasks', level='WARNING'):
            tasks.warm_gm_holdings(ADDR)

    def test_dispatch_never_raises_on_a_broker_failure(self):
        from cusd_plus import tasks
        with mock.patch.object(tasks.warm_gm_holdings, 'apply_async', side_effect=OSError('broker down')), \
             self.assertLogs('cusd_plus.tasks', level='WARNING'):
            tasks._dispatch_holdings_warmup(ADDR)


class LiveRegistryTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()

    def test_complete_scan_requires_the_live_registry(self):
        from cusd_plus import gm_holdings
        snapshot = {'TSLAon': {'address': '0x' + '11' * 20, 'decimals': 18}}
        with mock.patch.object(gm_holdings, '_fallback_registry', return_value=snapshot), \
             mock.patch('cusd_plus.gm_api.all_addresses', side_effect=TimeoutError('ondo down')), \
             mock.patch.object(gm_holdings, '_scan', return_value={'TSLAon': 1.0}) as scan, \
             self.assertLogs('cusd_plus.gm_holdings', level='WARNING'):
            self.assertIsNone(gm_holdings.holdings_units(ADDR, require_complete=True))
            self.assertEqual(gm_holdings.holdings_units(ADDR), {'TSLAon': 1.0})   # lists still degrade
        scan.assert_called_once()
        self.assertFalse(gm_holdings.registry_entry()[1])
        rows = [{'symbol': 'TSLAon', 'addresses': [
            {'networkChainId': 'bsc-56', 'address': '0x' + '11' * 20, 'decimals': 18}]}]
        cache.clear()
        with mock.patch('cusd_plus.gm_api.all_addresses', return_value=rows), \
             mock.patch.object(gm_holdings, '_fallback_registry', return_value=snapshot), \
             mock.patch.object(gm_holdings, '_scan', return_value={'TSLAon': 2.0}):
            self.assertEqual(gm_holdings.holdings_units(ADDR, require_complete=True), {'TSLAon': 2.0})
        self.assertTrue(gm_holdings.registry_entry()[1])

    def test_liveness_travels_with_the_registry_entry(self):
        # A registry cached by older code (no liveness) is refetched, never
        # read as "not live" for a day; and liveness can't be evicted apart.
        from cusd_plus import gm_holdings
        rows = [{'symbol': 'TSLAon', 'addresses': [
            {'networkChainId': 'bsc-56', 'address': '0x' + '11' * 20, 'decimals': 18}]}]
        cache.set('gm_bsc_registry_v1', {'TSLAon': {'address': '0x' + '11' * 20, 'decimals': 18}}, 3600)
        with mock.patch('cusd_plus.gm_api.all_addresses', return_value=rows) as fetch:
            self.assertIn('TSLAon', gm_holdings.registry())
            self.assertIn('TSLAon', gm_holdings.registry())
        fetch.assert_called_once()
        self.assertEqual(cache.get(gm_holdings.REGISTRY_CACHE_KEY)['live'], True)
        self.assertTrue(gm_holdings.registry_entry()[1])

    def test_complete_scan_includes_delisted_snapshot_tokens_best_effort(self):
        from cusd_plus import gm_holdings
        live = {'TSLAon': {'address': '0x' + '11' * 20, 'decimals': 18}}
        snapshot = {**live, 'OLDon': {'address': '0x' + '22' * 20, 'decimals': 18}}
        calls = []
        failing = set()

        def scan(_key, tokens, *, failures=None, **_kw):
            calls.append(sorted(tokens))
            failures.update(failing)
            return {'TSLAon': 1.0, 'OLDon': 3.0}

        with mock.patch.object(gm_holdings, 'registry_entry', return_value=(live, True)), \
             mock.patch.object(gm_holdings, '_fallback_registry', return_value=snapshot), \
             mock.patch.object(gm_holdings, '_scan', side_effect=scan):
            self.assertEqual(gm_holdings.holdings_units(ADDR, require_complete=True), {'TSLAon': 1.0, 'OLDon': 3.0})
            self.assertEqual(calls, [['OLDon', 'TSLAon']])                       # one Multicall pass
            gm_holdings.invalidate_holdings(ADDR)
            failing.add('OLDon')                                                   # a retired contract: tolerated
            self.assertEqual(gm_holdings.holdings_units(ADDR, require_complete=True), {'TSLAon': 1.0, 'OLDon': 3.0})
            gm_holdings.invalidate_holdings(ADDR)
            failing.add('TSLAon')                                                  # a live one: unknown
            with self.assertLogs('cusd_plus.gm_holdings', level='WARNING'):
                self.assertIsNone(gm_holdings.holdings_units(ADDR, require_complete=True))

    def test_a_trade_confirming_mid_scan_is_never_cached_or_used(self):
        from cusd_plus import gm_holdings
        live = {'TSLAon': {'address': '0x' + '11' * 20, 'decimals': 18}}
        answers = [{'TSLAon': 1.0}, {'TSLAon': 2.0}]                              # pre-trade, then post-trade

        def scan(_key, _tokens, **_kw):
            held = answers.pop(0)
            if held == {'TSLAon': 1.0}:
                gm_holdings.invalidate_holdings(ADDR)                              # the confirm task, mid-scan
            return held

        with mock.patch.object(gm_holdings, 'registry_entry', return_value=(live, True)), \
             mock.patch.object(gm_holdings, '_fallback_registry', return_value={}), \
             mock.patch.object(gm_holdings, '_scan', side_effect=scan):
            self.assertEqual(gm_holdings.holdings_units(ADDR, require_complete=True), {'TSLAon': 2.0})
        self.assertEqual(cache.get(f'gm_hold_full:{ADDR.lower()}'), {'TSLAon': 2.0})

    def test_a_list_scan_racing_a_trade_is_returned_but_not_cached(self):
        from cusd_plus import gm_holdings

        def scan(_key, _tokens, **_kw):
            gm_holdings.invalidate_holdings(ADDR)
            return {'TSLAon': 1.0}

        with mock.patch.object(gm_holdings, 'registry', return_value={'TSLAon': {'address': '0x' + '11' * 20}}), \
             mock.patch.object(gm_holdings, '_scan', side_effect=scan):
            self.assertEqual(gm_holdings.holdings_units(ADDR), {'TSLAon': 1.0})
        self.assertIsNone(cache.get(f'gm_hold:{ADDR.lower()}'))

    def test_scan_reports_tokens_that_did_not_answer(self):
        from cusd_plus import gm_holdings
        reg = {'TSLAon': {'address': '0x' + '11' * 20, 'decimals': 18},
               'AAPLon': {'address': '0x' + '22' * 20, 'decimals': 18}}
        one = (10 ** 18).to_bytes(32, 'big')
        failures = set()
        with mock.patch('cusd_plus.gm_holdings.vault._rpc', return_value='0x00'), \
             mock.patch('cusd_plus.gm_holdings.decode', return_value=([(True, one), (False, b'')],)):
            self.assertEqual(gm_holdings._scan(ADDR, reg, failures=failures), {'TSLAon': 1.0})
        self.assertEqual(failures, {'AAPLon'})


class PendingWindowTests(SimpleTestCase):
    def test_a_trade_in_flight_when_the_month_ended_makes_that_month_unknown(self):
        with mock.patch.object(sm, 'confirmed_trades', return_value=[
                trade('NVDAon', 'stock_buy', '1', '95', datetime(2026, 9, 5, tzinfo=UTC))]), \
             mock.patch.object(sm, 'pending_trades', return_value=[
                trade('NVDAon', 'stock_buy', '1', None, datetime(2026, 9, 30, 23, 55, tzinfo=UTC))]), \
             mock.patch('cusd_plus.gm_holdings.registry', return_value={}), \
             mock.patch('cusd_plus.gm_holdings.holdings_units', return_value={'NVDAon': 2.0}), \
             mock.patch('cusd_plus.gm_tvl._market_by_symbol', return_value={}):
            self.assertIsNone(sm.stock_month(ADDR, datetime(2026, 9, 1, tzinfo=UTC), OCT_START,
                                             datetime(2026, 10, 1, 0, 5, tzinfo=UTC)))

    def test_stuck_batches_stop_counting_as_settling(self):
        self.assertLessEqual(sm.PENDING_MAX_AGE, timedelta(minutes=15))
