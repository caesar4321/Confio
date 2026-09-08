"""NEXT quote/build API. This module never signs, sponsors, or broadcasts.

Contract: allbridge-io/allbridge-mcp/src/{next-api-client,next-tools}.ts.
Amounts are integer token units, including relayer fees; never use floats.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import re

import requests


class NextError(Exception):
    pass


TOKENS = {
    'BSC:USDT': ('0x55d398326f99059ff775485246999027b3197955', 18),
    'POL:USDC': ('0x3c499c542cef5e3811e1192ce70d8cc03d5c3359', 6),
}
ROUTE_FIELDS = (
    'sourceTokenId', 'destinationTokenId', 'sourceSwap',
    'sourceIntermediaryTokenId', 'destinationIntermediaryTokenId',
    'destinationSwap', 'messenger', 'estimatedTime', 'amount', 'amountOut',
)


def uint(value, *, positive=False):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,78}', value):
        raise NextError('Invalid NEXT integer amount')
    number = int(value)
    if number >= 2**256 or (positive and number == 0):
        raise NextError('NEXT amount is outside the supported range')
    return number


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', value):
        raise NextError('Invalid EVM address')
    if int(value[2:], 16) == 0:
        raise NextError('Zero EVM address is not allowed')
    return value.lower()


def to_units(amount, token_id):
    if token_id not in TOKENS:
        raise NextError('Unsupported NEXT token')
    try:
        value = Decimal(str(amount))
        if not value.is_finite() or value <= 0 or value >= Decimal('1e20'):
            raise NextError('Amount must be positive and within the supported range')
        with localcontext() as ctx:
            ctx.prec = 80
            scaled = value * (Decimal(10) ** TOKENS[token_id][1])
            if scaled != scaled.to_integral_value():
                raise NextError('Amount exceeds token precision')
            result = str(int(scaled))
        uint(result, positive=True)
        return result
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise NextError('Invalid amount') from exc


class NextClient:
    BASE_URL = 'https://api.next.allbridge.io'

    def __init__(self, session=None):
        self.session = session or requests.Session()

    def _request(self, method, path, body=None):
        try:
            response = self.session.request(
                method, self.BASE_URL + path, json=body,
                timeout=(5, 20), allow_redirects=False,
            )
            if not 200 <= response.status_code < 300:
                raise NextError('NEXT API request failed')
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise NextError('NEXT API is unavailable or returned invalid JSON') from exc

    def verify_tokens(self):
        tokens = self._request('GET', '/tokens')
        if not isinstance(tokens, list):
            raise NextError('Invalid NEXT token catalog')
        for token_id, (expected_address, decimals) in TOKENS.items():
            matches = [t for t in tokens if isinstance(t, dict) and t.get('tokenId') == token_id]
            if len(matches) != 1:
                raise NextError('Required NEXT token is unavailable or ambiguous')
            token = matches[0]
            if (address(token.get('address')) != expected_address
                    or token.get('decimals') != decimals
                    or token.get('chain') != token_id.split(':')[0]):
                raise NextError('NEXT token metadata does not match the configured asset')

    @staticmethod
    def validate_route(route, source, destination, amount):
        if not isinstance(route, dict):
            raise NextError('Invalid NEXT route')
        if (route.get('sourceTokenId'), route.get('destinationTokenId'), route.get('amount')) != (
            source, destination, amount,
        ):
            raise NextError('NEXT quote does not match the requested transfer')
        uint(route.get('amountOut'), positive=True)
        if 'amountOutMin' in route:
            if uint(route['amountOutMin'], positive=True) > uint(route['amountOut']):
                raise NextError('Invalid NEXT quote minimum output')
        if not isinstance(route.get('messenger'), str) or not route['messenger']:
            raise NextError('NEXT route has no messenger')
        fees = route.get('relayerFees')
        if not isinstance(fees, list) or (not fees and route['messenger'] != 'near-intents'):
            raise NextError('NEXT route has no relayer fee options')
        for fee in fees:
            if not isinstance(fee, dict) or not isinstance(fee.get('tokenId'), str) or not fee['tokenId']:
                raise NextError('Invalid NEXT relayer fee')
            uint(fee.get('amount'))
            if fee.get('approvalSpender'):
                address(fee['approvalSpender'])
        return deepcopy(route)

    def quote(self, source, destination, amount):
        if {source, destination} != set(TOKENS):
            raise NextError('Only BSC USDT ↔ Polygon USDC is supported')
        uint(amount, positive=True)
        self.verify_tokens()
        routes = self._request('POST', '/quote', {
            'sourceTokenId': source, 'destinationTokenId': destination, 'amount': amount,
        })
        if not isinstance(routes, list) or not routes or len(routes) > 50:
            raise NextError('No supported NEXT routes are available')
        return [self.validate_route(r, source, destination, amount) for r in routes]

    def build(self, route, *, source_address, destination_address, fee_index=0):
        """Internal integration primitive, deliberately not exposed to the sponsor.

        A caller must supply a fresh server-stored quote. The result is untrusted
        calldata until a route-specific execution policy validates it.
        """
        source, destination = route.get('sourceTokenId'), route.get('destinationTokenId')
        if {source, destination} != set(TOKENS):
            raise NextError('Unsupported NEXT route')
        self.validate_route(route, source, destination, route.get('amount'))
        uint(route.get('amount'), positive=True)
        body = {key: route[key] for key in ROUTE_FIELDS if key in route}
        body.update(sourceAddress=address(source_address), destinationAddress=address(destination_address))
        if route['messenger'] == 'near-intents':
            body['refundTo'] = body['sourceAddress']
        else:
            if type(fee_index) is not int or not 0 <= fee_index < len(route['relayerFees']):
                raise NextError('Invalid NEXT fee selection')
            body['relayerFee'] = deepcopy(route['relayerFees'][fee_index])
        result = self._request('POST', '/tx/create', body)
        if not isinstance(result, dict):
            raise NextError('Invalid NEXT transaction response')
        output = uint(result.get('amountOut'), positive=True)
        # Live NEXT uses amountOutMin; the public MCP types previously called
        # it amountMin. Normalize at the boundary, retaining the wire payload.
        minimum = uint(result.get('amountOutMin', result.get('amountMin')), positive=True)
        result['amountOutMin'] = str(minimum)
        if minimum > output:
            raise NextError('Invalid NEXT minimum output')
        tx = result.get('tx')
        if not isinstance(tx, dict):
            raise NextError('NEXT transaction is missing')
        address(tx.get('contractAddress'))
        uint(tx.get('value'))
        if isinstance(tx.get('tx'), str) and not tx['tx'].startswith('0x'):
            tx['tx'] = '0x' + tx['tx']
        if (route['messenger'] != 'near-intents' or tx.get('tx') is not None) and (
            not isinstance(tx.get('tx'), str)
            or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2}){4,}', tx['tx'])
        ):
            raise NextError('Invalid NEXT EVM calldata')
        return result
