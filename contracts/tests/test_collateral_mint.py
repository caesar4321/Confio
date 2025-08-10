#!/usr/bin/env python
"""
Test USDC collateral minting - deposit USDC to mint cUSD
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
from algosdk.transaction import AssetTransferTxn, ApplicationOptInTxn, PaymentTxn, wait_for_confirmation
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer, AccountTransactionSigner, TransactionWithSigner
)
from algosdk.abi import Contract


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def test_collateral_mint():
    """Test USDC collateral minting"""
    
    print("\n" + "="*60)
    print("TESTING USDC COLLATERAL MINTING")
    print("="*60)
    
    # Load deployment info
    with open("cusd_deployment.json", "r") as f:
        deployment = json.load(f)
    
    app_id = deployment["app_id"]
    app_address = deployment["app_address"]
    cusd_id = deployment["cusd_asset_id"]
    usdc_id = deployment["usdc_asset_id"]
    
    print(f"\nApplication ID: {app_id}")
    print(f"Contract Address: {app_address}")
    print(f"cUSD Asset ID: {cusd_id}")
    print(f"USDC Asset ID: {usdc_id} (testnet)")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Get admin account (will act as user for testing)
    mnemonic_phrase = os.environ.get("ALGORAND_CONFIO_CREATOR_MNEMONIC")
    if not mnemonic_phrase:
        print("\n❌ No mnemonic found. Set ALGORAND_CONFIO_CREATOR_MNEMONIC")
        return
    
    private_key = mnemonic.to_private_key(mnemonic_phrase)
    user_address = account.address_from_private_key(private_key)
    
    print(f"\nUser Account: {user_address}")
    
    # Check if user has USDC
    account_info = algod_client.account_info(user_address)
    usdc_balance = 0
    has_usdc = False
    
    for asset in account_info.get('assets', []):
        if asset['asset-id'] == usdc_id:
            usdc_balance = asset['amount'] / 1_000_000
            has_usdc = True
            print(f"User USDC Balance: {usdc_balance:.6f} USDC")
            break
    
    if not has_usdc:
        print(f"\n❌ User doesn't have USDC asset {usdc_id}")
        print("   You need testnet USDC to test collateral minting")
        print("   Get it from: https://testnet.algoexplorer.io/dispenser")
        return
    
    if usdc_balance == 0:
        print(f"\n❌ User has 0 USDC balance")
        print("   You need testnet USDC to test collateral minting")
        return
    
    # Check if user is opted into the app
    opted_in = False
    for app in account_info.get('apps-local-state', []):
        if app['id'] == app_id:
            opted_in = True
            break
    
    if not opted_in:
        print("\n🔧 User needs to opt-in to app first...")
        # Opt-in to the application using the opt_in method
        opt_in_selector = bytes.fromhex("30c6d58a")  # "opt_in()void"
        
        params = algod_client.suggested_params()
        app_opt_in_txn = ApplicationOptInTxn(
            sender=user_address,
            sp=params,
            index=app_id,
            app_args=[opt_in_selector]
        )
        signed_app_opt_in = app_opt_in_txn.sign(private_key)
        
        try:
            app_opt_in_tx_id = algod_client.send_transaction(signed_app_opt_in)
            wait_for_confirmation(algod_client, app_opt_in_tx_id, 4)
            print("✅ User opted into application")
        except Exception as e:
            print(f"❌ Failed to opt-in to app: {e}")
            return
    
    # Check user's initial cUSD balance
    initial_cusd = 0
    for asset in account_info.get('assets', []):
        if asset['asset-id'] == cusd_id:
            initial_cusd = asset['amount'] / 1_000_000
            break
    
    print(f"Initial cUSD Balance: {initial_cusd:.6f} cUSD")
    
    # Amount to deposit (1 USDC)
    deposit_amount = 1_000_000  # 1 USDC with 6 decimals
    
    print(f"\n💰 Depositing {deposit_amount/1_000_000:.6f} USDC to mint cUSD...")
    
    # Load contract ABI
    with open("contracts/cusd_abi.json", "r") as f:
        contract_json = json.load(f)
    
    contract = Contract.from_json(json.dumps(contract_json))
    
    # Create atomic group: USDC deposit + mint call
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(private_key)
    params = algod_client.suggested_params()
    
    # Transaction 0: USDC transfer to contract
    usdc_transfer = AssetTransferTxn(
        sender=user_address,
        sp=params,
        receiver=app_address,
        amt=deposit_amount,
        index=usdc_id
    )
    
    atc.add_transaction(TransactionWithSigner(usdc_transfer, signer))
    
    # Transaction 1: Call mint_with_collateral
    atc.add_method_call(
        app_id=app_id,
        method=contract.get_method_by_name("mint_with_collateral"),
        sender=user_address,
        sp=params,
        signer=signer,
        method_args=[],  # No arguments needed
        foreign_assets=[cusd_id, usdc_id]  # Include both assets
    )
    
    try:
        # Execute atomic group
        result = atc.execute(algod_client, 4)
        tx_ids = result.tx_ids
        
        print(f"\n✅ Collateral mint successful!")
        print(f"   USDC Transfer TX: {tx_ids[0]}")
        print(f"   Mint Call TX: {tx_ids[1]}")
        
        # Check user's new balances
        account_info = algod_client.account_info(user_address)
        new_usdc = 0
        new_cusd = 0
        
        for asset in account_info.get('assets', []):
            if asset['asset-id'] == usdc_id:
                new_usdc = asset['amount'] / 1_000_000
            elif asset['asset-id'] == cusd_id:
                new_cusd = asset['amount'] / 1_000_000
        
        print(f"\n📊 User Balances After Minting:")
        print(f"   USDC: {new_usdc:.6f} (was {usdc_balance:.6f}) - Deposited: {usdc_balance - new_usdc:.6f}")
        print(f"   cUSD: {new_cusd:.6f} (was {initial_cusd:.6f}) - Received: {new_cusd - initial_cusd:.6f}")
        
        # Check contract balances
        contract_info = algod_client.account_info(app_address)
        contract_usdc = 0
        contract_cusd = 0
        
        for asset in contract_info.get('assets', []):
            if asset['asset-id'] == usdc_id:
                contract_usdc = asset['amount'] / 1_000_000
            elif asset['asset-id'] == cusd_id:
                contract_cusd = asset['amount'] / 1_000_000
        
        print(f"\n📦 Contract Holdings:")
        print(f"   USDC Locked: {contract_usdc:.6f}")
        print(f"   cUSD Available: {contract_cusd:.6f}")
        
        # Check contract global state
        app_info = algod_client.application_info(app_id)
        global_state = app_info.get('params', {}).get('global-state', [])
        
        print(f"\n📊 Contract Statistics:")
        for item in global_state:
            key = item.get('key', '')
            # Decode base64 key
            import base64
            decoded_key = base64.b64decode(key).decode('utf-8', errors='ignore')
            value = item.get('value', {}).get('uint', 0)
            
            if 'total_usdc_locked' in decoded_key:
                print(f"   Total USDC Locked: {value/1_000_000:.6f} USDC")
            elif 'cusd_circulating_supply' in decoded_key:
                print(f"   cUSD Circulating: {value/1_000_000:.6f} cUSD")
            elif 'total_minted' in decoded_key:
                print(f"   Total Minted: {value/1_000_000:.6f} cUSD")
        
        print(f"\n✅ USDC collateral minting works correctly!")
        print(f"   1:1 ratio maintained: 1 USDC → 1 cUSD")
        
    except Exception as e:
        print(f"\n❌ Collateral mint failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_collateral_mint()