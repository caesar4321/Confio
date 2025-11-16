#!/usr/bin/env python3
"""Decode the actual signed transaction from the client"""
import base64
import msgpack
from algosdk import encoding

# The signed transaction from the client logs
signed_b64 = "gqNzaWfEQLeQYU6XY1+5SuNsHfC/KbIpN57WB8gvmQYZGBU2XSEP1DsPXtqSKGlA1sl3A9pjdujZBkICoEOazPoXfPa2CASjdHhui6RhcGFhksQOY2xhaW1fcmVmZXJyZXLEIGryNKHLCHv9KF0tVAnsmEmNXelWgwjmtk3AuXVYl3zWpGFwYXORziynGqakYXBhdJHEIGryNKHLCHv9KF0tVAnsmEmNXelWgwjmtk3AuXVYl3zWpGFwYniRgaFuxCBq8jShywh7/ShdLVQJ7JhJjV3pVoMI5rZNwLl1WJd81qRhcGlkziyu8R2iZnbOA23xQ6JnaMQgSGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiKjZ3JwxCB1FI7aWV52w6+j1yV+Fiv015Dxp+g0CQAVvM1LXAPiA6Jsds4DbfUro3NuZMQgf+2GekMK69pZngWKPmRNP8eSbIgQcuA50QUOMNYc5GOkdHlwZaRhcHBs"

# Decode the base64
signed_bytes = base64.b64decode(signed_b64)

# Decode the msgpack
signed_dict = msgpack.unpackb(signed_bytes, raw=False)

print("Signed transaction dict keys:", list(signed_dict.keys()))
print()

if 'txn' in signed_dict:
    txn_dict = signed_dict['txn']
    print("Inner transaction keys:", list(txn_dict.keys()))
    print()

    if 'apbx' in txn_dict:
        print(f"Boxes: {len(txn_dict['apbx'])} references")
        for i, box_ref in enumerate(txn_dict['apbx']):
            box_name = box_ref.get('n')
            box_addr = encoding.encode_address(box_name)
            print(f"  Box {i}: {box_addr}")
            print(f"         hex: {box_name.hex()}")
    else:
        print("❌ NO BOXES in the transaction!")

    print()
    print("Sender:", encoding.encode_address(txn_dict.get('snd')))

    if 'apat' in txn_dict:
        print(f"Accounts: {len(txn_dict['apat'])}")
        for i, addr_bytes in enumerate(txn_dict['apat']):
            print(f"  Account {i}: {encoding.encode_address(addr_bytes)}")

print()
print("=" * 80)
print("Now decode with algosdk.encoding.msgpack_decode")
print("=" * 80)

# Decode with algosdk
signed_txn_obj = encoding.msgpack_decode(signed_b64)
print(f"Type: {type(signed_txn_obj)}")
print(f"Transaction type: {type(signed_txn_obj.transaction)}")
print(f"Boxes: {signed_txn_obj.transaction.boxes}")

print()
print("=" * 80)
print("Now re-encode with algosdk.encoding.msgpack_encode")
print("=" * 80)

# Re-encode
reencoded_b64 = encoding.msgpack_encode(signed_txn_obj)
reencoded_bytes = base64.b64decode(reencoded_b64)
reencoded_dict = msgpack.unpackb(reencoded_bytes, raw=False)

if 'txn' in reencoded_dict and 'apbx' in reencoded_dict['txn']:
    print(f"Boxes after re-encoding: {len(reencoded_dict['txn']['apbx'])} references")
    for i, box_ref in enumerate(reencoded_dict['txn']['apbx']):
        box_name = box_ref.get('n')
        box_addr = encoding.encode_address(box_name)
        print(f"  Box {i}: {box_addr}")
        print(f"         hex: {box_name.hex()}")
else:
    print("❌ NO BOXES after re-encoding!")

print()
print("Original box hex:  6af234a1cb087bfd285d2d5409ec98498d5de9568308e6b64dc0b97558977cd6")
if 'txn' in reencoded_dict and 'apbx' in reencoded_dict['txn']:
    reencoded_box_hex = reencoded_dict['txn']['apbx'][0]['n'].hex()
    print(f"Re-encoded box hex: {reencoded_box_hex}")
    print(f"Are they the same? {reencoded_box_hex == '6af234a1cb087bfd285d2d5409ec98498d5de9568308e6b64dc0b97558977cd6'}")
