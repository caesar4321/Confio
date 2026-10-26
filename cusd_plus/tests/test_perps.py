"""Futuros foundation: market sync, catalog, country policy, gates, GraphQL."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from cusd_plus import hyperliquid, perps_catalog

OPEN_SETTINGS = dict(
    PERPS_ENABLED=True, PERPS_TRADING_ENABLED=True, PERPS_OPEN_ENABLED=True, PERPS_IOS_ENABLED=True,
    PERPS_ALLOWED_USER_IDS='', PERPS_BLOCKED_COUNTRIES='', PERPS_EXCLUDED_MARKETS='',
    CUSD_PLUS_7702_ENABLED=True, CUSD_PLUS_BATCH_DELEGATE_ADDRESS='0x' + '7a' * 20,
)


def _universe(*entries):
    return [
        {'name': name, 'szDecimals': sz, 'maxLeverage': lev, **extra}
        for name, sz, lev, extra in entries
    ]


class FakeHyperliquid:
    """Answers /info like Hyperliquid: perpDexs with core as the null entry,
    one USDC HIP-3 dex and one USDH dex (not tradable through Relay)."""

    def __init__(self, *, core=None, xyz=None, fail_on=None, dexs=None, tokens=None):
        self.dexs = dexs if dexs is not None else [None, {'name': 'xyz'}, {'name': 'flx'}]
        self.tokens = tokens if tokens is not None else [{'index': 0, 'name': 'USDC'}, {'index': 360, 'name': 'USDH'}]
        self.core = core if core is not None else _universe(
            ('BTC', 5, 40, {}), ('OLD', 0, 3, {'isDelisted': True}), ('kPEPE', 0, 10, {}))
        self.xyz = xyz if xyz is not None else _universe(('xyz:GOLD', 4, 25, {}), ('xyz:NVDA', 3, 20, {}))
        self.fail_on = fail_on

    def post(self, url, json=None, **kwargs):
        body = json
        if self.fail_on and body.get('dex') == self.fail_on:
            return SimpleNamespace(status_code=500, json=lambda: {})
        if body['type'] == 'spotMeta':
            result = {'tokens': self.tokens}
        elif body['type'] == 'perpDexs':
            result = self.dexs
        elif body['type'] == 'meta' and not body.get('dex'):
            result = {'universe': self.core, 'collateralToken': 0}
        elif body['type'] == 'meta' and body['dex'] == 'xyz':
            result = {'universe': self.xyz, 'collateralToken': getattr(self, 'xyz_collateral', 0)}
        elif body['type'] == 'meta' and body['dex'] == 'flx':
            result = {'universe': _universe(('flx:TSLA', 3, 10, {})), 'collateralToken': 360}
        else:
            raise AssertionError(body)
        return SimpleNamespace(status_code=200, json=lambda: result)


class AssetIdTests(SimpleTestCase):
    def test_core_is_the_index_and_hip3_is_offset_by_dex_position(self):
        self.assertEqual(perps_catalog.asset_id(0, 7), 7)
        self.assertEqual(perps_catalog.asset_id(1, 3), 110003)
        self.assertEqual(perps_catalog.asset_id(2, 0), 120000)


class SyncTests(TestCase):
    def test_sync_lists_core_and_usdc_dexes_only(self):
        from blockchain.models import PerpMarket

        result = perps_catalog.sync_markets(session=FakeHyperliquid())
        self.assertEqual(result['created'], 5)
        coins = set(PerpMarket.objects.values_list('coin', flat=True))
        self.assertEqual(coins, {'BTC', 'OLD', 'kPEPE', 'xyz:GOLD', 'xyz:NVDA'}, 'USDH dex skipped')
        gold = PerpMarket.objects.get(coin='xyz:GOLD')
        self.assertEqual((gold.dex, gold.asset_id, gold.max_leverage, gold.collateral), ('xyz', 110000, 25, 'USDC'))
        # Delisted entries keep their universe position: kPEPE is index 2.
        self.assertEqual(PerpMarket.objects.get(coin='kPEPE').asset_id, 2)
        self.assertFalse(PerpMarket.objects.get(coin='OLD').listed)

        openable = {m.coin for m in perps_catalog.markets()}
        self.assertEqual(openable, {'BTC', 'kPEPE', 'xyz:GOLD', 'xyz:NVDA'}, 'memecoins included')

    def test_delisted_market_stays_closeable_not_openable(self):
        from blockchain.models import PerpMarket

        perps_catalog.sync_markets(session=FakeHyperliquid())
        perps_catalog.sync_markets(session=FakeHyperliquid(
            xyz=_universe(('xyz:GOLD', 4, 20, {}), ('xyz:NVDA', 3, 20, {'isDelisted': True}))))
        self.assertFalse(PerpMarket.objects.get(coin='xyz:NVDA').listed)
        self.assertEqual(PerpMarket.objects.get(coin='xyz:GOLD').max_leverage, 20, 'venue max refreshed')
        self.assertNotIn('xyz:NVDA', {m.coin for m in perps_catalog.markets()})
        self.assertIn('xyz:NVDA', {m.coin for m in perps_catalog.markets(openable_only=False)})

    def test_dex_moving_off_usdc_delists_its_markets(self):
        from blockchain.models import PerpMarket

        perps_catalog.sync_markets(session=FakeHyperliquid())
        usdh_xyz = FakeHyperliquid()
        usdh_xyz.xyz_collateral = 360
        perps_catalog.sync_markets(session=usdh_xyz)
        self.assertFalse(PerpMarket.objects.get(coin='xyz:GOLD').listed)
        self.assertTrue(PerpMarket.objects.get(coin='BTC').listed)

    def test_partial_snapshot_aborts_instead_of_delisting_or_moving_ids(self):
        # Codex P2: Hyperliquid universes are append-only; a known market
        # missing or an id moving is a bad read, never a delisting.
        from blockchain.models import PerpMarket

        perps_catalog.sync_markets(session=FakeHyperliquid())
        for bad in (FakeHyperliquid(dexs=[None]),
                    FakeHyperliquid(xyz=_universe(('xyz:GOLD', 4, 25, {}))),
                    FakeHyperliquid(core=_universe(('OLD', 0, 3, {'isDelisted': True}), ('kPEPE', 0, 10, {}))),
                    FakeHyperliquid(core=_universe(('kPEPE', 0, 10, {}), ('BTC', 5, 40, {}), ('OLD', 0, 3, {}))),
                    FakeHyperliquid(dexs=[None, {'name': 'xyz'}, {'name': 'xyz'}])):
            with self.assertRaises(hyperliquid.HyperliquidError):
                perps_catalog.sync_markets(session=bad)
        self.assertEqual(PerpMarket.objects.get(coin='BTC').asset_id, 0)
        self.assertEqual(PerpMarket.objects.filter(listed=True).count(), 4)

    def test_a_failed_dex_read_changes_nothing(self):
        from blockchain.models import PerpMarket

        perps_catalog.sync_markets(session=FakeHyperliquid())
        with self.assertRaises(hyperliquid.HyperliquidError):
            perps_catalog.sync_markets(session=FakeHyperliquid(fail_on='xyz'))
        self.assertTrue(PerpMarket.objects.get(coin='xyz:GOLD').listed, 'partial read never delists')

    def test_unreadable_dex_list_or_collateral_aborts_instead_of_delisting(self):
        # Codex P2 x2: a junk perpDexs entry or a spotMeta missing USDC used
        # to read as "this dex is gone" and delist its markets.
        from blockchain.models import PerpMarket

        perps_catalog.sync_markets(session=FakeHyperliquid())
        for bad in (FakeHyperliquid(dexs=[None, 'bad']),
                    FakeHyperliquid(dexs=[]),
                    FakeHyperliquid(dexs=[{'name': 'xyz'}]),
                    FakeHyperliquid(core=[]),
                    FakeHyperliquid(xyz=[]),
                    FakeHyperliquid(tokens=[{'index': 360, 'name': 'USDH'}]),
                    FakeHyperliquid(tokens=[{'index': 0, 'name': None}, {'index': 360, 'name': 'USDH'}]),
                    FakeHyperliquid(tokens=[{'index': 0, 'name': 'USDC'}, {'index': '360', 'name': 'USDH'}])):
            with self.assertRaises(hyperliquid.HyperliquidError):
                perps_catalog.sync_markets(session=bad)
        self.assertEqual(
            set(PerpMarket.objects.filter(listed=True).values_list('coin', flat=True)),
            {'BTC', 'kPEPE', 'xyz:GOLD', 'xyz:NVDA'})
        self.assertEqual(PerpMarket.objects.get(coin='BTC').collateral, 'USDC')

    def test_malformed_universe_aborts(self):
        bad = FakeHyperliquid(core=[{'name': 'BTC', 'szDecimals': 'x', 'maxLeverage': 40}])
        with self.assertRaises(hyperliquid.HyperliquidError):
            perps_catalog.sync_markets(session=bad)
        for entry in ({'isDelisted': 'false'}, {'onlyIsolated': 1}):
            with self.assertRaises(hyperliquid.HyperliquidError):
                perps_catalog.sync_markets(session=FakeHyperliquid(core=_universe(('BTC', 5, 40, entry))))
        float_lev = FakeHyperliquid(core=_universe(('BTC', 5, 40.0, {})))
        with self.assertRaises(hyperliquid.HyperliquidError):
            perps_catalog.sync_markets(session=float_lev)
        float_collateral = FakeHyperliquid()
        float_collateral.xyz_collateral = 360.9
        with self.assertRaises(hyperliquid.HyperliquidError):
            perps_catalog.sync_markets(session=float_collateral)
        wrong_prefix = FakeHyperliquid(xyz=_universe(('abc:GOLD', 4, 25, {})))
        with self.assertRaises(hyperliquid.HyperliquidError):
            perps_catalog.sync_markets(session=wrong_prefix)

    def test_overlay_names_classes_and_ops_exclusion(self):
        perps_catalog.sync_markets(session=FakeHyperliquid())
        views = {m.coin: m for m in perps_catalog.markets()}
        self.assertEqual((views['xyz:GOLD'].name, views['xyz:GOLD'].asset_class), ('Oro', 'commodity'))
        self.assertEqual((views['xyz:NVDA'].ticker, views['xyz:NVDA'].asset_class), ('NVDA', 'stock'))
        self.assertEqual((views['BTC'].name, views['kPEPE'].asset_class), ('Bitcoin', 'crypto'))
        with override_settings(PERPS_EXCLUDED_MARKETS='kPEPE, xyz:NVDA'):
            self.assertEqual({m.coin for m in perps_catalog.markets()}, {'BTC', 'xyz:GOLD'})

    def test_overlay_classes_are_known(self):
        perps_catalog._overlay.cache_clear()
        self.assertTrue(perps_catalog._overlay())


@override_settings(**OPEN_SETTINGS)
class PerpsGateTests(TestCase):
    def setUp(self):
        from users.models import User

        self.user = User.objects.create(username='perpsgate', firebase_uid='perpsgate')

    def _gate(self, country, meta=None):
        from cusd_plus import perps_risk

        with mock.patch('security.geo.phone_country_of', return_value=country):
            return perps_risk.open_gate(self.user, meta or {})

    def test_open_needs_ack_and_venezuela_is_allowed(self):
        from cusd_plus import perps_risk

        self.assertEqual(self._gate('VE'), perps_risk.ACK_REQUIRED_CODE)
        perps_risk.acknowledge(self.user)
        for country in ('VE', 'BO', 'BR', 'PE', 'CO', 'AR'):
            self.assertIsNone(self._gate(country), country)

    def test_baseline_and_ops_blocklist_stop_opens_never_exits(self):
        from cusd_plus import perps_risk

        perps_risk.acknowledge(self.user)
        for country in ('US', 'CA', 'CU', 'IR', 'KP', 'SY', 'GB', 'BE', ''):
            self.assertEqual(self._gate(country), 'trade_not_available', country or 'missing phone')
        with override_settings(PERPS_BLOCKED_COUNTRIES='ar'):
            self.assertEqual(self._gate('AR'), 'trade_not_available')
        self.assertIsNone(perps_risk.exit_gate())
        with override_settings(PERPS_TRADING_ENABLED=False):
            self.assertEqual(perps_risk.exit_gate(), 'trade_not_available')

    def test_canary_open_switch_and_ios_kill_switch(self):
        from cusd_plus import perps_risk

        perps_risk.acknowledge(self.user)
        with override_settings(PERPS_ALLOWED_USER_IDS='999999'):
            self.assertEqual(self._gate('VE'), 'trade_not_available')
        with override_settings(PERPS_ALLOWED_USER_IDS=str(self.user.id)):
            self.assertIsNone(self._gate('VE'))
        with override_settings(PERPS_OPEN_ENABLED=False):
            self.assertEqual(self._gate('VE'), 'trade_not_available')
            self.assertIsNone(perps_risk.exit_gate(), 'closes stay open')
        ios = {'HTTP_X_CONFIO_PLATFORM': 'ios'}
        android = {'HTTP_X_CONFIO_PLATFORM': 'android'}
        with override_settings(PERPS_IOS_ENABLED=False):
            self.assertEqual(self._gate('VE', ios), 'trade_not_available')
            self.assertIsNone(self._gate('VE', android))

    def test_closes_depend_only_on_the_execution_switch(self):
        # Codex P2: BSC sponsorship settings must not block a Hyperliquid close.
        from cusd_plus import perps_risk

        with override_settings(CUSD_PLUS_7702_ENABLED=False, CUSD_PLUS_BATCH_DELEGATE_ADDRESS=''):
            self.assertIsNone(perps_risk.exit_gate())
            self.assertEqual(self._gate('VE'), 'trade_not_available')

    def test_ip_lookup_failure_refuses_opens(self):
        # Codex P2: fail closed on opens (closes are never country-gated).
        from cusd_plus import perps_risk

        perps_risk.acknowledge(self.user)
        with mock.patch('security.geo.country_for_request', side_effect=RuntimeError('geo down')):
            self.assertEqual(self._gate('VE', {'REMOTE_ADDR': '1.2.3.4'}), 'trade_not_available')
        self.assertIsNone(perps_risk.exit_gate())

    def test_promotion_overlay_is_separate_from_availability(self):
        from cusd_plus import perps_risk
        from cusd_plus.eligibility import perps_promotion_blocked

        perps_risk.acknowledge(self.user)
        with override_settings(PERPS_PROMOTION_BLOCKED_COUNTRIES='PE,CO'), \
                mock.patch('security.geo.phone_country_of', return_value='PE'):
            self.assertTrue(perps_promotion_blocked(self.user))
            self.assertIsNone(perps_risk.open_gate(self.user, {}), 'still available')
        with mock.patch('security.geo.phone_country_of', return_value='BO'):
            self.assertFalse(perps_promotion_blocked(self.user))


@override_settings(**OPEN_SETTINGS)
class PerpsSchemaTests(TestCase):
    def setUp(self):
        from users.models import User

        self.user = User.objects.create(username='perpsschema', firebase_uid='perpsschema')
        perps_catalog.sync_markets(session=FakeHyperliquid())

    def _execute(self, query, country='VE', meta=None):
        from config.schema import schema

        context = SimpleNamespace(user=self.user, META=meta or {})
        with mock.patch('security.geo.phone_country_of', return_value=country), \
                mock.patch('cusd_plus.perps_schema._personal_wallet', return_value='0x' + '44' * 20), \
                mock.patch('cusd_plus.crypto_policy.live_fee_bps', return_value=90):
            return schema.execute(query, context_value=context)

    def test_capabilities_markets_and_ack(self):
        result = self._execute(
            '{ perpsCapabilities { enabled openEnabled ackRequired ackVersion feeBps '
            'impactMaxBps promotionAllowed } perpsMarkets { coin assetClass assetId maxLeverage } }')
        self.assertIsNone(result.errors)
        caps = result.data['perpsCapabilities']
        self.assertEqual((caps['enabled'], caps['openEnabled'], caps['ackRequired']), (True, True, True))
        self.assertEqual((caps['feeBps'], caps['impactMaxBps'], caps['promotionAllowed']), (90, 300, True))
        coins = {m['coin'] for m in result.data['perpsMarkets']}
        self.assertEqual(coins, {'BTC', 'kPEPE', 'xyz:GOLD', 'xyz:NVDA'})

        ack = self._execute('mutation { acknowledgePerpsRisk(version: 1) { success error } }')
        self.assertTrue(ack.data['acknowledgePerpsRisk']['success'])
        stale = self._execute('mutation { acknowledgePerpsRisk(version: 0) { success error } }')
        self.assertEqual(stale.data['acknowledgePerpsRisk']['error'], 'OUTDATED_DISCLOSURE')
        again = self._execute('{ perpsCapabilities { ackRequired } }')
        self.assertFalse(again.data['perpsCapabilities']['ackRequired'])

    def test_blocked_country_sees_no_markets_and_the_message(self):
        result = self._execute('{ perpsCapabilities { enabled blockedMessage } perpsMarkets { coin } }', 'US')
        self.assertIsNone(result.errors)
        self.assertFalse(result.data['perpsCapabilities']['enabled'])
        self.assertIn('futuros', result.data['perpsCapabilities']['blockedMessage'])
        self.assertIsNone(result.data['perpsMarkets'])
