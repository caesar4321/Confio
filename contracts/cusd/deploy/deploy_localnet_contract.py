#!/usr/bin/env python3
"""
Deploy cUSD contract to LocalNet and configure it
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import base64
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCreateTxn, 
    AssetConfigTxn,
    PaymentTxn,
    ApplicationCallTxn,
    wait_for_confirmation,
    assign_group_id,
    OnComplete,
    StateSchema
)
from algosdk.abi import Contract, Method, Returns
from contracts.config.localnet_accounts import ADMIN_ADDRESS, ADMIN_PRIVATE_KEY
from contracts.config.localnet_assets import CUSD_ASSET_ID, TEST_USDC_ID
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN

# Initialize Algod client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

def compile_program(client, source_code):
    """Compile TEAL source code"""
    compile_response = client.compile(source_code)
    return base64.b64decode(compile_response['result'])

def deploy_contract(algod_client, deployer):
    """Deploy the cUSD contract"""
    
    # Read TEAL programs
    with open("contracts/cusd_approval.teal", "r") as f:
        approval_source = f.read()
    
    with open("contracts/cusd_clear.teal", "r") as f:
        clear_source = f.read()
    
    # Compile programs
    print("Compiling approval program...")
    approval_program = compile_program(algod_client, approval_source)
    
    print("Compiling clear program...")
    clear_program = compile_program(algod_client, clear_source)
    
    # Define state schemas
    global_schema = StateSchema(num_uints=10, num_byte_slices=2)
    local_schema = StateSchema(num_uints=2, num_byte_slices=0)
    
    # Calculate extra pages needed (each page is 2048 bytes)
    approval_len = len(approval_program)
    print(f"Approval program size: {approval_len} bytes")
    extra_pages = max(0, (approval_len - 2048 + 2047) // 2048)  # Round up
    print(f"Extra pages needed: {extra_pages}")
    
    # Get suggested params
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = 2000 + (extra_pages * 1000)  # Higher fee for create transaction + extra pages
    
    # Create application (ABI router expects create selector in app args)
    create_selector = Method(name="create", args=[], returns=Returns("void")).get_selector()
    txn = ApplicationCreateTxn(
        sender=deployer["address"],
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        extra_pages=extra_pages,
        app_args=[create_selector]
    )
    
    # Sign transaction
    signed_txn = txn.sign(deployer["private_key"])
    
    # Send transaction
    txid = algod_client.send_transaction(signed_txn)
    print(f"Deploying contract, transaction ID: {txid}")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, txid, 4)
    app_id = confirmed_txn["application-index"]
    app_address = algod_client.application_info(app_id)["params"]["address"]
    
    print(f"Contract deployed with App ID: {app_id}")
    print(f"App Address: {app_address}")
    
    return app_id, app_address

def update_cusd_clawback(algod_client, admin, asset_id, new_clawback):
    """Update cUSD clawback to the app address"""
    params = algod_client.suggested_params()
    
    # Create asset config transaction to update clawback
    txn = AssetConfigTxn(
        sender=admin["address"],
        sp=params,
        index=asset_id,
        manager=admin["address"],
        reserve=admin["address"],
        freeze=admin["address"],
        clawback=new_clawback  # Set app as clawback
    )
    
    # Sign and send
    signed_txn = txn.sign(admin["private_key"])
    txid = algod_client.send_transaction(signed_txn)
    print(f"Updating cUSD clawback, transaction ID: {txid}")
    
    # Wait for confirmation
    wait_for_confirmation(algod_client, txid, 4)
    print(f"cUSD clawback updated to: {new_clawback}")

def setup_assets(algod_client, admin, app_id, cusd_id, usdc_id):
    """Setup assets in the contract with proper funding"""
    
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = 3000  # Cover the app call + 2 inner transactions
    
    # Create payment transaction to fund the app
    payment_txn = PaymentTxn(
        sender=admin["address"],
        sp=params,
        receiver=algod_client.application_info(app_id)["params"]["address"],
        amt=600000  # 0.6 ALGO for opt-ins and min balance
    )
    
    # Create app call transaction
    # Encode arguments for setup_assets method
    from algosdk.abi import Method, Argument, Returns
    from algosdk.atomic_transaction_composer import AtomicTransactionComposer, TransactionWithSigner
    from algosdk.account import address_from_private_key
    from algosdk.signer import BasicAccountTransactionSigner
    
    # Create signer
    signer = BasicAccountTransactionSigner(admin["private_key"])
    
    # Load contract ABI
    with open("contracts/cusd.json", "r") as f:
        import json
        contract_json = json.load(f)
    
    contract = Contract.from_json(json.dumps(contract_json))
    
    # Find setup_assets method
    setup_method = None
    for method in contract.methods:
        if method.name == "setup_assets":
            setup_method = method
            break
    
    if not setup_method:
        # Create method manually if not in ABI
        setup_method = Method(
            name="setup_assets",
            args=[
                Argument(arg_type="uint64", name="cusd_id"),
                Argument(arg_type="uint64", name="usdc_id")
            ],
            returns=Returns(return_type="void")
        )
    
    # Create atomic transaction composer
    atc = AtomicTransactionComposer()
    
    # Add transactions
    atc.add_transaction(TransactionWithSigner(payment_txn, signer))
    
    # Add method call
    atc.add_method_call(
        app_id=app_id,
        method=setup_method,
        sender=admin["address"],
        sp=params,
        signer=signer,
        method_args=[cusd_id, usdc_id]
    )
    
    # Execute atomic transaction
    print("Setting up assets in contract...")
    result = atc.execute(algod_client, 4)
    
    print(f"Assets setup complete, transaction IDs: {result.tx_ids}")
    return result

def main():
    print("=" * 60)
    print("Deploying cUSD Contract to LocalNet")
    print("=" * 60)
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"\nConnected to LocalNet:")
        print(f"  Last round: {status.get('last-round', 0)}")
    except Exception as e:
        print(f"Error connecting to LocalNet: {e}")
        print("Make sure LocalNet is running: algokit localnet start")
        sys.exit(1)
    
    # Admin account
    admin = {
        "address": ADMIN_ADDRESS,
        "private_key": ADMIN_PRIVATE_KEY
    }
    
    print(f"\nUsing admin account: {admin['address'][:8]}...")
    print(f"cUSD Asset ID: {CUSD_ASSET_ID}")
    print(f"Test USDC ID: {TEST_USDC_ID}")
    
    # Step 1: Deploy contract
    print("\n" + "=" * 60)
    print("STEP 1: DEPLOYING CONTRACT")
    print("=" * 60)
    
    app_id, app_address = deploy_contract(algod_client, admin)
    
    # Step 2: Update cUSD clawback to app address
    print("\n" + "=" * 60)
    print("STEP 2: UPDATING cUSD CLAWBACK")
    print("=" * 60)
    
    update_cusd_clawback(algod_client, admin, CUSD_ASSET_ID, app_address)
    
    # Step 3: Setup assets in contract
    print("\n" + "=" * 60)
    print("STEP 3: SETTING UP ASSETS IN CONTRACT")
    print("=" * 60)
    
    setup_assets(algod_client, admin, app_id, CUSD_ASSET_ID, TEST_USDC_ID)
    
    # Save deployment info
    print("\n" + "=" * 60)
    print("SAVING DEPLOYMENT INFORMATION")
    print("=" * 60)
    
    deployment_content = f"""# LocalNet Deployment Configuration
# Generated by deploy_localnet_contract.py

# Contract deployment
APP_ID = {app_id}
APP_ADDRESS = "{app_address}"

# Import assets and accounts
from contracts.config.localnet_assets import *
from contracts.config.localnet_accounts import *
"""
    
    with open("localnet_deployment.py", "w") as f:
        f.write(deployment_content)
    
    print("Deployment configuration saved to: localnet_deployment.py")
    
    print("\n" + "=" * 60)
    print("DEPLOYMENT COMPLETE!")
    print("=" * 60)
    print(f"\nApp ID: {app_id}")
    print(f"App Address: {app_address}")
    print(f"cUSD Asset ID: {CUSD_ASSET_ID} (clawback: app)")
    print(f"Test USDC ID: {TEST_USDC_ID}")
    print("\nThe contract is now ready for testing!")
    print("\nNext steps:")
    print("1. Test mint_admin functionality")
    print("2. Test mint_with_collateral")
    print("3. Test transfers and burns")

if __name__ == "__main__":
    main()
