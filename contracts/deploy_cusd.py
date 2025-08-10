#!/usr/bin/env python3
"""
Deploy cUSD contract to Algorand testnet
Website: https://confio.lat
"""

import os
import json
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import ApplicationCreateTxn, OnComplete, StateSchema, wait_for_confirmation
from algosdk.transaction import AssetConfigTxn, AssetOptInTxn
from algosdk.logic import get_application_address
import base64

# Testnet configuration
ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
ALGOD_TOKEN = ""  # No token needed for AlgoNode

# Initialize Algod client
algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

def create_account():
    """Create a new account for deployment"""
    private_key, address = account.generate_account()
    mn = mnemonic.from_private_key(private_key)
    
    print("=" * 60)
    print("NEW ACCOUNT CREATED")
    print("=" * 60)
    print(f"Address: {address}")
    print(f"Mnemonic: {mn}")
    print("=" * 60)
    print("\n⚠️  SAVE THIS MNEMONIC SECURELY! ⚠️")
    print("\nFund this account with testnet ALGO from:")
    print("https://testnet.algoexplorer.io/dispenser")
    print("or")
    print("https://bank.testnet.algorand.network/")
    print("\nYou'll need at least 1 ALGO for deployment")
    
    return private_key, address, mn

def check_balance(address):
    """Check account balance"""
    account_info = algod_client.account_info(address)
    balance = account_info.get('amount') / 1000000  # Convert microAlgos to Algos
    print(f"Account balance: {balance:.6f} ALGO")
    return balance

def compile_program(client, source_code):
    """Compile TEAL program"""
    compile_response = client.compile(source_code)
    return base64.b64decode(compile_response['result'])

def deploy_cusd_contract(deployer_private_key, deployer_address):
    """Deploy the cUSD contract"""
    
    # Read compiled TEAL programs
    with open("cusd_approval.teal", "r") as f:
        approval_source = f.read()
    
    with open("cusd_clear.teal", "r") as f:
        clear_source = f.read()
    
    print("\nCompiling TEAL programs...")
    
    # Compile programs
    approval_program = compile_program(algod_client, approval_source)
    clear_program = compile_program(algod_client, clear_source)
    
    # Define global and local state schemas
    # Based on our contract state variables
    global_schema = StateSchema(
        num_uints=10,  # All our global state values are uints
        num_byte_slices=1  # admin address
    )
    
    local_schema = StateSchema(
        num_uints=2,  # is_frozen, is_vault
        num_byte_slices=0
    )
    
    # Get suggested parameters
    params = algod_client.suggested_params()
    
    # Create application transaction
    txn = ApplicationCreateTxn(
        sender=deployer_address,
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema
    )
    
    # Sign transaction
    signed_txn = txn.sign(deployer_private_key)
    
    # Send transaction
    print("\nDeploying contract...")
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Transaction ID: {tx_id}")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    app_id = confirmed_txn['application-index']
    app_address = get_application_address(app_id)
    
    print(f"\n✅ Contract deployed successfully!")
    print(f"Application ID: {app_id}")
    print(f"Application Address: {app_address}")
    
    return app_id, app_address

def create_cusd_asset(creator_private_key, creator_address):
    """Create the cUSD asset (ASA)"""
    
    params = algod_client.suggested_params()
    
    # Create cUSD asset
    txn = AssetConfigTxn(
        sender=creator_address,
        sp=params,
        total=10_000_000_000_000,  # 10 trillion units (with 6 decimals = 10 million cUSD)
        default_frozen=False,
        unit_name="cUSD",
        asset_name="Confío Dollar",
        manager=creator_address,  # Can update asset
        reserve=creator_address,  # Holds non-circulating supply
        freeze=creator_address,   # Can freeze accounts
        clawback=creator_address, # Can clawback (needed for minting)
        url="https://confio.lat",
        decimals=6,
        metadata_hash=None
    )
    
    # Sign and send transaction
    signed_txn = txn.sign(creator_private_key)
    
    print("\nCreating cUSD asset...")
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Transaction ID: {tx_id}")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    asset_id = confirmed_txn['asset-index']
    
    print(f"\n✅ cUSD asset created successfully!")
    print(f"Asset ID: {asset_id}")
    print(f"Asset Name: Confío Dollar")
    print(f"Unit Name: cUSD")
    
    return asset_id

def main():
    """Main deployment function"""
    
    print("\n" + "="*60)
    print("CONFÍO DOLLAR (cUSD) - TESTNET DEPLOYMENT")
    print("="*60)
    
    # Check if we have existing credentials
    mnemonic_phrase = os.getenv("ALGORAND_MNEMONIC")
    
    if mnemonic_phrase:
        print("\nUsing existing account from ALGORAND_MNEMONIC environment variable")
        private_key = mnemonic.to_private_key(mnemonic_phrase)
        address = account.address_from_private_key(private_key)
    else:
        print("\nNo ALGORAND_MNEMONIC found. Creating new account...")
        private_key, address, mnemonic_phrase = create_account()
        
        print("\nPress Enter after funding the account to continue...")
        input()
    
    # Check balance
    balance = check_balance(address)
    if balance < 1:
        print(f"\n❌ Insufficient balance. Please fund the account with at least 1 ALGO")
        print(f"Address: {address}")
        return
    
    try:
        # Deploy contract
        app_id, app_address = deploy_cusd_contract(private_key, address)
        
        # Create cUSD asset
        cusd_asset_id = create_cusd_asset(private_key, address)
        
        # Save deployment info
        deployment_info = {
            "network": "testnet",
            "deployer_address": address,
            "app_id": app_id,
            "app_address": app_address,
            "cusd_asset_id": cusd_asset_id,
            "usdc_asset_id": 10458941,  # Testnet USDC
            "deployment_status": "Contract deployed, asset created. Run setup_assets next."
        }
        
        with open("deployment_info.json", "w") as f:
            json.dump(deployment_info, f, indent=2)
        
        print("\n" + "="*60)
        print("DEPLOYMENT SUMMARY")
        print("="*60)
        print(f"Application ID: {app_id}")
        print(f"Application Address: {app_address}")
        print(f"cUSD Asset ID: {cusd_asset_id}")
        print(f"USDC Asset ID (testnet): 10458941")
        print("\n📁 Deployment info saved to deployment_info.json")
        
        print("\n" + "="*60)
        print("NEXT STEPS")
        print("="*60)
        print("1. Rekey the cUSD reserve account to the application address")
        print(f"   to allow the contract to mint cUSD:")
        print(f"   Application Address: {app_address}")
        print("\n2. Call setup_assets() to configure the contract with:")
        print(f"   - cUSD Asset ID: {cusd_asset_id}")
        print(f"   - USDC Asset ID: 10458941")
        print("\n3. Test admin minting and USDC collateral minting")
        
    except Exception as e:
        print(f"\n❌ Deployment failed: {e}")
        return

if __name__ == "__main__":
    main()