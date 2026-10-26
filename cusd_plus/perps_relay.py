"""Relay binding for Futuros: BSC USDT ⇄ the member's HyperCore account.

Measured 2026-10-25 (docs/designs/hyperliquid-perps.md §2): Relay credits the
HyperCore perps balance directly (chain 1337, no Arbitrum, no Bridge2), and
withdraws with two member signatures: a RelayNonceMapping authorization and a
Hyperliquid `sendAsset` to Relay's HyperCore depository using the same nonce.

Every quote is checked against terms WE own (sender = recipient = the
member's address, the exact assets and chains, refunds to the member, no
destination calls or order fees, bounded slippage and total cost), never
against other fields of the same response. Nothing here signs or moves money.
"""
from __future__ import annotations

import re
import time
from copy import deepcopy
from decimal import Decimal

from django.conf import settings
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode

from payment_accounts.relay import RelayClient, RelayError

BSC_CHAIN_ID = 56
HL_CHAIN_ID = 1337
BSC_USDT = '0x55d398326f99059ff775485246999027b3197955'
HL_USDC = '0x00000000000000000000000000000000'
HL_USDC_TOKEN = 'USDC:0x6d1e7cde53ba9467b783cb7c530ce054'
USDT_DECIMALS = 18
HL_USDC_DECIMALS = 8
PROTOCOL_CHAIN = {BSC_CHAIN_ID: 'bnb', HL_CHAIN_ID: 'hyperliquid'}
SEL_APPROVE = '095ea7b3'
SEL_DEPOSIT = 'e8017952'  # depositErc20(address depositor, address token, uint256 amount, bytes32 id)

# Slippage: Relay's own tolerance is ~2% at these sizes; bind it like the
# payment rail does (dollar floor for small sizes, bps above, hard cap).
DETERIORATION_BPS = 250
DETERIORATION_FLOOR_CENTS = 15
DETERIORATION_MAX_BPS = 1000
# Total cost cap, including Hyperliquid's one-time $1.20 new-account charge
# on a first deposit (a $12 first open is ~10%).
TOTAL_COST_MAX_BPS = 2000
QUOTE_TTL_S = 600

_HEX32 = re.compile(r'0x[0-9a-f]{64}')
_ADDR = re.compile(r'0x[0-9a-f]{40}')


# ── order authentication ────────────────────────────────────────────────
# A quote's orderId is Relay's EIP-712 hashStruct of the order itself
# (relay-settlement packages/sdk/src/order getOrderId), and orderSignature is
# the solver's eth_sign of that id. Recomputing the id from the order terms
# (payout recipient, amounts, refunds, deadline) and recovering the solver
# binds every term to the order Relay will execute, whoever fetched the
# quote: a rewritten field no longer hashes to the id, a forged order has no
# solver signature. Measured on recorded quotes both ways (2026-10-26).

_ORDER_TYPES = {
    'Order': [('version', 'string'), ('solverChainId', 'string'), ('solver', 'address'), ('salt', 'uint256'),
              ('inputs', 'Input[]'), ('output', 'Output'), ('fees', 'Fee[]')],
    'Input': [('payment', 'InputPayment'), ('refunds', 'InputRefund[]')],
    'InputPayment': [('chainId', 'string'), ('currency', 'bytes'), ('amount', 'uint256'), ('weight', 'uint256')],
    'InputRefund': [('chainId', 'string'), ('recipient', 'bytes'), ('currency', 'bytes'),
                    ('minimumAmount', 'uint256'), ('deadline', 'uint32'), ('extraData', 'bytes')],
    'Output': [('chainId', 'string'), ('payments', 'OutputPayment[]'), ('deadline', 'uint32'),
               ('calls', 'bytes[]'), ('extraData', 'bytes')],
    'OutputPayment': [('recipient', 'bytes'), ('currency', 'bytes'), ('minimumAmount', 'uint256'),
                      ('expectedAmount', 'uint256')],
    'Fee': [('recipientChainId', 'string'), ('recipient', 'bytes'), ('currencyChainId', 'string'),
            ('currency', 'bytes'), ('amount', 'uint256')],
}


