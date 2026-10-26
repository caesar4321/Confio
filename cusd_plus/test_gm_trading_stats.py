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


class InvestScopeTests(TestCase):
    """Scope 'all' (Home's Inversiones): stocks + Bitcoin & gold; 'stocks'
    keeps store builds' Acciones numbers exactly as before."""

    def setUp(self):
        for scope in gm_trading_stats.SCOPES:
            for key in (gm_trading_stats.CACHE_KEY, gm_trading_stats.FRESH_KEY, gm_trading_stats.LOCK_KEY):
                cache.delete(gm_trading_stats._key(key, scope))
        self.user = User.objects.create_user(username='inv-1', email='inv1@example.com', firebase_uid='inv-1')
        self.decoded = []
        self.n = 0

    def trade(self, kind, symbol, usd, wallet):
        from blockchain.models import CryptoTrade

        self.n += 1
        batch = SponsoredBatch.objects.create(
            user=self.user, user_bsc_address=wallet, kind=kind, status='confirmed', tx_hash=f'0x{self.n + 500:064x}',
            calls_json='[]', num_calls=1, source_id=self.n + 500, gas_limit=1, max_fee_wei='1',
            client_request_id=f'inv-{self.n}')
        UnifiedTransactionTable.objects.create(
            transaction_type='send', amount=str(usd), token_type='CUSD_PLUS', status='CONFIRMED',
            transaction_date=timezone.now(), sponsored_batch=batch)
        if kind.startswith('crypto'):
            CryptoTrade.objects.create(batch=batch, wallet=wallet, symbol=symbol, kind=kind,
                                       units=Decimal('1'), usd=Decimal(str(usd)), traded_at=timezone.now())
        else:
            self.decoded.append(Trade(symbol=symbol, kind=kind, units=Decimal('1'), usd=Decimal(str(usd)),
                                      when=timezone.now()))

    def compute(self, scope):
        with patch('cusd_plus.stock_month._decode_trades', side_effect=lambda batches: self.decoded[:len(batches)]), \
                patch.object(gm_trading_stats, '_names', return_value={'NVDAon': ('NVDA', 'NVIDIA')}):
            return gm_trading_stats.compute(scope)

    def test_all_adds_bitcoin_and_gold_stocks_stays_stock_only(self):
        for i in range(3):
            self.trade('stock_buy', 'NVDAon', 10, f'0x{i:040x}')
            self.trade('crypto_buy', 'BTCB', 5, f'0x{i:040x}')
        self.trade('crypto_sell', 'XAUT', 2, '0x' + '9' * 40)

        stocks = self.compute('stocks')
        self.assertEqual(stocks.total_usd, 30.0)
        self.assertEqual([a.ticker for a in stocks.top_assets], ['NVDA'])

        both = self.compute('all')
        self.assertEqual(both.total_usd, 47.0)
        self.assertEqual((both.buy_count, both.sell_count, both.trader_count), (6, 1, 4))
        by_ticker = {a.ticker: a for a in both.top_assets}
        self.assertEqual(by_ticker['BTC'].kind, 'crypto')
        self.assertEqual(by_ticker['BTC'].name, 'Bitcoin')
        self.assertEqual(by_ticker['NVDA'].kind, 'stock')
        self.assertNotIn('XAUT', by_ticker)  # one wallet: below the privacy floor

    def test_all_is_withheld_while_one_or_two_people_trade_crypto(self):
        from . import gm_volume

        for i in range(3):
            self.trade('stock_buy', 'NVDAon', 10, f'0x{i:040x}')
        self.trade('crypto_buy', 'BTCB', 7, '0x' + '8' * 40)  # one crypto trader
        with patch('cusd_plus.stock_month._decode_trades', side_effect=lambda b: self.decoded[:len(b)]), \
                patch.object(gm_trading_stats, '_names', return_value={}):
            # all − stocks would be that one person's exact volume.
            self.assertEqual(gm_volume.traded_usd('stocks'), 30.0)
            self.assertIsNone(gm_volume.traded_usd('all'))
            self.assertIsNone(gm_trading_stats.trading_stats('all'))
            for i in range(1, 3):
                self.trade('crypto_buy', 'BTCB', 1, f'0x{i:040x}')
            for scope in gm_trading_stats.SCOPES:
                cache.delete(gm_trading_stats._key(gm_trading_stats.FRESH_KEY, scope))
            self.assertEqual(gm_volume.traded_usd('all'), 39.0)

    def test_scopes_cache_separately(self):
        for i in range(3):
            self.trade('crypto_buy', 'BTCB', 5, f'0x{i:040x}')
        with patch('cusd_plus.stock_month._decode_trades', return_value=[]), \
                patch.object(gm_trading_stats, '_names', return_value={}):
            self.assertEqual(gm_trading_stats.snapshot('stocks').total_usd, 0.0)
            self.assertEqual(gm_trading_stats.snapshot('all').total_usd, 15.0)
        from . import gm_volume
        self.assertEqual(gm_volume.traded_usd('all'), 15.0)
        self.assertIsNone(gm_volume.traded_usd('stocks'))  # no traders: below the floor


