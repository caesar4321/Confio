#!/usr/bin/env python
"""
Deploy updated cUSD contract with clawback minting fix
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
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
from algosdk.transaction import ApplicationCreateTxn, StateSchema, wait_for_confirmation, AssetConfigTxn
from algosdk.logic import get_application_address
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer, AccountTransactionSigner
)
from algosdk.abi import Contract

def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def deploy_contract():
    """Deploy the updated cUSD contract"""
    
    print("\n" + "="*60)
    print("DEPLOYING UPDATED cUSD CONTRACT")
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
    
    if balance < 2:
        print("\n❌ Insufficient balance. Need at least 2 ALGO for deployment and asset creation")
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
    
    # Create application
    txn = ApplicationCreateTxn(
        sender=address,
        sp=params,
        on_complete=0,  # NoOp
        approval_program=approval_binary,
        clear_program=clear_binary,
        global_schema=global_schema,
        local_schema=local_schema,
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
    
    # Create new cUSD asset
    print("\n" + "="*60)
    print("CREATING NEW cUSD ASSET")
    print("="*60)
    
    params = algod_client.suggested_params()
    
    asset_txn = AssetConfigTxn(
        sender=address,
        sp=params,
        total=2**64 - 1,  # Maximum possible supply
        default_frozen=False,
        unit_name="cUSD",
        asset_name="Confio Dollar",
        manager=address,
        reserve=address,
        freeze=address,
        clawback=address,  # Will be rekeyed to contract
        url="confio.lat",
        decimals=6,
        strict_empty_address_check=False
    )
    
    signed_asset_txn = asset_txn.sign(private_key)
    asset_tx_id = algod_client.send_transaction(signed_asset_txn)
    
    print(f"\nAsset creation transaction ID: {asset_tx_id}")
    confirmed_asset_txn = wait_for_confirmation(algod_client, asset_tx_id, 4)
    
    cusd_asset_id = confirmed_asset_txn["asset-index"]
    print(f"✅ cUSD Asset created! ID: {cusd_asset_id}")
    
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
        "deployment_status": "Contract deployed. Needs setup."
    }
    
    with open("cusd_deployment_v2.json", "w") as f:
        json.dump(deployment_info, f, indent=2)
    
    print(f"\n📝 Deployment info saved to cusd_deployment_v2.json")
    
    print("\n" + "="*60)
    print("NEXT STEPS:")
    print("="*60)
    print("\n1. Fund the contract:")
    print(f"   python fund_contract_v2.py")
    print("\n2. Setup assets in the contract:")
    print(f"   python setup_cusd_assets_v2.py")
    print("\n3. Rekey clawback to contract:")
    print(f"   python rekey_clawback_v2.py")
    print("\n4. Test admin minting:")
    print(f"   python test_admin_mint_v2.py")


if __name__ == "__main__":
    deploy_contract()