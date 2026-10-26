"""exitHeldTokens: the addresses the app remembers for the Emergency Exit."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from cusd_plus.schema import Query

ADDR = '0x' + 'a1' * 20


def _info():
    return SimpleNamespace(context=SimpleNamespace(user=SimpleNamespace(is_authenticated=True), META={}))


class ExitHeldTokensTests(SimpleTestCase):
    def _resolve(self, ondo, crypto, registry):
        account = SimpleNamespace(bsc_address=ADDR)
        token = SimpleNamespace(symbol='BTCB', address='0x7130D2A12B9BCBFAE4F2634D864A1EE1CE3EAD9C')
        with mock.patch('cusd_plus.schema._active_account', return_value=account), \
                mock.patch('cusd_plus.gm_holdings.holdings_units', return_value=ondo), \
                mock.patch('cusd_plus.gm_holdings.registry', return_value=registry), \
                mock.patch('cusd_plus.crypto_holdings.holdings_units', return_value=crypto), \
                mock.patch('cusd_plus.crypto_catalog.tokens', return_value=[token]):
            return Query().resolve_exit_held_tokens(_info())

    def test_lists_held_ondo_and_crypto_with_addresses(self):
        rows = self._resolve({'NEWon': 1.5}, {'BTCB': 10}, {'NEWon': {'address': '0xABCDEF' + '0' * 34}})
        self.assertEqual([(r.symbol, r.address, r.kind) for r in rows], [
            ('NEWon', '0xabcdef' + '0' * 34, 'ondo'),
            ('BTCB', '0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c', 'crypto'),
        ])

    def test_unknown_is_not_empty(self):
        self.assertIsNone(self._resolve(None, {}, {}))
        self.assertEqual(self._resolve({}, {}, {}), [])
