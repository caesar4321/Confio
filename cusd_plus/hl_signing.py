"""Hyperliquid action hashing and signer recovery (mirrors the official SDK).

The member's app signs every Hyperliquid action with their own key; the
server never signs. It recomputes the exact EIP-712 payload to recover the
signer, so it forwards an action only when it really is the member's.

Two signature schemes:
- L1 actions (order, cancel, updateLeverage, updateIsolatedMargin): the
  "phantom agent" {source, connectionId = keccak(msgpack(action) ‖ nonce ‖
  vault flag)} under domain Exchange/1/1337. msgpack follows the action's
  key order, so callers must build actions in the SDK's field order.
- User-signed actions (sendAsset, userSetAbstraction): plain EIP-712 under
  HyperliquidSignTransaction/1/<signatureChainId>.
"""
from __future__ import annotations

import msgpack
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak

MAINNET = 'Mainnet'

_DOMAIN_TYPES = [
    {'name': 'name', 'type': 'string'},
    {'name': 'version', 'type': 'string'},
    {'name': 'chainId', 'type': 'uint256'},
    {'name': 'verifyingContract', 'type': 'address'},
]
ZERO_ADDRESS = '0x0000000000000000000000000000000000000000'

SEND_ASSET_TYPES = [
    {'name': 'hyperliquidChain', 'type': 'string'},
    {'name': 'destination', 'type': 'string'},
    {'name': 'sourceDex', 'type': 'string'},
    {'name': 'destinationDex', 'type': 'string'},
    {'name': 'token', 'type': 'string'},
    {'name': 'amount', 'type': 'string'},
    {'name': 'fromSubAccount', 'type': 'string'},
    {'name': 'nonce', 'type': 'uint64'},
]
USER_SET_ABSTRACTION_TYPES = [
    {'name': 'hyperliquidChain', 'type': 'string'},
    {'name': 'user', 'type': 'address'},
    {'name': 'abstraction', 'type': 'string'},
    {'name': 'nonce', 'type': 'uint64'},
]
WITHDRAW_TYPES = [
    {'name': 'hyperliquidChain', 'type': 'string'},
    {'name': 'destination', 'type': 'string'},
    {'name': 'amount', 'type': 'string'},
    {'name': 'time', 'type': 'uint64'},
]
USER_SIGNED = {
    'sendAsset': ('HyperliquidTransaction:SendAsset', SEND_ASSET_TYPES),
    'userSetAbstraction': ('HyperliquidTransaction:UserSetAbstraction', USER_SET_ABSTRACTION_TYPES),
    'withdraw3': ('HyperliquidTransaction:Withdraw', WITHDRAW_TYPES),
}
L1_TYPES = {'order', 'cancel', 'updateLeverage', 'updateIsolatedMargin'}

RELAY_NONCE_MAPPING_TYPES = [
    {'name': 'chainId', 'type': 'string'},
    {'name': 'wallet', 'type': 'address'},
    {'name': 'depositor', 'type': 'address'},
    {'name': 'id', 'type': 'bytes32'},
    {'name': 'nonce', 'type': 'uint256'},
]


class SignatureError(Exception):
    pass


def action_hash(action: dict, nonce: int, vault_address: str | None = None) -> bytes:
    data = msgpack.packb(action)
    data += int(nonce).to_bytes(8, 'big')
    if vault_address is None:
        data += b'\x00'
    else:
        data += b'\x01' + bytes.fromhex(vault_address[2:])
    return keccak(data)


def l1_typed_data(action: dict, nonce: int) -> dict:
    return {
        'domain': {'chainId': 1337, 'name': 'Exchange', 'verifyingContract': ZERO_ADDRESS, 'version': '1'},
        'types': {
            'Agent': [{'name': 'source', 'type': 'string'}, {'name': 'connectionId', 'type': 'bytes32'}],
            'EIP712Domain': _DOMAIN_TYPES,
        },
        'primaryType': 'Agent',
        'message': {'source': 'a', 'connectionId': action_hash(action, nonce)},
    }


def user_signed_typed_data(action: dict) -> dict:
    try:
        primary, types = USER_SIGNED[action['type']]
        chain_id = int(action['signatureChainId'], 16)
    except (KeyError, TypeError, ValueError) as exc:
        raise SignatureError('bad_user_signed_action') from exc
    message = {field['name']: action[field['name']] for field in types if field['name'] in action}
    if len(message) != len(types):
        raise SignatureError('bad_user_signed_action')
    return {
        'domain': {'name': 'HyperliquidSignTransaction', 'version': '1', 'chainId': chain_id,
                   'verifyingContract': ZERO_ADDRESS},
        'types': {primary: types, 'EIP712Domain': _DOMAIN_TYPES},
        'primaryType': primary,
        'message': message,
    }


def relay_nonce_mapping_typed_data(value: dict, chain_id: int) -> dict:
    return {
        'domain': {'name': 'RelayNonceMapping', 'version': '2', 'chainId': chain_id,
                   'verifyingContract': ZERO_ADDRESS},
        'types': {'NonceMapping': RELAY_NONCE_MAPPING_TYPES, 'EIP712Domain': _DOMAIN_TYPES},
        'primaryType': 'NonceMapping',
        'message': value,
    }


def _signature_parts(signature: dict) -> tuple[int, int, int]:
    try:
        r = int(signature['r'], 16)
        s = int(signature['s'], 16)
        v = int(signature['v'])
    except (KeyError, TypeError, ValueError) as exc:
        raise SignatureError('bad_signature') from exc
    if v not in (27, 28) or not 0 < r < 2 ** 256 or not 0 < s < 2 ** 256:
        raise SignatureError('bad_signature')
    return v, r, s


def recover(typed_data: dict, signature: dict) -> str:
    v, r, s = _signature_parts(signature)
    try:
        encoded = encode_typed_data(full_message=typed_data)
        return Account.recover_message(encoded, vrs=(v, r, s)).lower()
    except Exception as exc:  # noqa: BLE001 — any malformed payload is a refusal
        raise SignatureError('bad_signature') from exc


def recover_action_signer(action: dict, nonce: int, signature: dict) -> str:
    """The address that signed this Hyperliquid action."""
    kind = action.get('type') if isinstance(action, dict) else None
    if kind in L1_TYPES:
        return recover(l1_typed_data(action, nonce), signature)
    if kind in USER_SIGNED:
        return recover(user_signed_typed_data(action), signature)
    raise SignatureError('action_not_allowed')


def signature_hex(signature: dict) -> str:
    v, r, s = _signature_parts(signature)
    return '0x' + r.to_bytes(32, 'big').hex() + s.to_bytes(32, 'big').hex() + bytes([v]).hex()
