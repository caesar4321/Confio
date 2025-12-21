#!/usr/bin/env python3
"""
Debug an InviteSend invitation by phone number.

Resolves the invitation_id candidates for a phone (canonical + legacy),
fetches the existing box (if any), and decodes:
- inviter address
- asset_id
- amount (micro)
- created_at, expires_at
- claimed/reclaimed flags

Also checks whether a provided recipient address is opted-in to the asset.

Env:
- ALGORAND_ALGOD_ADDRESS, ALGORAND_ALGOD_TOKEN
- ALGORAND_INVITE_SEND_APP_ID

Usage:
  python scripts/debug_invite_box.py --phone 9293993619 --country AS [--recipient QNCSEK...]
"""
import argparse
import base64
import os
from algosdk.v2client import algod
from algosdk.encoding import encode_address
from users.phone_utils import normalize_phone
from users.country_codes import COUNTRY_CODES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phone', required=True)
    ap.add_argument('--country', required=False)
    ap.add_argument('--recipient', required=False)
    args = ap.parse_args()

    algod_addr = os.getenv('ALGORAND_ALGOD_ADDRESS')
    algod_token = os.getenv('ALGORAND_ALGOD_TOKEN', '')
    app_id = int(os.getenv('ALGORAND_INVITE_SEND_APP_ID', '0'))
    if not algod_addr or not app_id:
        raise SystemExit('Set ALGORAND_ALGOD_ADDRESS and ALGORAND_INVITE_SEND_APP_ID in env')

    client = algod.AlgodClient(algod_token, algod_addr)

    # Build single canonical invitation ID (strict cc:digits)
    canon = normalize_phone(args.phone, args.country)
    if not canon or ':' not in canon:
        print('Cannot canonicalize phone. Provide country (ISO or calling code) or E.164 format (+CC...).')
        return
    # Hashing scheme mirrors server: sha256(phone_key)[:56] prefixed with 'ph:'
    import hashlib
    def make_id(key: str) -> str:
        return 'ph:' + hashlib.sha256(key.encode()).hexdigest()[:56]

    cid = make_id(canon)
    try:
        box = client.application_box_by_name(app_id, cid.encode())
        val = box.get('value', {})
        b = base64.b64decode(val['bytes']) if isinstance(val, dict) else base64.b64decode(val)
        print(f'Found invitation box: {cid} (len={len(b)})')
        inviter = encode_address(b[0:32])
        amount = int.from_bytes(b[32:40], 'big')
        asset_id = int.from_bytes(b[40:48], 'big')
        created = int.from_bytes(b[48:56], 'big')
        expires = int.from_bytes(b[56:64], 'big')
        is_claimed = (b[64] == 1) if len(b) > 64 else False
        is_reclaimed = (b[65] == 1) if len(b) > 65 else False
        print(f'  inviter:   {inviter}')
        print(f'  asset_id:  {asset_id}')
        print(f'  amount:    {amount} micro')
        print(f'  created:   {created}')
        print(f'  expires:   {expires}')
        print(f'  claimed:   {is_claimed} reclaimed: {is_reclaimed}')
        if args.recipient:
            try:
                client.account_asset_info(args.recipient, asset_id)
                print(f'  recipient {args.recipient} is opted in to asset {asset_id}')
            except Exception as e:
                print(f'  recipient {args.recipient} NOT opted in to asset {asset_id}: {e}')
    except Exception:
        print('No invitation box found for canonical id.')


if __name__ == '__main__':
    main()
