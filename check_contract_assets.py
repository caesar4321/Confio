#!/usr/bin/env python
"""
Check contract asset holdings
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


def check_assets():
    """Check contract asset holdings"""
    
    print("\n" + "="*60)
    print("CONTRACT ASSET STATUS")
    print("="*60)
    
    # Load deployment info
    with open("cusd_deployment.json", "r") as f:
        deployment = json.load(f)
    
    app_address = deployment["app_address"]
    cusd_id = deployment["cusd_asset_id"]
    usdc_id = deployment["usdc_asset_id"]
    
    print(f"\nContract Address: {app_address}")
    print(f"cUSD Asset ID: {cusd_id}")
    print(f"USDC Asset ID: {usdc_id}")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Check account info
    account_info = algod_client.account_info(app_address)
    
    print(f"\n📊 Account Balance:")
    print(f"   ALGO: {account_info.get('amount', 0) / 1_000_000:.6f}")
    
    print(f"\n📦 Asset Holdings:")
    assets = account_info.get('assets', [])
    
    if not assets:
        print("   No assets opted in yet")
    else:
        for asset in assets:
            asset_id = asset['asset-id']
            amount = asset['amount']
            
            if asset_id == cusd_id:
                print(f"   cUSD (ID: {asset_id}): {amount / 1_000_000:.6f} cUSD")
            elif asset_id == usdc_id:
                print(f"   USDC (ID: {asset_id}): {amount / 1_000_000:.6f} USDC")
            else:
                print(f"   Unknown Asset (ID: {asset_id}): {amount}")
    
    # Check if the contract is the creator's account (for cUSD)
    cusd_info = algod_client.asset_info(cusd_id)
    cusd_params = cusd_info.get('params', {})
    
    print(f"\n🪙 cUSD Asset Info:")
    print(f"   Total Supply: {cusd_params.get('total', 0) / 1_000_000:.2f} cUSD")
    print(f"   Reserve: {cusd_params.get('reserve')}")
    print(f"   Manager: {cusd_params.get('manager')}")
    print(f"   Clawback: {cusd_params.get('clawback')}")
    
    print(f"\n✅ Ready for:")
    print(f"   1. Admin minting (needs cUSD in reserve)")
    print(f"   2. USDC collateral minting (users deposit USDC)")


if __name__ == "__main__":
    check_assets()