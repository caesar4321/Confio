#!/usr/bin/env python3
"""
Print on-chain admin and sponsor for a given Algorand app and compare
with addresses derived from local .env mnemonics.

Reads env:
- ALGORAND_ALGOD_ADDRESS, ALGORAND_ALGOD_TOKEN
- ALGORAND_INVITE_SEND_APP_ID (default if --app-id not passed)
- ALGORAND_ADMIN_MNEMONIC (optional)
- ALGORAND_SPONSOR_MNEMONIC (optional)

Usage:
  python scripts/print_app_roles.py [--app-id 123]
"""
import argparse
import os
import base64
from algosdk.v2client import algod
from algosdk import mnemonic
from algosdk.encoding import encode_address


def b64key(gstate, k: str) -> bytes | None:
    for kv in gstate:
        try:
            if base64.b64decode(kv.get('key')).decode() == k:
                v = kv.get('value', {})
                if v.get('type') == 1:
                    return base64.b64decode(v.get('bytes'))
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--app-id', type=int, default=int(os.getenv('ALGORAND_INVITE_SEND_APP_ID', '0')))
    args = ap.parse_args()

    if not args.app_id:
        raise SystemExit('Missing --app-id and ALGORAND_INVITE_SEND_APP_ID')

    algod_addr = os.getenv('ALGORAND_ALGOD_ADDRESS')
    algod_token = os.getenv('ALGORAND_ALGOD_TOKEN', '')
    if not algod_addr:
        raise SystemExit('ALGORAND_ALGOD_ADDRESS is required')

    client = algod.AlgodClient(algod_token, algod_addr)
    info = client.application_info(args.app_id)
    gstate = info.get('params', {}).get('global-state', [])
    admin_b = b64key(gstate, 'admin')
    sponsor_b = b64key(gstate, 'sponsor_address')
    on_admin = encode_address(admin_b) if admin_b else 'unknown'
    on_sponsor = encode_address(sponsor_b) if sponsor_b else 'unknown'

    print(f'App {args.app_id} on-chain admin:   {on_admin}')
    print(f'App {args.app_id} on-chain sponsor: {on_sponsor}')

    # Local env-derived addresses
    adm_mn = os.getenv('ALGORAND_ADMIN_MNEMONIC')
    spon_mn = os.getenv('ALGORAND_SPONSOR_MNEMONIC')
    def addr_from_mn(mn: str | None) -> str:
        if not mn:
            return 'not set'
        try:
            from algosdk import account as _acct
            sk = mnemonic.to_private_key(mn)
            return _acct.address_from_private_key(sk)
        except Exception:
            return 'invalid mnemonic'

    print(f'Local admin addr (env):   {addr_from_mn(adm_mn)}')
    print(f'Local sponsor addr (env): {addr_from_mn(spon_mn)}')

    mismatch = []
    if on_admin != 'unknown' and adm_mn:
        if addr_from_mn(adm_mn) != on_admin:
            mismatch.append('admin')
    if on_sponsor != 'unknown' and spon_mn:
        if addr_from_mn(spon_mn) != on_sponsor:
            mismatch.append('sponsor')
    if mismatch:
        print('MISMATCH:', ', '.join(mismatch))


if __name__ == '__main__':
    main()