def _type_string(name: str) -> str:
    deps: set = set()

    def walk(t):
        t = t.rstrip('[]')
        if t in _ORDER_TYPES and t not in deps:
            deps.add(t)
            for _, field_type in _ORDER_TYPES[t]:
                walk(field_type)

    walk(name)
    deps.discard(name)
    return ''.join(f"{n}({','.join(f'{ft} {fn}' for fn, ft in _ORDER_TYPES[n])})" for n in [name] + sorted(deps))


def _hex_bytes(value) -> bytes:
    text = str(value)
    if not re.fullmatch(r'0x([0-9a-fA-F]{2})*', text):
        raise RelayError('Relay order field is not hex')
    return bytes.fromhex(text[2:])


def _encode_field(field_type: str, value) -> bytes:
    from eth_utils import keccak

    if field_type.endswith('[]'):
        if not isinstance(value, list):
            raise RelayError('Relay order array expected')
        return keccak(b''.join(_encode_field(field_type[:-2], v) for v in value))
    if field_type in _ORDER_TYPES:
        return _order_struct_hash(field_type, value)
    if field_type == 'string':
        if not isinstance(value, str):
            raise RelayError('Relay order string expected')
        return keccak(text=value)
    if field_type == 'bytes':
        return keccak(_hex_bytes(value))
    if field_type == 'address':
        raw = _hex_bytes(value)
        if len(raw) != 20:
            raise RelayError('Relay order address expected')
        return bytes(12) + raw
    if field_type.startswith('uint'):
        number = int(value, 16) if isinstance(value, str) and value.startswith('0x') else int(str(value))
        if number < 0 or number >= 2 ** int(field_type[4:]):
            raise RelayError('Relay order integer out of range')
        return number.to_bytes(32, 'big')
    raise RelayError('Relay order type unsupported')


def _order_struct_hash(name: str, data) -> bytes:
    from eth_utils import keccak

    if not isinstance(data, dict):
        raise RelayError('Relay order struct expected')
    return keccak(keccak(text=_type_string(name))
                  + b''.join(_encode_field(ft, data[fn]) for fn, ft in _ORDER_TYPES[name]))


def order_id(order: dict) -> str:
    return '0x' + _order_struct_hash('Order', order).hex()


def relay_solvers() -> frozenset:
    return frozenset(s.lower() for s in getattr(settings, 'RELAY_PERPS_SOLVERS', ())
                     or ('0xf70da97812cb96acdf810712aa562db8dfa3dbef',))


def authenticate_order(v2: dict) -> str:
    """The order id, proven to be the hash of these order terms and signed
    by Relay's (pinned) solver. Raises RelayError otherwise."""
    from eth_account import Account
    from eth_account.messages import encode_defunct

    order = v2['orderData']
    if order.get('version') != 'v1':
        raise RelayError('Unsupported Relay order version')
    claimed = str(v2['orderId']).lower()
    if order_id(order) != claimed:
        raise RelayError('Relay order id does not match its terms')
    solver = _addr(order['solver'])
    if solver not in relay_solvers():
        raise RelayError('Relay solver is not recognized')
    try:
        signer = Account.recover_message(encode_defunct(primitive=bytes.fromhex(claimed[2:])),
                                         signature=_hex_bytes(v2['orderSignature']))
    except Exception as exc:  # noqa: BLE001 — any malformed signature is a refusal
        raise RelayError('Relay order signature is invalid') from exc
    if signer.lower() != solver:
        raise RelayError('Relay order is not signed by its solver')
    return claimed


def _request_quote(origin: int, destination: int, amount: int, wallet: str, client=None) -> dict:
    origin_currency, destination_currency = _currency(origin)[0], _currency(destination)[0]
    body = {
        'user': wallet, 'recipient': wallet, 'refundTo': wallet,
        'originChainId': origin, 'destinationChainId': destination,
        'originCurrency': origin_currency, 'destinationCurrency': destination_currency,
        'amount': str(amount), 'tradeType': 'EXACT_INPUT',
        'includeProtocolData': True,
        # Mandatory for HyperCore withdrawals; harmless for deposits.
        'protocolVersion': 'v2',
    }
    return (client or RelayClient())._request('POST', '/quote/v2', body=body)

