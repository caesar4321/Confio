"""Leveraged and inverse funds: their own list, and one confirmation per person
before the first purchase (asked by the app, enforced by PrepareGmTrade)."""
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from blockchain.models import StockRiskAcknowledgement
from cusd_plus import complex_products
from cusd_plus.schema import AcknowledgeGmComplexProducts, PrepareGmTrade, Query

TRADING = dict(
    CUSD_PLUS_STOCKS_ENABLED=True,
    CUSD_PLUS_STOCK_TRADING_ENABLED=True,
    CUSD_PLUS_STOCK_ROUTER_ADDRESS='0x' + '11' * 20,
    CUSD_PLUS_7702_ENABLED=True,
    CUSD_PLUS_BATCH_DELEGATE_ADDRESS='0x' + '22' * 20,
    CUSD_PLUS_GM_TRADE_FEE_BPS=30,
)


class ComplexProductListTests(TestCase):
    def test_curated_factors(self):
        self.assertEqual(complex_products.factors(),
                         {'TQQQ': 3, 'SQQQ': -3, 'SOXL': 3, 'SOXS': -3, 'PSQ': -1})

    def test_symbol_lookup(self):
        self.assertEqual(complex_products.factor_for_symbol('TQQQon'), 3)
        self.assertEqual(complex_products.factor_for_symbol('PSQon'), -1)
        self.assertIsNone(complex_products.factor_for_symbol('TSLAon'))
        self.assertIsNone(complex_products.factor_for_symbol(''))

    def test_every_listed_fund_carries_a_warning(self):
        from cusd_plus.schema import _gm_highlights
        warnings = _gm_highlights()['warnings']
        for ticker in complex_products.factors():
            self.assertIn(ticker, warnings)


class AcknowledgementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='lev_user', email='lev@example.com')

    def _info(self, user=None):
        return SimpleNamespace(context=SimpleNamespace(user=user or self.user, META={}))

    def test_acknowledge_records_the_current_version(self):
        self.assertFalse(complex_products.acknowledged(self.user))
        result = AcknowledgeGmComplexProducts().mutate(self._info(), version=complex_products.ACK_VERSION)
        self.assertTrue(result.success)
        self.assertTrue(complex_products.acknowledged(self.user))
        # Idempotent: a second tap keeps one row.
        AcknowledgeGmComplexProducts().mutate(self._info(), version=complex_products.ACK_VERSION)
        self.assertEqual(StockRiskAcknowledgement.objects.filter(user=self.user).count(), 1)

    def test_outdated_disclosure_does_not_count(self):
        result = AcknowledgeGmComplexProducts().mutate(self._info(), version=complex_products.ACK_VERSION - 1)
        self.assertFalse(result.success)
        self.assertEqual(result.error, 'OUTDATED_DISCLOSURE')
        self.assertFalse(complex_products.acknowledged(self.user))

    def test_raised_version_asks_again(self):
        StockRiskAcknowledgement.objects.create(user=self.user, version=complex_products.ACK_VERSION)
        with mock.patch.object(complex_products, 'ACK_VERSION', complex_products.ACK_VERSION + 1):
            self.assertFalse(complex_products.acknowledged(self.user))

    def test_anonymous_cannot_acknowledge(self):
        result = AcknowledgeGmComplexProducts().mutate(self._info(SimpleNamespace(is_authenticated=False)), version=1)
        self.assertFalse(result.success)

    def test_query_reports_products_and_state(self):
        with mock.patch('cusd_plus.schema._stock_surfaces_enabled', return_value=True):
            before = Query().resolve_gm_complex_products(self._info())
            complex_products.acknowledge(self.user)
            after = Query().resolve_gm_complex_products(self._info())
        self.assertFalse(before.acknowledged)
        self.assertTrue(after.acknowledged)
        self.assertEqual(before.version, complex_products.ACK_VERSION)
        self.assertEqual({p.ticker: p.factor for p in before.products}['SQQQ'], -3)
        self.assertEqual(before.title, complex_products.DISCLOSURE_TITLE)
        self.assertEqual(len(before.points), len(complex_products.DISCLOSURE_POINTS))

    def test_query_hidden_where_stocks_are_hidden(self):
        with mock.patch('cusd_plus.schema._stock_surfaces_enabled', return_value=False):
            self.assertIsNone(Query().resolve_gm_complex_products(self._info()))


