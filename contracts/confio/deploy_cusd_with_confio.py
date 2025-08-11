#!/usr/bin/env python3
"""
Deploy cUSD contract with CONFIO as collateral asset
Tests the collateral minting/burning mechanism
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import base64
from algosdk import account
from algosdk.v2client import algod
from algosdk.transaction import (
    AssetConfigTxn, 
    ApplicationCreateTxn,
    PaymentTxn,
    AssetTransferTxn,
    ApplicationCallTxn,
    wait_for_confirmation,
    assign_group_id,
    OnComplete,
    StateSchema
)
from algosdk.abi import Method, Argument, Returns, ABIType
from algosdk.encoding import encode_address
import struct
import hashlib
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN
from contracts.config.localnet_accounts import ADMIN_ADDRESS, ADMIN_PRIVATE_KEY
from contracts.config.confio_token_config import (
    CONFIO_ASSET_ID, 
    CONFIO_CREATOR_ADDRESS
)

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

def compile_program(client, source_code):
    """Compile TEAL source code"""
    compile_response = client.compile(source_code)
    return base64.b64decode(compile_response['result'])

def create_cusd_asset():
    """Create cUSD asset with maximum supply"""
    print("\n1. Creating cUSD Asset...")
    
    params = algod_client.suggested_params()
    max_supply = 2**64 - 1
    
    txn = AssetConfigTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        total=max_supply,
        default_frozen=False,
        unit_name="cUSD",
        asset_name="Confio Dollar",
        manager=ADMIN_ADDRESS,
        reserve=ADMIN_ADDRESS,
        freeze=ADMIN_ADDRESS,
        clawback=ADMIN_ADDRESS,  # Will be updated to app address
        decimals=6,
        url="https://confio.lat",
        metadata_hash=None
    )
    
    signed_txn = txn.sign(ADMIN_PRIVATE_KEY)
    txid = algod_client.send_transaction(signed_txn)
    confirmed = wait_for_confirmation(algod_client, txid, 4)
    asset_id = confirmed["asset-index"]
    
    print(f"   ✅ cUSD Asset created: {asset_id}")
    return asset_id

def deploy_cusd_contract():
    """Deploy the cUSD smart contract"""
    print("\n2. Deploying cUSD Contract...")
    
    # Read and compile TEAL programs
    with open("contracts/cusd_approval.teal", "r") as f:
        approval_source = f.read()
    
    with open("contracts/cusd_clear.teal", "r") as f:
        clear_source = f.read()
    
    approval_program = compile_program(algod_client, approval_source)
    clear_program = compile_program(algod_client, clear_source)
    
    # Check program size
    approval_len = len(approval_program)
    print(f"   Approval program size: {approval_len} bytes")
    extra_pages = max(0, (approval_len - 2048 + 2047) // 2048)
    
    # Define state schemas
    global_schema = StateSchema(num_uints=10, num_byte_slices=2)
    local_schema = StateSchema(num_uints=2, num_byte_slices=0)
    
    # Create application with create method selector
    params = algod_client.suggested_params()
    
    # Add create method selector
    create_selector = Method(
        name="create",
        args=[],
        returns=Returns("void")
    ).get_selector()
    
    txn = ApplicationCreateTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        extra_pages=extra_pages,
        app_args=[create_selector]
    )
    
    signed_txn = txn.sign(ADMIN_PRIVATE_KEY)
    txid = algod_client.send_transaction(signed_txn)
    confirmed = wait_for_confirmation(algod_client, txid, 4)
    app_id = confirmed["application-index"]
    
    # Calculate app address
    app_bytes = b"appID" + struct.pack(">Q", app_id)
    hash = hashlib.new('sha512_256', app_bytes).digest()
    app_address = encode_address(hash)
    
    print(f"   ✅ Contract deployed: App ID {app_id}")
    print(f"   ✅ App Address: {app_address}")
    
    return app_id, app_address

def setup_contract_assets(app_id, app_address, cusd_id):
    """Setup assets in the contract"""
    print("\n3. Setting up Contract Assets...")
    
    # Fund the app
    print("   Funding app account...")
    params = algod_client.suggested_params()
    
    fund_txn = PaymentTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        receiver=app_address,
        amt=1_000_000  # 1 ALGO
    )
    
    signed = fund_txn.sign(ADMIN_PRIVATE_KEY)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print(f"   ✅ App funded with 1 ALGO")
    
    # Setup assets (cUSD and CONFIO)
    print(f"   Setting up assets: cUSD={cusd_id}, CONFIO={CONFIO_ASSET_ID}")
    
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = 3000
    
    # Build method selector and arguments
    method_selector = Method(
        name="setup_assets",
        args=[
            Argument(arg_type="uint64", name="cusd_id"),
            Argument(arg_type="uint64", name="usdc_id")  # We're using CONFIO here
        ],
        returns=Returns("void")
    ).get_selector()
    
    cusd_arg = ABIType.from_string("uint64").encode(cusd_id)
    confio_arg = ABIType.from_string("uint64").encode(CONFIO_ASSET_ID)
    
    # Create grouped transactions
    payment_txn = PaymentTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        receiver=app_address,
        amt=600000  # 0.6 ALGO for opt-ins
    )
    
    app_call_txn = ApplicationCallTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        index=app_id,
        on_complete=OnComplete.NoOpOC,
        app_args=[method_selector, cusd_arg, confio_arg],
        foreign_assets=[cusd_id, CONFIO_ASSET_ID]
    )
    
    # Group and send
    assign_group_id([payment_txn, app_call_txn])
    signed_payment = payment_txn.sign(ADMIN_PRIVATE_KEY)
    signed_app_call = app_call_txn.sign(ADMIN_PRIVATE_KEY)
    
    txid = algod_client.send_transactions([signed_payment, signed_app_call])
    wait_for_confirmation(algod_client, txid, 4)
    print(f"   ✅ Assets setup complete")

def update_cusd_clawback(cusd_id, app_address):
    """Update cUSD clawback to app address"""
    print("\n4. Updating cUSD Clawback...")
    
    params = algod_client.suggested_params()
    
    txn = AssetConfigTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        index=cusd_id,
        manager=ADMIN_ADDRESS,
        reserve=ADMIN_ADDRESS,
        freeze=ADMIN_ADDRESS,
        clawback=app_address  # Update clawback to app
    )
    
    signed = txn.sign(ADMIN_PRIVATE_KEY)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print(f"   ✅ cUSD clawback updated to app address")

def distribute_confio_tokens(cusd_id):
    """Distribute CONFIO tokens to test accounts"""
    print("\n5. Distributing CONFIO Tokens...")
    
    # Create test user account
    user_private_key, user_address = account.generate_account()
    
    print(f"   Created test user: {user_address}")
    
    # Fund user with ALGO
    params = algod_client.suggested_params()
    
    fund_txn = PaymentTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        receiver=user_address,
        amt=5_000_000  # 5 ALGO
    )
    
    signed = fund_txn.sign(ADMIN_PRIVATE_KEY)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print(f"   ✅ User funded with 5 ALGO")
    
    # User opt-in to CONFIO
    opt_in_txn = AssetTransferTxn(
        sender=user_address,
        sp=params,
        receiver=user_address,
        amt=0,
        index=CONFIO_ASSET_ID
    )
    
    signed = opt_in_txn.sign(user_private_key)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print(f"   ✅ User opted in to CONFIO")
    
    # Transfer CONFIO to user (1000 CONFIO)
    transfer_txn = AssetTransferTxn(
        sender=CONFIO_CREATOR_ADDRESS,
        sp=params,
        receiver=user_address,
        amt=1000_000_000,  # 1000 CONFIO (6 decimals)
        index=CONFIO_ASSET_ID
    )
    
    creator_pk = os.environ.get("CONFIO_CREATOR_PRIVATE_KEY")
    if not creator_pk:
        raise RuntimeError("CONFIO_CREATOR_PRIVATE_KEY env var is required to sign creator transfers (not stored in repo)")
    signed = transfer_txn.sign(creator_pk)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print(f"   ✅ Transferred 1000 CONFIO to user")
    
    # User opt-in to cUSD
    opt_in_txn = AssetTransferTxn(
        sender=user_address,
        sp=params,
        receiver=user_address,
        amt=0,
        index=cusd_id
    )
    
    signed = opt_in_txn.sign(user_private_key)
    txid = algod_client.send_transaction(signed)
    wait_for_confirmation(algod_client, txid, 4)
    print(f"   ✅ User opted in to cUSD")
    
    return user_address, user_private_key

def save_deployment_config(app_id, app_address, cusd_id, user_address, user_key):
    """Save deployment configuration"""
    config_file = os.path.join(os.path.dirname(__file__), "../config/cusd_deployment_config.py")
    
    with open(config_file, "w") as f:
        f.write(f"# cUSD Deployment Configuration for LocalNet\n")
        f.write(f"# Using CONFIO as collateral asset instead of USDC\n\n")
        f.write(f"APP_ID = {app_id}\n")
        f.write(f'APP_ADDRESS = "{app_address}"\n')
        f.write(f"CUSD_ASSET_ID = {cusd_id}\n")
        f.write(f"COLLATERAL_ASSET_ID = {CONFIO_ASSET_ID}  # Using CONFIO instead of USDC\n")
        f.write(f'TEST_USER_ADDRESS = "{user_address}"\n')
        # Do not persist private keys by default
        if os.environ.get("ALLOW_WRITE_KEYS") == "1":
            f.write(f'TEST_USER_PRIVATE_KEY = "{user_key}"\n')
        else:
            f.write(f'# TEST_USER_PRIVATE_KEY not persisted; set ALLOW_WRITE_KEYS=1 to include (dev only)\n')
    
    print(f"\n✅ Configuration saved to: {config_file}")

def main():
    print("=" * 60)
    print("DEPLOYING cUSD WITH CONFIO COLLATERAL")
    print("=" * 60)
    
    # Check connection
    status = algod_client.status()
    print(f"Connected to LocalNet (round {status.get('last-round', 0)})")
    
    try:
        # Deploy cUSD
        cusd_id = create_cusd_asset()
        
        # Deploy contract
        app_id, app_address = deploy_cusd_contract()
        
        # Setup assets
        setup_contract_assets(app_id, app_address, cusd_id)
        
        # Update clawback
        update_cusd_clawback(cusd_id, app_address)
        
        # Distribute CONFIO tokens
        user_address, user_key = distribute_confio_tokens(cusd_id)
        
        # Save configuration
        save_deployment_config(app_id, app_address, cusd_id, user_address, user_key)
        
        print("\n" + "=" * 60)
        print("DEPLOYMENT COMPLETE!")
        print("=" * 60)
        print(f"\nDeployment Summary:")
        print(f"  App ID: {app_id}")
        print(f"  App Address: {app_address}")
        print(f"  cUSD Asset: {cusd_id}")
        print(f"  Collateral Asset: {CONFIO_ASSET_ID} (CONFIO)")
        print(f"  Test User: {user_address}")
        print(f"  Test User CONFIO Balance: 1000 CONFIO")
        
        print("\nNext steps:")
        print("1. Test collateral minting (CONFIO → cUSD)")
        print("2. Test collateral burning (cUSD → CONFIO)")
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
