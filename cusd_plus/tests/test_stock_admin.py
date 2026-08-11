from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib import admin
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from blockchain.admin import OndoStockTradeAdmin, SponsoredBatchAdmin
from blockchain.models import OndoStockTrade
from cusd_plus.metrics import get_stock_router_metrics, get_stock_trade_stats


def _counting_queryset(count):
    queryset = mock.MagicMock()
    queryset.count.return_value = count
    return queryset


class StockTradeStatsTests(SimpleTestCase):
    @mock.patch('users.models_unified.UnifiedTransactionTable.objects')
    @mock.patch('blockchain.models.SponsoredBatch.objects')
    def test_counts_only_stock_batches_and_sums_exact_settlements(
            self, batches_manager, unified_manager):
        rows = mock.MagicMock()
        confirmed = mock.MagicMock()
        status_values = mock.MagicMock()
        status_values.annotate.return_value = [
            {'status': 'confirmed', 'count': 2},
            {'status': 'reverted', 'count': 1},
        ]
        rows.values.return_value = status_values
        rows.count.return_value = 3

        def rows_filter(**kwargs):
            if kwargs == {'status': 'confirmed'}:
                return confirmed
            if kwargs == {'kind': 'stock_buy'}:
                return _counting_queryset(2)
            if kwargs == {'kind': 'stock_sell'}:
                return _counting_queryset(1)
            if kwargs == {'status__in': ('signed', 'sent')}:
                return _counting_queryset(0)
            if kwargs == {'status__in': ('reverted', 'noop_failed', 'dropped', 'reorged')}:
                return _counting_queryset(1)
            raise AssertionError(f'unexpected stock filter: {kwargs}')

        rows.filter.side_effect = rows_filter
        confirmed.count.return_value = 2
        confirmed.filter.side_effect = lambda **kwargs: _counting_queryset(
            1 if kwargs.get('kind') in ('stock_buy', 'stock_sell') else 0
        )
        trader_values = mock.MagicMock()
        trader_values.distinct.return_value.count.return_value = 1
        confirmed.values.return_value = trader_values
        batches_manager.filter.return_value = rows

        settlements = mock.MagicMock()
        settlements.aggregate.return_value = {
            'buy': Decimal('100.30'),
            'sell': Decimal('49.85'),
        }
        settlements.count.return_value = 2
        unified_manager.filter.return_value = settlements

        stats = get_stock_trade_stats()

        batches_manager.filter.assert_called_once_with(
            kind__in=('stock_buy', 'stock_sell')
        )
        unified_manager.filter.assert_called_once_with(
            sponsored_batch__in=confirmed,
            deleted_at__isnull=True,
            status='CONFIRMED',
            amount_denomination='USD_VALUE',
        )
        self.assertEqual(stats['total'], 3)
        self.assertEqual(stats['confirmed'], 2)
        self.assertEqual(stats['confirmed_buys'], 1)
        self.assertEqual(stats['confirmed_sells'], 1)
        self.assertEqual(stats['unique_traders'], 1)
        self.assertEqual(stats['buy_volume'], Decimal('100.30'))
        self.assertEqual(stats['sell_volume'], Decimal('49.85'))
        self.assertEqual(stats['total_volume'], Decimal('150.15'))
        self.assertEqual(stats['failed'], 1)
        self.assertEqual(stats['history_missing'], 0)

    @mock.patch('users.models_unified.UnifiedTransactionTable.objects')
    @mock.patch('blockchain.models.SponsoredBatch.objects')
    def test_confirmed_batch_without_history_is_an_integrity_alert(
            self, batches_manager, unified_manager):
        rows = mock.MagicMock()
        confirmed = mock.MagicMock()
        rows.values.return_value.annotate.return_value = [
            {'status': 'confirmed', 'count': 1},
        ]
        rows.count.return_value = 1

        def rows_filter(**kwargs):
            if kwargs == {'status': 'confirmed'}:
                return confirmed
            return _counting_queryset(0)

        rows.filter.side_effect = rows_filter
        confirmed.count.return_value = 1
        confirmed.filter.return_value = _counting_queryset(0)
        confirmed.values.return_value.distinct.return_value.count.return_value = 1
        batches_manager.filter.return_value = rows
        settlements = mock.MagicMock()
        settlements.aggregate.return_value = {'buy': None, 'sell': None}
        settlements.count.return_value = 0
        unified_manager.filter.return_value = settlements

        stats = get_stock_trade_stats()

        self.assertEqual(stats['confirmed'], 1)
        self.assertEqual(stats['history_missing'], 1)
        self.assertEqual(stats['total_volume'], Decimal('0'))


