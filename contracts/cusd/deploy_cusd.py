#!/usr/bin/env python3
"""
Deploy cUSD contract to Algorand testnet
Website: https://confio.lat
"""

import os
import json
import sys
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import ApplicationCreateTxn, ApplicationUpdateTxn, OnComplete, StateSchema, wait_for_confirmation
from algosdk.transaction import AssetConfigTxn, PaymentTxn, AssetTransferTxn
from algosdk.logic import get_application_address
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, TransactionWithSigner
from algosdk.abi import Contract
from algosdk.transaction import ApplicationCallTxn
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
    # Based on our contract state variables (including new sponsor_address)
    global_schema = StateSchema(
        num_uints=9,  # 9 global uints in contract
        num_byte_slices=3  # admin address + reserve_address + sponsor_address
    )
    
    local_schema = StateSchema(
        num_uints=2,  # is_frozen, is_vault
        num_byte_slices=0
    )
    
    # Get suggested parameters
    params = algod_client.suggested_params()
    
    # Create application transaction with method selector
    # The contract expects "create()void" selector: 0x4c5c61ba
    create_method_selector = bytes.fromhex("4c5c61ba")
    
    txn = ApplicationCreateTxn(
        sender=deployer_address,
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=[create_method_selector],  # Pass create method selector
        extra_pages=3  # Use 3 extra pages for large contract (4 pages total = 8KB)
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

def update_cusd_contract(app_id, admin_private_key, admin_address):
    """Update an existing cUSD contract"""
    
    # Read compiled TEAL programs
    with open("cusd_approval.teal", "r") as f:
        approval_source = f.read()
    
    with open("cusd_clear.teal", "r") as f:
        clear_source = f.read()
    
    print("\nCompiling TEAL programs for update...")
    
    # Compile programs
    approval_program = compile_program(algod_client, approval_source)
    clear_program = compile_program(algod_client, clear_source)
    
    print(f"Approval program size: {len(approval_program)} bytes")
    print(f"Clear program size: {len(clear_program)} bytes")
    
    # Get suggested parameters
    params = algod_client.suggested_params()
    
    # For Beaker contracts, we need to provide the method selector even for updates
    # The update method selector for Beaker's @app.update decorator
    update_selector = bytes.fromhex("a0e81872")  # update()void
    
    # Create update transaction with method selector
    txn = ApplicationUpdateTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        approval_program=approval_program,
        clear_program=clear_program,
        app_args=[update_selector]  # Include the update method selector
    )
    
    # Sign transaction
    signed_txn = txn.sign(admin_private_key)
    
    # Send transaction
    print("\nUpdating contract...")
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Transaction ID: {tx_id}")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    
    print(f"\n✅ Contract updated successfully!")
    print(f"Update confirmed in round: {confirmed_txn.get('confirmed-round', 0)}")
    
    return True

def set_sponsor_address(app_id, admin_private_key, admin_address, sponsor_address=None):
    """Set the sponsor address in the contract"""
    from algosdk.abi import Method, Returns, Argument
    from algosdk import encoding
    
    # Use admin address as sponsor if not specified
    if sponsor_address is None:
        sponsor_address = admin_address
    
    print(f"\nSetting sponsor address to: {sponsor_address}")
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    # Create method selector for set_sponsor_address
    method = Method(
        name="set_sponsor_address",
        args=[Argument(arg_type="address", name="sponsor")],
        returns=Returns("void")
    )
    
    selector = method.get_selector()
    sponsor_bytes = encoding.decode_address(sponsor_address)
    
    # Create app call
    txn = ApplicationCallTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        on_complete=0,  # NoOp
        app_args=[selector, sponsor_bytes]
    )
    
    # Sign and send
    signed_txn = txn.sign(admin_private_key)
    tx_id = algod_client.send_transaction(signed_txn)
    
    print(f"Set sponsor transaction sent: {tx_id}")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    print(f"✅ Sponsor address set successfully in round {confirmed_txn.get('confirmed-round', 0)}")
    
    return True

