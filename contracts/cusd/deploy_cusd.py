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
from algosdk.transaction import AssetConfigTxn, PaymentTxn
from algosdk.logic import get_application_address
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, TransactionWithSigner
from algosdk.abi import Contract
from algosdk.account import AccountTransactionSigner
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
    print("\nYou'll need at least 2 ALGO for deployment")
    
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
    # Based on our contract state variables (including new reserve_address)
    global_schema = StateSchema(
        num_uints=9,  # 9 global uints in contract
        num_byte_slices=2  # admin address + reserve_address
    )
    
    local_schema = StateSchema(
        num_uints=2,  # is_frozen, is_vault
        num_byte_slices=0
    )
    
    # Get suggested parameters
    params = algod_client.suggested_params()
    
    # Create application transaction (NO ABI selector for create)
    txn = ApplicationCreateTxn(
        sender=deployer_address,
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=[]  # No args for bare create call
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

def create_cusd_asset(creator_private_key, creator_address, app_address):
    """Create the cUSD asset (ASA) with app as clawback and freeze"""
    
    params = algod_client.suggested_params()
    
    # Create cUSD asset with app as clawback/freeze
    txn = AssetConfigTxn(
        sender=creator_address,
        sp=params,
        total=10_000_000_000_000,  # 10 trillion units (with 6 decimals = 10 million cUSD)
        default_frozen=False,
        unit_name="cUSD",
        asset_name="Confío Dollar",
        manager=creator_address,  # Can update asset config
        reserve=creator_address,  # Holds non-circulating supply
        freeze=app_address,       # App controls freezing
        clawback=app_address,     # App controls clawback for minting
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
    print(f"Clawback: {app_address}")
    print(f"Freeze: {app_address}")
    
    return asset_id

def setup_assets(app_id, app_address, cusd_asset_id, usdc_asset_id, admin_private_key, admin_address):
    """Call setup_assets on the contract to configure asset IDs"""
    
    print("\nSetting up assets in contract...")
    
    # Load ABI
    with open("cusd.json", "r") as f:
        abi_json = json.load(f)
    
    # Create contract interface
    contract = Contract.from_json(json.dumps(abi_json))
    
    # Get suggested parameters
    params = algod_client.suggested_params()
    
    # Create atomic transaction composer
    atc = AtomicTransactionComposer()
    
    # Create payment transaction (funding for opt-ins)
    payment_txn = PaymentTxn(
        sender=admin_address,
        sp=params,
        receiver=app_address,
        amt=600000  # 0.6 ALGO for opt-ins
    )
    
    # Create signer
    signer = AccountTransactionSigner(admin_private_key)
    
    # Add payment transaction
    atc.add_transaction(TransactionWithSigner(payment_txn, signer))
    
    # Setup params with proper fee for method call
    method_params = algod_client.suggested_params()
    method_params.flat_fee = True
    method_params.fee = 3000  # 3x min fee for app call + 2 inner transactions
    
    # Add method call for setup_assets
    atc.add_method_call(
        app_id=app_id,
        method=contract.get_method_by_name("setup_assets"),
        sender=admin_address,
        sp=method_params,
        signer=signer,
        method_args=[cusd_asset_id, usdc_asset_id]
    )
    
    # Execute transactions
    result = atc.execute(algod_client, 4)
    
    print(f"✅ Assets configured successfully!")
    print(f"Transaction IDs: {result.tx_ids}")
    
    return result

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
    if balance < 2:
        print(f"\n❌ Insufficient balance. Please fund the account with at least 2 ALGO")
        print(f"Address: {address}")
        return
    
    try:
        # Step 1: Deploy contract
        app_id, app_address = deploy_cusd_contract(private_key, address)
        
        # Step 2: Create cUSD asset with app as clawback/freeze
        cusd_asset_id = create_cusd_asset(private_key, address, app_address)
        
        # Step 3: Setup assets in the contract
        usdc_asset_id = 10458941  # Testnet USDC
        setup_result = setup_assets(app_id, app_address, cusd_asset_id, usdc_asset_id, private_key, address)
        
        # Save deployment info
        deployment_info = {
            "network": "testnet",
            "deployer_address": address,
            "app_id": app_id,
            "app_address": app_address,
            "cusd_asset_id": cusd_asset_id,
            "usdc_asset_id": usdc_asset_id,
            "deployment_status": "Complete - Contract deployed and configured"
        }
        
        with open("deployment_info.json", "w") as f:
            json.dump(deployment_info, f, indent=2)
        
        print("\n" + "="*60)
        print("DEPLOYMENT COMPLETE")
        print("="*60)
        print(f"Application ID: {app_id}")
        print(f"Application Address: {app_address}")
        print(f"cUSD Asset ID: {cusd_asset_id}")
        print(f"USDC Asset ID (testnet): {usdc_asset_id}")
        print("\n📁 Deployment info saved to deployment_info.json")
        
        print("\n" + "="*60)
        print("CONTRACT IS NOW READY")
        print("="*60)
        print("✅ Contract deployed")
        print("✅ cUSD asset created with app as clawback/freeze")
        print("✅ Assets configured in contract")
        print("\nThe contract can now:")
        print("- Mint cUSD via admin_mint")
        print("- Accept USDC collateral for minting")
        print("- Freeze/unfreeze addresses")
        print("- Manage collateral ratios")
        
    except Exception as e:
        print(f"\n❌ Deployment failed: {e}")
        import traceback
        traceback.print_exc()
        return

if __name__ == "__main__":
    main()