from copy import deepcopy
from decimal import Decimal
from unittest import mock

import requests
from django.test import SimpleTestCase

from payment_accounts.allbridge_next import NextClient, NextError, TOKENS, to_units


SOURCE = '0x' + '11' * 20
DESTINATION = '0x' + '22' * 20


def route(source='BSC:USDT', destination='POL:USDC', amount='10000000000000000000'):
    return {
        'sourceTokenId': source, 'destinationTokenId': destination,
        'amount': amount, 'amountOut': '9900000', 'messenger': 'cctp',
        'relayerFees': [{'tokenId': 'native', 'amount': '100'}],
    }


class NextClientTests(SimpleTestCase):
    def setUp(self):
        self.session = mock.Mock()
        self.client = NextClient(self.session)

    def responses(self, *payloads):
        self.session.request.side_effect = [
            mock.Mock(status_code=200, json=mock.Mock(return_value=p)) for p in payloads
        ]

    @staticmethod
    def tokens():
        return [dict(tokenId=k, chain=k.split(':')[0], address=v[0], decimals=v[1])
                for k, v in TOKENS.items()]

    def test_exact_precision_above_default_decimal_context(self):
        value = Decimal('1234567890123456789.123456789012345678')
        self.assertEqual(to_units(value, 'BSC:USDT'), '1234567890123456789123456789012345678')
        self.assertEqual(to_units('1.000001', 'POL:USDC'), '1000001')

    def test_rejects_non_finite_negative_and_excess_precision(self):
        for value in ['NaN', 'Infinity', '-1', '0', '1.0000001', '1e10000']:
            with self.subTest(value=value), self.assertRaises(NextError):
                to_units(value, 'POL:USDC')

    def test_quotes_both_directions_with_integer_units(self):
        for source, destination, amount in [
            ('BSC:USDT', 'POL:USDC', '10000000000000000000'),
            ('POL:USDC', 'BSC:USDT', '10000000'),
        ]:
            self.responses(self.tokens(), [route(source, destination, amount)])
            result = self.client.quote(source, destination, amount)
            self.assertEqual(result[0]['amount'], amount)
            self.assertEqual(self.session.request.call_args.kwargs['json']['amount'], amount)
            self.assertFalse(self.session.request.call_args.kwargs['allow_redirects'])

    def test_rejects_token_substitution_before_requesting_quote(self):
        tokens = self.tokens()
        tokens[1]['address'] = SOURCE
        self.responses(tokens)
        with self.assertRaisesRegex(NextError, 'metadata'):
            self.client.quote('BSC:USDT', 'POL:USDC', '10')
        self.assertEqual(self.session.request.call_count, 1)

    def test_rejects_mismatched_or_malformed_quote(self):
        for change in [{'amount': '1'}, {'destinationTokenId': 'BSC:USDT'},
                       {'amountOut': '-5'}, {'relayerFees': []}]:
            self.responses(self.tokens(), [dict(route(), **change)])
            with self.assertRaises(NextError):
                self.client.quote('BSC:USDT', 'POL:USDC', route()['amount'])

    def test_build_preserves_independent_recipient_and_selected_fee(self):
        quoted = route()
        quoted['sourceSwap'] = 'source-dex'
        quoted['relayerFees'].append({'tokenId': 'BSC:USDT', 'amount': '200'})
        original = deepcopy(quoted)
        self.responses({'amountOut': '9900000', 'amountMin': '9800000',
                        'tx': {'contractAddress': SOURCE, 'value': '0', 'tx': '0x12345678'}})
        self.client.build(quoted, source_address=SOURCE, destination_address=DESTINATION, fee_index=1)
        call = self.session.request.call_args
        self.assertTrue(call.args[1].endswith('/tx/create'))
        body = call.kwargs['json']
        self.assertEqual(body['sourceAddress'], SOURCE)
        self.assertEqual(body['destinationAddress'], DESTINATION)
        self.assertEqual(body['relayerFee'], quoted['relayerFees'][1])
        self.assertEqual(body['amountOut'], quoted['amountOut'])
        self.assertEqual(body['sourceSwap'], 'source-dex')
        self.assertNotIn('relayerFees', body)
        self.assertEqual(quoted, original)

    def test_near_intents_refunds_source_not_provider(self):
        quoted = dict(route(), messenger='near-intents', relayerFees=[])
        self.responses({'amountOut': '9900000', 'amountMin': '9800000',
                        'tx': {'contractAddress': SOURCE, 'value': '0'}})
        self.client.build(quoted, source_address=SOURCE, destination_address=DESTINATION)
        self.assertEqual(self.session.request.call_args.kwargs['json']['refundTo'], SOURCE)

    def test_api_failure_does_not_expose_response_body(self):
        self.session.request.return_value = mock.Mock(status_code=500)
        with self.assertRaisesRegex(NextError, '^NEXT API request failed$'):
            self.client.verify_tokens()

    def test_timeout_fails_without_retrying(self):
        self.session.request.side_effect = requests.Timeout()
        with self.assertRaises(NextError):
            self.client.verify_tokens()
        self.assertEqual(self.session.request.call_count, 1)