class PerpsTradingStatsTests(TestCase):
    """Futuros in scope 'all': margin in and dollars back, never the leveraged size."""

    def setUp(self):
        from blockchain.models import PerpMarket

        for scope in gm_trading_stats.SCOPES:
            for key in (gm_trading_stats.CACHE_KEY, gm_trading_stats.FRESH_KEY, gm_trading_stats.LOCK_KEY):
                cache.delete(gm_trading_stats._key(key, scope))
        self.user = User.objects.create_user(username='pts-1', email='pts1@example.com', firebase_uid='pts-1')
        self.market = PerpMarket.objects.create(coin='BTC', dex='', asset_id=0, sz_decimals=5, max_leverage=40,
                                                collateral='USDC', synced_at=timezone.now())
        self.n = 0

    def batch(self, kind, usd, wallet):
        self.n += 1
        batch = SponsoredBatch.objects.create(
            user=self.user, user_bsc_address=wallet, kind=kind, status='confirmed', tx_hash=f'0x{self.n:064x}',
            calls_json='[]', num_calls=1, gas_limit=1, max_fee_wei='1', client_request_id=f'pts-{self.n}')
        UnifiedTransactionTable.objects.create(
            transaction_type='send', amount=str(usd), token_type='CUSD_PLUS', status='CONFIRMED',
            transaction_date=timezone.now(), sponsored_batch=batch)
        return batch

    def position(self, wallet, margin, state='open', leverage=10, returned=None):
        from blockchain.models import PerpPosition

        position = PerpPosition.objects.create(
            user=self.user, wallet=wallet, market=self.market, side='long', leverage=leverage,
            margin_usd=Decimal(str(margin)), state=state, open_batch=self.batch('perps_open', margin, wallet))
        if returned is not None:
            position.return_batch = self.batch('perps_return', returned, wallet)
            position.save(update_fields=['return_batch'])
        return position

    def stats(self):
        with patch('cusd_plus.stock_month._decode_trades', return_value=[]), \
                patch.object(gm_trading_stats, '_names', return_value={}):
            return gm_trading_stats.compute('all')

    def test_margin_counts_never_the_leveraged_size(self):
        for i in range(3):
            self.position(f'0x{i:040x}', 20, leverage=10, returned=(23 if i == 0 else None))
        s = self.stats()
        self.assertAlmostEqual(s.total_usd, 83.0)          # 3 × US$20 margin + US$23 back; never US$200 each
        self.assertEqual((s.buy_count, s.sell_count, s.trader_count, s.crypto_trader_count), (3, 1, 3, 3))
        self.assertEqual([(a.kind, a.symbol, a.ticker, a.trade_count, a.trader_count) for a in s.top_assets],
                         [('perps', 'BTC', 'BTC', 4, 3)])

    def test_one_persons_return_never_shows_through_the_split(self):
        for i in range(3):
            self.position(f'0x{i:040x}', 20, returned=(25 if i == 0 else None))   # one return only
        for i in range(3, 6):
            self.batch('stock_buy', 10, f'0x{i:040x}')
            self.batch('stock_sell', 5, f'0x{i:040x}')
        with patch('cusd_plus.stock_month._decode_trades', side_effect=lambda b: [None] * 0), \
                patch.object(gm_trading_stats, '_symbols', side_effect=lambda bs: [
                    'NVDAon' if b.kind.startswith('stock') else 'BTC' for b in bs]), \
                patch.object(gm_trading_stats, '_names', return_value={}):
            s = gm_trading_stats.compute('all')
        # 'all' sells − 'stocks' sells would be that one member's US$25.
        self.assertEqual((s.buy_usd, s.sell_usd), (None, None))

    def test_a_refund_kept_as_dollars_never_traded(self):
        from blockchain.models import PerpMarginChange

        for i in range(3):
            self.position(f'0x{i:040x}', 20)
        self.position('0x' + '9' * 40, 50, state='cancelled')
        live = self.position('0x' + '8' * 40, 10)
        PerpMarginChange.objects.create(position=live, direction='add', amount_usd=Decimal('5'), state='refunded',
                                        batch=self.batch('perps_open', 5, '0x' + '8' * 40))
        s = self.stats()
        self.assertAlmostEqual(s.total_usd, 70.0)
        self.assertEqual((s.buy_count, s.trader_count), (4, 4))

    def test_a_late_refund_rebuilds_the_snapshot(self):
        position = None
        for i in range(3):
            position = self.position(f'0x{i:040x}', 20, state='refunded')
        with patch('cusd_plus.stock_month._decode_trades', return_value=[]), \
                patch.object(gm_trading_stats, '_names', return_value={}):
            self.assertEqual(gm_trading_stats.snapshot('all').total_usd, 0.0)   # refunded: not yet traded
            from blockchain.models import PerpPosition
            PerpPosition.objects.filter(pk=position.pk).update(state='bridging', updated_at=timezone.now())
            cache.delete(gm_trading_stats._key(gm_trading_stats.FRESH_KEY, 'all'))
            self.assertEqual(gm_trading_stats.snapshot('all').total_usd, 20.0)  # re-bridged: it trades now


class InvestFieldsGateTests(TestCase):
    def info(self):
        from types import SimpleNamespace
        return SimpleNamespace(context=SimpleNamespace(user=SimpleNamespace(is_authenticated=True), META={}))

    def test_open_to_every_country(self):
        # A network fact like Movido: it also counts Futuros, whose countries
        # differ from stocks' and crypto's (2026-10-26).
        from .schema import Query

        with patch('cusd_plus.gm_volume.traded_usd', return_value=12.5):
            for stocks, crypto, expected in ((True, False, 12.5), (False, True, 12.5), (False, False, 12.5)):
                with patch('cusd_plus.schema._stock_surfaces_enabled', return_value=stocks), \
                        patch('cusd_plus.crypto_risk.surfaces_enabled', return_value=crypto):
                    self.assertEqual(Query().resolve_invest_traded_usd(self.info()), expected)
