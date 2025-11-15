#!/usr/bin/env python3
import sys
import base64
from algosdk import encoding, transaction

if len(sys.argv) != 2:
    print("Usage: decode_stx.py <base64>")
    sys.exit(1)

payload = sys.argv[1]
raw = base64.b64decode(payload)
obj = encoding.msgpack_decode(raw)
stx = transaction.SignedTransaction.undictify(obj)
txn = stx.transaction
print('type:', txn.type)
print('app id:', getattr(txn, 'index', None))
print('foreign apps:', getattr(txn, 'foreign_apps', None))
print('foreign assets:', getattr(txn, 'foreign_assets', None))
print('accounts:', getattr(txn, 'accounts', None))
print('boxes:', getattr(txn, 'boxes', None))
print('app args:', getattr(txn, 'app_args', None))
