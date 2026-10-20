"""Tu mes "Oro y Bitcoin": the month's crypto & gold result net of the user's own money."""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from cusd_plus import crypto_month as cm
from cusd_plus.stock_month import Trade

UTC = dt_tz.utc
OCT_START = datetime(2026, 10, 1, tzinfo=UTC)
NOV_START = datetime(2026, 11, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
ADDR = '0x' + 'cc' * 20
BTC = 10 ** 18          # BTCB base units per coin
XAUT = 10 ** 6          # XAUt base units per ounce


def candle(day: datetime, close):
    """An OKX daily candle opening on `day` (closes 24h later), ms timestamp."""
    return {'timestamp': int(day.timestamp() * 1000), 'close': float(close), 'confirmed': True}


def trade(symbol, kind, units, usd, when, block=None):
    return Trade(symbol=symbol, kind=kind, units=Decimal(units),
                 usd=None if usd is None else Decimal(usd), when=when, block=block)


class CryptoMonthTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.trades = []
        self.chain = {}                 # {symbol: base units}
        self.block = None
        self.in_flight = []
        self.live = {'BTCB': Decimal('70000'), 'XAUT': Decimal('4100')}
        self.priced_at = NOW - timedelta(minutes=10)
        self.candles = {
            'BTC-USDT': [candle(datetime(2026, 9, 30, tzinfo=UTC), 60000),
                         candle(datetime(2026, 10, 31, tzinfo=UTC), 65000)],
            'XAUT-USDT': [candle(datetime(2026, 9, 30, tzinfo=UTC), 4000),
                          candle(datetime(2026, 10, 31, tzinfo=UTC), 4200)],
        }
        in_flight = mock.MagicMock()
        in_flight.values_list.side_effect = lambda *a, **k: list(self.in_flight)
        patches = [
            mock.patch.object(cm, 'confirmed_trades', side_effect=lambda _a: list(self.trades)),
            mock.patch('cusd_plus.crypto_holdings.batches_in_flight', return_value=in_flight),
            mock.patch('cusd_plus.crypto_holdings.holdings_snapshot', side_effect=self.scan),
            mock.patch('cusd_plus.crypto_prices.market_rows', side_effect=self.market_rows),
            mock.patch('cusd_plus.crypto_chart.ohlc', side_effect=lambda t, _r: self.candles.get(t.chart_instrument, [])),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def scan(self, _address, *, allow_last_known=True):
        self.assertFalse(allow_last_known)                    # a failed scan is unknown, never the old row
        return None if self.chain is None else (dict(self.chain), self.block)

    def market_rows(self):
        from cusd_plus.crypto_catalog import by_symbol
        return [{'token': by_symbol(s), 'price_usd': p, 'priced_at': self.priced_at} for s, p in self.live.items()]

    def run_month(self, start=OCT_START, end=NOV_START, now=NOW):
        return cm.crypto_month(ADDR, start, end, now)

    def test_purchase_is_not_a_gain(self):
        # 0.001 BTC on the 1st (US$60 at the Sep 30 close); bought 0.001 more
        # for US$66 (gross, fee included) on the 10th; BTC now US$70,000.
        self.trades = [trade('BTCB', 'crypto_buy', '0.001', '55', datetime(2026, 9, 25, tzinfo=UTC)),
                       trade('BTCB', 'crypto_buy', '0.001', '66', datetime(2026, 10, 10, tzinfo=UTC))]
        self.chain = {'BTCB': 2 * BTC // 1000}
        r = self.run_month()
        self.assertEqual(r.state, 'gain')
        self.assertEqual(r.value_start, Decimal('60'))
        self.assertEqual(r.value_end, Decimal('140'))
        self.assertEqual(r.bought, Decimal('66'))
        self.assertEqual(r.gain, Decimal('14'))               # 140 − 60 − 66
        self.assertEqual(r.gain_pct.quantize(Decimal('0.01')), Decimal('11.11'))
        self.assertEqual(len(r.assets), 1)
        self.assertEqual((r.assets[0].name, r.assets[0].change_pct.quantize(Decimal('0.01'))),
                         ('Bitcoin', Decimal('16.67')))

    def test_sale_counts_its_net_proceeds_and_sold_out_month_still_counts(self):
        self.trades = [trade('XAUT', 'crypto_buy', '0.01', '39', datetime(2026, 9, 25, tzinfo=UTC)),
                       trade('XAUT', 'crypto_sell', '0.01', '40.50', datetime(2026, 10, 15, tzinfo=UTC))]
        self.chain = {}
        r = self.run_month()
        self.assertEqual(r.state, 'gain')
        self.assertEqual(r.sold, Decimal('40.50'))
        self.assertEqual(r.gain, Decimal('0.50'))             # 0 − 40 − 0 + 40.50
        self.assertEqual((r.holdings, r.assets), (0, []))

    def test_gold_is_named_oro_and_bitcoin_comes_first(self):
        self.trades = [trade('XAUT', 'crypto_buy', '0.01', '40', datetime(2026, 9, 25, tzinfo=UTC)),
                       trade('BTCB', 'crypto_buy', '0.001', '60', datetime(2026, 9, 26, tzinfo=UTC))]
        self.chain = {'XAUT': XAUT // 100, 'BTCB': BTC // 1000}
        r = self.run_month()
        self.assertEqual([(a.name, a.category) for a in r.assets], [('Bitcoin', 'crypto'), ('Oro', 'metal')])
        self.assertEqual(r.value_end, Decimal('111'))         # 70 + 41

    def test_past_month_ends_at_the_last_close(self):
        self.trades = [trade('BTCB', 'crypto_buy', '0.001', '55', datetime(2026, 9, 25, tzinfo=UTC)),
                       trade('BTCB', 'crypto_sell', '0.001', '68', datetime(2026, 11, 3, tzinfo=UTC))]
        self.chain = {}
        r = self.run_month(now=datetime(2026, 11, 10, tzinfo=UTC))
        self.assertEqual(r.state, 'gain')
        self.assertEqual(r.value_end, Decimal('65'))          # Oct 31 close; the November sale is outside
        self.assertEqual(r.gain, Decimal('5'))

    def test_coins_from_outside_confio_show_value_only_now_and_nothing_for_a_past_month(self):
        self.trades = [trade('BTCB', 'crypto_buy', '0.001', '55', datetime(2026, 9, 25, tzinfo=UTC))]
        self.chain = {'BTCB': 3 * BTC // 1000}                # 0.002 arrived from elsewhere
        r = self.run_month()
        self.assertEqual((r.state, r.value_end, r.gain), ('value_only', Decimal('210'), None))
        self.assertIsNone(self.run_month(now=datetime(2026, 11, 10, tzinfo=UTC)))

    def test_an_unreadable_swap_never_yields_a_gain(self):
        self.trades = [trade('BTCB', 'crypto_buy', '0.001', '55', datetime(2026, 9, 25, tzinfo=UTC)),
                       trade('?17', 'crypto_buy', '0', None, datetime(2026, 10, 2, tzinfo=UTC))]
        self.chain = {'BTCB': BTC // 1000}
        self.assertEqual(self.run_month().state, 'value_only')

    def test_a_swap_on_the_wire_is_settling(self):
        self.trades = [trade('BTCB', 'crypto_buy', '0.001', '55', datetime(2026, 9, 25, tzinfo=UTC))]
        self.chain = {'BTCB': 2 * BTC // 1000}                # the new buy already landed, not final
        self.in_flight = [NOW - timedelta(seconds=20)]
        r = self.run_month()
        self.assertEqual((r.state, r.value_end, r.gain), ('settling', Decimal('140'), None))

    def test_a_scan_behind_a_confirmed_swap_is_settling_with_that_swap_counted(self):
        self.trades = [trade('BTCB', 'crypto_buy', '0.001', '55', datetime(2026, 9, 25, tzinfo=UTC), block=100),
                       trade('BTCB', 'crypto_sell', '0.001', '69', datetime(2026, 10, 20, tzinfo=UTC), block=205)]
        self.chain = {'BTCB': BTC // 1000}                    # the node is at block 200: pre-sale
        self.block = 200
        r = self.run_month()
        self.assertEqual((r.state, r.value_end, r.holdings), ('settling', Decimal('0'), 0))

    def test_a_past_month_ending_under_a_swap_in_flight_is_unknown(self):
        self.trades = [trade('BTCB', 'crypto_buy', '0.001', '55', datetime(2026, 9, 25, tzinfo=UTC))]
        self.chain = {'BTCB': BTC // 1000}
        self.in_flight = [datetime(2026, 10, 31, 23, 50, tzinfo=UTC)]
        self.assertIsNone(self.run_month(now=datetime(2026, 11, 1, 0, 5, tzinfo=UTC)))

    def test_stale_live_price_hides_the_card(self):
        self.trades = [trade('BTCB', 'crypto_buy', '0.001', '55', datetime(2026, 9, 25, tzinfo=UTC))]
        self.chain = {'BTCB': BTC // 1000}
        self.priced_at = NOW - timedelta(hours=3)             # snapshot job stopped
        with mock.patch('cusd_plus.crypto_prices.price_usd', return_value=Decimal('70000')) as quote:
            self.assertIsNone(self.run_month())               # a listed token never falls back to a quote
        quote.assert_not_called()

    def test_no_boundary_close_within_a_week_hides_the_card(self):
        self.trades = [trade('BTCB', 'crypto_buy', '0.001', '55', datetime(2026, 9, 1, tzinfo=UTC))]
        self.chain = {'BTCB': BTC // 1000}
        self.candles['BTC-USDT'] = [candle(datetime(2026, 9, 20, tzinfo=UTC), 60000)]
        self.assertIsNone(self.run_month())

    def test_an_unfinished_candle_is_never_a_month_boundary(self):
        # Cached at 23:50 on Oct 31: that day's candle was still forming.
        self.trades = [trade('BTCB', 'crypto_buy', '0.001', '55', datetime(2026, 9, 25, tzinfo=UTC))]
        self.chain = {}
        self.candles['BTC-USDT'][1]['confirmed'] = False
        self.assertIsNone(self.run_month(now=datetime(2026, 11, 1, 0, 5, tzinfo=UTC)))

    def test_unknown_scan_is_none_never_no_crypto(self):
        self.chain = None
        self.assertIsNone(self.run_month())

    def test_nothing_held_nor_traded_is_none_state(self):
        self.assertEqual(self.run_month().state, 'none')
        # A past month before the first buy of someone who holds now: no card.
        self.trades = [trade('BTCB', 'crypto_buy', '0.001', '55', datetime(2026, 11, 3, tzinfo=UTC))]
        self.chain = {'BTCB': BTC // 1000}
        self.assertIsNone(self.run_month(now=datetime(2026, 11, 10, tzinfo=UTC)))


class ConfirmedTradesTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create(username='cryptomonth', firebase_uid='cryptomonth-uid')

    def batch(self, kind, status='confirmed', block=10, tx='0x' + 'ab' * 32):
        from blockchain.models import SponsoredBatch
        return SponsoredBatch.objects.create(
            user=self.user, user_bsc_address=ADDR.upper().replace('0X', '0x'), kind=kind, num_calls=2,
            calls_json='[]', tx_hash=tx, status=status, gas_limit=1, max_fee_wei=1, block_number=block)

    def test_ledger_rows_and_a_confirmed_swap_without_one(self):
        from blockchain.models import CryptoTrade
        from django.utils import timezone
        b1 = self.batch('crypto_buy', block=11)
        CryptoTrade.objects.create(batch=b1, wallet=ADDR, symbol='BTCB', kind='crypto_buy',
                                   units=Decimal('0.001'), usd=Decimal('66'), traded_at=timezone.now())
        b2 = self.batch('crypto_sell', block=12, tx='0x' + 'cd' * 32)       # receipt had no exact event
        self.batch('crypto_buy', status='sent', tx='0x' + 'ef' * 32)        # not final: not in the ledger
        trades = cm.confirmed_trades(ADDR)
        self.assertEqual([(t.symbol, t.kind, t.usd, t.block) for t in trades],
                         [('BTCB', 'crypto_buy', Decimal('66'), 11), (f'?{b2.id}', 'crypto_sell', None, 12)])


class HoldingsSnapshotTests(TestCase):
    def test_scan_block_is_reported(self):
        from cusd_plus import crypto_holdings
        with mock.patch.object(crypto_holdings, '_scan', return_value=({'BTCB': '5'}, 321)), \
             mock.patch.object(crypto_holdings, '_storable', return_value=True):
            self.assertEqual(crypto_holdings.holdings_snapshot(ADDR), ({'BTCB': 5}, 321))
            # The stored fresh row answers next, with the block it was read at.
            self.assertEqual(crypto_holdings.holdings_snapshot(ADDR), ({'BTCB': 5}, 321))
            self.assertEqual(crypto_holdings.holdings_units(ADDR), {'BTCB': 5})

    def test_a_failed_scan_is_unknown_when_last_known_is_refused(self):
        from blockchain.models import CryptoHoldings
        from django.utils import timezone
        from cusd_plus import crypto_holdings
        CryptoHoldings.objects.create(bsc_address=ADDR, held={'BTCB': '5'}, blocks={'BTCB': 9},
                                      scanned_at=timezone.now() - timedelta(hours=1))
        with mock.patch.object(crypto_holdings, '_scan', side_effect=RuntimeError('rpc down')):
            self.assertEqual(crypto_holdings.holdings_snapshot(ADDR), ({'BTCB': 5}, 9))
            self.assertIsNone(crypto_holdings.holdings_snapshot(ADDR, allow_last_known=False))


class CryptoMonthResolverTests(SimpleTestCase):
    def resolve(self, result, *, surfaces=True):
        from types import SimpleNamespace
        from zoneinfo import ZoneInfo
        from users import cashflow_schema
        account = SimpleNamespace(id=1, bsc_address=ADDR)
        info = SimpleNamespace(context=SimpleNamespace(META={}))
        ctx = (object(), account, 'personal', None, ZoneInfo('UTC'))
        with mock.patch.object(cashflow_schema, '_summary_context', return_value=ctx), \
             mock.patch('cusd_plus.crypto_risk.surfaces_enabled', return_value=surfaces), \
             mock.patch('cusd_plus.crypto_month.crypto_month', return_value=result):
            return cashflow_schema.MonthSummaryQuery().resolve_crypto_month(info, 2026, 10)

    def test_gain_and_assets_are_serialized_with_cents(self):
        r = cm.CryptoMonth(state='gain', value_end=Decimal('140'), value_start=Decimal('60'),
                           bought=Decimal('66'), sold=Decimal('0'), gain=Decimal('14'),
                           gain_pct=Decimal('11.1111'), holdings=1,
                           assets=[cm.AssetMove('BTCB', 'BTC', 'Bitcoin', 'crypto', Decimal('16.6667')),
                                   cm.AssetMove('XAUT', 'XAUT', 'Oro', 'metal', None)])
        out = self.resolve(r)
        self.assertEqual((out.state, out.gain_usd, out.gain_pct, out.value_usd), ('gain', '14.00', '11.11', '140.00'))
        self.assertEqual([(a.name, a.change_pct) for a in out.assets], [('Bitcoin', '16.67'), ('Oro', None)])

    def test_gain_adds_up_from_the_cents_shown(self):
        r = cm.CryptoMonth(state='gain', value_end=Decimal('100.004'), value_start=Decimal('50.005'),
                           bought=Decimal('0'), sold=Decimal('0'), gain=Decimal('49.999'), holdings=1)
        self.assertEqual(self.resolve(r).gain_usd, '49.99')

    def test_unknown_or_gated_is_null(self):
        self.assertIsNone(self.resolve(None))
        self.assertIsNone(self.resolve(cm.CryptoMonth(state='gain'), surfaces=False))
        self.assertEqual(self.resolve(cm.CryptoMonth(state='none')).state, 'none')
