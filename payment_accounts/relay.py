"""Relay quote boundary. No signing, broadcasting, or automatic retries.

Amounts are base units. Quote details are checked against caller-owned terms,
not against other fields supplied by the same response. Execution integration
must additionally validate the selected funding mechanism.
"""
from copy import deepcopy
import re
import time

import requests

from .allbridge_next import NextError, TOKENS, address, uint


CHAINS = {'BSC:USDT': 56, 'POL:USDC': 137}
PROTOCOL_CHAINS = {'BSC:USDT': 'bnb', 'POL:USDC': 'polygon'}


class RelayError(NextError):
    """Safe provider error compatible with existing bridge error handling."""

    def __init__(self, message, *, code='', status_code=None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class RelayClient:
    BASE_URL = 'https://api.relay.link'

    def __init__(self, session=None):
        self.session = session or requests.Session()

    def _request(self, method, path, *, body=None, params=None):
        try:
            response = self.session.request(
                method, self.BASE_URL + path, json=body, params=params,
                timeout=(5, 20), allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RelayError('Relay is temporarily unavailable') from exc
        if not 200 <= response.status_code < 300:
            # Do not expose arbitrary upstream bodies, addresses, or HTML.
            code = ''
            try:
                payload = response.json()
                value = payload.get('errorCode', payload.get('error', payload.get('code', '')))
                if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_]{1,80}', value):
                    code = value
            except (ValueError, AttributeError):
                pass
            message = {
                'AMOUNT_TOO_LOW': 'The amount is too low for this Relay route',
                'amount_too_low': 'The amount is too low for this Relay route',
                'NO_QUOTES': 'No Relay route is available for this amount',
                'INSUFFICIENT_LIQUIDITY': 'Relay has insufficient liquidity for this route',
            }.get(code, 'Relay request failed' + (f' ({code})' if code else ''))
            raise RelayError(message, code=code, status_code=response.status_code)
        try:
            result = response.json()
        except ValueError as exc:
            raise RelayError('Relay returned invalid JSON') from exc
        if not isinstance(result, dict):
            raise RelayError('Relay returned an invalid response')
        return result

    def quote(self, source, destination, amount, *, source_address,
              destination_address, deposit_address=False):
        if {source, destination} != set(TOKENS):
            raise RelayError('Only BSC USDT and Polygon USDC are supported')
        uint(amount, positive=True)
        sender, recipient = address(source_address), address(destination_address)
        body = {
            'user': sender, 'recipient': recipient, 'refundTo': sender,
            'originChainId': CHAINS[source], 'destinationChainId': CHAINS[destination],
            'originCurrency': TOKENS[source][0], 'destinationCurrency': TOKENS[destination][0],
            'amount': amount, 'tradeType': 'EXACT_INPUT', 'slippageTolerance': '50',
            'includeProtocolData': True,
        }
        if deposit_address:
            # /quote/v2 ignores strict; EXACT_INPUT deposit addresses can be
            # requoted on deposit. Never claim strict guarantees from this flag.
            body['useDepositAddress'] = True
        result = self._request('POST', '/quote/v2', body=body)
        self.validate_quote(result, source, destination, amount, sender, recipient)
        return deepcopy(result)

    @staticmethod
    def validate_quote(result, source, destination, amount, sender, recipient):
        try:
            details = result['details']
            if address(details['sender']) != sender or address(details['recipient']) != recipient:
                raise RelayError('Relay recipient or sender mismatch')
            for field, token in [('currencyIn', source), ('currencyOut', destination),
                                 ('refundCurrency', source)]:
                currency = details[field]['currency']
                if (currency['chainId'] != CHAINS[token]
                        or address(currency['address']) != TOKENS[token][0]
                        or currency['decimals'] != TOKENS[token][1]):
                    raise RelayError('Relay asset or network mismatch')
            if details['currencyIn']['amount'] != amount:
                raise RelayError('Relay input amount mismatch')
            output = uint(details['currencyOut']['amount'], positive=True)
            minimum = uint(details['currencyOut']['minimumAmount'], positive=True)
            if minimum > output or minimum < output * 9950 // 10000:
                raise RelayError('Relay output exceeds the allowed slippage')
            order = result['protocol']['v2']['orderData']
            inputs, output_order = order['inputs'], order['output']
            if len(inputs) != 1 or len(output_order['payments']) != 1:
                raise RelayError('Unsupported Relay split order')
            payment = inputs[0]['payment']
            if (payment['chainId'] != PROTOCOL_CHAINS[source]
                    or address(payment['currency']) != TOKENS[source][0]
                    or payment['amount'] != amount):
                raise RelayError('Relay order input mismatch')
            output_payment = output_order['payments'][0]
            if (output_order['chainId'] != PROTOCOL_CHAINS[destination]
                    or address(output_payment['currency']) != TOKENS[destination][0]
                    or address(output_payment['recipient']) != recipient
                    or output_payment['minimumAmount'] != str(minimum)
                    or output_payment['expectedAmount'] != str(output)):
                raise RelayError('Relay order output mismatch')
            if output_order['calls'] or order['fees']:
                raise RelayError('Relay extra calls or order fees are not supported')
            refunds = inputs[0]['refunds']
            if not refunds:
                raise RelayError('Relay refund terms are missing')
            origin_refund = False
            for refund in refunds:
                token, owner = (source, sender) if refund['chainId'] == PROTOCOL_CHAINS[source] else (destination, recipient)
                if (refund['chainId'] != PROTOCOL_CHAINS[token]
                        or address(refund['currency']) != TOKENS[token][0]
                        or address(refund['recipient']) != owner):
                    raise RelayError('Relay refund terms mismatch')
                origin_refund |= token == source
            if not origin_refund:
                raise RelayError('Relay origin refund is missing')
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise RelayError('Relay quote is missing required binding data') from exc

    def status(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', request_id):
            raise RelayError('Invalid Relay request ID')
        return self._request('GET', '/intents/status/v3', params={'requestId': request_id})

    def routes(self, source, destination, amount, sender, recipient):
        started = int(time.time())
        response = self.quote(source, destination, amount, source_address=sender,
                              destination_address=recipient, deposit_address=True)
        route = {'sourceTokenId': source, 'destinationTokenId': destination,
                 'amount': amount, 'messenger': 'relay', 'relayerFees': [],
                 'amountOut': response['details']['currencyOut']['amount'],
                 'amountOutMin': response['details']['currencyOut']['minimumAmount'],
                 'relay': response, 'relayRequestedAt': started}
        # Validate the actual payment step before displaying an actionable quote.
        self.build(route, source_address=sender, destination_address=recipient)
        return [route]

    def build(self, route, *, source_address, destination_address):
        from .bridge_binding import deposit_call
        source, destination, amount = (route['sourceTokenId'], route['destinationTokenId'], route['amount'])
        if route.get('messenger') != 'relay' or {source, destination} != set(TOKENS):
            raise RelayError('Invalid Relay route')
        sender, recipient = address(source_address), address(destination_address)
        response = route['relay']
        self.validate_quote(response, source, destination, amount, sender, recipient)
        try:
            steps = response['steps']
            if len(steps) != 1 or steps[0]['id'] != 'deposit' or steps[0]['kind'] != 'transaction':
                raise RelayError('Relay must supply a single deposit transfer')
            step = steps[0]
            if len(step['items']) != 1:
                raise RelayError('Relay must supply a single deposit transfer')
            item = step['items'][0]
            tx = item['data']
            request_id = step['requestId']
            if not re.fullmatch(r'0x[0-9a-fA-F]{64}', request_id):
                raise RelayError('Invalid Relay request ID')
            if (response.get('requestId', request_id) != request_id
                    or item['check'] != {'method': 'GET', 'endpoint': '/intents/status/v3?requestId=' + request_id}
                    or tx['chainId'] != CHAINS[source] or address(tx['from']) != sender):
                raise RelayError('Relay deposit binding mismatch')
            build = {'amountOut': response['details']['currencyOut']['amount'],
                     'amountOutMin': response['details']['currencyOut']['minimumAmount'],
                     'tx': {'contractAddress': tx['to'], 'value': tx['value'], 'tx': tx['data']}}
            deposit, _ = deposit_call(build, source, amount)
            if deposit != address(step['depositAddress']) or deposit in {sender, recipient, TOKENS[source][0]}:
                raise RelayError('Relay deposit address mismatch')
            if (route['amountOut'] != build['amountOut'] or route['amountOutMin'] != build['amountOutMin']):
                raise RelayError('Relay stored price mismatch')
            requested = route['relayRequestedAt']
            if type(requested) is not int or requested > int(time.time()) + 5:
                raise RelayError('Invalid Relay quote time')
            order_deadline = response['protocol']['v2']['orderData']['output']['deadline']
            if type(order_deadline) is not int:
                raise RelayError('Invalid Relay order deadline')
            deadline = min(order_deadline, requested + 600)
            if deadline <= int(time.time()) + 60:
                raise RelayError('Relay deposit expires too soon')
            build['relay'] = {'provider': 'relay', 'request_id': request_id,
                              'response': deepcopy(response), 'deadline': deadline}
            return build
        except (KeyError, TypeError, AttributeError) as exc:
            raise RelayError('Relay deposit is missing required binding data') from exc
