#!/usr/bin/env python
"""
Test USDC collateral minting with existing test account
Account: SW3VSGM6DCZEL7WW6LPLTJORGHQD5IMCE4C7IR3WKT5YBCTZABJAGI6D5Q
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
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

from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import AssetTransferTxn, ApplicationOptInTxn, wait_for_confirmation
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer, AccountTransactionSigner, TransactionWithSigner
)
from algosdk.abi import Contract


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def test_with_existing_account():
    """Test collateral minting with existing account"""
    
    print("\n" + "="*60)
    print("TESTING USDC COLLATERAL WITH EXISTING ACCOUNT")
    print("="*60)
    
    # Test account address
    test_address = "SW3VSGM6DCZEL7WW6LPLTJORGHQD5IMCE4C7IR3WKT5YBCTZABJAGI6D5Q"
    
    # Load deployment info
    with open("cusd_deployment.json", "r") as f:
        deployment = json.load(f)
    
    app_id = deployment["app_id"]
    app_address = deployment["app_address"]
    cusd_id = deployment["cusd_asset_id"]
    usdc_id = deployment["usdc_asset_id"]
    
    print(f"\nContract Info:")
    print(f"  App ID: {app_id}")
    print(f"  cUSD Asset: {cusd_id}")
    print(f"  USDC Asset: {usdc_id}")
    
    print(f"\nTest Account: {test_address}")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Check account status
    try:
        account_info = algod_client.account_info(test_address)
        balance = account_info.get('amount', 0) / 1_000_000
        print(f"Account Balance: {balance:.6f} ALGO")
        
        # Check assets
        assets = account_info.get('assets', [])
        print(f"\nCurrent Assets:")
        
        has_usdc = False
        has_cusd = False
        usdc_balance = 0
        cusd_balance = 0
        
        for asset in assets:
            asset_id = asset['asset-id']
            amount = asset['amount']
            
            if asset_id == usdc_id:
                has_usdc = True
                usdc_balance = amount / 1_000_000
                print(f"  ✅ USDC: {usdc_balance:.6f}")
            elif asset_id == cusd_id:
                has_cusd = True
                cusd_balance = amount / 1_000_000
                print(f"  ✅ cUSD: {cusd_balance:.6f}")
            else:
                print(f"  Asset {asset_id}: {amount}")
        
        if not has_usdc:
            print(f"  ❌ No USDC - needs opt-in and tokens from faucet")
        if not has_cusd:
            print(f"  ❌ No cUSD - needs opt-in")
        
        # Check app opt-in status
        apps = account_info.get('apps-local-state', [])
        opted_into_app = any(app['id'] == app_id for app in apps)
        
        if opted_into_app:
            print(f"  ✅ Opted into cUSD app")
        else:
            print(f"  ❌ Not opted into cUSD app")
        
        print(f"\n📋 Steps needed for collateral testing:")
        print(f"   1. Opt into USDC asset (if not done)")
        print(f"   2. Get USDC from faucet: https://faucet.circle.com")
        print(f"   3. Opt into cUSD asset (if not done)")
        print(f"   4. Opt into cUSD app (if not done)")
        print(f"   5. Execute collateral mint transaction")
        
        if has_usdc and usdc_balance > 0:
            print(f"\n✅ Ready to test! Account has {usdc_balance:.6f} USDC")
            print(f"   Run the full collateral mint test")
        else:
            print(f"\n⏳ Waiting for USDC...")
            print(f"   Send testnet USDC to: {test_address}")
            print(f"   From: https://faucet.circle.com")
        
        # Show expected transaction flow
        print(f"\n📝 Collateral Mint Transaction Flow:")
        print(f"   TX[0]: Transfer USDC from user to contract")
        print(f"   TX[1]: Call mint_with_collateral()")
        print(f"   Result: User receives cUSD 1:1 with deposited USDC")
        
    except Exception as e:
        print(f"❌ Failed to check account: {e}")


def prepare_account_for_testing():
    """Prepare the test account for collateral minting"""
    
    # NOTE: This function would need the private key to execute
    # For now, just show what needs to be done
    
    test_address = "SW3VSGM6DCZEL7WW6LPLTJORGHQD5IMCE4C7IR3WKT5YBCTZABJAGI6D5Q"
    
    print(f"\n🔧 To prepare account {test_address} for testing:")
    print(f"   1. Opt into USDC asset {deployment['usdc_asset_id']}")
    print(f"   2. Opt into cUSD asset {deployment['cusd_asset_id']}")
    print(f"   3. Opt into cUSD app {deployment['app_id']}")
    print(f"   4. Get USDC from https://faucet.circle.com")
    
    print(f"\n⚠️  Need private key/mnemonic to execute opt-ins")


if __name__ == "__main__":
    test_with_existing_account()