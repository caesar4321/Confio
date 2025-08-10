#!/usr/bin/env python
"""
Setup cUSD contract with asset IDs
This configures the deployed contract with cUSD and USDC asset IDs
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
from algosdk.transaction import ApplicationCallTxn, wait_for_confirmation
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer, AccountTransactionSigner
)
from algosdk.abi import Contract


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def setup_assets():
    """Setup asset IDs in the deployed contract"""
    
    print("\n" + "="*60)
    print("UPDATED cUSD CONTRACT - ASSET SETUP")
    print("="*60)
    
    # Load deployment info
    with open("cusd_deployment_v2.json", "r") as f:
        deployment = json.load(f)
    
    app_id = deployment["app_id"]
    cusd_asset_id = deployment["cusd_asset_id"]
    usdc_asset_id = deployment["usdc_asset_id"]
    
    print(f"\nContract Info:")
    print(f"  Application ID: {app_id}")
    print(f"  cUSD Asset ID: {cusd_asset_id}")
    print(f"  USDC Asset ID: {usdc_asset_id}")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Get admin account (deployer)
    mnemonic_phrase = os.environ.get("ALGORAND_CONFIO_CREATOR_MNEMONIC")
    if not mnemonic_phrase:
        print("\n❌ No mnemonic found. Set ALGORAND_CONFIO_CREATOR_MNEMONIC")
        return
    
    private_key = mnemonic.to_private_key(mnemonic_phrase)
    address = account.address_from_private_key(private_key)
    
    print(f"\nUsing admin account: {address}")
    
    # Load contract ABI
    with open("contracts/cusd_abi.json", "r") as f:
        contract_json = json.load(f)
    
    contract = Contract.from_json(json.dumps(contract_json))
    
    # Create ATC
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(private_key)
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    print("\nCalling setup_assets...")
    
    # Call setup_assets method
    # Need to include both assets in foreign assets array for inner transactions
    atc.add_method_call(
        app_id=app_id,
        method=contract.get_method_by_name("setup_assets"),
        sender=address,
        sp=params,
        signer=signer,
        method_args=[cusd_asset_id, usdc_asset_id],
        foreign_assets=[cusd_asset_id, usdc_asset_id]  # Include both assets
    )
    
    try:
        # Execute transaction
        result = atc.execute(algod_client, 4)
        tx_id = result.tx_ids[0]
        
        print(f"\n✅ Assets configured successfully!")
        print(f"   Transaction ID: {tx_id}")
        print(f"   cUSD Asset ID: {cusd_asset_id}")
        print(f"   USDC Asset ID: {usdc_asset_id}")
        
        # Update deployment status
        deployment["deployment_status"] = "Assets configured. Ready for clawback rekey!"
        with open("cusd_deployment_v2.json", "w") as f:
            json.dump(deployment, f, indent=2)
        
        print("\n" + "="*60)
        print("NEXT STEPS:")
        print("="*60)
        print("\n1. REKEY CLAWBACK to contract:")
        print(f"   The cUSD clawback must be rekeyed to the app address")
        print(f"   App Address: {deployment['app_address']}")
        print("\n2. TEST ADMIN MINTING:")
        print(f"   python test_admin_mint_v2.py")
        print("\n3. TEST USDC COLLATERAL:")
        print(f"   Deposit USDC to mint cUSD automatically")
        
    except Exception as e:
        print(f"\n❌ Failed to setup assets: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    setup_assets()