def create_cusd_asset(creator_private_key, creator_address, app_address):
    """Create the cUSD asset (ASA) with app holding all reserve"""
    
    params = algod_client.suggested_params()
    
    # Maximum possible supply (2^64 - 1)
    MAX_UINT64 = 18_446_744_073_709_551_615
    
    # Create cUSD asset with CONTRACT as reserve holder
    txn = AssetConfigTxn(
        sender=creator_address,
        sp=params,
        total=MAX_UINT64,         # Maximum possible supply
        default_frozen=False,
        unit_name="cUSD",
        asset_name="Confío Dollar",
        manager=creator_address,  # Can update asset config
        reserve=app_address,      # CONTRACT holds ALL supply - no backdoor!
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
    print(f"Total Supply: {MAX_UINT64:,} units (max possible)")
    print(f"Initial holder: {creator_address} (temporary)")
    print(f"Reserve field: {app_address}")
    print(f"Clawback: {app_address}")
    print(f"Freeze: {app_address}")
    
    # IMPORTANT: Transfer all tokens to the app
    print(f"\n🔄 Transferring all cUSD to contract...")
    print(f"This ensures no backdoor minting is possible")
    
    # First, app needs to opt-in to the asset (will be done in setup_assets)
    # The transfer will happen after setup_assets
    
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
    
    # Create signer using a lambda function
    class SimpleSigner:
        def __init__(self, private_key):
            self.private_key = private_key
        def sign_transactions(self, txns, indexes):
            return [txn.sign(self.private_key) for txn in txns]
    
    signer = SimpleSigner(admin_private_key)
    
    # Add payment transaction
    atc.add_transaction(TransactionWithSigner(payment_txn, signer))
    
    # Setup params with proper fee for method call
    method_params = algod_client.suggested_params()
    method_params.flat_fee = True
    method_params.fee = 3000  # 3x min fee for app call + 2 inner transactions
    
    # Add method call for setup_assets with foreign assets
    atc.add_method_call(
        app_id=app_id,
        method=contract.get_method_by_name("setup_assets"),
        sender=admin_address,
        sp=method_params,
        signer=signer,
        method_args=[cusd_asset_id, usdc_asset_id],
        foreign_assets=[cusd_asset_id, usdc_asset_id]  # Include assets in transaction
    )
    
    # Execute transactions
    result = atc.execute(algod_client, 4)
    
    print(f"✅ Assets configured successfully!")
    print(f"Transaction IDs: {result.tx_ids}")
    
    return result

def main():
    """Main deployment function"""
    
    # Check command line arguments
    update_mode = len(sys.argv) > 1 and sys.argv[1] == "update"
    
    if update_mode:
        print("\n" + "="*60)
        print("CONFÍO DOLLAR (cUSD) - CONTRACT UPDATE")
        print("="*60)
    else:
        print("\n" + "="*60)
        print("CONFÍO DOLLAR (cUSD) - TESTNET DEPLOYMENT")
        print("="*60)
    
    # Check if we have existing credentials
    mnemonic_phrase = os.getenv("ALGORAND_SPONSOR_MNEMONIC")
    
    if mnemonic_phrase:
        print("\nUsing existing sponsor account from ALGORAND_SPONSOR_MNEMONIC environment variable")
        private_key = mnemonic.to_private_key(mnemonic_phrase)
        address = account.address_from_private_key(private_key)
    else:
        if update_mode:
            print("\n❌ ALGORAND_SPONSOR_MNEMONIC required for update mode")
            return
        print("\nNo ALGORAND_SPONSOR_MNEMONIC found. Creating new account...")
        private_key, address, mnemonic_phrase = create_account()
        
        print("\nPress Enter after funding the account to continue...")
        input()
    
    # Check balance
    balance = check_balance(address)
    if balance < 0.1:
        print(f"\n❌ Insufficient balance. Please fund the account")
        print(f"Address: {address}")
        return
    
    try:
        if update_mode:
            # Update existing contract
            app_id = 744192908  # New testnet contract with sponsor support
            print(f"\nUpdating existing contract: {app_id}")
            
            # Build the contract first
            print("\nBuilding contract...")
            os.system("../../myvenv/bin/python build_contracts.py")
            
            # Update the contract
            if update_cusd_contract(app_id, private_key, address):
                # Set sponsor address after update
                set_sponsor_address(app_id, private_key, address)
                print("\n✅ Update complete!")
            return
            
        # Step 1: Deploy contract
        app_id, app_address = deploy_cusd_contract(private_key, address)
        
        # Step 2: Create cUSD asset with app as clawback/freeze
        cusd_asset_id = create_cusd_asset(private_key, address, app_address)
        
        # Step 3: Setup assets in the contract
        usdc_asset_id = 10458941  # Testnet USDC
        setup_result = setup_assets(app_id, app_address, cusd_asset_id, usdc_asset_id, private_key, address)
        
        # Step 4: Transfer ALL cUSD to the contract (security critical!)
        print("\n" + "="*60)
        print("STEP 4: SECURING RESERVE")
        print("="*60)
        print("Transferring all cUSD to contract to prevent backdoor minting...")
        
        # Get the MAX_UINT64 value
        MAX_UINT64 = 18_446_744_073_709_551_615
        
        params = algod_client.suggested_params()
        transfer_txn = AssetTransferTxn(
            sender=address,
            sp=params,
            receiver=app_address,
            amt=MAX_UINT64,  # Transfer ALL tokens
            index=cusd_asset_id
        )
        
        signed_transfer = transfer_txn.sign(private_key)
        transfer_tx_id = algod_client.send_transaction(signed_transfer)
        print(f"Transfer TX: {transfer_tx_id}")
        
        wait_for_confirmation(algod_client, transfer_tx_id, 4)
        print(f"✅ All {MAX_UINT64:,} units transferred to contract!")
        
        # Verify the transfer
        print("\nVerifying transfer...")
        app_info = algod_client.account_info(app_address)
        app_assets = app_info.get('assets', [])
        cusd_holding = next((a for a in app_assets if a['asset-id'] == cusd_asset_id), None)
        
        if cusd_holding and cusd_holding['amount'] == MAX_UINT64:
            print(f"✅ Verified: Contract holds {cusd_holding['amount']:,} cUSD units")
            print(f"🔒 Security achieved - no backdoor minting possible!")
        else:
            print(f"⚠️ WARNING: Contract balance verification failed!")
            if cusd_holding:
                print(f"Contract holds: {cusd_holding['amount']:,} units")
            else:
                print(f"Contract not opted into cUSD asset!")
            raise Exception("Transfer verification failed")
        
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