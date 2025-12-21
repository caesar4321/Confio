#!/usr/bin/env python3
"""
Rotate InviteSend admin to the configured sponsor address via set_admin(address).

Reads:
- ALGORAND_ALGOD_ADDRESS, ALGORAND_ALGOD_TOKEN
- ALGORAND_INVITE_SEND_APP_ID
- ALGORAND_ADMIN_MNEMONIC (must be current on-chain admin)
- ALGORAND_SPONSOR_ADDRESS (new admin target)

Usage:
  python scripts/set_invite_admin.py
"""
import os
import json
import sys
from pathlib import Path

from algosdk.v2client import algod
from algosdk import mnemonic
from algosdk import transaction
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    AccountTransactionSigner,
    TransactionWithSigner,
)
from algosdk.abi import Contract
from algosdk.encoding import encode_address
import base64


def load_env(var: str, required: bool = True) -> str:
    val = os.getenv(var)
    if required and not val:
        print(f"Missing required env var: {var}", file=sys.stderr)
        sys.exit(2)
    return val or ""


def get_global_addr_bytes(gstate, key: str) -> bytes | None:
    for kv in gstate:
        try:
            k = base64.b64decode(kv.get('key')).decode()
            if k == key:
                v = kv.get('value', {})
                if v.get('type') == 1:
                    return base64.b64decode(v.get('bytes'))
        except Exception:
            continue
    return None


def main():
    algod_addr = load_env('ALGORAND_ALGOD_ADDRESS')
    algod_token = load_env('ALGORAND_ALGOD_TOKEN', required=False)
    app_id = int(load_env('ALGORAND_INVITE_SEND_APP_ID'))
    admin_mn = load_env('ALGORAND_ADMIN_MNEMONIC')
    new_admin = load_env('ALGORAND_SPONSOR_ADDRESS')

    client = algod.AlgodClient(algod_token, algod_addr)

    # Introspect current on-chain admin/sponsor
    info = client.application_info(app_id)
    gstate = info.get('params', {}).get('global-state', [])
    admin_b = get_global_addr_bytes(gstate, 'admin')
    sponsor_b = get_global_addr_bytes(gstate, 'sponsor_address')
    on_admin = encode_address(admin_b) if admin_b else 'unknown'
    on_sponsor = encode_address(sponsor_b) if sponsor_b else 'unknown'
    print(f"On-chain admin={on_admin} sponsor={on_sponsor}")

    # Derive sender from admin mnemonic
    sk = mnemonic.to_private_key(admin_mn)
    from algosdk import account as _acct
    sender = _acct.address_from_private_key(sk)
    if on_admin != 'unknown' and sender != on_admin:
        print(f"Provided ALGORAND_ADMIN_MNEMONIC address {sender} does not match on-chain admin {on_admin}", file=sys.stderr)
        sys.exit(3)

    # Load ABI
    abi_path = Path('contracts/invite_send/contract.json')
    contract = Contract.from_json(abi_path.read_text())
    method = next((m for m in contract.methods if m.name == 'set_admin'), None)
    if method is None:
        print('ABI method set_admin not found', file=sys.stderr)
        sys.exit(4)

    sp = client.suggested_params()
    min_fee = getattr(sp, 'min_fee', 1000) or 1000
    sp.flat_fee = True

    # Fee-bump from sponsor so admin need not hold ALGO
    sponsor_addr = load_env('ALGORAND_SPONSOR_ADDRESS')
    sponsor_mn = load_env('ALGORAND_SPONSOR_MNEMONIC')
    sponsor_sk = mnemonic.to_private_key(sponsor_mn)

    pay0 = transaction.PaymentTxn(
        sender=sponsor_addr,
        sp=transaction.SuggestedParams(fee=min_fee * 2, first=sp.first, last=sp.last, gh=sp.gh, gen=sp.gen, flat_fee=True),
        receiver=sponsor_addr,
        amt=0,
    )

    atc = AtomicTransactionComposer()
    atc.add_transaction(TransactionWithSigner(pay0, AccountTransactionSigner(sponsor_sk)))
    atc.add_method_call(
        app_id=app_id,
        method=method,
        sender=sender,
        sp=transaction.SuggestedParams(fee=0, first=sp.first, last=sp.last, gh=sp.gh, gen=sp.gen, flat_fee=True),
        signer=AccountTransactionSigner(sk),
        method_args=[new_admin],
    )

    res = atc.execute(client, 10)
    txid = res.tx_ids[-1] if res.tx_ids else ''
    print(f"set_admin submitted. txid={txid}")


if __name__ == '__main__':
    main()
