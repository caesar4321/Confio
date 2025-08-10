#!/usr/bin/env python
"""
Deploy cUSD contract and create cUSD token on Algorand

Contract Features:
- Dual backing: USDC collateral + T-bills reserves
- Admin minting for T-bills backed supply
- Automatic USDC collateral minting/burning
- Multi-sig support for admin transfer
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import django
import base64
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
                    # Remove quotes if present
                    value = value.strip('"').strip("'")
                    os.environ[key] = value

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCreateTxn, OnComplete, StateSchema, 
    AssetConfigTxn, wait_for_confirmation,
    ApplicationCallTxn
)
from algosdk.logic import get_application_address
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer, TransactionWithSigner, AccountTransactionSigner
)
from algosdk.abi import Contract, Method
from algosdk.account import address_from_private_key


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def compile_program(client, source_code):
    """Compile TEAL program"""
    compile_response = client.compile(source_code)
    return base64.b64decode(compile_response['result'])


def create_cusd_asset(algod_client, creator_private_key, creator_address):
    """Create the cUSD asset (ASA)"""
    
    print("\n" + "-" * 60)
    print("CREATING cUSD ASSET")
    print("-" * 60)
    
    params = algod_client.suggested_params()
    
    # Create cUSD asset with maximum possible supply (2^64 - 1)
    # This allows unlimited minting based on collateral
    txn = AssetConfigTxn(
        sender=creator_address,
        sp=params,
        total=2**64 - 1,  # Maximum possible supply (18,446,744,073,709,551,615 units)
        default_frozen=False,
        unit_name="cUSD",
        asset_name="Confío Dollar",
        manager=creator_address,  # Can update asset
        reserve=creator_address,  # Holds non-circulating supply
        freeze=creator_address,   # Can freeze accounts (for compliance)
        clawback=creator_address, # Needed for contract to mint
        url="confio.lat",
        decimals=6,
        metadata_hash=b"USD-pegged stablecoin by Confio".ljust(32, b' ')[:32]
    )
    
    # Sign and send transaction
    signed_txn = txn.sign(creator_private_key)
    
    print("Creating cUSD asset...")
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Transaction ID: {tx_id}")
    
    # Wait for confirmation
    print("Waiting for confirmation...")
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    asset_id = confirmed_txn["asset-index"]
    
    print(f"✅ cUSD asset created!")
    print(f"   Asset ID: {asset_id}")
    print(f"   Name: Confío Dollar")
    print(f"   Symbol: cUSD")
    
    return asset_id


def deploy_cusd_contract(algod_client, deployer_private_key, deployer_address):
    """Deploy the cUSD smart contract using ABI"""
    
    print("\n" + "-" * 60)
    print("DEPLOYING cUSD CONTRACT")
    print("-" * 60)
    
    # Read compiled TEAL programs
    with open("contracts/cusd_approval.teal", "r") as f:
        approval_source = f.read()
    
    with open("contracts/cusd_clear.teal", "r") as f:
        clear_source = f.read()
    
    # Read ABI
    with open("contracts/cusd.json", "r") as f:
        contract_json = json.load(f)
    
    print("Compiling TEAL programs...")
    
    # Compile programs
    approval_program = compile_program(algod_client, approval_source)
    clear_program = compile_program(algod_client, clear_source)
    
    # Define state schemas
    # Global state: admin(bytes), is_paused, cusd_asset_id, usdc_asset_id, 
    #               collateral_ratio, total_minted, total_burned, 
    #               total_usdc_locked, cusd_circulating_supply, tbills_backed_supply
    global_schema = StateSchema(
        num_uints=9,  # All numeric values
        num_byte_slices=1  # admin address
    )
    
    # Local state: is_frozen, is_vault
    local_schema = StateSchema(
        num_uints=2,
        num_byte_slices=0
    )
    
    # Get suggested parameters
    params = algod_client.suggested_params()
    
    # Create ATC for deployment
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(deployer_private_key)
    
    # Create the application with the create() method call
    create_method = Method.from_json(json.dumps({
        "name": "create",
        "args": [],
        "returns": {"type": "void"},
        "desc": "Initialize the Confío Dollar contract"
    }))
    
    # Add create app transaction with ABI method call
    # Use extra pages for large contract (3 extra pages = 4 total pages = 8KB)
    atc.add_method_call(
        app_id=0,  # 0 for create
        method=create_method,
        sender=deployer_address,
        sp=params,
        signer=signer,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        extra_pages=3  # Allow up to 8KB total (2KB per page)
    )
    
    # Execute transaction
    print("Deploying contract...")
    result = atc.execute(algod_client, 4)
    
    # Get app ID from result
    tx_id = result.tx_ids[0]
    confirmed_txn = algod_client.pending_transaction_info(tx_id)
    app_id = confirmed_txn['application-index']
    app_address = get_application_address(app_id)
    
    print(f"✅ Contract deployed!")
    print(f"   Application ID: {app_id}")
    print(f"   Application Address: {app_address}")
    print(f"   Transaction ID: {tx_id}")
    
    return app_id, app_address


def main():
    """Main deployment function"""
    
    print("\n" + "="*60)
    print("cUSD (CONFÍO DOLLAR) DEPLOYMENT")
    print("="*60)
    print("Website: https://confio.lat")
    
    algod_client = get_algod_client()
    
    # Check network status
    try:
        status = algod_client.status()
        print(f"\n✓ Connected to Algorand Testnet")
        print(f"  Current round: {status.get('last-round')}")
    except Exception as e:
        print(f"\n✗ Failed to connect: {e}")
        return
    
    # Get or create deployer account
    print("\n" + "-" * 60)
    print("DEPLOYER ACCOUNT")
    print("-" * 60)
    
    # First try to use the main CONFIO creator account
    mnemonic_phrase = os.environ.get("ALGORAND_CUSD_DEPLOYER_MNEMONIC") or \
                      os.environ.get("ALGORAND_CONFIO_CREATOR_MNEMONIC")
    
    if mnemonic_phrase:
        print("Using existing deployer account from environment")
        private_key = mnemonic.to_private_key(mnemonic_phrase)
        address = account.address_from_private_key(private_key)
    else:
        print("Creating new deployer account...")
        private_key, address = account.generate_account()
        mnemonic_phrase = mnemonic.from_private_key(private_key)
        print(f"\n⚠️  SAVE THIS MNEMONIC:")
        print(f"{mnemonic_phrase}")
        print(f"\nSet in environment:")
        print(f'export ALGORAND_CUSD_DEPLOYER_MNEMONIC="{mnemonic_phrase}"')
        print(f"\nAddress: {address}")
        print(f"\nFund this account at:")
        print(f"https://dispenser.testnet.aws.algodev.network/")
        print(f"\nPress Enter after funding to continue...")
        input()
    
    # Check balance
    account_info = algod_client.account_info(address)
    balance = account_info.get('amount', 0) / 1_000_000
    print(f"Account balance: {balance:.6f} ALGO")
    
    if balance < 1:
        print(f"\n❌ Insufficient balance. Need at least 1 ALGO")
        print(f"Fund account: {address}")
        return
    
    try:
        # Step 1: Deploy the contract
        app_id, app_address = deploy_cusd_contract(algod_client, private_key, address)
        
        # Step 2: Create cUSD asset
        cusd_asset_id = create_cusd_asset(algod_client, private_key, address)
        
        # Step 3: Save deployment info
        deployment_info = {
            "network": "testnet",
            "deployer_address": address,
            "app_id": app_id,
            "app_address": app_address,
            "cusd_asset_id": cusd_asset_id,
            "usdc_asset_id": 10458941,  # Testnet USDC
            "deployment_status": "Deployed. Next: setup_assets and rekey reserve"
        }
        
        with open("cusd_deployment.json", "w") as f:
            json.dump(deployment_info, f, indent=2)
        
        print("\n" + "="*60)
        print("DEPLOYMENT COMPLETE!")
        print("="*60)
        print(f"\n📊 DEPLOYMENT SUMMARY:")
        print(f"   Application ID: {app_id}")
        print(f"   Application Address: {app_address}")
        print(f"   cUSD Asset ID: {cusd_asset_id}")
        print(f"   USDC Asset ID: 10458941 (testnet)")
        
        print(f"\n📁 Saved to: cusd_deployment.json")
        
        print("\n" + "="*60)
        print("NEXT STEPS:")
        print("="*60)
        print("\n1. SETUP ASSETS in the contract:")
        print(f"   Run: python setup_cusd_assets.py")
        print(f"   This will configure cUSD ID: {cusd_asset_id}")
        print(f"   And USDC ID: 10458941")
        
        print("\n2. REKEY RESERVE ACCOUNT:")
        print(f"   The cUSD reserve must be rekeyed to: {app_address}")
        print(f"   This allows the contract to mint cUSD")
        
        print("\n3. TEST MINTING:")
        print(f"   - Admin minting (T-bills backed)")
        print(f"   - USDC collateral minting (automatic)")
        
        print("\n4. TRANSFER TO MULTI-SIG (optional):")
        print(f"   Call update_admin() to transfer control")
        
        print("\n📍 View on explorer:")
        print(f"   https://testnet.algoexplorer.io/application/{app_id}")
        print(f"   https://testnet.algoexplorer.io/asset/{cusd_asset_id}")
        
    except Exception as e:
        print(f"\n❌ Deployment failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # First compile the contract for testnet
    print("Compiling cUSD contract for testnet...")
    os.environ['ALGORAND_NETWORK'] = 'testnet'
    os.system("myvenv/bin/python contracts/cusd.py")
    
    # Then deploy
    main()