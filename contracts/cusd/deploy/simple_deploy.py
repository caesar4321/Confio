#!/usr/bin/env python3
"""
Simple deployment of cUSD contract to LocalNet
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import base64
from algosdk import account
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCreateTxn,
    wait_for_confirmation,
    OnComplete,
    StateSchema
)
from contracts.config.localnet_accounts import ADMIN_ADDRESS, ADMIN_PRIVATE_KEY
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN

# Initialize Algod client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

def compile_program(client, source_code):
    """Compile TEAL source code"""
    compile_response = client.compile(source_code)
    return base64.b64decode(compile_response['result'])

def main():
    print("=" * 60)
    print("Simple Contract Deployment")
    print("=" * 60)
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"\nConnected to LocalNet:")
        print(f"  Last round: {status.get('last-round', 0)}")
    except Exception as e:
        print(f"Error connecting to LocalNet: {e}")
        sys.exit(1)
    
    # Read TEAL programs
    with open("contracts/cusd_approval.teal", "r") as f:
        approval_source = f.read()
    
    with open("contracts/cusd_clear.teal", "r") as f:
        clear_source = f.read()
    
    # Compile programs
    print("\nCompiling programs...")
    approval_program = compile_program(algod_client, approval_source)
    clear_program = compile_program(algod_client, clear_source)
    
    # Check program size
    approval_len = len(approval_program)
    print(f"Approval program size: {approval_len} bytes")
    extra_pages = max(0, (approval_len - 2048 + 2047) // 2048)
    print(f"Extra pages needed: {extra_pages}")
    
    # Define state schemas
    global_schema = StateSchema(num_uints=10, num_byte_slices=2)
    local_schema = StateSchema(num_uints=2, num_byte_slices=0)
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    # Create application
    txn = ApplicationCreateTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        extra_pages=extra_pages
    )
    
    # Sign transaction
    signed_txn = txn.sign(ADMIN_PRIVATE_KEY)
    
    # Send transaction
    print("\nDeploying contract...")
    txid = algod_client.send_transaction(signed_txn)
    print(f"Transaction ID: {txid}")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, txid, 4)
    app_id = confirmed_txn["application-index"]
    
    # Get app address
    from algosdk.encoding import encode_address
    import struct
    import hashlib
    app_bytes = b"appID" + struct.pack(">Q", app_id)
    hash = hashlib.sha512_256(app_bytes).digest()
    app_address = encode_address(hash)
    
    print("\n" + "=" * 60)
    print("CONTRACT DEPLOYED SUCCESSFULLY!")
    print("=" * 60)
    print(f"\nApp ID: {app_id}")
    print(f"App Address: {app_address}")
    
    # Save to file
    with open("localnet_app.py", "w") as f:
        f.write(f"# LocalNet App Configuration\n")
        f.write(f"APP_ID = {app_id}\n")
        f.write(f'APP_ADDRESS = "{app_address}"\n')
    
    print("\nConfiguration saved to: localnet_app.py")
    print("\nNext steps:")
    print("1. Update cUSD clawback to app address")
    print("2. Fund app account")
    print("3. Call setup_assets method")

if __name__ == "__main__":
    main()