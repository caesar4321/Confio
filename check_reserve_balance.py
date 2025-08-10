#!/usr/bin/env python
"""
Check reserve account cUSD balance
"""

import os
import sys
import django
import json
from pathlib import Path

# Load environment variables from .env.algorand if it exists
env_file = Path('.env.algorand')
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    value = value.strip('"').strip("'")
                    os.environ[key] = value

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from algosdk.v2client import algod


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def check_reserve():
    """Check reserve account holdings"""
    
    print("\n" + "="*60)
    print("RESERVE ACCOUNT STATUS")
    print("="*60)
    
    # Load deployment info
    with open("cusd_deployment.json", "r") as f:
        deployment = json.load(f)
    
    reserve_address = deployment["deployer_address"]  # The deployer is also the reserve
    cusd_id = deployment["cusd_asset_id"]
    
    print(f"\nReserve Address: {reserve_address}")
    print(f"cUSD Asset ID: {cusd_id}")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Check account info
    account_info = algod_client.account_info(reserve_address)
    
    print(f"\n📊 Account Balance:")
    print(f"   ALGO: {account_info.get('amount', 0) / 1_000_000:.6f}")
    
    print(f"\n📦 Asset Holdings:")
    assets = account_info.get('assets', [])
    
    cusd_found = False
    for asset in assets:
        if asset['asset-id'] == cusd_id:
            cusd_found = True
            amount = asset['amount'] / 1_000_000
            print(f"   cUSD: {amount:.2f} cUSD")
            print(f"   (Raw amount: {asset['amount']})")
            
            if amount > 0:
                print(f"\n✅ Reserve has cUSD available for minting!")
            else:
                print(f"\n⚠️  Reserve has 0 cUSD - all tokens might be circulating")
    
    if not cusd_found:
        print(f"   ❌ Reserve has not opted into cUSD asset!")


if __name__ == "__main__":
    check_reserve()