def bsc_depository() -> str:
    return (getattr(settings, 'PERPS_RELAY_BSC_DEPOSITORY', '')
            or '0x4cd00e387622c35bddb9b4c962c136462338bc31').lower()


def hl_depository() -> str:
    return (getattr(settings, 'PERPS_RELAY_HL_DEPOSITORY', '')
            or '0x66cf0aace1b4e562593bec10ec7868fba9932224').lower()


def _addr(value) -> str:
    if not isinstance(value, str) or not _ADDR.fullmatch(value.lower()) or int(value, 16) == 0:
        raise RelayError('Relay returned an invalid address')
    return value.lower()


def _uint(value) -> int:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,78}', value):
        raise RelayError('Relay returned an invalid amount')
    return int(value)


def _currency(chain_id: int) -> tuple[str, int]:
    return (BSC_USDT, USDT_DECIMALS) if chain_id == BSC_CHAIN_ID else (HL_USDC, HL_USDC_DECIMALS)


def _rebase(amount: int, from_chain: int, to_chain: int) -> int:
    return amount * 10 ** _currency(to_chain)[1] // 10 ** _currency(from_chain)[1]


def allowed_deterioration(output: int, chain_id: int) -> int:
    floor = DETERIORATION_FLOOR_CENTS * 10 ** _currency(chain_id)[1] // 100
    return min(max(output * DETERIORATION_BPS // 10_000, floor), output * DETERIORATION_MAX_BPS // 10_000)


def usdc_units_to_str(units: int) -> str:
    """HyperCore USDC base units (8 dp) -> the sendAsset amount string."""
    return format((Decimal(units) / Decimal(10) ** HL_USDC_DECIMALS).quantize(Decimal('0.00000001')), 'f')


def validate_quote(result: dict, origin: int, destination: int, amount: int, wallet: str) -> dict:
    """Bind a raw quote to our terms. Returns the normalized facts."""
    try:
        details = result['details']
        if _addr(details['sender']) != wallet or _addr(details['recipient']) != wallet:
            raise RelayError('Relay recipient or sender mismatch')
        for field, chain in (('currencyIn', origin), ('currencyOut', destination), ('refundCurrency', origin)):
            currency = details[field]['currency']
            expected, decimals = _currency(chain)
            if (currency['chainId'] != chain or str(currency['address']).lower() != expected
                    or currency['decimals'] != decimals):
                raise RelayError('Relay asset or network mismatch')
        if _uint(details['currencyIn']['amount']) != amount:
            raise RelayError('Relay input amount mismatch')
        output = _uint(details['currencyOut']['amount'])
        minimum = _uint(details['currencyOut']['minimumAmount'])
        if not 0 < minimum <= output or output - minimum > allowed_deterioration(output, destination):
            raise RelayError('Relay output exceeds the allowed slippage')
        if minimum * 10_000 < _rebase(amount, origin, destination) * (10_000 - TOTAL_COST_MAX_BPS):
            raise RelayError('Este monto es muy pequeño para mover en este momento.')

        v2 = result['protocol']['v2']
        order_id = str(v2['orderId']).lower()
        if not _HEX32.fullmatch(order_id):
            raise RelayError('Invalid Relay order id')
        authenticate_order(v2)  # every term below is now the order Relay executes
        order = v2['orderData']
        inputs, out = order['inputs'], order['output']
        if len(inputs) != 1 or len(out['payments']) != 1 or out['calls'] or order['fees']:
            raise RelayError('Unsupported Relay order shape')
        payment = inputs[0]['payment']
        if (payment['chainId'] != PROTOCOL_CHAIN[origin]
                or str(payment['currency']).lower() != _currency(origin)[0]
                or _uint(payment['amount']) != amount):
            raise RelayError('Relay order input mismatch')
        paid = out['payments'][0]
        if (out['chainId'] != PROTOCOL_CHAIN[destination]
                or str(paid['currency']).lower() != _currency(destination)[0]
                or _addr(paid['recipient']) != wallet
                or _uint(paid['minimumAmount']) != minimum
                or _uint(paid['expectedAmount']) != output):
            raise RelayError('Relay order output mismatch')
        refunds = inputs[0]['refunds']
        if not refunds or not any(r['chainId'] == PROTOCOL_CHAIN[origin] for r in refunds):
            raise RelayError('Relay origin refund is missing')
        for refund in refunds:
            chain = {v: k for k, v in PROTOCOL_CHAIN.items()}.get(refund['chainId'])
            if (chain is None or str(refund['currency']).lower() != _currency(chain)[0]
                    or _addr(refund['recipient']) != wallet):
                raise RelayError('Relay refund terms mismatch')
        deadline = out['deadline']
        if type(deadline) is not int or deadline <= int(time.time()) + 60:
            raise RelayError('Relay order expires too soon')
        details_pay = v2['paymentDetails']
        if details_pay['chainId'] != PROTOCOL_CHAIN[origin] or _uint(details_pay['amount']) != amount:
            raise RelayError('Relay payment details mismatch')
        depository = _addr(details_pay['depository'])
        expected_depository = bsc_depository() if origin == BSC_CHAIN_ID else hl_depository()
        if depository != expected_depository:
            raise RelayError('Relay depository mismatch')
        request_id = str(result['requestId']).lower()
        if not _HEX32.fullmatch(request_id):
            raise RelayError('Invalid Relay request ID')
        fees = result.get('fees') or {}
        if fees.get('app') not in (None, {}) and _uint(str((fees.get('app') or {}).get('amount', '0'))) != 0:
            raise RelayError('Relay app fees are not supported')
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise RelayError('Relay quote is missing required binding data') from exc
    return {
        'request_id': request_id,
        'order_id': order_id,
        'depository': depository,
        'amount_in': amount,
        'expected_out': output,
        'minimum_out': minimum,
        'deadline': min(deadline, int(time.time()) + QUOTE_TTL_S),
        'time_estimate_s': details.get('timeEstimate'),
    }


def deposit_calldata(wallet: str, amount: int, order_id: str) -> str:
    return '0x' + SEL_DEPOSIT + abi_encode(
        ['address', 'address', 'uint256', 'bytes32'],
        [wallet, BSC_USDT, amount, bytes.fromhex(order_id[2:])]).hex()


def decode_deposit(data: str) -> tuple[str, str, int, str]:
    """(depositor, token, amount, order_id) of a depository deposit call."""
    if not isinstance(data, str) or not data.lower().startswith('0x' + SEL_DEPOSIT):
        raise RelayError('not_a_relay_deposit')
    raw = bytes.fromhex(data[10:])
    types = ['address', 'address', 'uint256', 'bytes32']
    try:
        depositor, token, amount, order_id = abi_decode(types, raw)
    except Exception as exc:  # noqa: BLE001
        raise RelayError('bad_relay_deposit') from exc
    if abi_encode(types, [depositor, token, amount, order_id]) != raw:
        raise RelayError('bad_relay_deposit')
    return depositor.lower(), token.lower(), int(amount), '0x' + order_id.hex()


def quote_open(wallet: str, usdt_wei: int, *, client=None) -> dict:
    """BSC USDT (the exit's net) -> the member's HyperCore perps balance.
    The raw quote goes to the app too: it authenticates the order itself."""
    wallet = _addr(wallet)
    raw = _request_quote(BSC_CHAIN_ID, HL_CHAIN_ID, usdt_wei, wallet, client)
    bound = validate_quote(raw, BSC_CHAIN_ID, HL_CHAIN_ID, usdt_wei, wallet)
    try:
        steps = {s['id']: s for s in raw['steps']}
        deposit = steps['deposit']['items'][0]['data']
        if (_addr(deposit['to']) != bound['depository'] or deposit['chainId'] != BSC_CHAIN_ID
                or _addr(deposit['from']) != wallet or str(deposit.get('value', '0')) != '0'):
            raise RelayError('Relay deposit binding mismatch')
        # The call we sign is rebuilt from our own terms, then must equal Relay's.
        ours = deposit_calldata(wallet, usdt_wei, bound['order_id'])
        if str(deposit['data']).lower() != ours:
            raise RelayError('Relay deposit binding mismatch')
    except (KeyError, TypeError, IndexError) as exc:
        raise RelayError('Relay deposit is missing required binding data') from exc
    bound['deposit_data'] = ours
    bound['raw'] = deepcopy(raw)
    return bound


def quote_return(wallet: str, usdc_units: int, *, client=None) -> dict:
    """The member's HyperCore perps USDC -> BSC USDT at the member's address.
    The raw quote goes to the app too: it authenticates the order itself."""
    wallet = _addr(wallet)
    raw = _request_quote(HL_CHAIN_ID, BSC_CHAIN_ID, usdc_units, wallet, client)
    bound = validate_quote(raw, HL_CHAIN_ID, BSC_CHAIN_ID, usdc_units, wallet)
    try:
        steps = {s['id']: s for s in raw['steps']}
        sign = steps['authorize']['items'][0]['data']['sign']
        value = sign['value']
        post = steps['authorize']['items'][0]['data']['post']
        action = steps['deposit']['items'][0]['data']['action']
        params = action['parameters']
        nonce = value['nonce']
        if (sign['domain'].get('name') != 'RelayNonceMapping' or sign['domain'].get('version') != '2'
                or sign['primaryType'] != 'NonceMapping'
                or value.get('chainId') != 'hyperliquid'
                or _addr(value['wallet']) != wallet or _addr(value['depositor']) != wallet
                or str(value['id']).lower() != bound['order_id']
                or type(nonce) is not int or nonce <= 0
                or post.get('endpoint') != '/authorize' or post.get('method') != 'POST'):
            raise RelayError('Relay authorization binding mismatch')
        if (action.get('type') != 'sendAsset' or params.get('hyperliquidChain') != 'Mainnet'
                or _addr(params['destination']) != bound['depository']
                or params.get('sourceDex') != '' or params.get('destinationDex') != ''
                or params.get('token') != HL_USDC_TOKEN or params.get('fromSubAccount') != ''
                or params.get('nonce') != nonce
                or Decimal(str(params['amount'])) * 10 ** HL_USDC_DECIMALS != usdc_units):
            raise RelayError('Relay withdrawal binding mismatch')
    except (KeyError, TypeError, IndexError, ArithmeticError) as exc:
        raise RelayError('Relay withdrawal is missing required binding data') from exc
    bound.update({
        'nonce': nonce,
        'mapping': {'chainId': 'hyperliquid', 'wallet': wallet, 'depositor': wallet,
                    'id': bound['order_id'], 'nonce': nonce},
        'send_asset': {'destination': bound['depository'], 'sourceDex': '', 'destinationDex': '',
                       'token': HL_USDC_TOKEN, 'amount': str(params['amount']), 'fromSubAccount': '',
                       'nonce': nonce},
        'raw': deepcopy(raw),
    })
    return bound


def authorize(mapping: dict, signature_hex: str, signature_chain_id: int, *, client=None) -> dict:
    """Post the member-signed nonce mapping (signature as a query parameter)."""
    body = {'type': 'nonce-mapping', 'walletChainId': HL_CHAIN_ID, 'wallet': mapping['wallet'],
            'nonce': mapping['nonce'], 'id': mapping['id'], 'depositor': mapping['depositor'],
            'signatureChainId': signature_chain_id}
    return (client or RelayClient())._request('POST', '/authorize', body=body,
                                              params={'signature': signature_hex})


def status(request_id: str, *, client=None) -> dict:
    return (client or RelayClient()).status(request_id)
