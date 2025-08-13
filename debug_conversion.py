#!/usr/bin/env python3
"""
Debug the conversion transaction to see why it's failing
"""

import os
import sys
import django
import base64
import json

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from algosdk import encoding
from algosdk.transaction import calculate_group_id
import msgpack

# The failed transaction data from the logs
signed_txns_json = '{"userSignedTxns":["gqNzaWfEQK3bm+B8pv/KRWYfRRvFWrSGs3x5CtaTFqXKTf1ba5/4mJehUYr3EVyvMYj4bPFRP+cGJD1dp0occjf7V8kUiQWjdHhuiqNmZWXNA+iiZnbOAz+W8qNnZW6sdGVzdG5ldC12MS4womdoxCBIY7UYpLPITsgQ8i1PEIHLD3HwWaesIN7GL39w5Qk6IqNncnDEIDCvZ47Bs1rRRzImiVYsW4M2qP8LgWVxvQTn4vF4FC7Homx2zgM/mtqkbm90ZcQbTWluIGJhbGFuY2UgdG9wLXVwIGZvciBjVVNEo3JjdsQgbufbQqEFWTkiuGhWghOXaVY8LxuSEP8HxyNANfqH+cGjc25kxCB5SmN/gNhmFj3JlNIFoQXj3bTBIpbsrGLjhD+076Q2oKR0eXBlo3BheQ==","gqNzaWfEQIZ+95u8ZiirIbyieH15PRpo4f0Z3h0PWDBXnqgtyYeUDCzruedHzsvmV5XkfZzMQdnKZKr7MjTeaZKPjx9BlA+jdHhuiqRhYW10zgAc1tCkYXJjdsQgfbYUu971jp9yAar2LwmswO3XyiEMvXW7nAy2F6lDWGaiZnbOAz+W8qNnZW6sdGVzdG5ldC12MS4womdoxCBIY7UYpLPITsgQ8i1PEIHLD3HwWaesIN7GL39w5Qk6IqNncnDEIDCvZ47Bs1rRRzImiVYsW4M2qP8LgWVxvQTn4vF4FC7Homx2zgM/mtqjc25kxCBu59tCoQVZOSK4aFaCE5dpVjwvG5IQ/wfHI0A1+of5waR0eXBlpWF4ZmVypHhhaWTOAJ+XPQ==","gqNzaWfEQH3bdR3BB14FKNX/m6Kiu0htXoa77Fdxq9MYn2yUBHTiDQi51EOVLeOXuBhGaPCyEg6CTpurDnbxsj3YMJc7uw2jdHhujKRhcGFhkcQEQmaxpqRhcGFzks4An5c9zixbe5mkYXBhdJHEIG7n20KhBVk5IrhoVoITl2lWPC8bkhD/B8cjQDX6h/nBpGFwaWTOLFt7jKNmZWXNC7iiZnbOAz+W8qNnZW6sdGVzdG5ldC12MS4womdoxCBIY7UYpLPITsgQ8i1PEIHLD3HwWaesIN7GL39w5Qk6IqNncnDEIDCvZ47Bs1rRRzImiVYsW4M2qP8LgWVxvQTn4vF4FC7Homx2zgM/mtqjc25kxCB5SmN/gNhmFj3JlNIFoQXj3bTBIpbsrGLjhD+076Q2oKR0eXBlpGFwcGw="],"groupId":"MK9njsGzWtFHMiaJVixbgzao/wuBZXG9BOfi8XgULsc=","sponsorTxIndex":0}'

data = json.loads(signed_txns_json)

print("="*60)
print("DEBUGGING CONVERSION TRANSACTION FAILURE")
print("="*60)

# Decode transactions
txns = []
for i, txn_b64 in enumerate(data['userSignedTxns']):
    txn_bytes = base64.b64decode(txn_b64)
    txn = msgpack.unpackb(txn_bytes)
    txns.append(txn)
    
    print(f"\nTransaction {i}:")
    print("-"*40)
    
    # Handle both signed and unsigned transaction formats
    txn_data = txn.get(b'txn', txn)
    
    # Get transaction type
    if b'type' in txn_data:
        tx_type = txn_data[b'type'].decode('utf-8')
        print(f"  Type: {tx_type}")
    
    # Get sender
    if b'snd' in txn_data:
        sender_bytes = txn_data[b'snd']
        sender = encoding.encode_address(sender_bytes)
        print(f"  Sender: {sender}")
    
    # Get receiver if payment or asset transfer
    if b'rcv' in txn_data:
        receiver_bytes = txn_data[b'rcv']
        receiver = encoding.encode_address(receiver_bytes)
        print(f"  Receiver: {receiver}")
    
    # Get amount
    if b'amt' in txn_data:
        amt = txn_data[b'amt']
        print(f"  Amount: {amt:,} microAlgos/microUnits")
    
    # Get fee
    if b'fee' in txn_data:
        fee = txn_data[b'fee']
        print(f"  Fee: {fee} microAlgos")
    
    # Get asset ID if asset transfer
    if b'xaid' in txn_data:
        asset_id = txn_data[b'xaid']
        print(f"  Asset ID: {asset_id}")
    
    # Get app ID if app call
    if b'apid' in txn_data:
        app_id = txn_data[b'apid']
        print(f"  App ID: {app_id}")
    
    # Get note
    if b'note' in txn_data:
        note = txn_data[b'note']
        try:
            note_str = note.decode('utf-8')
            print(f"  Note: {note_str}")
        except:
            print(f"  Note (hex): {note.hex()}")

print("\n" + "="*60)
print("TRANSACTION GROUP ANALYSIS")
print("="*60)

# Check group ID
txn0_data = txns[0].get(b'txn', txns[0])
if b'grp' in txn0_data:
    group_bytes = txn0_data[b'grp']
    group_b64 = base64.b64encode(group_bytes).decode('utf-8')
    print(f"Group ID from txn: {group_b64}")
    print(f"Group ID expected: {data['groupId']}")
    print(f"Match: {group_b64 == data['groupId']}")

# Identify the pattern
print("\nTransaction Pattern:")
if len(txns) == 3:
    print("  3-transaction group (Sponsored)")
    print("  Expected order:")
    print("    Tx 0: Payment from sponsor to user (fee funding)")
    print("    Tx 1: USDC transfer from user to app")
    print("    Tx 2: App call to mint_with_collateral")
    
    # Check if sponsor is the app call sender
    txn2_data = txns[2].get(b'txn', txns[2])
    if b'type' in txn2_data and txn2_data[b'type'] == b'appl':
        app_sender_bytes = txn2_data[b'snd']
        app_sender = encoding.encode_address(app_sender_bytes)
        print(f"\n  App call sender: {app_sender}")
        print(f"  Expected sponsor: PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY")
        print(f"  Is sponsor? {app_sender == 'PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY'}")

print("\n" + "="*60)
print("PROBLEM IDENTIFIED")
print("="*60)

# The actual problem
if len(txns) == 3:
    txn2_data = txns[2].get(b'txn', txns[2])
    if b'type' in txn2_data and txn2_data[b'type'] == b'appl':
        app_sender_bytes = txn2_data[b'snd']
        app_sender = encoding.encode_address(app_sender_bytes)
        if app_sender != 'PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY':
            print("❌ The app call is being sent by the USER, not the SPONSOR!")
            print(f"   App call sender: {app_sender}")
            print(f"   Should be sponsor: PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY")
            print("\nThis is why the contract assertion is failing.")
            print("The contract expects: Txn.sender() == app.state.sponsor_address")
            print("But the user is sending the app call instead of the sponsor.")
        else:
            print("✅ App call is correctly sent by the sponsor")