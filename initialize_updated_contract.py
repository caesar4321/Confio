#!/usr/bin/env python
"""
Initialize the updated cUSD contract by calling create method
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
from algosdk.transaction import ApplicationCallTxn, wait_for_confirmation, AssetConfigTxn
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


def initialize_contract():
    """Initialize the deployed contract"""
    
    print("\n" + "="*60)
    print("INITIALIZING cUSD CONTRACT")
    print("="*60)
    
    # Load deployment info
    with open("cusd_deployment_v2.json", "r") as f:
        deployment = json.load(f)
    
    app_id = deployment["app_id"]
    app_address = get_application_address(app_id)
    
    print(f"\nApplication ID: {app_id}")
    print(f"Application Address: {app_address}")
    
    # Update deployment file
    deployment["app_address"] = app_address
    
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
    
    # Load contract ABI
    with open("contracts/cusd_abi.json", "r") as f:
        contract_json = json.load(f)
    
    contract = Contract.from_json(json.dumps(contract_json))
    
    # Create ATC
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(private_key)
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    print("\nCalling create() method...")
    
    # Call create method
    atc.add_method_call(
        app_id=app_id,
        method=contract.get_method_by_name("create"),
        sender=address,
        sp=params,
        signer=signer,
        method_args=[]
    )
    
    try:
        # Execute transaction
        result = atc.execute(algod_client, 4)
        tx_id = result.tx_ids[0]
        
        print(f"\n✅ Contract initialized successfully!")
        print(f"   Transaction ID: {tx_id}")
        
        # Now create cUSD asset
        print("\n" + "="*60)
        print("CREATING cUSD ASSET")
        print("="*60)
        
        params = algod_client.suggested_params()
        
        asset_txn = AssetConfigTxn(
            sender=address,
            sp=params,
            total=2**64 - 1,  # Maximum possible supply
            default_frozen=False,
            unit_name="cUSD",
            asset_name="Confio Dollar V2",
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
        
        # Update deployment info
        deployment["cusd_asset_id"] = cusd_asset_id
        deployment["deployment_status"] = "Contract initialized. Needs asset setup."
        
        with open("cusd_deployment_v2.json", "w") as f:
            json.dump(deployment, f, indent=2)
        
        print(f"\n📝 Deployment info updated in cusd_deployment_v2.json")
        
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
        
    except Exception as e:
        print(f"\n❌ Failed to initialize: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    initialize_contract()