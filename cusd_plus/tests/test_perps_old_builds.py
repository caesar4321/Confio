"""Builds before Futuros (below PERPS_SHARE_MIN_APP_VERSION) never meet a
Futuros screen they don't have: no ranking row that opens as a stock, no
Comunidad post read as crypto, no push to a screen that doesn't exist."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

OLD = {'HTTP_X_CONFIO_VERSION': '5.2.8'}
NEW = {'HTTP_X_CONFIO_VERSION': '5.2.9'}


@override_settings(PERPS_SHARE_MIN_APP_VERSION='5.2.9')
class RankingRowsTests(SimpleTestCase):
    def resolve(self, meta):
        from cusd_plus import gm_trading_stats
        from cusd_plus.schema import Query

        stats = gm_trading_stats.TradingStats(
            total_usd=100.0, buy_usd=None, sell_usd=None, buy_count=3, sell_count=0, trader_count=3,
            median_buy_usd=None, since=None, top_assets=[
                gm_trading_stats.TopAsset('BTC', 'BTC', 'Bitcoin', 5, 3, kind='perps'),
                gm_trading_stats.TopAsset('BTCB', 'BTC', 'Bitcoin', 4, 3, kind='crypto')])
        info = SimpleNamespace(context=SimpleNamespace(user=SimpleNamespace(is_authenticated=True), META=meta))
        with mock.patch('cusd_plus.schema._invest_surfaces_enabled', return_value=True), \
                mock.patch.object(gm_trading_stats, 'trading_stats', return_value=stats):
            return Query().resolve_invest_trading_stats(info)

    def test_older_builds_get_no_futuros_rows(self):
        self.assertEqual([a.asset_kind for a in self.resolve(OLD).top_assets], ['crypto'])
        self.assertEqual(self.resolve(OLD).total_usd, 100.0)
        self.assertEqual([a.asset_kind for a in self.resolve(NEW).top_assets], ['perps', 'crypto'])


@override_settings(PERPS_SHARE_MIN_APP_VERSION='5.2.9')
class ShareCategoryTests(SimpleTestCase):
    def test_a_stock_twin_carries_no_perp_category(self):
        from inbox.schema import build_activity_type

        public = {'kind': 'perps_open', 'name': 'BTC · Corto 5x', 'ticker': 'BTC', 'category': 'perp',
                  'amount_usd': '20.00'}
        with mock.patch('inbox.activity_share.activity_headline', return_value='x'):
            old = build_activity_type(public, {}, OLD)
            new = build_activity_type(public, {}, NEW)
        self.assertEqual((old.kind, old.category, old.ticker), ('stock_buy', None, 'BTC · Corto 5x'))
        self.assertEqual((new.kind, new.category), ('perps_open', 'perp'))


class PortfolioPositionTests(SimpleTestCase):
    def test_a_futuros_position_opens_nothing_and_shows_no_size(self):
        from inbox import schema
        from inbox.member_portfolio import OpenPosition

        portfolio = SimpleNamespace(
            total_usd=None, dollars_usd=None, stocks_usd=None, stocks_change_24h_usd=None, presale_confio=None,
            presale_invested_usd=None, trade_count=None, avg_hold_seconds=None, member_since=None,
            closed_positions=None, open_positions=[
                OpenPosition(symbol='perp:7', ticker='BTC', name='BTC · Largo 10x', units=Decimal('0.002'),
                             value_usd=Decimal('21')),
                OpenPosition(symbol='BTCB', ticker='BTC', name='Bitcoin', units=Decimal('0.001'),
                             value_usd=Decimal('110'))])
        target = SimpleNamespace(id=1)
        with mock.patch.object(schema, '_portfolio_target', return_value=target), \
                mock.patch.object(schema.member_portfolio, 'build_portfolio', return_value=portfolio), \
                mock.patch.object(schema.community, 'portfolio_hidden', return_value=False), \
                mock.patch.object(schema, '_today_gain', return_value=None):
            result = schema.build_member_portfolio(target, 1)
        perp, coin = result.open_positions
        self.assertEqual((perp.symbol, perp.units, perp.value_usd), ('', '', '21.00'))
        self.assertEqual((coin.symbol, coin.units), ('BTCB', '0.001'))


@override_settings(PERPS_SHARE_MIN_APP_VERSION='5.2.9')
class PushBuildTests(TestCase):
    def test_futuros_notices_reach_only_devices_with_futuros(self):
        from notifications.fcm_service import _tokens_on_builds
        from notifications.models import FCMDeviceToken
        from users.models import User

        user = User.objects.create_user(username='pob-1', email='pob1@example.com', firebase_uid='pob-1')
        old = FCMDeviceToken.objects.create(user=user, token='old', device_type='android', device_id='a',
                                            app_version='5.2.8')
        new = FCMDeviceToken.objects.create(user=user, token='new', device_type='ios', device_id='b',
                                            app_version='5.2.10')
        blank = FCMDeviceToken.objects.create(user=user, token='blank', device_type='ios', device_id='c')
        pairs = [(t.token, t.id) for t in (old, new, blank)]
        self.assertEqual(_tokens_on_builds(pairs, 'PERPS_SHARE_MIN_APP_VERSION'), [('new', new.id)])


@override_settings(PERPS_SHARE_MIN_APP_VERSION='5.2.9')
class InboxTypesTests(SimpleTestCase):
    def test_older_builds_list_no_futuros_notices(self):
        from notifications.schema import _types_this_build_cannot_open

        info = lambda meta: SimpleNamespace(context=SimpleNamespace(META=meta))  # noqa: E731
        self.assertEqual(_types_this_build_cannot_open(info(OLD)), ['PERPS_POSITION_UPDATE'])
        self.assertEqual(_types_this_build_cannot_open(info({})), ['PERPS_POSITION_UPDATE'])
        self.assertEqual(_types_this_build_cannot_open(info(NEW)), [])


class ReconcileLockTests(SimpleTestCase):
    def test_a_sweep_releases_only_its_own_lock_and_skips_while_one_runs(self):
        from django.core.cache import cache

        from cusd_plus import tasks

        cache.delete(tasks.PERPS_RECONCILE_LOCK)
        with override_settings(PERPS_TRADING_ENABLED=True), \
                mock.patch.object(tasks, '_reconcile_perps_positions', return_value=2) as sweep:
            cache.set(tasks.PERPS_RECONCILE_LOCK, 'someone-else', 60)
            self.assertEqual(tasks.reconcile_perps_positions(), 0)
            self.assertEqual(cache.get(tasks.PERPS_RECONCILE_LOCK), 'someone-else')
            cache.delete(tasks.PERPS_RECONCILE_LOCK)
            self.assertEqual(tasks.reconcile_perps_positions(), 2)
            self.assertIsNone(cache.get(tasks.PERPS_RECONCILE_LOCK))
            self.assertEqual(sweep.call_count, 1)


@override_settings(PERPS_SHARE_MIN_APP_VERSION='5.2.9')
class BadgeTests(TestCase):
    def test_older_phones_badge_without_hidden_futuros_notices(self):
        from notifications import fcm_service
        from notifications.models import FCMDeviceToken, Notification
        from users.models import User

        user = User.objects.create_user(username='pob-2', email='pob2@example.com', firebase_uid='pob-2')
        FCMDeviceToken.objects.create(user=user, token='old', device_type='android', device_id='a',
                                      app_version='5.2.8')
        FCMDeviceToken.objects.create(user=user, token='new', device_type='ios', device_id='b',
                                      app_version='5.2.9')
        Notification.objects.create(user=user, notification_type='PERPS_POSITION_UPDATE', title='t', message='m')
        note = Notification.objects.create(user=user, notification_type='SEND_RECEIVED', title='t', message='m')
        sent = []

        def batch(tokens, badge_count, **_kw):
            sent.append(([t for t, _i in tokens], badge_count))
            return {'success': True, 'sent': len(tokens), 'failed': 0, 'errors': [], 'invalid_tokens': []}

        with mock.patch.object(fcm_service, 'FIREBASE_INITIALIZED', True), \
                mock.patch.object(fcm_service, 'should_send_push', return_value=True), \
                mock.patch.object(fcm_service, 'send_batch_notifications', side_effect=batch):
            result = fcm_service.send_push_notification(note)
        self.assertEqual(sorted(sent), [(['new'], 2), (['old'], 1)])
        self.assertEqual(result['sent'], 2)


class SweepDeadlineTests(SimpleTestCase):
    def test_no_hyperliquid_read_starts_past_the_sweep_deadline(self):
        import time

        from cusd_plus import hyperliquid

        session = mock.Mock()
        with hyperliquid.reads_until(time.monotonic() - 1):
            with self.assertRaises(hyperliquid.SweepDeadline):
                hyperliquid.info({'type': 'meta'}, session=session)
        # Never a HyperliquidError: no "unread → fallback" handler may catch it.
        self.assertFalse(issubclass(hyperliquid.SweepDeadline, hyperliquid.HyperliquidError))
        session.post.assert_not_called()
        session.post.return_value = mock.Mock(status_code=200, json=lambda: {'ok': 1})
        self.assertEqual(hyperliquid.info({'type': 'meta'}, session=session), {'ok': 1})  # outside a sweep

    def test_a_deadline_never_reads_as_no_credit_yet(self):
        # _hl_credit maps a failed read to None, and an aged top-up then falls
        # back to Relay's minimum_out: the deadline must unwind past both.
        from cusd_plus import hyperliquid, perps_flow

        with mock.patch.object(hyperliquid, 'ledger_updates', side_effect=hyperliquid.SweepDeadline()):
            with self.assertRaises(hyperliquid.SweepDeadline):
                perps_flow._hl_credit('0xabc', {'txHashes': ['0x' + '1' * 64]}, 0)


class ClosedPositionsPageTests(TestCase):
    """perpsPositions(doneLimit): the Futuros list pages closed positions; a
    read without it (position screen, resume flows) still gets them all."""

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        from blockchain.models import PerpMarket, PerpPosition, SponsoredBatch
        from users.models import User

        self.user = User.objects.create(username='perpspage', firebase_uid='perpspage')
        self.wallet = '0x' + '66' * 20
        market = PerpMarket.objects.create(coin='BTC', dex='', asset_id=0, sz_decimals=5, max_leverage=40,
                                           collateral='USDC', synced_at=timezone.now())
        batch = SponsoredBatch.objects.create(user=self.user, user_bsc_address=self.wallet, kind='perps_open',
                                              calls_json='[]', num_calls=3, tx_hash='0x' + '02' * 32,
                                              status='confirmed', gas_limit=1, max_fee_wei=1, block_number=10)
        now = timezone.now()

        def make(state, days_ago=0, **kw):
            return PerpPosition.objects.create(user=self.user, wallet=self.wallet, market=market, side='long',
                                               leverage=5, margin_usd=Decimal('20'), state=state, **kw).id

        self.closed = [make('done', open_batch=batch, returned_usd=Decimal('21'),
                            done_at=now - timedelta(days=d)) for d in (3, 1, 2)]
        self.refunded = make('done', returned_usd=Decimal('20'), done_at=now)  # never opened
        self.failed = make('failed')
        self.live = make('funded')

    def _ids(self, **kw):
        from cusd_plus import perps_schema

        with mock.patch.object(perps_schema, '_user', return_value=self.user), \
                mock.patch.object(perps_schema, '_personal_wallet', return_value=self.wallet), \
                mock.patch('cusd_plus.hyperliquid.clearinghouse_state',
                           return_value={'withdrawable': '0', 'assetPositions': []}), \
                mock.patch('cusd_plus.perps_market_data.all_contexts', return_value={}), \
                mock.patch.object(perps_schema, '_position_type', side_effect=lambda p, *a, **k: p.id):
            return perps_schema.Query.resolve_perps_positions(None, SimpleNamespace(), **kw)

    def test_limit_keeps_live_and_the_newest_real_results(self):
        self.assertEqual(self._ids(include_done=True, done_limit=2), [self.live, self.closed[1], self.closed[2]])

    def test_without_a_limit_every_row_still_comes_back(self):
        self.assertEqual(set(self._ids(include_done=True)),
                         {*self.closed, self.refunded, self.failed, self.live})
        self.assertEqual(self._ids(), [self.live])


class OhlcTests(SimpleTestCase):
    """Candlesticks for traders: Hyperliquid's own candles, bad rows dropped."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_parses_candles_and_drops_bad_rows(self):
        from cusd_plus import perps_market_data

        rows = [
            {'t': 1000, 'o': '10', 'h': '12', 'l': '9', 'c': '11', 'v': '3.5'},
            {'t': 2000, 'o': '11', 'h': 'x', 'l': '9', 'c': '10', 'v': '1'},   # bad high
            {'t': '3000', 'o': '1', 'h': '1', 'l': '1', 'c': '1', 'v': '1'},   # bad time
            {'t': 4000, 'o': '0', 'h': '1', 'l': '0', 'c': '1', 'v': '1'},     # zero price
            {'t': 5000, 'o': '11', 'h': '11', 'l': '10', 'c': '10.5'},          # no volume
        ]
        with mock.patch('cusd_plus.hyperliquid.candles', return_value=rows) as upstream:
            out = perps_market_data.ohlc('xyz:GOLD', '1m')
        self.assertEqual(out, [
            {'t': 1000, 'o': 10.0, 'h': 12.0, 'l': 9.0, 'c': 11.0, 'v': 3.5},
            {'t': 5000, 'o': 11.0, 'h': 11.0, 'l': 10.0, 'c': 10.5, 'v': 0.0},
        ])
        coin, interval, start, end = upstream.call_args.args
        self.assertEqual((coin, interval, end - start), ('xyz:GOLD', '1m', 150 * 60 * 1000))

    def test_unknown_interval_is_refused(self):
        from cusd_plus import perps_market_data

        with self.assertRaises(ValueError):
            perps_market_data.ohlc('BTC', '2m')

    def test_resolver_keeps_unknown_coins_and_intervals_out(self):
        from cusd_plus import perps_schema

        with mock.patch.object(perps_schema, '_user', return_value=object()), \
                mock.patch('cusd_plus.perps_catalog.by_coin', side_effect=lambda c: object() if c == 'BTC' else None), \
                mock.patch('cusd_plus.perps_market_data.ohlc', return_value=[
                    {'t': 1000, 'o': 1.0, 'h': 2.0, 'l': 0.5, 'c': 1.5, 'v': 7.0}]) as ohlc:
            self.assertEqual(perps_schema.Query.resolve_perps_ohlc(None, None, 'DOGE', '1m'), [])
            self.assertEqual(perps_schema.Query.resolve_perps_ohlc(None, None, 'BTC', '2m'), [])
            got = perps_schema.Query.resolve_perps_ohlc(None, None, 'BTC', '1m')
        self.assertEqual([(c.time, c.open, c.high, c.low, c.close, c.volume) for c in got],
                         [(1000.0, 1.0, 2.0, 0.5, 1.5, 7.0)])
        ohlc.assert_called_once_with('BTC', '1m')

    def test_upstream_failure_reads_as_unknown(self):
        from cusd_plus import hyperliquid, perps_schema

        with mock.patch.object(perps_schema, '_user', return_value=object()), \
                mock.patch('cusd_plus.perps_catalog.by_coin', return_value=object()), \
                mock.patch('cusd_plus.perps_market_data.ohlc', side_effect=hyperliquid.HyperliquidError('x')):
            self.assertIsNone(perps_schema.Query.resolve_perps_ohlc(None, None, 'BTC', '5m'))
