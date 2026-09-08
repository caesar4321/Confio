"""Validate NEXT's currently supported NEAR Intents deposit route end to end."""
import requests
from django.utils.dateparse import parse_datetime

from .allbridge_next import NextError, TOKENS, address, uint


class IntentsClient:
    BASE = 'https://1click.chaindefuser.com/v0'

    def get(self, path, **params):
        try:
            response = requests.get(self.BASE + path, params=params, timeout=(5, 20), allow_redirects=False)
            if response.status_code != 200:
                raise NextError('Unable to verify bridge deposit binding')
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise NextError('Bridge status is unavailable') from exc

    def status(self, deposit):
        return self.get('/status', depositAddress=address(deposit))

    def tokens(self):
        return self.get('/tokens')


def deposit_call(build, source_token, amount):
    """Accept only one exact ERC20 transfer; no arbitrary router calldata."""
    tx = build.get('tx', {})
    if address(tx.get('contractAddress')) != TOKENS[source_token][0] or uint(tx.get('value')) != 0:
        raise NextError('Bridge must transfer the exact source token without native value')
    data = str(tx.get('tx', '')).removeprefix('0x').lower()
    if len(data) != 136 or not data.startswith('a9059cbb') or data[8:32] != '0' * 24:
        raise NextError('Unsupported bridge deposit calldata')
    try:
        if int(data[72:], 16) != uint(amount, positive=True):
            raise NextError('Bridge deposit amount mismatch')
        recipient = address('0x' + data[32:72])
    except ValueError as exc:
        raise NextError('Invalid bridge calldata') from exc
    return recipient, {'to': TOKENS[source_token][0], 'value': '0', 'data': '0x' + data}


def validate_binding(status, tokens, quote, deposit, *, minimum, now):
    response = status.get('quoteResponse') or {}
    request = response.get('quoteRequest') or {}
    result = response.get('quote') or {}
    if status.get('status') != 'PENDING_DEPOSIT':
        raise NextError('Bridge deposit is not unused')
    if (request.get('depositMode', 'SIMPLE') != 'SIMPLE'
            or request.get('swapType') != 'EXACT_INPUT'
            or request.get('depositType') != 'ORIGIN_CHAIN'
            or request.get('recipientType') != 'DESTINATION_CHAIN'
            or request.get('refundType') != 'ORIGIN_CHAIN'
            or request.get('dry') is not False
            or result.get('depositMemo') or request.get('customRecipientMsg')
            or request.get('virtualChainRecipient') or request.get('virtualChainRefundRecipient')):
        raise NextError('Unsupported bridge deposit mode')
    if (address(request.get('recipient')) != quote.destination_address
            or address(request.get('refundTo')) != quote.source_address
            or address(result.get('depositAddress')) != deposit
            or request.get('amount') != quote.amount_units
            or result.get('amountIn') != quote.amount_units):
        raise NextError('Bridge destination, refund, or amount mismatch')
    for field, token_id in [('originAsset', quote.source_token_id), ('destinationAsset', quote.destination_token_id)]:
        matches = [t for t in tokens if t.get('assetId') == request.get(field)]
        if len(matches) != 1:
            raise NextError('Unverified bridge asset')
        token = matches[0]
        expected, decimals = TOKENS[token_id]
        if (address(token.get('contractAddress')) != expected or token.get('decimals') != decimals
                or token.get('blockchain') != token_id.split(':')[0].lower()):
            raise NextError('Bridge asset does not match token contract')
    if uint(result.get('minAmountOut'), positive=True) != uint(minimum, positive=True):
        raise NextError('Bridge minimum output mismatch')
    if uint(result.get('amountOut'), positive=True) < uint(minimum):
        raise NextError('Bridge output below minimum')
    deadlines = [parse_datetime(request.get('deadline', '')), parse_datetime(result.get('deadline', ''))]
    if any(d is None or d.tzinfo is None for d in deadlines):
        raise NextError('Bridge deadline is missing')
    deadline = min(int(d.timestamp()) for d in deadlines)
    if deadline <= now + 60:
        raise NextError('Bridge deposit expires too soon')
    return deadline
