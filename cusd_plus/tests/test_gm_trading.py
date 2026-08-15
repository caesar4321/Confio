import base64
import time
from types import SimpleNamespace
from unittest import mock

import graphene
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from cusd_plus import gm_api
from cusd_plus import gm_holdings
from cusd_plus.schema import (
    PrepareGmTrade,
    Query,
    _acquire_gm_quote_lock,
    _bsc_rate_limited,
    _normalize_gm_quote,
    _stock_execution_ready,
    _validated_gm_trade_request,
)


class GmApiTradingTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()
        gm_holdings._fallback_registry.cache_clear()
        super().tearDown()

    @override_settings(
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS='0x' + '11' * 20,
        CUSD_PLUS_7702_ENABLED=True,
        CUSD_PLUS_BATCH_DELEGATE_ADDRESS='0x' + '22' * 20,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
    )
    def test_execution_gate_requires_all_settlement_rails(self):
        self.assertTrue(_stock_execution_ready())
        with override_settings(CUSD_PLUS_7702_ENABLED=False):
            self.assertFalse(_stock_execution_ready())
        with override_settings(CUSD_PLUS_GM_TRADE_FEE_BPS=31):
            self.assertFalse(_stock_execution_ready())

    @override_settings(ONDO_API_KEY='read-key', ONDO_GM_WRITE_KEY='write-key')
    def test_soft_and_binding_use_split_keys_and_bsc_chain(self):
        response = mock.Mock(ok=True)
        response.json.return_value = {'ok': True}
        with mock.patch('cusd_plus.gm_api.requests.post', return_value=response) as post:
            gm_api.soft_attestation('TSLAon', 'buy', '99.7', 'short')
            gm_api.binding_attestation('TSLAon', 'buy', '99.7', 'short')
        self.assertEqual(post.call_args_list[0].kwargs['headers']['x-api-key'], 'read-key')
        self.assertEqual(post.call_args_list[1].kwargs['headers']['x-api-key'], 'write-key')
        self.assertEqual(post.call_args_list[0].kwargs['json']['chainId'], 'bsc-56')
        self.assertNotIn('userAddress', post.call_args_list[0].kwargs['json'])

    @override_settings(CUSD_PLUS_GM_MAX_TRADE_USD=100_000)
    def test_binding_quote_is_normalized_for_router_abi(self):
        request = _validated_gm_trade_request('TSLAon', 'buy', '600', 'short')
        data = {
            'attestationId': '123',
            'userId': '0x' + '44' * 32,
            'chainId': '56',
            'symbol': 'TSLAon',
            'ticker': 'TSLA',
            'assetAddress': '0x' + '55' * 20,
            'side': '0',
            'tokenAmount': str(2 * 10**18),
            'price': str(300 * 10**18),
            'expiration': int(time.time()) + 300,
            'signature': base64.b64encode(b'\x66' * 65).decode(),
            'additionalData': '',
        }
        quote = _normalize_gm_quote(data, request, binding=True)
        self.assertTrue(quote['success'])
        self.assertEqual(quote['notional_wei'], str(600 * 10**18))
        self.assertEqual(quote['signature_hex'], '0x' + '66' * 65)
        self.assertEqual(quote['additional_data_hex'], '0x' + '00' * 32)

    @override_settings(CUSD_PLUS_GM_MAX_TRADE_USD=100_000)
    def test_quote_arithmetic_outside_micro_usdt_is_rejected(self):
        request = _validated_gm_trade_request('TSLAon', 'buy', '600', 'short')
        data = {
            'chainId': '56', 'symbol': 'TSLAon', 'ticker': 'TSLA',
            'assetAddress': '0x' + '55' * 20, 'side': '0',
            'tokenAmount': str(1 * 10**18), 'price': str(599 * 10**18),
        }
        with self.assertRaises(gm_api.GmApiError):
            _normalize_gm_quote(data, request, binding=False)

    @override_settings(CUSD_PLUS_GM_MAX_TRADE_USD=100_000)
    def test_quote_cost_slightly_above_request_is_used_for_settlement(self):
        request = _validated_gm_trade_request('TSLAon', 'buy', '1.0967', 'short')
        requested = 1_096_700_000_000_000_000
        data = {
            'chainId': '56', 'symbol': 'TSLAon', 'ticker': 'TSLA',
            'assetAddress': '0x' + '55' * 20, 'side': '0',
            'tokenAmount': str(requested + 40), 'price': str(10**18),
        }
        quote = _normalize_gm_quote(data, request, binding=False)
        self.assertEqual(quote['notional_wei'], str(requested + 40))

    @override_settings(CUSD_PLUS_GM_MAX_TRADE_USD=100_000)
    def test_quote_cost_above_request_by_more_than_micro_usdt_is_rejected(self):
        request = _validated_gm_trade_request('TSLAon', 'buy', '1.0967', 'short')
        requested = 1_096_700_000_000_000_000
        data = {
            'chainId': '56', 'symbol': 'TSLAon', 'ticker': 'TSLA',
            'assetAddress': '0x' + '55' * 20, 'side': '0',
            'tokenAmount': str(requested + 10**12 + 1), 'price': str(10**18),
        }
        with self.assertRaises(gm_api.GmApiError):
            _normalize_gm_quote(data, request, binding=False)

    @override_settings(CUSD_PLUS_GM_MAX_TRADE_USD=100_000)
    def test_numeric_zero_buy_side_is_accepted(self):
        request = _validated_gm_trade_request('TSLAon', 'buy', '600', 'short')
        data = {
            'chainId': 56, 'symbol': 'TSLAon', 'ticker': 'TSLA',
            'assetAddress': '0x' + '55' * 20, 'side': 0,
            'tokenAmount': str(2 * 10**18), 'price': str(300 * 10**18),
        }
        self.assertEqual(_normalize_gm_quote(data, request, binding=False)['side'], '0')

    def test_structured_upstream_error_is_preserved(self):
        response = mock.Mock(ok=False, status_code=403)
        response.json.return_value = {'code': 'MARKET_CLOSED', 'message': 'market is closed'}
        with override_settings(ONDO_API_KEY='read-key'), \
             mock.patch('cusd_plus.gm_api.requests.post', return_value=response), \
             self.assertRaises(gm_api.GmApiError) as ctx:
            gm_api.soft_attestation('TSLAon', 'buy', '100', 'short')
        self.assertEqual(ctx.exception.code, 'MARKET_CLOSED')

    def test_holdings_registry_uses_official_bsc_addresses(self):
        rows = [{
            'symbol': 'TSLAon',
            'addresses': [
                {'networkChainId': 'ethereum-1', 'address': '0x' + '11' * 20, 'decimals': 18},
                {'networkChainId': 'bsc-56', 'address': '0x' + '22' * 20, 'decimals': 18},
            ],
        }]
        with mock.patch('cusd_plus.gm_holdings.Path.read_text', return_value='{}'), \
             mock.patch('cusd_plus.gm_api.all_addresses', return_value=rows):
            registry = gm_holdings.registry()
        self.assertEqual(registry['TSLAon']['address'], '0x' + '22' * 20)

    def test_holdings_registry_is_cached_across_requests(self):
        rows = [{
            'symbol': 'TSLAon',
            'addresses': [{
                'networkChainId': 'bsc-56',
                'address': '0x' + '22' * 20,
                'decimals': 18,
            }],
        }]
        with mock.patch('cusd_plus.gm_holdings.Path.read_text', return_value='{}'), \
             mock.patch('cusd_plus.gm_api.all_addresses', return_value=rows) as addresses:
            self.assertEqual(gm_holdings.registry(), gm_holdings.registry())
        addresses.assert_called_once()

    @override_settings(CUSD_PLUS_GM_AUDIT_MIN_LIVE_ASSETS=1)
    def test_audit_registry_uses_fresh_live_metadata_and_unions_snapshot(self):
        snapshot_address = '0x' + '11' * 20
        live_address = '0x' + '22' * 20
        fallback = {
            'OLDon': {'address': snapshot_address, 'decimals': 18},
        }
        rows = [{
            'symbol': 'NEWon',
            'addresses': [{
                'networkChainId': 'bsc-56',
                'address': live_address,
                'decimals': 18,
            }],
        }]
        with mock.patch.object(gm_holdings, '_fallback_registry', return_value=fallback), \
             mock.patch('cusd_plus.gm_api.all_addresses_fresh', return_value=rows) as fresh, \
             mock.patch('cusd_plus.gm_api.all_addresses') as cached:
            registry = gm_holdings.audit_registry()
        fresh.assert_called_once_with()
        cached.assert_not_called()
        self.assertEqual(
            {item['address'].lower() for item in registry.values()},
            {snapshot_address.lower(), live_address.lower()},
        )

    @override_settings(CUSD_PLUS_GM_AUDIT_MIN_LIVE_ASSETS=10)
    def test_audit_registry_fails_closed_on_truncated_live_metadata(self):
        fallback = {
            f'SYM{i}': {'address': f'0x{i:040x}', 'decimals': 18}
            for i in range(10)
        }
        rows = [{
            'symbol': 'ONLYon',
            'addresses': [{
                'networkChainId': 'bsc-56',
                'address': '0x' + '22' * 20,
                'decimals': 18,
            }],
        }]
        with mock.patch.object(gm_holdings, '_fallback_registry', return_value=fallback), \
             mock.patch('cusd_plus.gm_api.all_addresses_fresh', return_value=rows), \
             self.assertRaisesRegex(RuntimeError, 'incomplete'):
            gm_holdings.audit_registry()

    def test_audit_registry_propagates_fresh_fetch_failure(self):
        with mock.patch('cusd_plus.gm_api.all_addresses_fresh', side_effect=TimeoutError('down')), \
             self.assertRaises(TimeoutError):
            gm_holdings.audit_registry()

    def test_audit_registry_fails_closed_on_malformed_live_metadata(self):
        with mock.patch.object(gm_holdings, '_fallback_registry', return_value={}), \
             mock.patch(
                 'cusd_plus.gm_api.all_addresses_fresh',
                 return_value=[{'symbol': 'BADon', 'addresses': 'not-a-list'}],
             ), \
             self.assertRaisesRegex(RuntimeError, 'malformed addresses'):
            gm_holdings.audit_registry()

    def test_fresh_holdings_cache_skips_registry_lookup(self):
        holder = '0x' + '77' * 20
        cache.set(f'gm_hold:{holder}', {'TSLAon': 1.0}, 30)
        with mock.patch('cusd_plus.gm_holdings.registry') as registry:
            self.assertEqual(gm_holdings.holdings_units(holder), {'TSLAon': 1.0})
        registry.assert_not_called()

    def test_empty_registry_outage_is_unknown_not_empty_portfolio(self):
        with mock.patch('cusd_plus.gm_holdings.Path.read_text', return_value='{}'), \
             mock.patch('cusd_plus.gm_api.all_addresses', side_effect=RuntimeError('down')):
            self.assertIsNone(gm_holdings.registry())

    def test_rate_limit_counts_atomically_to_the_configured_cap(self):
        for _ in range(6):
            self.assertFalse(_bsc_rate_limited(991, 'gm_firm_quote', 6))
        self.assertTrue(_bsc_rate_limited(991, 'gm_firm_quote', 6))

    @override_settings(CUSD_PLUS_STOCKS_ENABLED=True)
    def test_ondo_ineligible_user_cannot_read_stock_surfaces(self):
        user = SimpleNamespace(is_authenticated=True, id=33, phone_country='US')
        info = SimpleNamespace(context=SimpleNamespace(
            user=user, META={'HTTP_CF_IPCOUNTRY': 'CO'}))
        query = Query()
        with mock.patch('cusd_plus.gm_api.all_market') as market, \
             mock.patch('cusd_plus.gm_api.ohlc') as ohlc, \
             mock.patch('cusd_plus.gm_tvl.snapshot') as community, \
             mock.patch('cusd_plus.schema._active_account') as account:
            self.assertIsNone(query.resolve_gm_market(info))
            self.assertIsNone(query.resolve_gm_community(info))
            self.assertEqual(query.resolve_gm_holdings(info), [])
            self.assertEqual(query.resolve_gm_ohlc(info, 'TSLAon'), [])
        market.assert_not_called()
        ohlc.assert_not_called()
        community.assert_not_called()
        account.assert_not_called()

    @override_settings(CUSD_PLUS_STOCKS_ENABLED=True)
    def test_eligible_user_gets_privacy_safe_marked_to_market_community_stats(self):
        user = SimpleNamespace(is_authenticated=True, id=35, phone_country='CO')
        info = SimpleNamespace(context=SimpleNamespace(
            user=user, META={'HTTP_CF_IPCOUNTRY': 'CO'}))
        snapshot = {
            'value_usd': 325.0,
            'holder_wallets': 3,
            'positions': 3,
            'as_of_block': 123,
            'updated_at': '2026-08-13T12:34:00+00:00',
            'assets': [{
                'symbol': 'TSLAon',
                'ticker': 'TSLA',
                'name': 'Tesla, Inc.',
                'units': 3.25,
                'price_usd': 100.0,
                'value_usd': 325.0,
                'share_pct': 100.0,
                'holders': 3,
                'day_change_pct': 1.5,
            }],
        }
        with mock.patch('cusd_plus.gm_tvl.snapshot', return_value=snapshot):
            result = Query().resolve_gm_community(info)

        self.assertEqual(result.value_usd, 325.0)
        self.assertEqual(result.holder_wallets, 3)
        self.assertEqual(result.positions, 3)
        self.assertEqual(result.assets, [{
            'symbol': 'TSLAon',
            'ticker': 'TSLA',
            'name': 'Tesla',
            'value_usd': 325.0,
            'share_pct': 100.0,
        }])

    @override_settings(
        CUSD_PLUS_STOCKS_ENABLED=True,
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS='0x' + '11' * 20,
        CUSD_PLUS_7702_ENABLED=True,
        CUSD_PLUS_BATCH_DELEGATE_ADDRESS='0x' + '22' * 20,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
        CUSD_PLUS_STOCK_BUY_BLOCKED_COUNTRIES=[],
    )
    def test_colombia_summary_allows_usdy_and_stock_exits_but_not_buys(self):
        user = SimpleNamespace(is_authenticated=True, id=35, phone_country='CO')
        info = SimpleNamespace(context=SimpleNamespace(
            user=user, META={'HTTP_CF_IPCOUNTRY': 'CO'}))

        with mock.patch('cusd_plus.schema._active_bsc_address', return_value=None), \
             mock.patch('cusd_plus.vault.apy_split', return_value=(3.5, 3.0)):
            result = Query().resolve_cusd_plus_summary(info)

        self.assertTrue(result.savings_enabled)
        self.assertTrue(result.stocks_enabled)
        self.assertTrue(result.stocks_trading_enabled)
        self.assertFalse(result.stocks_buy_enabled)

    @override_settings(CUSD_PLUS_STOCKS_ENABLED=True)
    def test_community_graphql_contract_uses_camel_case_client_fields(self):
        context = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, id=35, phone_country='CO'),
            META={'HTTP_CF_IPCOUNTRY': 'CO'},
        )
        snapshot = {
            'value_usd': 325.0,
            'holder_wallets': 3,
            'positions': 3,
            'as_of_block': 123,
            'updated_at': '2026-08-13T12:34:00+00:00',
            'assets': [{
                'symbol': 'TSLAon', 'ticker': 'TSLA', 'name': 'Tesla',
                'value_usd': 325.0, 'share_pct': 100.0, 'holders': 3,
            }],
        }
        schema = graphene.Schema(query=Query)
        with mock.patch('cusd_plus.gm_tvl.snapshot', return_value=snapshot):
            result = schema.execute(
                '{ gmCommunity { valueUsd holderWallets positions updatedAt '
                'assets { symbol ticker name valueUsd sharePct } } }',
                context_value=context,
            )

        self.assertIsNone(result.errors)
        self.assertEqual(result.data['gmCommunity']['valueUsd'], 325.0)
        self.assertEqual(result.data['gmCommunity']['holderWallets'], 3)
        self.assertEqual(result.data['gmCommunity']['assets'][0]['ticker'], 'TSLA')

    @override_settings(CUSD_PLUS_STOCKS_ENABLED=True)
    def test_community_hides_assets_held_by_fewer_than_three_wallets(self):
        context = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, id=35, phone_country='CO'),
            META={'HTTP_CF_IPCOUNTRY': 'CO'},
        )
        snapshot = {
            'value_usd': 100.0,
            'holder_wallets': 2,
            'positions': 2,
            'as_of_block': 123,
            'updated_at': '2026-08-13T12:34:00+00:00',
            'assets': [{
                'symbol': 'TSLAon', 'ticker': 'TSLA', 'name': 'Tesla',
                'value_usd': 100.0, 'share_pct': 100.0, 'holders': 2,
            }],
        }
        schema = graphene.Schema(query=Query)
        with mock.patch('cusd_plus.gm_tvl.snapshot', return_value=snapshot):
            result = schema.execute(
                '{ gmCommunity { valueUsd assets { ticker } } }',
                context_value=context,
            )

        self.assertIsNone(result.errors)
        self.assertEqual(result.data['gmCommunity']['valueUsd'], 100.0)
        self.assertEqual(result.data['gmCommunity']['assets'], [])

    @override_settings(CUSD_PLUS_STOCKS_ENABLED=False)
    def test_hidden_stock_surface_never_reads_community_snapshot(self):
        user = SimpleNamespace(is_authenticated=True, id=36, phone_country='CO')
        info = SimpleNamespace(context=SimpleNamespace(
            user=user, META={'HTTP_CF_IPCOUNTRY': 'CO'}))
        with mock.patch('cusd_plus.gm_tvl.snapshot') as snapshot:
            self.assertIsNone(Query().resolve_gm_community(info))
        snapshot.assert_not_called()

    @override_settings(
        CUSD_PLUS_STOCKS_ENABLED=True,
        CUSD_PLUS_STOCK_BUY_BLOCKED_COUNTRIES=[],
    )
    def test_colombia_soft_buy_is_blocked_but_sell_is_not(self):
        user = SimpleNamespace(is_authenticated=True, id=34, phone_country='CO')
        info = SimpleNamespace(context=SimpleNamespace(
            user=user, META={'HTTP_CF_IPCOUNTRY': 'PE'}))
        query = Query()
        buy = query.resolve_gm_soft_quote(info, 'TSLAon', 'buy', '100')
        self.assertEqual(buy.error_code, 'TRADE_NOT_AVAILABLE')
        with mock.patch('cusd_plus.gm_api.soft_attestation',
                        side_effect=gm_api.GmApiError('SELL_REACHED', 'sell reached', 400)):
            sell = query.resolve_gm_soft_quote(info, 'TSLAon', 'sell', '100')
        self.assertEqual(sell.error_code, 'SELL_REACHED')

    @override_settings(CUSD_PLUS_STOCKS_ENABLED=True)
    def test_soft_sell_quote_is_blocked_by_ondo_issuer_country(self):
        user = SimpleNamespace(is_authenticated=True, id=36, phone_country='US')
        info = SimpleNamespace(context=SimpleNamespace(
            user=user, META={'HTTP_CF_IPCOUNTRY': 'CO'}))
        with mock.patch('cusd_plus.gm_api.soft_attestation') as soft:
            sell = Query().resolve_gm_soft_quote(info, 'TSLAon', 'sell', '100')
        self.assertEqual(sell.error_code, 'TRADE_NOT_AVAILABLE')
        soft.assert_not_called()

    @override_settings(
        CUSD_PLUS_STOCKS_ENABLED=True,
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS='0x' + '11' * 20,
        CUSD_PLUS_7702_ENABLED=True,
        CUSD_PLUS_BATCH_DELEGATE_ADDRESS='0x' + '22' * 20,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
        CUSD_PLUS_STOCK_BUY_BLOCKED_COUNTRIES=[],
    )
    def test_colombia_binding_buy_quote_is_blocked(self):
        user = SimpleNamespace(is_authenticated=True, id=35, phone_country='CO')
        info = SimpleNamespace(context=SimpleNamespace(
            user=user, META={'HTTP_CF_IPCOUNTRY': 'PE'}))
        account = SimpleNamespace(id=53, bsc_address='0x' + '33' * 20)
        with mock.patch('cusd_plus.schema._active_account', return_value=account), \
             mock.patch(
                 'users.jwt_context.get_jwt_business_context_with_validation',
                 return_value=None,
             ), \
             mock.patch('cusd_plus.gm_api.binding_attestation') as binding:
            result = PrepareGmTrade().mutate(
                info,
                request_id='blocked_buy_123456',
                symbol='TSLAon',
                side='buy',
                notional_value='100',
                duration='short',
            )
        self.assertEqual(result.quote.error_code, 'TRADE_NOT_AVAILABLE')
        binding.assert_not_called()

    @override_settings(
        CUSD_PLUS_STOCKS_ENABLED=True,
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS='0x' + '11' * 20,
        CUSD_PLUS_7702_ENABLED=True,
        CUSD_PLUS_BATCH_DELEGATE_ADDRESS='0x' + '22' * 20,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
    )
    def test_binding_sell_quote_is_blocked_by_ondo_issuer_country(self):
        user = SimpleNamespace(is_authenticated=True, id=37, phone_country='US')
        info = SimpleNamespace(context=SimpleNamespace(
            user=user, META={'HTTP_CF_IPCOUNTRY': 'CO'}))
        account = SimpleNamespace(id=54, bsc_address='0x' + '33' * 20)
        with mock.patch('cusd_plus.schema._active_account', return_value=account), \
             mock.patch(
                 'users.jwt_context.get_jwt_business_context_with_validation',
                 return_value=None,
             ), \
             mock.patch('cusd_plus.gm_api.binding_attestation') as binding:
            result = PrepareGmTrade().mutate(
                info,
                request_id='blocked_sell_123456',
                symbol='TSLAon',
                side='sell',
                notional_value='100',
                duration='short',
            )
        self.assertEqual(result.quote.error_code, 'TRADE_NOT_AVAILABLE')
        binding.assert_not_called()

    def test_quote_lock_does_not_delete_a_reacquired_lease(self):
        lock_key = 'gm:test:owner-safe-lock'
        release = _acquire_gm_quote_lock(cache, lock_key, 30)
        self.assertIsNotNone(release)
        cache.set(lock_key, 'new-owner', 30)
        release()
        self.assertEqual(cache.get(lock_key), 'new-owner')

    @override_settings(
        CUSD_PLUS_STOCKS_ENABLED=True,
        CUSD_PLUS_STOCK_TRADING_ENABLED=True,
        CUSD_PLUS_STOCK_ROUTER_ADDRESS='0x' + '11' * 20,
        CUSD_PLUS_7702_ENABLED=True,
        CUSD_PLUS_BATCH_DELEGATE_ADDRESS='0x' + '22' * 20,
        CUSD_PLUS_GM_TRADE_FEE_BPS=30,
        CUSD_PLUS_GM_MAX_TRADE_USD=100_000,
    )
    def test_binding_quote_retry_does_not_issue_while_same_id_is_in_flight(self):
        request_id = 'retry_key_123456'
        user = mock.Mock(is_authenticated=True, id=41, phone_country='CO')
        account = mock.Mock(id=52, bsc_address='0x' + '33' * 20)
        info = mock.Mock()
        info.context.user = user
        info.context.META = {}
        cache.set(f'gm_firm_attestation:41:52:{request_id}:lock', 1, 30)

        with mock.patch('cusd_plus.schema._active_account', return_value=account), \
             mock.patch(
                 'users.jwt_context.get_jwt_business_context_with_validation',
                 return_value=None,
             ), \
             mock.patch('cusd_plus.schema._stock_issuer_eligible', return_value=True), \
             mock.patch('cusd_plus.eligibility.check_stock_buy_eligibility', return_value=True), \
             mock.patch('cusd_plus.gm_api.binding_attestation') as binding:
            result = PrepareGmTrade().mutate(
                info,
                request_id=request_id,
                symbol='TSLAon',
                side='buy',
                notional_value='100',
                duration='short',
            )

        self.assertEqual(result.quote.error_code, 'QUOTE_IN_PROGRESS')
        binding.assert_not_called()
