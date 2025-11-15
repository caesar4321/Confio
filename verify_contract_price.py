#!/usr/bin/env python3
"""Verify the on-chain price setting for the contract"""
from algosdk.v2client import algod
import base64

client = algod.AlgodClient("", "https://testnet-api.4160.nodely.dev")
app_id = 749662493

# Get contract global state
app_info = client.application_info(app_id)
global_state = app_info['params'].get('global-state', [])

# Decode global state
for entry in global_state:
    key = base64.b64decode(entry['key']).decode('utf-8', errors='ignore')
    value = entry['value']
    
    if key == 'manual_price':
        price_micro_cusd = value.get('uint', 0)
        price_cusd = price_micro_cusd / 1_000_000
        print(f"Manual Price: ${price_cusd} per CONFIO")
        print(f"  (or {price_micro_cusd} micro-cUSD per CONFIO)")
    elif key == 'manual_active':
        active = value.get('uint', 0)
        print(f"Manual Price Active: {'Yes' if active == 1 else 'No'}")