class OndoStockTradeAdminTests(SimpleTestCase):
    @mock.patch.object(SponsoredBatchAdmin, 'get_queryset')
    def test_proxy_admin_filters_non_stock_batches(self, parent_get_queryset):
        base_queryset = mock.MagicMock()
        filtered_queryset = mock.MagicMock()
        final_queryset = mock.sentinel.stock_queryset
        parent_get_queryset.return_value = base_queryset
        base_queryset.filter.return_value = filtered_queryset
        filtered_queryset.select_related.return_value = final_queryset
        model_admin = OndoStockTradeAdmin(OndoStockTrade, admin.AdminSite())

        result = model_admin.get_queryset(RequestFactory().get('/admin/'))

        base_queryset.filter.assert_called_once_with(
            kind__in=('stock_buy', 'stock_sell')
        )
        filtered_queryset.select_related.assert_called_once_with('unified_transaction')
        self.assertIs(result, final_queryset)

    def test_displays_event_backed_settlement(self):
        model_admin = OndoStockTradeAdmin(OndoStockTrade, admin.AdminSite())
        row = SimpleNamespace(
            kind='stock_buy',
            tx_hash='0x' + '12' * 32,
            unified_transaction=SimpleNamespace(
                amount='25.075',
                description='Ondo Stocks: Compra de NVDA',
            ),
        )

        self.assertEqual(model_admin.trade_side(row), 'Buy')
        self.assertEqual(model_admin.stock_symbol(row), 'NVDA')
        self.assertEqual(model_admin.settled_usd(row), '$25.08')
        self.assertIn('bscscan.com/tx/', str(model_admin.transaction_link(row)))


class StockRouterMetricsTests(SimpleTestCase):
    ROUTER = '0x' + '40' * 20
    USDT = '0x' + '55' * 20

    def tearDown(self):
        cache.clear()

    @override_settings(
        CUSD_PLUS_STOCK_ROUTER_ADDRESS=ROUTER,
        CUSD_PLUS_STOCKS_ENABLED=True,
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
    )
    @mock.patch('cusd_plus.tasks._rpc')
    def test_reads_accrued_fee_separately_from_raw_router_balance(self, rpc):
        rpc.side_effect = [
            hex(3 * 10 ** 18),
            hex(30),
            hex(0),
            hex(int(self.USDT, 16)),
            hex(4 * 10 ** 18),
        ]

        metrics = get_stock_router_metrics(use_cache=False)

        self.assertEqual(metrics['source'], 'bsc')
        self.assertEqual(metrics['accrued_usdt_fees'], Decimal('3'))
        self.assertEqual(metrics['router_usdt_balance'], Decimal('4'))
        self.assertEqual(metrics['fee_bps_onchain'], 30)
        self.assertFalse(metrics['paused'])
        self.assertTrue(metrics['trading_enabled'])
        self.assertEqual(rpc.call_count, 5)

    @override_settings(CUSD_PLUS_STOCK_ROUTER_ADDRESS='')
    def test_unconfigured_router_is_not_reported_as_zero(self):
        metrics = get_stock_router_metrics(use_cache=False)

        self.assertEqual(metrics['source'], 'unconfigured')
        self.assertIsNone(metrics['accrued_usdt_fees'])
        self.assertIsNone(metrics['router_usdt_balance'])
