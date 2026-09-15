"""Offline checks: preview cannot sign/broadcast and spend limits fail closed."""
import contextlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import prepare_infinia_test_funding as funding
from eth_abi import encode, decode


class FundingPreviewTests(unittest.TestCase):
    def run_preview(self, extra=(), pending=False, balance=10**18):
        destination = '0x1111111111111111111111111111111111111111'
        signer = Mock(address='0x2222222222222222222222222222222222222222')
        account = Mock()
        account.objects.filter.return_value.values.return_value = [
            {'id': 7, 'account_index': 0, 'bsc_address': destination}]
        settings = types.SimpleNamespace(BSC_CHAIN_ID=56, BSC_SPONSOR_ADDRESS=signer.address,
                                         BSC_RPC_URL='https://example.invalid')
        modules = {'django': types.SimpleNamespace(setup=lambda: None),
                   'django.conf': types.SimpleNamespace(settings=settings),
                   'users.models': types.SimpleNamespace(Account=account),
                   'blockchain.evm_kms_signer': types.SimpleNamespace(
                       get_bsc_sponsor_signer_from_settings=lambda: signer)}
        quote = 5 * 10**16

        def post(url, json, timeout):
            method, params = json['method'], json['params']
            if method == 'eth_chainId': result = '0x38'
            elif method == 'eth_getCode': result = '0x1234'
            elif method == 'eth_getTransactionCount': result = hex(4 if pending and params[1] == 'pending' else 3)
            elif method == 'eth_getBalance': result = hex(balance)
            elif method == 'eth_gasPrice': result = hex(100_000_000)
            elif method == 'eth_estimateGas': result = hex(150_000)
            elif method == 'eth_call':
                data = params[0]['data']
                if data == funding.calldata('WETH()'): result = encode(['address'], [funding.WBNB])
                elif data == funding.calldata('decimals()'): result = encode(['uint256'], [18])
                elif data.startswith(funding.calldata('balanceOf(address)', ['address'], [destination])[:10]):
                    result = encode(['uint256'], [0])
                else:
                    result = encode(['uint256[]'], [[quote, funding.AMOUNT]])
                    if 'value' in params[0]:
                        amount, path, to, deadline = decode(
                            ['uint256', 'address[]', 'address', 'uint256'], bytes.fromhex(data[10:]))
                        self.assertEqual(amount, 50 * 10**18)
                        self.assertEqual(to, destination)
                        self.assertEqual([p.lower() for p in path], [funding.WBNB.lower(), funding.USDT.lower()])
                        self.assertEqual(data[:10], '0xfb3bdb41')
                result = '0x' + result.hex()
            else:
                raise AssertionError(f'Unexpected or mutating RPC: {method}')
            return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'result': result})

        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(sys.modules, modules), \
             patch.object(funding, 'JOURNAL', Path(directory) / 'journal.json'), \
             patch.object(sys, 'argv', ['preview', *extra]), \
             patch.object(funding.requests, 'post', side_effect=post), \
             contextlib.redirect_stdout(io.StringIO()):
            try:
                funding.main()
            finally:
                signer.sign_transaction.assert_not_called()

    def test_default_preview_never_signs_or_broadcasts(self):
        self.run_preview()

    def test_low_cap_rejected(self):
        with self.assertRaisesRegex(SystemExit, 'exceeds the reviewed'):
            self.run_preview(['--max-bnb', '0.001'])

    def test_pending_sponsor_transaction_rejected(self):
        with self.assertRaisesRegex(SystemExit, 'pending transactions'):
            self.run_preview(pending=True)

    def test_reserve_preserved(self):
        with self.assertRaisesRegex(SystemExit, 'less than 0.005'):
            self.run_preview(balance=5 * 10**16)

    def test_changed_recipient_rejected(self):
        with self.assertRaisesRegex(SystemExit, 'reviewed address'):
            self.run_preview(['--expected-to', '0x3333333333333333333333333333333333333333'])


if __name__ == '__main__':
    unittest.main()
