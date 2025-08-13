#!/usr/bin/env python3
"""
Update cUSD contract on Algorand testnet
Website: https://confio.lat
"""

import os
import json
import sys
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import ApplicationUpdateTxn, wait_for_confirmation
import base64

# Testnet configuration
ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
ALGOD_TOKEN = ""  # No token needed for AlgoNode

# Initialize Algod client
algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

# Existing contract ID
APP_ID = 744180876

def compile_program(client, source_code):
    """Compile TEAL program"""
    compile_response = client.compile(source_code)
    return base64.b64decode(compile_response['result'])

def update_cusd_contract():
    """Update the cUSD contract"""
    
    # Get admin mnemonic from environment
    admin_mnemonic = os.environ.get('ALGORAND_SPONSOR_MNEMONIC')
    if not admin_mnemonic:
        print("Error: ALGORAND_SPONSOR_MNEMONIC environment variable not set")
        sys.exit(1)
    
    admin_private_key = mnemonic.to_private_key(admin_mnemonic)
    admin_address = account.address_from_private_key(admin_private_key)
    
    print(f"Admin address: {admin_address}")
    
    # Check balance
    account_info = algod_client.account_info(admin_address)
    balance = account_info.get('amount') / 1000000
    print(f"Account balance: {balance:.6f} ALGO")
    
    # Read compiled TEAL programs
    with open("cusd_approval.teal", "r") as f:
        approval_source = f.read()
    
    with open("cusd_clear.teal", "r") as f:
        clear_source = f.read()
    
    print("\nCompiling TEAL programs...")
    
    # Compile programs
    approval_program = compile_program(algod_client, approval_source)
    clear_program = compile_program(algod_client, clear_source)
    
    print(f"Approval program size: {len(approval_program)} bytes")
    print(f"Clear program size: {len(clear_program)} bytes")
    
    # Get suggested parameters
    params = algod_client.suggested_params()
    
    # Create update transaction
    txn = ApplicationUpdateTxn(
        sender=admin_address,
        sp=params,
        index=APP_ID,
        approval_program=approval_program,
        clear_program=clear_program
    )
    
    # Sign transaction
    signed_txn = txn.sign(admin_private_key)
    
    # Send transaction
    try:
        tx_id = algod_client.send_transaction(signed_txn)
        print(f"\nUpdate transaction sent: {tx_id}")
        
        # Wait for confirmation
        confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
        print(f"✅ Contract updated successfully in round {confirmed_txn.get('confirmed-round', 0)}")
        print(f"Transaction ID: {tx_id}")
        
        # Now set the sponsor address
        print("\n📝 Setting sponsor address...")
        set_sponsor_address(admin_private_key, admin_address)
        
    except Exception as e:
        print(f"❌ Error updating contract: {e}")
        import traceback
        traceback.print_exc()

def set_sponsor_address(admin_private_key, admin_address):
    """Set the sponsor address in the contract"""
    from algosdk.transaction import ApplicationCallTxn
    from algosdk.abi import Method, Returns
    from algosdk import encoding
    
    try:
        # Get suggested params
        params = algod_client.suggested_params()
        
        # Create method selector for set_sponsor_address
        method = Method(
            name="set_sponsor_address",
            args=[{"type": "address", "name": "sponsor"}],
            returns=Returns("void")
        )
        
        selector = method.get_selector()
        
        # Use admin address as sponsor for now
        sponsor_address = admin_address
        sponsor_bytes = encoding.decode_address(sponsor_address)
        
        # Create app call
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=APP_ID,
            on_complete=0,  # NoOp
            app_args=[selector, sponsor_bytes]
        )
        
        # Sign and send
        signed_txn = txn.sign(admin_private_key)
        tx_id = algod_client.send_transaction(signed_txn)
        
        print(f"Set sponsor transaction sent: {tx_id}")
        
        # Wait for confirmation
        confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
        print(f"✅ Sponsor address set successfully in round {confirmed_txn.get('confirmed-round', 0)}")
        print(f"Sponsor address: {sponsor_address}")
        
    except Exception as e:
        print(f"❌ Error setting sponsor address: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("=" * 60)
    print("cUSD CONTRACT UPDATE SCRIPT")
    print("Website: https://confio.lat")
    print("=" * 60)
    
    update_cusd_contract()