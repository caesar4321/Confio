from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from blockchain.models import SponsoredBatch
from users.models import User
from users.models_unified import UnifiedTransactionTable

from . import gm_trading_stats
from .stock_month import Trade


class TradingStatsTests(TestCase):
    def setUp(self):
        for key in (gm_trading_stats.CACHE_KEY, gm_trading_stats.FRESH_KEY, gm_trading_stats.LOCK_KEY):
            cache.delete(key)
        self.user = User.objects.create_user(username='ts-1', email='ts1@example.com', firebase_uid='ts-1')
        self.decoded = []

    def trade(self, kind, symbol, usd, wallet, n=[0]):
        n[0] += 1
        batch = SponsoredBatch.objects.create(
            user=self.user, user_bsc_address=wallet, kind=kind, status='confirmed', tx_hash=f'0x{n[0]:064x}',
            calls_json='[]', num_calls=1, source_id=n[0], gas_limit=1, max_fee_wei='1', client_request_id=f'ts-{n[0]}')
        UnifiedTransactionTable.objects.create(
            transaction_type='send', amount=str(usd), token_type='CUSD_PLUS', status='CONFIRMED',
            transaction_date=timezone.now(), sponsored_batch=batch)
        self.decoded.append(Trade(symbol=symbol, kind=kind, units=Decimal('1'), usd=Decimal(str(usd)),
                                  when=timezone.now()))

    def stats(self):
        with patch('cusd_plus.stock_month._decode_trades', return_value=self.decoded), \
                patch.object(gm_trading_stats, '_names', return_value={'NVDAon': ('NVDA', 'NVIDIA')}):
            return gm_trading_stats.compute()

    def test_split_counts_and_privacy_floor(self):
        for i in range(3):
            self.trade('stock_buy', 'NVDAon', 2, f'0x{i:040x}')
        self.trade('stock_sell', 'NVDAon', 1.5, '0x' + '0' * 40)
        self.trade('stock_buy', 'KLACon', 10, '0x' + '9' * 40)  # one person only
        s = self.stats()
        self.assertEqual((s.buy_count, s.sell_count, s.trader_count), (4, 1, 4))
        self.assertAlmostEqual(s.total_usd, 17.5)
        self.assertEqual([a.ticker for a in s.top_assets], ['NVDA'])
        self.assertEqual((s.top_assets[0].trade_count, s.top_assets[0].trader_count), (4, 3))
        self.assertIsNone(s.median_buy_usd)  # too few purchases to state
        # One person sold: the split would expose that sale, so it is withheld.
        self.assertEqual((s.buy_usd, s.sell_usd), (None, None))

    def test_one_wallets_many_purchases_never_state_a_median(self):
        for i in range(12):
            self.trade('stock_buy', 'NVDAon', i + 1, '0x' + '1' * 40)
        self.assertIsNone(self.stats().median_buy_usd)

    def test_the_public_breakdown_needs_three_traders(self):
        self.trade('stock_buy', 'NVDAon', 5, '0x' + '1' * 40)
        self.trade('stock_buy', 'NVDAon', 5, '0x' + '2' * 40)
        with patch('cusd_plus.stock_month._decode_trades', return_value=self.decoded), \
                patch.object(gm_trading_stats, '_names', return_value={}):
            self.assertIsNone(gm_trading_stats.trading_stats())
            self.assertEqual(gm_trading_stats.snapshot().total_usd, 10.0)  # Home's tile still sums it

    def test_typical_purchase_once_there_are_enough(self):
        for i in range(10):
            self.trade('stock_buy', 'NVDAon', i + 1, f'0x{i:040x}')
        self.assertEqual(self.stats().median_buy_usd, 5.5)

    def test_an_old_snapshot_is_rebuilt_even_without_new_trades(self):
        for i in range(3):
            self.trade('stock_buy', 'NVDAon', 2, f'0x{i:040x}')
        with patch('cusd_plus.stock_month._decode_trades', return_value=self.decoded), \
                patch.object(gm_trading_stats, '_names', return_value={}):
            first = gm_trading_stats.snapshot()
            cache.delete(gm_trading_stats.FRESH_KEY)
            with patch.object(gm_trading_stats, 'compute', wraps=gm_trading_stats.compute) as rebuild:
                gm_trading_stats.snapshot()
                rebuild.assert_not_called()  # same signature, still young
                first.computed_at -= gm_trading_stats.MAX_AGE + 1
                cache.set(gm_trading_stats.CACHE_KEY, (gm_trading_stats._signature(), first))
                cache.delete(gm_trading_stats.FRESH_KEY)
                gm_trading_stats.snapshot()
                rebuild.assert_called_once()

    def test_a_cold_build_in_progress_is_never_duplicated(self):
        cache.add(gm_trading_stats.LOCK_KEY, 1, 60)
        with patch.object(gm_trading_stats, 'compute') as rebuild:
            self.assertIsNone(gm_trading_stats.snapshot())
        rebuild.assert_not_called()
        self.assertTrue(cache.get(gm_trading_stats.LOCK_KEY))  # not released by a non-holder
