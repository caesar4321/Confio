"""
SubmitBscTransaction's PancakeSwap-router path: the relay must accept ONLY
swapExactETHForTokens to the router, only while the master gate is on, and
must ledger every accepted swap (the BnbAutoConvert row is what makes
outbound BNB a deterministic farming signal).

Runs without a database (ledger write is mocked):
    myvenv/bin/python manage.py test cusd_plus.tests.test_bnb_autoconvert_relay
"""
from unittest import mock

import rlp
from django.test import SimpleTestCase, override_settings

from cusd_plus.schema import SubmitBscTransaction

ROUTER = '0x10ED43C718714eb63d5aA57B78B54704E256024E'
VAULT = '0x3C29417eb4314155e63d4C7D4507852b87763Ed1'
SWAP_SELECTOR = bytes.fromhex('7ff36ab5')  # swapExactETHForTokens
CHAIN_ID = 56


def _legacy_tx(to: str, value: int, data: bytes) -> str:
    """Minimal RLP legacy tx the relay's decoder accepts (sig unverified)."""
    v = 35 + 2 * CHAIN_ID
    fields = [
        b'\x01',                          # nonce
        b'\x3b\x9a\xca\x00',              # gasPrice 1 gwei
        b'\x03\xd0\x90',                  # gas 250k
        bytes.fromhex(to[2:]),            # to
        value.to_bytes((value.bit_length() + 7) // 8 or 1, 'big'),
        data,
        v.to_bytes(2, 'big'),
        b'\x01', b'\x01',                 # r, s (decode-only path)
    ]
    return '0x' + rlp.encode(fields).hex()


class _Info:
    class context:
        user = mock.Mock(is_authenticated=True, id=1)


@override_settings(
    CUSD_PLUS_PANCAKE_ROUTER=ROUTER,
    CUSD_PLUS_VAULT_ADDRESS=VAULT,
    CUSD_PLUS_BNB_AUTOCONVERT_ENABLED=True,
)
class RelayRouterGuardTests(SimpleTestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # reset the relay rate limiter between tests

    def _submit(self, raw):
        return SubmitBscTransaction.mutate(None, _Info(), raw)

    def test_swap_to_router_is_relayed_and_ledgered(self):
        raw = _legacy_tx(ROUTER, 10 ** 16, SWAP_SELECTOR + b'\x00' * 128)
        with mock.patch('cusd_plus.tasks._rpc', return_value='0xabc') as rpc, \
             mock.patch('cusd_plus.models.BnbAutoConvert.objects') as ledger:
            res = self._submit(raw)
        self.assertTrue(res.success, res.error)
        rpc.assert_called_once()
        ledger.create.assert_called_once_with(
            user=_Info.context.user, value_wei=str(10 ** 16), tx_hash='0xabc')

    def test_router_with_other_selector_is_rejected(self):
        transfer = bytes.fromhex('a9059cbb') + b'\x00' * 64  # ERC-20 transfer
        raw = _legacy_tx(ROUTER, 0, transfer)
        with mock.patch('cusd_plus.tasks._rpc') as rpc:
            res = self._submit(raw)
        self.assertFalse(res.success)
        self.assertEqual(res.error, 'selector_not_allowed')
        rpc.assert_not_called()

    @override_settings(CUSD_PLUS_BNB_AUTOCONVERT_ENABLED=False)
    def test_master_gate_off_rejects_router(self):
        raw = _legacy_tx(ROUTER, 10 ** 16, SWAP_SELECTOR + b'\x00' * 128)
        res = self._submit(raw)
        self.assertFalse(res.success)
        self.assertEqual(res.error, 'destination_not_allowed')

    def test_vault_destination_still_relays_without_selector_check(self):
        raw = _legacy_tx(VAULT, 0, bytes.fromhex('deadbeef'))
        with mock.patch('cusd_plus.tasks._rpc', return_value='0xdef'), \
             mock.patch('cusd_plus.models.BnbAutoConvert.objects') as ledger:
            res = self._submit(raw)
        self.assertTrue(res.success, res.error)
        ledger.create.assert_not_called()  # vault txs are not BNB converts

    def test_unknown_destination_still_rejected(self):
        raw = _legacy_tx('0x' + 'ab' * 20, 10 ** 16, SWAP_SELECTOR + b'\x00' * 128)
        res = self._submit(raw)
        self.assertFalse(res.success)
        self.assertEqual(res.error, 'destination_not_allowed')


USDT = '0x55d398326f99059fF775485246999027B3197955'
TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
USER_ADDR = '0x' + 'aa' * 20
TX = '0x' + 'cd' * 32


def _usdt_log(to_addr: str, units: int, log_index: str = '0x2'):
    return {
        'address': USDT,
        'topics': [TRANSFER, '0x' + '00' * 32, '0x' + '00' * 12 + to_addr[2:]],
        'data': hex(units),
        'logIndex': log_index,
    }


class RegisterArrivalTests(SimpleTestCase):
    """The foreground fast-path must mirror the beat scanner's guards
    exactly: registered addresses only, deposit floor, in-flight skip."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _mutate(self, receipt, registered=None, awaited=()):
        from cusd_plus.schema import RegisterBscUsdtArrival
        registered = registered if registered is not None else {USER_ADDR: 7}
        in_flight = mock.MagicMock()
        in_flight.exclude.return_value.values_list.return_value = list(awaited)
        with mock.patch('cusd_plus.tasks._rpc', return_value=receipt), \
             mock.patch('cusd_plus.tasks._registered_bsc_addresses', return_value=registered), \
             mock.patch('cusd_plus.tasks._record_inbound_deposit') as rec, \
             mock.patch('cusd_plus.models.CusdPlusConversion.objects') as conv:
            conv.filter.return_value = in_flight
            res = RegisterBscUsdtArrival.mutate(None, _Info(), TX)
        return res, rec

    def test_registered_arrival_is_recorded(self):
        receipt = {'status': '0x1', 'logs': [_usdt_log(USER_ADDR, 5 * 10 ** 18)]}
        res, rec = self._mutate(receipt)
        self.assertTrue(res.success, res.error)
        self.assertTrue(res.recorded)
        rec.assert_called_once()
        kwargs = rec.call_args.kwargs
        self.assertEqual(kwargs['account_id'], 7)
        self.assertEqual(kwargs['to_addr'], USER_ADDR)
        self.assertEqual(str(kwargs['amount_usd']), '5.000000')
        self.assertEqual(kwargs['tx_ref'], f'{TX}:2')

    def test_unregistered_address_not_recorded(self):
        receipt = {'status': '0x1', 'logs': [_usdt_log('0x' + 'bb' * 20, 5 * 10 ** 18)]}
        res, rec = self._mutate(receipt)
        self.assertTrue(res.success)
        self.assertFalse(res.recorded)
        rec.assert_not_called()

    def test_below_floor_arrival_not_recorded(self):
        receipt = {'status': '0x1', 'logs': [_usdt_log(USER_ADDR, 10 ** 17)]}  # $0.10
        res, rec = self._mutate(receipt)
        self.assertTrue(res.success)
        self.assertFalse(res.recorded)
        rec.assert_not_called()

    def test_in_flight_address_left_for_beat_scanner(self):
        receipt = {'status': '0x1', 'logs': [_usdt_log(USER_ADDR, 5 * 10 ** 18)]}
        res, rec = self._mutate(receipt, awaited=[USER_ADDR])
        self.assertTrue(res.success)
        self.assertFalse(res.recorded)
        rec.assert_not_called()

    def test_reverted_tx_rejected(self):
        res, rec = self._mutate({'status': '0x0', 'logs': []})
        self.assertFalse(res.success)
        self.assertEqual(res.error, 'tx_reverted')

    def test_unmined_tx_rejected(self):
        res, rec = self._mutate(None)
        self.assertFalse(res.success)
        self.assertEqual(res.error, 'not_mined')

    def test_bad_hash_rejected(self):
        from cusd_plus.schema import RegisterBscUsdtArrival
        res = RegisterBscUsdtArrival.mutate(None, _Info(), '0x1234')
        self.assertFalse(res.success)
        self.assertEqual(res.error, 'bad_tx_hash')
