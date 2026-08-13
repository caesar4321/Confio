from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from cusd_plus import gm_holdings, gm_tvl


class GmTvlTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_refresh_scans_confirmed_participants_at_one_block_and_prices_holdings(self):
        registry = {
            'TSLAon': {'address': '0x' + '11' * 20, 'decimals': 18},
            'AAPLon': {'address': '0x' + '22' * 20, 'decimals': 18},
        }
        market = [
            {
                'primaryMarket': {
                    'symbol': 'TSLAon', 'price': '100', 'priceChangePct24h': '2.5',
                },
                'underlyingMarket': {'ticker': 'TSLA', 'name': 'Tesla, Inc.'},
            },
            {
                'primaryMarket': {
                    'symbol': 'AAPLon', 'price': '50', 'priceChangePct24h': '-1.25',
                },
                'underlyingMarket': {'ticker': 'AAPL', 'name': 'Apple Inc.'},
            },
        ]
        first = '0x' + 'aa' * 20
        second = '0x' + 'bb' * 20

        with mock.patch.object(gm_tvl, '_participant_addresses', return_value=[first, second]), \
             mock.patch('cusd_plus.gm_holdings.registry', return_value=registry), \
             mock.patch('cusd_plus.gm_api.all_market', return_value=market), \
             mock.patch('cusd_plus.vault._rpc', return_value='0x123') as rpc, \
             mock.patch(
                 'cusd_plus.gm_holdings._scan',
                 side_effect=[{'TSLAon': 2.0}, {'AAPLon': 0.5}],
             ) as scan:
            result = gm_tvl.refresh()

        self.assertEqual(result['value_usd'], 225.0)
        self.assertEqual(result['accounts_scanned'], 2)
        self.assertEqual(result['holder_wallets'], 2)
        self.assertEqual(result['positions'], 2)
        self.assertEqual([a['ticker'] for a in result['assets']], ['TSLA', 'AAPL'])
        self.assertEqual(result['assets'][0]['value_usd'], 200.0)
        self.assertAlmostEqual(result['assets'][0]['share_pct'], 200 / 225 * 100)
        self.assertEqual(result['assets'][0]['holders'], 1)
        self.assertEqual(result['assets'][0]['day_change_pct'], 2.5)
        self.assertEqual(result['as_of_block'], 0x123)
        rpc.assert_called_once_with('eth_blockNumber', [])
        self.assertEqual(scan.call_args_list[0].kwargs['block_tag'], '0x123')
        self.assertEqual(scan.call_args_list[1].kwargs['block_tag'], '0x123')
        self.assertTrue(scan.call_args_list[0].kwargs['require_complete'])
        self.assertTrue(scan.call_args_list[1].kwargs['require_complete'])
        self.assertEqual(gm_tvl.value_usd(), 225.0)

    def test_refresh_with_no_confirmed_traders_publishes_zero_without_rpc(self):
        with mock.patch.object(gm_tvl, '_participant_addresses', return_value=[]), \
             mock.patch('cusd_plus.gm_holdings.registry') as registry, \
             mock.patch('cusd_plus.gm_api.all_market') as market, \
             mock.patch('cusd_plus.vault._rpc') as rpc:
            result = gm_tvl.refresh()

        self.assertEqual(result['value_usd'], 0.0)
        self.assertEqual(result['accounts_scanned'], 0)
        self.assertEqual(result['holder_wallets'], 0)
        self.assertEqual(result['assets'], [])
        registry.assert_not_called()
        market.assert_not_called()
        rpc.assert_not_called()

    def test_failed_refresh_keeps_last_known_value(self):
        cache.set(gm_tvl.TVL_LAST_CACHE_KEY, {'value_usd': 91.25}, 60)
        with self.assertLogs('cusd_plus.gm_tvl', level='ERROR'), \
             mock.patch.object(
                 gm_tvl,
                 '_participant_addresses',
                 return_value=['0x' + 'aa' * 20],
             ), mock.patch('cusd_plus.gm_holdings.registry', side_effect=RuntimeError('down')):
            self.assertIsNone(gm_tvl.refresh())

        self.assertEqual(gm_tvl.value_usd(), 91.25)

    def test_incomplete_participant_scan_never_replaces_last_known_value(self):
        cache.set(gm_tvl.TVL_LAST_CACHE_KEY, {'value_usd': 91.25}, 60)
        registry = {'TSLAon': {'address': '0x' + '11' * 20, 'decimals': 18}}
        with self.assertLogs('cusd_plus.gm_tvl', level='ERROR'), \
             mock.patch.object(
                 gm_tvl,
                 '_participant_addresses',
                 return_value=['0x' + 'aa' * 20],
             ), mock.patch('cusd_plus.gm_holdings.registry', return_value=registry), \
             mock.patch(
                 'cusd_plus.gm_api.all_market',
                 return_value=[{'primaryMarket': {'symbol': 'TSLAon', 'price': '100'}}],
             ), mock.patch('cusd_plus.vault._rpc', return_value='0x123'), \
             mock.patch(
                 'cusd_plus.gm_holdings._scan',
                 side_effect=RuntimeError('GM balanceOf failed for TSLAon'),
             ):
            self.assertIsNone(gm_tvl.refresh())

        self.assertEqual(gm_tvl.value_usd(), 91.25)

    def test_strict_multicall_scan_rejects_failed_token_subcall(self):
        registry = {'TSLAon': {'address': '0x' + '11' * 20, 'decimals': 18}}
        with mock.patch('cusd_plus.gm_holdings.vault._rpc', return_value='0x00'), \
             mock.patch('cusd_plus.gm_holdings.decode', return_value=([(False, b'')],)):
            with self.assertRaisesRegex(RuntimeError, 'TSLAon'):
                gm_holdings._scan(
                    '0x' + 'aa' * 20,
                    registry,
                    block_tag='0x123',
                    require_complete=True,
                )

    def test_held_asset_without_price_never_replaces_last_known_value(self):
        cache.set(gm_tvl.TVL_LAST_CACHE_KEY, {'value_usd': 91.25}, 60)
        registry = {'TSLAon': {'address': '0x' + '11' * 20, 'decimals': 18}}
        with self.assertLogs('cusd_plus.gm_tvl', level='ERROR'), \
             mock.patch.object(
                 gm_tvl,
                 '_participant_addresses',
                 return_value=['0x' + 'aa' * 20],
             ), mock.patch('cusd_plus.gm_holdings.registry', return_value=registry), \
             mock.patch(
                 'cusd_plus.gm_api.all_market',
                 return_value=[{'primaryMarket': {'symbol': 'AAPLon', 'price': '50'}}],
             ), mock.patch('cusd_plus.vault._rpc', return_value='0x123'), \
             mock.patch('cusd_plus.gm_holdings._scan', return_value={'TSLAon': 2.0}):
            self.assertIsNone(gm_tvl.refresh())

        self.assertEqual(gm_tvl.value_usd(), 91.25)

    def test_refresh_marks_the_same_units_to_the_latest_market_price(self):
        registry = {'TSLAon': {'address': '0x' + '11' * 20, 'decimals': 18}}
        address = '0x' + 'aa' * 20
        market = [
            {'primaryMarket': {'symbol': 'TSLAon', 'price': '100'}},
        ]
        with mock.patch.object(gm_tvl, '_participant_addresses', return_value=[address]), \
             mock.patch('cusd_plus.gm_holdings.registry', return_value=registry), \
             mock.patch('cusd_plus.gm_api.all_market', return_value=market), \
             mock.patch('cusd_plus.vault._rpc', return_value='0x123'), \
             mock.patch('cusd_plus.gm_holdings._scan', return_value={'TSLAon': 2.0}):
            first = gm_tvl.refresh()
            market[0]['primaryMarket']['price'] = '125'
            second = gm_tvl.refresh()

        self.assertEqual(first['value_usd'], 200.0)
        self.assertEqual(second['value_usd'], 250.0)
        self.assertEqual(second['assets'][0]['price_usd'], 125.0)

    def test_community_asset_rollup_combines_units_and_unique_wallets(self):
        registry = {'TSLAon': {'address': '0x' + '11' * 20, 'decimals': 18}}
        participants = ['0x' + 'aa' * 20, '0x' + 'bb' * 20]
        market = [{
            'primaryMarket': {'symbol': 'TSLAon', 'price': '100'},
            'underlyingMarket': {'ticker': 'TSLA', 'name': 'Tesla'},
        }]
        with mock.patch.object(gm_tvl, '_participant_addresses', return_value=participants), \
             mock.patch('cusd_plus.gm_holdings.registry', return_value=registry), \
             mock.patch('cusd_plus.gm_api.all_market', return_value=market), \
             mock.patch('cusd_plus.vault._rpc', return_value='0x123'), \
             mock.patch('cusd_plus.gm_holdings._scan', side_effect=[
                 {'TSLAon': 2.0}, {'TSLAon': 1.25},
             ]):
            result = gm_tvl.refresh()

        self.assertEqual(result['value_usd'], 325.0)
        self.assertEqual(result['holder_wallets'], 2)
        self.assertEqual(result['positions'], 2)
        self.assertEqual(result['assets'][0]['units'], 3.25)
        self.assertEqual(result['assets'][0]['holders'], 2)

    def test_locmem_release_does_not_delete_a_successor_lock(self):
        release = gm_tvl._acquire_lock()
        self.assertIsNotNone(release)
        cache.set(gm_tvl.TVL_LOCK_KEY, 'new-owner', 60)

        release()

        self.assertEqual(cache.get(gm_tvl.TVL_LOCK_KEY), 'new-owner')