@override_settings(**TRADING)
class PurchaseGateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='lev_buyer', email='buyer@example.com')
        self.account = SimpleNamespace(id=7, bsc_address='0x' + '33' * 20)

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _prepare(self, symbol, side='buy'):
        info = SimpleNamespace(context=SimpleNamespace(user=self.user, META={}))
        with mock.patch('cusd_plus.schema._active_account', return_value=self.account), \
             mock.patch('users.jwt_context.get_jwt_business_context_with_validation', return_value=None), \
             mock.patch('cusd_plus.schema._stock_issuer_eligible', return_value=True), \
             mock.patch('cusd_plus.schema._stock_buy_enabled', return_value=True), \
             mock.patch('cusd_plus.gm_api.binding_attestation', side_effect=RuntimeError('upstream')) as binding:
            result = PrepareGmTrade().mutate(info, request_id=f'req_{symbol}_{side}_123456',
                                             symbol=symbol, side=side, notional_value='10')
        return result.quote, binding

    def test_leveraged_buy_needs_the_acknowledgement(self):
        quote, binding = self._prepare('TQQQon')
        self.assertFalse(quote.success)
        self.assertEqual(quote.error_code, complex_products.ACK_REQUIRED_CODE)
        self.assertEqual(quote.error_message, complex_products.ACK_REQUIRED_MESSAGE)
        binding.assert_not_called()

    def test_acknowledged_buy_reaches_ondo(self):
        complex_products.acknowledge(self.user)
        quote, binding = self._prepare('SQQQon')
        binding.assert_called_once()
        self.assertNotEqual(quote.error_code, complex_products.ACK_REQUIRED_CODE)

    def test_selling_never_asks(self):
        quote, binding = self._prepare('SOXLon', side='sell')
        binding.assert_called_once()
        self.assertNotEqual(quote.error_code, complex_products.ACK_REQUIRED_CODE)

    def test_plain_stock_never_asks(self):
        quote, binding = self._prepare('TSLAon')
        binding.assert_called_once()
        self.assertNotEqual(quote.error_code, complex_products.ACK_REQUIRED_CODE)


class SponsoredBatchGateTests(TestCase):
    """A quote is not bound to the person who requested it, so the sponsored
    batch checks the fund by its on-chain address too."""
    TQQQ = '0xe42cfb20e00912409b77a602b5bdcff3c7acc5f4'
    TSLA_LIKE = '0x' + 'ab' * 20

    def _calls(self, *actions):
        return [{'to': '0xrouter', 'data': f'0x{i}'} for i, _ in enumerate(actions)], list(actions)

    def _buys(self, *actions):
        calls, decoded = self._calls(*actions)
        with mock.patch('cusd_plus.sponsor_7702._decode_stock_call', side_effect=decoded):
            return complex_products.buys_complex_product(calls)

    def test_buy_of_a_leveraged_fund_is_recognised_by_address(self):
        self.assertTrue(self._buys({'kind': 'stock_buy', 'asset': self.TQQQ}))

    def test_selling_or_a_plain_stock_is_not(self):
        self.assertFalse(self._buys({'kind': 'stock_sell', 'asset': self.TQQQ}))
        self.assertFalse(self._buys({'kind': 'stock_buy', 'asset': self.TSLA_LIKE}))
        self.assertFalse(self._buys(None))  # not a router call at all

    def test_undecodable_router_call_fails_closed(self):
        from cusd_plus.sponsor_7702 import PolicyError
        with mock.patch('cusd_plus.sponsor_7702._decode_stock_call', side_effect=PolicyError('bad_calldata')):
            self.assertTrue(complex_products.buys_complex_product([{'to': '0xrouter', 'data': '0x'}]))
