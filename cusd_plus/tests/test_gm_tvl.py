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
            {'primaryMarket': {'symbol': 'TSLAon', 'price': '100'}},
            {'primaryMarket': {'symbol': 'AAPLon', 'price': '50'}},
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
        self.assertEqual(result['positions'], 2)
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

    def test_locmem_release_does_not_delete_a_successor_lock(self):
        release = gm_tvl._acquire_lock()
        self.assertIsNotNone(release)
        cache.set(gm_tvl.TVL_LOCK_KEY, 'new-owner', 60)

        release()

        self.assertEqual(cache.get(gm_tvl.TVL_LOCK_KEY), 'new-owner')
