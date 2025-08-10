#!/usr/bin/env python
"""
Opt-in test account SW3VSGM6DCZEL7WW6LPLTJORGHQD5IMCE4C7IR3WKT5YBCTZABJAGI6D5Q
to USDC, cUSD assets and cUSD app
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

from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import AssetTransferTxn, ApplicationOptInTxn, wait_for_confirmation


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def find_test_account_key():
    """Try to find the test account private key"""
    
    test_address = "SW3VSGM6DCZEL7WW6LPLTJORGHQD5IMCE4C7IR3WKT5YBCTZABJAGI6D5Q"
    
    # Check common environment variables
    possible_env_vars = [
        "TEST_ACCOUNT_MNEMONIC",
        "TEST_ACCOUNT_PRIVATE_KEY", 
        "ALGORAND_TEST_MNEMONIC",
        "PYTHON_SDK_ACCOUNT_MNEMONIC"
    ]
    
    for env_var in possible_env_vars:
        value = os.environ.get(env_var)
        if value:
            try:
                if len(value.split()) == 25:  # Mnemonic
                    private_key = mnemonic.to_private_key(value)
                    derived_address = account.address_from_private_key(private_key)
                    if derived_address == test_address:
                        print(f"✅ Found test account key in {env_var}")
                        return private_key
                else:  # Might be hex private key
                    private_key = bytes.fromhex(value)
                    derived_address = account.address_from_private_key(private_key)
                    if derived_address == test_address:
                        print(f"✅ Found test account key in {env_var}")
                        return private_key
            except:
                continue
    
    print(f"❌ Could not find private key for {test_address}")
    print(f"   Please set one of these environment variables:")
    for var in possible_env_vars:
        print(f"   - {var}")
    print(f"   Example: export TEST_ACCOUNT_MNEMONIC='word1 word2 ... word25'")
    
    return None


def opt_in_assets():
    """Opt-in to USDC, cUSD, and cUSD app"""
    
    print("\n" + "="*60)
    print("OPTING IN TEST ACCOUNT TO ASSETS & APP")
    print("="*60)
    
    test_address = "SW3VSGM6DCZEL7WW6LPLTJORGHQD5IMCE4C7IR3WKT5YBCTZABJAGI6D5Q"
    
    # Find private key
    private_key = find_test_account_key()
    if not private_key:
        return False
    
    # Load deployment info
    with open("cusd_deployment.json", "r") as f:
        deployment = json.load(f)
    
    app_id = deployment["app_id"]
    cusd_id = deployment["cusd_asset_id"]
    usdc_id = deployment["usdc_asset_id"]
    
    print(f"\nAccount: {test_address}")
    print(f"USDC Asset: {usdc_id}")
    print(f"cUSD Asset: {cusd_id}")
    print(f"cUSD App: {app_id}")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Check current status
    account_info = algod_client.account_info(test_address)
    balance = account_info.get('amount', 0) / 1_000_000
    print(f"Account Balance: {balance:.6f} ALGO")
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    # Check and opt-in to USDC
    has_usdc = any(asset['asset-id'] == usdc_id for asset in account_info.get('assets', []))
    
    if not has_usdc:
        print(f"\n📝 Step 1: Opt into USDC asset...")
        try:
            usdc_opt_in = AssetTransferTxn(
                sender=test_address,
                sp=params,
                receiver=test_address,
                amt=0,
                index=usdc_id
            )
            
            signed_usdc = usdc_opt_in.sign(private_key)
            usdc_tx_id = algod_client.send_transaction(signed_usdc)
            wait_for_confirmation(algod_client, usdc_tx_id, 4)
            
            print(f"✅ Opted into USDC")
            print(f"   TX ID: {usdc_tx_id}")
            
        except Exception as e:
            print(f"❌ USDC opt-in failed: {e}")
            return False
    else:
        print(f"✅ Already opted into USDC")
    
    # Check and opt-in to cUSD
    has_cusd = any(asset['asset-id'] == cusd_id for asset in account_info.get('assets', []))
    
    if not has_cusd:
        print(f"\n📝 Step 2: Opt into cUSD asset...")
        try:
            cusd_opt_in = AssetTransferTxn(
                sender=test_address,
                sp=params,
                receiver=test_address,
                amt=0,
                index=cusd_id
            )
            
            signed_cusd = cusd_opt_in.sign(private_key)
            cusd_tx_id = algod_client.send_transaction(signed_cusd)
            wait_for_confirmation(algod_client, cusd_tx_id, 4)
            
            print(f"✅ Opted into cUSD")
            print(f"   TX ID: {cusd_tx_id}")
            
        except Exception as e:
            print(f"❌ cUSD opt-in failed: {e}")
            return False
    else:
        print(f"✅ Already opted into cUSD")
    
    # Check and opt-in to cUSD app
    account_info = algod_client.account_info(test_address)  # Refresh
    has_app = any(app['id'] == app_id for app in account_info.get('apps-local-state', []))
    
    if not has_app:
        print(f"\n📝 Step 3: Opt into cUSD app...")
        try:
            # Use the opt_in method selector
            opt_in_selector = bytes.fromhex("30c6d58a")  # "opt_in()void"
            
            app_opt_in = ApplicationOptInTxn(
                sender=test_address,
                sp=params,
                index=app_id,
                app_args=[opt_in_selector]
            )
            
            signed_app = app_opt_in.sign(private_key)
            app_tx_id = algod_client.send_transaction(signed_app)
            wait_for_confirmation(algod_client, app_tx_id, 4)
            
            print(f"✅ Opted into cUSD app")
            print(f"   TX ID: {app_tx_id}")
            
        except Exception as e:
            print(f"❌ App opt-in failed: {e}")
            return False
    else:
        print(f"✅ Already opted into cUSD app")
    
    print(f"\n🎉 SUCCESS! Account is ready for collateral testing")
    print(f"\n📋 Next Steps:")
    print(f"   1. Get testnet USDC from: https://faucet.circle.com")
    print(f"   2. Send USDC to: {test_address}")
    print(f"   3. Run collateral mint test")
    
    return True


if __name__ == "__main__":
    opt_in_assets()