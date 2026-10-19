"""Crypto & metals: catalog, relay policy, gates, history, holdings."""
import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from eth_abi import encode as abi_encode
from eth_utils import keccak

from cusd_plus import crypto_catalog, crypto_policy, sponsor_7702
from cusd_plus.crypto_policy import (
    SEL_CRYPTO_BUY, SEL_CRYPTO_SELL, CryptoPolicyError, decode_crypto_call,
)

ROUTER = '0x' + '5a' * 20
VAULT = '0x' + '11' * 20
CUSD = '0x' + '22' * 20
USER = '0x' + '44' * 20
USDT = crypto_catalog.USDT_BSC
BTCB = crypto_catalog.by_symbol('BTCB')
XAUT = crypto_catalog.by_symbol('XAUT', include_unlisted=True)
WAD = 10 ** 18


def _buy_data(*, dollar=0, amount=100 * WAD, min_usdt=99 * WAD, route=None, token=BTCB.address,
              min_token=10 ** 14, max_fee=90):
    route = route if route is not None else BTCB.route_bytes('buy')
    return '0x' + SEL_CRYPTO_BUY + abi_encode(
        crypto_policy.BUY_TYPES, [dollar, amount, min_usdt, route, token, min_token, max_fee]).hex()


def _sell_data(*, dollar=0, token=BTCB.address, amount=10 ** 15, route=None, min_usdt=99 * WAD,
               min_out=97 * WAD, max_fee=90):
    route = route if route is not None else BTCB.route_bytes('sell')
    return '0x' + SEL_CRYPTO_SELL + abi_encode(
        crypto_policy.SELL_TYPES, [dollar, token, amount, route, min_usdt, min_out, max_fee]).hex()


def _call(to, data):
    return {'to': to.lower(), 'value': '0', 'data': data.lower()}


def _approve(spender):
    return '0x' + sponsor_7702.SEL_APPROVE + spender[2:].rjust(64, '0') + 'f' * 64


class CatalogTests(SimpleTestCase):
    def test_featured_assets_listed_and_xaut_gated(self):
        symbols = {t.symbol for t in crypto_catalog.tokens()}
        self.assertTrue({'BTCB', 'ETH', 'WBNB'} <= symbols)
        self.assertNotIn('XAUT', symbols, 'XAUt stays unlisted until verified against tether.to')
        self.assertIsNotNone(XAUT)
        self.assertEqual(crypto_catalog.by_symbol('WBNB').ticker, 'BNB')

    def test_route_bytes_match_router_encoding(self):
        packed = bytes.fromhex(USDT[2:]) + (100).to_bytes(3, 'big') + bytes.fromhex(BTCB.address[2:])
        self.assertEqual(BTCB.route_bytes('buy'), abi_encode(['uint8', 'bytes'], [0, packed]))
        reverse = bytes.fromhex(BTCB.address[2:]) + (100).to_bytes(3, 'big') + bytes.fromhex(USDT[2:])
        self.assertEqual(BTCB.route_bytes('sell'), abi_encode(['uint8', 'bytes'], [0, reverse]))

    def test_parse_rejects_bad_routes(self):
        base = {'symbol': 'X', 'name': 'X', 'address': '0x' + '33' * 20, 'decimals': 18, 'category': 'crypto'}
        with self.assertRaises(ValueError):
            crypto_catalog._parse({**base, 'route': {'kind': 'v3', 'path': ['0x' + '33' * 20, 100, USDT]}})
        with self.assertRaises(ValueError):
            crypto_catalog._parse({**base, 'route': {'kind': 'v3', 'path': [USDT, 123, '0x' + '33' * 20]}})
        with self.assertRaises(ValueError):
            crypto_catalog._parse({**base, 'category': 'meme', 'route': {'kind': 'v2', 'path': [USDT, '0x' + '33' * 20]}})


