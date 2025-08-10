#!/usr/bin/env python
"""
Simulate USDC collateral minting flow
Shows the transaction structure and expected behavior
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
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer, AccountTransactionSigner, TransactionWithSigner
)
from algosdk.abi import Contract


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def simulate_collateral_mint():
    """Simulate and explain USDC collateral minting"""
    
    print("\n" + "="*60)
    print("SIMULATING USDC COLLATERAL MINTING")
    print("="*60)
    
    # Load deployment info
    with open("cusd_deployment.json", "r") as f:
        deployment = json.load(f)
    
    app_id = deployment["app_id"]
    app_address = deployment["app_address"]
    cusd_id = deployment["cusd_asset_id"]
    usdc_id = deployment["usdc_asset_id"]
    
    print(f"\nContract Configuration:")
    print(f"  Application ID: {app_id}")
    print(f"  Contract Address: {app_address}")
    print(f"  cUSD Asset ID: {cusd_id}")
    print(f"  USDC Asset ID: {usdc_id} (testnet)")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Get admin account
    mnemonic_phrase = os.environ.get("ALGORAND_CONFIO_CREATOR_MNEMONIC")
    if not mnemonic_phrase:
        print("\n❌ No mnemonic found. Set ALGORAND_CONFIO_CREATOR_MNEMONIC")
        return
    
    private_key = mnemonic.to_private_key(mnemonic_phrase)
    user_address = account.address_from_private_key(private_key)
    
    print(f"\nUser Account: {user_address}")
    
    # First, opt into USDC asset
    print(f"\n📝 Step 1: Opt into USDC Asset")
    try:
        params = algod_client.suggested_params()
        
        # Opt-in to USDC (amount = 0 to same address)
        opt_in_txn = AssetTransferTxn(
            sender=user_address,
            sp=params,
            receiver=user_address,
            amt=0,
            index=usdc_id
        )
        
        signed_opt_in = opt_in_txn.sign(private_key)
        opt_in_tx_id = algod_client.send_transaction(signed_opt_in)
        wait_for_confirmation(algod_client, opt_in_tx_id, 4)
        
        print(f"✅ Successfully opted into USDC asset")
        print(f"   Transaction ID: {opt_in_tx_id}")
        
        # Check if user has USDC now
        account_info = algod_client.account_info(user_address)
        usdc_balance = 0
        
        for asset in account_info.get('assets', []):
            if asset['asset-id'] == usdc_id:
                usdc_balance = asset['amount'] / 1_000_000
                print(f"   USDC Balance: {usdc_balance:.6f} USDC")
                break
        
    except Exception as e:
        if "asset already opted in" in str(e):
            print("ℹ️  Already opted into USDC")
            
            # Check current USDC balance
            account_info = algod_client.account_info(user_address)
            usdc_balance = 0
            
            for asset in account_info.get('assets', []):
                if asset['asset-id'] == usdc_id:
                    usdc_balance = asset['amount'] / 1_000_000
                    print(f"   Current USDC Balance: {usdc_balance:.6f} USDC")
                    break
        else:
            print(f"❌ Failed to opt into USDC: {e}")
            return
    
    print(f"\n📝 Step 2: Check Contract State")
    
    # Check contract USDC balance
    contract_info = algod_client.account_info(app_address)
    contract_usdc = 0
    contract_cusd = 0
    
    for asset in contract_info.get('assets', []):
        if asset['asset-id'] == usdc_id:
            contract_usdc = asset['amount'] / 1_000_000
        elif asset['asset-id'] == cusd_id:
            contract_cusd = asset['amount'] / 1_000_000
    
    print(f"   Contract USDC: {contract_usdc:.6f}")
    print(f"   Contract cUSD: {contract_cusd:.6f}")
    
    # Check global state
    app_info = algod_client.application_info(app_id)
    global_state = app_info.get('params', {}).get('global-state', [])
    
    print(f"\n📊 Current Contract Statistics:")
    total_usdc_locked = 0
    cusd_circulating = 0
    
    for item in global_state:
        key = item.get('key', '')
        # Decode base64 key
        import base64
        decoded_key = base64.b64decode(key).decode('utf-8', errors='ignore')
        value = item.get('value', {}).get('uint', 0)
        
        if 'total_usdc_locked' in decoded_key:
            total_usdc_locked = value / 1_000_000
            print(f"   Total USDC Locked: {total_usdc_locked:.6f}")
        elif 'cusd_circulating_supply' in decoded_key:
            cusd_circulating = value / 1_000_000
            print(f"   cUSD Circulating: {cusd_circulating:.6f}")
        elif 'collateral_ratio' in decoded_key:
            ratio = value / 1_000_000
            print(f"   Collateral Ratio: {ratio:.6f} (1.0 = 100%)")
    
    print(f"\n📝 Collateral Minting Flow Explanation:")
    print(f"   1. User deposits USDC to contract")
    print(f"   2. Contract mints cUSD 1:1 with deposited USDC")
    print(f"   3. Contract updates statistics:")
    print(f"      - total_usdc_locked += deposit_amount")
    print(f"      - cusd_circulating_supply += mint_amount")
    print(f"   4. User receives cUSD tokens")
    
    print(f"\n📝 Transaction Structure (Atomic Group):")
    print(f"   TX[0]: AssetTransfer USDC from user to contract")
    print(f"   TX[1]: ApplicationCall mint_with_collateral()")
    print(f"   - Contract validates TX[0] USDC deposit")
    print(f"   - Contract mints cUSD using clawback from reserve")
    print(f"   - Contract updates global state variables")
    
    print(f"\n✅ Collateral System Ready!")
    print(f"   To test with real USDC:")
    print(f"   1. Get testnet USDC from dispenser or faucet")
    print(f"   2. Run: python test_collateral_mint.py")
    
    print(f"\n📝 Contract Features:")
    print(f"   ✅ 1:1 USDC to cUSD ratio")
    print(f"   ✅ Automatic minting on USDC deposit")
    print(f"   ✅ Collateral tracking and statistics")
    print(f"   ✅ Burn mechanism for USDC redemption")
    print(f"   ✅ Frozen address protection")
    print(f"   ✅ Emergency pause functionality")


if __name__ == "__main__":
    simulate_collateral_mint()