#!/usr/bin/env python
"""
Deploy fixed cUSD contract with proper clawback minting
Uses existing cUSD asset 744031413
"""

import os
import sys
import django
import json
import base64
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
from algosdk.transaction import ApplicationCreateTxn, StateSchema, wait_for_confirmation
from algosdk.logic import get_application_address
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer, AccountTransactionSigner
)
from algosdk.abi import Contract, Method

def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def deploy_contract():
    """Deploy the fixed cUSD contract"""
    
    print("\n" + "="*60)
    print("DEPLOYING FIXED cUSD CONTRACT")
    print("="*60)
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Get creator account
    mnemonic_phrase = os.environ.get("ALGORAND_CONFIO_CREATOR_MNEMONIC")
    if not mnemonic_phrase:
        print("\n❌ No mnemonic found. Set ALGORAND_CONFIO_CREATOR_MNEMONIC")
        return
    
    private_key = mnemonic.to_private_key(mnemonic_phrase)
    address = account.address_from_private_key(private_key)
    
    print(f"\nUsing account: {address}")
    
    # Check account balance
    account_info = algod_client.account_info(address)
    balance = account_info.get('amount', 0) / 1_000_000
    print(f"Account balance: {balance:.6f} ALGO")
    
    if balance < 1:
        print("\n❌ Insufficient balance. Need at least 1 ALGO for deployment")
        return
    
    # Load compiled contract
    with open("contracts/cusd_approval.teal", "r") as f:
        approval_program = f.read()
    
    with open("contracts/cusd_clear.teal", "r") as f:
        clear_program = f.read()
    
    # Compile programs
    approval_result = algod_client.compile(approval_program)
    approval_binary = base64.b64decode(approval_result["result"])
    
    clear_result = algod_client.compile(clear_program)
    clear_binary = base64.b64decode(clear_result["result"])
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    # Define state schemas
    global_schema = StateSchema(num_uints=12, num_byte_slices=1)
    local_schema = StateSchema(num_uints=2, num_byte_slices=0)
    
    # Create the create method selector for app args
    create_selector = bytes.fromhex("4c5c61ba")  # "create()void"
    
    # Create application with create method call
    txn = ApplicationCreateTxn(
        sender=address,
        sp=params,
        on_complete=0,  # NoOp
        approval_program=approval_binary,
        clear_program=clear_binary,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=[create_selector],  # Call create method on deployment
        extra_pages=3  # For large contract
    )
    
    # Sign and send
    signed_txn = txn.sign(private_key)
    tx_id = algod_client.send_transaction(signed_txn)
    
    print(f"\nDeployment transaction ID: {tx_id}")
    print("Waiting for confirmation...")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    
    app_id = confirmed_txn["application-index"]
    app_address = get_application_address(app_id)
    
    print(f"\n✅ Contract deployed successfully!")
    print(f"   Application ID: {app_id}")
    print(f"   Application Address: {app_address}")
    
    # Use existing cUSD asset
    cusd_asset_id = 744031413  # Existing cUSD asset
    
    # Get USDC asset ID from environment
    if os.getenv('USDC_ASSET_ID'):
        usdc_asset_id = int(os.getenv('USDC_ASSET_ID'))
    else:
        network = os.getenv('ALGORAND_NETWORK', 'testnet').lower()
        if network == 'mainnet':
            usdc_asset_id = 31566704  # Mainnet USDC
        else:
            usdc_asset_id = 10458941  # Testnet USDC
    
    # Save deployment info
    deployment_info = {
        "network": "testnet",
        "deployer_address": address,
        "app_id": app_id,
        "app_address": app_address,
        "cusd_asset_id": cusd_asset_id,
        "usdc_asset_id": usdc_asset_id,
        "deployment_status": "Contract deployed and initialized. Needs funding and asset setup.",
        "note": "Using existing cUSD asset 744031413"
    }
    
    with open("cusd_deployment_fixed.json", "w") as f:
        json.dump(deployment_info, f, indent=2)
    
    print(f"\n📝 Deployment info saved to cusd_deployment_fixed.json")
    
    print("\n" + "="*60)
    print("NEXT STEPS:")
    print("="*60)
    print("\n1. Fund the contract (0.5 ALGO):")
    print(f"   python fund_fixed_contract.py")
    print("\n2. Setup assets in the contract:")
    print(f"   python setup_fixed_assets.py")
    print("\n3. IMPORTANT: Rekey cUSD clawback to new contract:")
    print(f"   From: KKGQY57MM4EIC4DT4L56PSOMELE64H4BYJTCBT2DIWMPYX3ELFJR5PHPAA (old)")
    print(f"   To: {app_address} (new)")
    print("\n4. Test admin minting:")
    print(f"   python test_fixed_minting.py")


if __name__ == "__main__":
    deploy_contract()