@override_settings(CRYPTO_SWAP_ROUTER_ADDRESS=ROUTER, CRYPTO_TRADING_ENABLED=True, CRYPTO_MAX_SLIPPAGE_BPS=100)
class CryptoPolicyTests(SimpleTestCase):
    def setUp(self):
        patches = [
            mock.patch.object(crypto_policy, 'live_fee_bps', return_value=90),
            # $100 of cUSD+ exits to $99.10 net; $99.10 buys 1e15 BTC wei.
            mock.patch.object(crypto_policy, 'expected_exit_usdt', return_value=(100 * WAD, 991 * WAD // 10)),
            mock.patch('cusd_plus.crypto_prices.quote_exact_in',
                       side_effect=lambda token, side, amount: 10 ** 15 if side == 'buy' else 100 * WAD),
            # cUSD+ at pPlus 1: shares == net USDT entering.
            mock.patch.object(crypto_policy, '_expected_plus_shares', side_effect=lambda net: net),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _decode(self, data, **kw):
        return decode_crypto_call(_call(ROUTER, data), **kw)

    def test_honest_buy_accepted(self):
        action = self._decode(_buy_data(min_usdt=991 * WAD // 10, min_token=99 * 10 ** 13))
        self.assertEqual(action['kind'], 'crypto_buy')
        self.assertEqual(action['token'].symbol, 'BTCB')
        self.assertEqual(action['history_amount_wei'], 100 * WAD)

    def test_other_destination_is_not_ours(self):
        self.assertIsNone(decode_crypto_call(_call(VAULT, _buy_data())))

    def test_trading_switch_off_refuses(self):
        with override_settings(CRYPTO_TRADING_ENABLED=False):
            with self.assertRaisesMessage(CryptoPolicyError, 'crypto_trading_disabled'):
                self._decode(_buy_data())

    def test_route_must_be_the_catalog_route(self):
        bad = abi_encode(['uint8', 'bytes'], [0, bytes.fromhex(USDT[2:]) + (500).to_bytes(3, 'big')
                                              + bytes.fromhex(BTCB.address[2:])])
        with self.assertRaisesMessage(CryptoPolicyError, 'route_not_allowed'):
            self._decode(_buy_data(route=bad, min_usdt=99 * WAD, min_token=99 * 10 ** 13))

    def test_unlisted_token_cannot_be_bought_but_can_be_sold(self):
        with self.assertRaisesMessage(CryptoPolicyError, 'token_not_listed'):
            self._decode(_buy_data(token=XAUT.address, route=XAUT.route_bytes('buy')))
        action = self._decode(_sell_data(token=XAUT.address, route=XAUT.route_bytes('sell'),
                                         amount=2412, min_usdt=99 * WAD, min_out=98 * WAD))
        self.assertEqual(action['kind'], 'crypto_sell')

    def test_unknown_token_refused(self):
        with self.assertRaisesMessage(CryptoPolicyError, 'token_not_listed'):
            self._decode(_buy_data(token='0x' + '99' * 20))

    def test_fee_cap_must_equal_live_fee(self):
        for cap in (30, 89, 91):
            with self.assertRaisesMessage(CryptoPolicyError, 'bad_crypto_fee_cap'):
                self._decode(_buy_data(min_usdt=99 * WAD, min_token=99 * 10 ** 13, max_fee=cap))

    def test_buy_floors(self):
        # Above what the exit yields: the trade would just revert.
        with self.assertRaisesMessage(CryptoPolicyError, 'bad_crypto_floor'):
            self._decode(_buy_data(min_usdt=100 * WAD, min_token=99 * 10 ** 13))
        # Token floor weaker than 1% below the live quote.
        with self.assertRaisesMessage(CryptoPolicyError, 'bad_crypto_floor'):
            self._decode(_buy_data(min_usdt=99 * WAD, min_token=98 * 10 ** 13))
        with self.assertRaisesMessage(CryptoPolicyError, 'bad_crypto_floor'):
            self._decode(_buy_data(min_usdt=0))

    def test_sell_floors(self):
        with self.assertRaisesMessage(CryptoPolicyError, 'bad_crypto_floor'):
            self._decode(_sell_data(min_usdt=98 * WAD))
        # cUSD destination: the dollar floor is exact math, slippage only.
        # $99 USDT enters as $98.109 cUSD; 1% below is $97.128.
        self._decode(_sell_data(dollar=1, min_usdt=99 * WAD, min_out=98 * WAD))
        with self.assertRaisesMessage(CryptoPolicyError, 'bad_crypto_floor'):
            self._decode(_sell_data(dollar=1, min_usdt=99 * WAD, min_out=97 * WAD))
        with self.assertRaisesMessage(CryptoPolicyError, 'bad_crypto_floor'):
            self._decode(_sell_data(dollar=1, min_usdt=99 * WAD, min_out=90 * WAD))

    def test_dollar_plus_sell_floor_is_enforced(self):
        # Codex [P1]: a cUSD+ destination used to accept any positive floor.
        self._decode(_sell_data(dollar=0, min_usdt=99 * WAD, min_out=98 * WAD))
        with self.assertRaisesMessage(CryptoPolicyError, 'bad_crypto_floor'):
            self._decode(_sell_data(dollar=0, min_usdt=99 * WAD, min_out=1))

    def test_dollar_plus_sell_never_mints_below_redeem_floor(self):
        # Codex [P1]: ~$1 after the entry fee would strand a new position.
        with mock.patch('cusd_plus.crypto_prices.quote_exact_in', return_value=10 ** 18):
            with self.assertRaisesMessage(CryptoPolicyError, 'savings_mint_too_small'):
                self._decode(_sell_data(dollar=0, min_usdt=10 ** 18 - 1, min_out=1))
            # The same sale into cUSD (no redeem floor) is fine.
            self._decode(_sell_data(dollar=1, min_usdt=10 ** 18 - 1, min_out=982 * 10 ** 15))

    def test_history_decodes_after_a_catalog_route_change(self):
        old = abi_encode(['uint8', 'bytes'], [0, bytes.fromhex(USDT[2:]) + (500).to_bytes(3, 'big')
                                              + bytes.fromhex(BTCB.address[2:])])
        action = self._decode(_buy_data(route=old, min_usdt=1, min_token=1), historical=True)
        self.assertEqual(action['kind'], 'crypto_buy')

    def test_bad_dollar_and_noncanonical(self):
        with self.assertRaisesMessage(CryptoPolicyError, 'bad_dollar'):
            self._decode(_buy_data(dollar=2))
        with self.assertRaisesMessage(CryptoPolicyError, 'bad_calldata'):
            self._decode(_buy_data(min_usdt=99 * WAD, min_token=99 * 10 ** 13) + '00' * 32)

    def test_quote_failure_fails_closed(self):
        with mock.patch('cusd_plus.crypto_prices.quote_exact_in', side_effect=RuntimeError('rpc')):
            with self.assertRaisesMessage(CryptoPolicyError, 'crypto_quote_unavailable'):
                self._decode(_buy_data(min_usdt=99 * WAD))

    def test_historical_skips_live_checks(self):
        with override_settings(CRYPTO_TRADING_ENABLED=False):
            action = self._decode(_buy_data(dollar=1, max_fee=30, min_usdt=1, min_token=1), historical=True)
        self.assertEqual(action['history_amount_wei'], 100 * WAD)

    def test_classify_and_batch_shape(self):
        buy = _call(ROUTER, _buy_data(min_usdt=99 * WAD, min_token=99 * 10 ** 13))
        self.assertEqual(sponsor_7702.classify_calls_kind([_call(VAULT, _approve(ROUTER)), buy]), 'crypto_buy')
        self.assertEqual(sponsor_7702.classify_calls_kind([_call(ROUTER, _sell_data())]), 'crypto_sell')
        with mock.patch.object(sponsor_7702, '_vault_address', return_value=VAULT), \
             mock.patch.object(sponsor_7702, '_cusd_address', return_value=CUSD):
            sponsor_7702.validate_policy([_call(VAULT, _approve(ROUTER)), buy], None, USER)
            with self.assertRaisesMessage(sponsor_7702.PolicyError, 'bad_crypto_batch'):
                # Approving cUSD for a cUSD+ buy.
                sponsor_7702.validate_policy([_call(CUSD, _approve(ROUTER)), buy], None, USER)
            with self.assertRaisesMessage(sponsor_7702.PolicyError, 'approve_spender_not_allowed'):
                sponsor_7702.validate_policy([_call(VAULT, _approve(VAULT)), buy], None, USER)
            with self.assertRaisesMessage(sponsor_7702.PolicyError, 'bad_crypto_batch'):
                sponsor_7702.validate_policy(
                    [_call(VAULT, _approve(ROUTER)), _call(VAULT, _approve(ROUTER)), buy], None, USER)
            with self.assertRaisesMessage(sponsor_7702.PolicyError, 'multiple_crypto_trades'):
                sponsor_7702.validate_policy([buy, buy], None, USER)
            # A sell approves the token itself.
            sell = _call(ROUTER, _sell_data(min_out=98 * WAD))
            sponsor_7702.validate_policy([_call(BTCB.address, _approve(ROUTER)), sell], None, USER)


@override_settings(
    CRYPTO_ENABLED=True, CRYPTO_TRADING_ENABLED=True, CRYPTO_SWAP_ROUTER_ADDRESS=ROUTER,
    CUSD_PLUS_7702_ENABLED=True, CUSD_PLUS_BATCH_DELEGATE_ADDRESS='0x' + '77' * 20,
    CRYPTO_BLOCKED_COUNTRIES='', CRYPTO_BUY_ALLOWED_USER_IDS='',
)
class CryptoGateTests(TestCase):
    def setUp(self):
        from users.models import User

        self.user = User.objects.create(username='cryptogate', firebase_uid='cryptogate')

    def _gate(self, kind, country):
        from cusd_plus import crypto_risk

        with mock.patch('security.geo.phone_country_of', return_value=country):
            return crypto_risk.sponsor_gate(kind, self.user, {})

    def test_buy_needs_ack_then_passes_and_venezuela_is_allowed(self):
        from cusd_plus import crypto_risk

        self.assertEqual(self._gate('crypto_buy', 'VE'), crypto_risk.ACK_REQUIRED_CODE)
        crypto_risk.acknowledge(self.user)
        self.assertIsNone(self._gate('crypto_buy', 'VE'))
        self.assertIsNone(self._gate('crypto_buy', 'BR'), 'Ondo rules do not apply')

    def test_sanctioned_and_ops_blocklist_stop_buys_never_sells(self):
        from cusd_plus import crypto_risk

        crypto_risk.acknowledge(self.user)
        self.assertEqual(self._gate('crypto_buy', 'CU'), 'trade_not_available')
        self.assertIsNone(self._gate('crypto_sell', 'CU'))
        with override_settings(CRYPTO_BLOCKED_COUNTRIES='AR, co'):
            self.assertEqual(self._gate('crypto_buy', 'AR'), 'trade_not_available')
            self.assertEqual(self._gate('crypto_buy', 'CO'), 'trade_not_available')
            self.assertIsNone(self._gate('crypto_sell', 'AR'))

    def test_sell_into_dollar_plus_needs_savings_eligibility(self):
        # Codex [P2]: minting cUSD+ is an Ondo acquisition; cUSD stays open.
        with mock.patch('cusd_plus.eligibility.check_savings_mint_eligibility', return_value=False):
            self.assertEqual(
                self._gate_dollar('crypto_sell', 0), 'savings_not_available')
            self.assertIsNone(self._gate_dollar('crypto_sell', 1))
        with mock.patch('cusd_plus.eligibility.check_savings_mint_eligibility', return_value=True):
            self.assertIsNone(self._gate_dollar('crypto_sell', 0))

    def _gate_dollar(self, kind, dollar):
        from cusd_plus import crypto_risk

        with mock.patch('security.geo.phone_country_of', return_value='VE'):
            return crypto_risk.sponsor_gate(kind, self.user, {}, dollar=dollar)

    def test_canary_allowlist_and_kill_switches(self):
        from cusd_plus import crypto_risk

        crypto_risk.acknowledge(self.user)
        with override_settings(CRYPTO_BUY_ALLOWED_USER_IDS='999999'):
            self.assertEqual(self._gate('crypto_buy', 'VE'), 'trade_not_available')
        with override_settings(CRYPTO_BUY_ALLOWED_USER_IDS=str(self.user.id)):
            self.assertIsNone(self._gate('crypto_buy', 'VE'))
        with override_settings(CRYPTO_BUY_ENABLED=False):
            self.assertEqual(self._gate('crypto_buy', 'VE'), 'trade_not_available')
            self.assertIsNone(self._gate('crypto_sell', 'VE'))
        with override_settings(CRYPTO_TRADING_ENABLED=False):
            self.assertEqual(self._gate('crypto_sell', 'VE'), 'trade_not_available')


@override_settings(CRYPTO_SWAP_ROUTER_ADDRESS=ROUTER, CUSD_VAULT_ADDRESS=CUSD)
class CryptoHistoryAmountTests(SimpleTestCase):
    def _receipt(self, kind, usdt, fee_event_sig, fee, extra_topics=()):
        sig = ('CryptoBought(address,address,uint8,uint256,uint256,uint256)' if kind == 'crypto_buy'
               else 'CryptoSold(address,address,uint8,uint256,uint256,uint256)')
        return {'logs': [
            {'address': ROUTER,
             'topics': ['0x' + keccak(text=sig).hex(), '0x' + USER[2:].rjust(64, '0'),
                        '0x' + BTCB.address[2:].rjust(64, '0')],
             'data': '0x' + abi_encode(['uint256'] * 4, [0, 100 * WAD, usdt, 10 ** 15]).hex()},
            {'address': CUSD,
             'topics': ['0x' + keccak(text=fee_event_sig).hex(), *extra_topics],
             'data': '0x' + abi_encode(['uint256'] * 4, [10 ** 20, fee, 10 ** 20 - fee, 90]).hex()},
        ]}

    def test_buy_debit_is_usdt_spent_plus_exit_fee(self):
        from cusd_plus.unified import _crypto_event_amount

        receipt = self._receipt('crypto_buy', 991 * WAD // 10,
                                'SavingsExitSettled(address,uint256,uint256,uint256,uint256)', 9 * 10 ** 17,
                                ['0x' + ROUTER[2:].rjust(64, '0')])
        self.assertEqual(_crypto_event_amount(receipt, 'crypto_buy', USER, ROUTER, BTCB.address), 100 * WAD)

    def test_sell_credit_is_proceeds_minus_entry_fee(self):
        from cusd_plus.unified import _crypto_event_amount

        receipt = self._receipt('crypto_sell', 100 * WAD,
                                'MintedWithFee(address,address,uint256,uint256,uint256,uint256)', 9 * 10 ** 17,
                                ['0x' + ROUTER[2:].rjust(64, '0'), '0x' + USER[2:].rjust(64, '0')])
        self.assertEqual(_crypto_event_amount(receipt, 'crypto_sell', USER, ROUTER, BTCB.address),
                         991 * WAD // 10)

    def test_settlement_carries_exact_units(self):
        from cusd_plus.unified import _crypto_event_settlement

        buy = self._receipt('crypto_buy', 991 * WAD // 10,
                            'SavingsExitSettled(address,uint256,uint256,uint256,uint256)', 9 * 10 ** 17,
                            ['0x' + ROUTER[2:].rjust(64, '0')])
        self.assertEqual(_crypto_event_settlement(buy, 'crypto_buy', USER, ROUTER, BTCB.address),
                         {'usd_wei': 100 * WAD, 'units': 10 ** 15})
        sell = self._receipt('crypto_sell', 100 * WAD,
                             'MintedWithFee(address,address,uint256,uint256,uint256,uint256)', 9 * 10 ** 17,
                             ['0x' + ROUTER[2:].rjust(64, '0'), '0x' + USER[2:].rjust(64, '0')])
        # Sell: the units the user gave up (amountIn), not the router's output.
        self.assertEqual(_crypto_event_settlement(sell, 'crypto_sell', USER, ROUTER, BTCB.address)['units'],
                         100 * WAD)

    def test_missing_router_event_is_unknown(self):
        from cusd_plus.unified import _crypto_event_amount

        self.assertIsNone(_crypto_event_amount({'logs': []}, 'crypto_buy', USER, ROUTER, BTCB.address))


class CryptoHoldingsScanTests(SimpleTestCase):
    def test_scan_reads_every_token_exactly(self):
        from cusd_plus import crypto_holdings

        universe = crypto_catalog.tokens(include_unlisted=True)
        results = [(True, (12345).to_bytes(32, 'big'))] + [
            (True, (7 if t.symbol == 'BTCB' else 0).to_bytes(32, 'big')) for t in universe
        ]
        encoded = '0x' + abi_encode(['(bool,bytes)[]'], [results]).hex()
        with mock.patch.object(crypto_holdings.vault, '_rpc', return_value=encoded):
            held, block = crypto_holdings._scan(USER)
        self.assertEqual(held, {'BTCB': '7'})
        self.assertEqual(block, 12345)

    def test_scan_refuses_partial_answers(self):
        from cusd_plus import crypto_holdings

        universe = crypto_catalog.tokens(include_unlisted=True)
        results = [(True, (1).to_bytes(32, 'big'))] + [(False, b'')] + [
            (True, (0).to_bytes(32, 'big')) for _ in universe[1:]
        ]
        encoded = '0x' + abi_encode(['(bool,bytes)[]'], [results]).hex()
        with mock.patch.object(crypto_holdings.vault, '_rpc', return_value=encoded):
            with self.assertRaises(RuntimeError):
                crypto_holdings._scan(USER)


class CryptoHoldingsStoreTests(TestCase):
    def test_invalidation_during_write_leaves_row_stale(self):
        # Codex [P2]: a scan stored while a swap invalidated must not stay fresh.
        from blockchain.models import CryptoHoldings
        from cusd_plus import crypto_holdings

        def scan(_addr):
            crypto_holdings.invalidate_holdings(USER)  # lands mid-read
            return {'BTCB': '5'}, 100

        with mock.patch.object(crypto_holdings, '_scan', side_effect=scan), \
             mock.patch.object(crypto_holdings, '_storable', return_value=True):
            self.assertEqual(crypto_holdings.holdings_units(USER), {'BTCB': 5})
        self.assertTrue(CryptoHoldings.objects.get(bsc_address=USER).is_stale)


class CryptoReconcilerSkipTests(SimpleTestCase):
    def test_crypto_receipts_never_become_conversions(self):
        from cusd_plus.tasks import _reconcile_cusd_fee_event

        for kind in ('crypto_buy', 'crypto_sell'):
            batch = SimpleNamespace(kind=kind, user_bsc_address=USER, tx_hash='0x' + 'ab' * 32)
            with mock.patch('cusd_plus.tasks._cusd_fee_events', side_effect=AssertionError('must not read')):
                self.assertEqual(_reconcile_cusd_fee_event(batch=batch, receipt={}), [])


class SharedNonceLockGuardTests(SimpleTestCase):
    """Sponsor-signing ops commands may broadcast only where the relay's
    nonce lock is shared: Redis AND a fresh production heartbeat in it."""

    REDIS = {'default': {'BACKEND': 'django_redis.cache.RedisCache'}}

    def _check(self, caches, heartbeat):
        from cusd_plus import sponsor_7702

        store = {sponsor_7702.RELAY_CACHE_HEARTBEAT_KEY: {'host': 'prod'}} if heartbeat else {}
        with mock.patch.object(sponsor_7702.settings, 'CACHES', caches), \
             mock.patch.object(sponsor_7702, 'cache', mock.Mock(get=store.get)):
            sponsor_7702.require_shared_nonce_lock()

    def test_process_local_cache_refused(self):
        from cusd_plus import sponsor_7702

        with self.assertRaises(sponsor_7702.PolicyError):
            self._check({'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}, True)

    def test_redis_without_relay_heartbeat_refused(self):
        from cusd_plus import sponsor_7702

        with self.assertRaises(sponsor_7702.PolicyError):
            self._check(self.REDIS, False)

    def test_shared_redis_with_heartbeat_allowed(self):
        self._check(self.REDIS, True)
