"""Chain proofs and Polygon USDC authorization; no private user keys."""
import re
import requests
from eth_abi import encode
from eth_utils import keccak
from django.conf import settings

from .allbridge_next import NextError, TOKENS, address

TRANSFER_TOPIC = '0x' + keccak(text='Transfer(address,address,uint256)').hex()
USDC = TOKENS['POL:USDC'][0]


def rpc(chain, method, params):
    if chain not in {'BSC', 'POL'}:
        raise NextError('Unsupported bridge chain')
    url = getattr(settings, 'BSC_RPC_URL' if chain == 'BSC' else 'PAYMENT_BRIDGE_POLYGON_RPC_URL', '')
    if not url.startswith('https://'):
        raise NextError('Bridge RPC is not configured')
    try:
        response = requests.post(url, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, timeout=(5, 15))
        response.raise_for_status()
        body = response.json()
        if body.get('error') or 'result' not in body:
            raise NextError('Bridge RPC request failed')
        return body['result']
    except (requests.RequestException, ValueError) as exc:
        raise NextError('Bridge RPC unavailable') from exc


def require_chain(chain):
    if int(rpc(chain, 'eth_chainId', []), 16) != {'BSC': 56, 'POL': 137}[chain]:
        raise NextError('Bridge RPC chain mismatch')


def token_balance(token_id, holder):
    chain = token_id.split(':')[0]
    return int(rpc(chain, 'eth_call', [{'to': TOKENS[token_id][0],
        'data': '0x70a08231' + address(holder)[2:].rjust(64, '0')}, 'latest']), 16)


def final_receipt(chain, tx_hash):
    if not re.fullmatch(r'0x[0-9a-fA-F]{64}', tx_hash or ''):
        raise NextError('Invalid transaction hash')
    require_chain(chain)
    receipt = rpc(chain, 'eth_getTransactionReceipt', [tx_hash])
    if not receipt:
        return None
    number = int(receipt['blockNumber'], 16)
    finalized = rpc(chain, 'eth_getBlockByNumber', ['finalized', False])
    if not finalized or int(finalized['number'], 16) < number:
        return None
    block = rpc(chain, 'eth_getBlockByNumber', [hex(number), False])
    if not block or block['hash'].lower() != receipt['blockHash'].lower():
        return None
    if receipt.get('transactionHash', '').lower() != tx_hash.lower():
        raise NextError('Receipt hash mismatch')
    return receipt


def received_units(receipt, token_id, recipient, sender=None):
    if int(receipt.get('status', '0x0'), 16) != 1:
        return 0
    total = 0
    for log in receipt.get('logs', []):
        topics = log.get('topics', [])
        if (log.get('removed') or log.get('address', '').lower() != TOKENS[token_id][0]
                or len(topics) != 3 or topics[0].lower() != TRANSFER_TOPIC):
            continue
        if topics[2].lower() != '0x' + address(recipient)[2:].rjust(64, '0'):
            continue
        if sender and topics[1].lower() != '0x' + address(sender)[2:].rjust(64, '0'):
            continue
        if not re.fullmatch(r'0x[0-9a-fA-F]{64}', log.get('data', '')):
            raise NextError('Invalid token transfer log')
        total += int(log['data'], 16)
    return total


def authorization_nonce(transfer):
    return keccak(text='confio-polygon-bridge:' + str(transfer.internal_id))


def authorization_domain():
    return keccak(encode(['bytes32', 'bytes32', 'bytes32', 'uint256', 'address'], [
        keccak(text='EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)'),
        keccak(text='USD Coin'), keccak(text='2'), 137, USDC,
    ]))


def authorization_digest(transfer):
    q = transfer.quote
    message = keccak(encode(
        ['bytes32', 'address', 'address', 'uint256', 'uint256', 'uint256', 'bytes32'],
        [keccak(text='TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)'),
         q.source_address, transfer.deposit_address, int(q.amount_units), 0,
         transfer.deadline, authorization_nonce(transfer)],
    ))
    return keccak(b'\x19\x01' + authorization_domain() + message)


def authorization_calldata(transfer, signature):
    from cusd_plus.sponsor_7702 import recover_intent_signer
    if recover_intent_signer(authorization_digest(transfer), signature) != transfer.quote.source_address:
        raise NextError('Invalid Polygon authorization signature')
    raw = bytes.fromhex(signature.removeprefix('0x'))
    if len(raw) != 65:
        raise NextError('Invalid authorization length')
    v = raw[64] + 27 if raw[64] < 27 else raw[64]
    types = ['address', 'address', 'uint256', 'uint256', 'uint256', 'bytes32', 'uint8', 'bytes32', 'bytes32']
    values = [transfer.quote.source_address, transfer.deposit_address, int(transfer.quote.amount_units),
              0, transfer.deadline, authorization_nonce(transfer), v, raw[:32], raw[32:64]]
    return '0x' + keccak(text='transferWithAuthorization(' + ','.join(types) + ')')[:4].hex() + encode(types, values).hex()
