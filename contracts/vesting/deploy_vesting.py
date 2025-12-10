from algosdk import account, mnemonic, encoding
from algosdk.v2client import algod
from algosdk.future.transaction import ApplicationCreateTxn, StateSchema, wait_for_confirmation
import base64
import os
import sys
from dotenv import load_dotenv

# Add the directory to the path so we can import the contract
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from confio_vesting import compile_vesting

load_dotenv()

def deploy_vesting():
    # Initialize Algod client
    algod_address = "https://testnet-api.algonode.cloud" 
    algod_token = ""
    # Check if we should use mainnet
    if os.getenv("ALGORAND_NETWORK") == "mainnet":
         algod_address = "https://mainnet-api.algonode.cloud"

    client = algod.AlgodClient(algod_token, algod_address)

    # Get creator account
    # In a real scenario, use KMS or a secure way. validating with mnemonic for now if available, 
    # or expect ENV var.
    mnemonic_secret = os.getenv("DEPLOYER_MNEMONIC")
    if not mnemonic_secret:
        print("Please set DEPLOYER_MNEMONIC in env")
        return

    creator_private_key = mnemonic.to_private_key(mnemonic_secret)
    creator_address = account.address_from_private_key(creator_private_key)
    print(f"Deploying from: {creator_address}")

    # Compile contract
    approval_teal = compile_vesting()
    clear_teal = "#pragma version 8\nint 1" # Simple clear program

    # Compile to bytes
    approval_result = client.compile(approval_teal)
    approval_program = base64.b64decode(approval_result["result"])
    
    clear_result = client.compile(clear_teal)
    clear_program = base64.b64decode(clear_result["result"])

    # Define schema
    # Global: 5 ints (confio_id, start_time, duration, total_locked, total_claimed), 2 bytes (admin, beneficiary) -> 7 total
    # Actually checking the code: 
    # admin (bytes), beneficiary (bytes), confio_id (bytes? NO check core), start_time (byte key, int val), ...
    # Wait, let's double check the key types in confio_vesting.py
    # admin: Bytes
    # beneficiary: Bytes
    # confio_id: Bytes (Key) -> Value is Int (initialized with Btoi)? 
    # Let's check `App.globalPut(confio_asset_id, confio_id_arg)` -> confio_id_arg is Btoi(args[0]) -> Int.
    # So we have:
    # Ints: confio_id, start_time, duration, total_locked, total_claimed = 5
    # Bytes: admin, beneficiary = 2
    global_schema = StateSchema(num_uints=5, num_byte_slices=2)
    local_schema = StateSchema(num_uints=0, num_byte_slices=0)

    # App Args for initialization
    # initialize(confio_id, beneficiary, duration)
    # Example values for testnet:
    # CONFIO ID: Assuming from env or args. Let's use a placeholder or input.
    confio_id = int(os.getenv("CONFIO_ASSET_ID", "123456")) # Default dummy
    beneficiary = os.getenv("BENEFICIARY_ADDRESS", creator_address) # Default to creator
    duration = int(os.getenv("VESTING_DURATION", "63072000")) # 24 months default (24 * 30.41 * 24 * 60 * 60 approx 63M)
    
    # Actually just 24 months = 2 * 365 * 24 * 3600 = 63072000
    
    app_args = [
        confio_id.to_bytes(8, 'big'),
        encoding.decode_address(beneficiary),
        duration.to_bytes(8, 'big')
    ]

    # Create Txn
    sp = client.suggested_params()
    txn = ApplicationCreateTxn(
        sender=creator_address,
        sp=sp,
        on_complete=0, # NoOp
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=app_args
    )

    # Sign and Send
    signed_txn = txn.sign(creator_private_key)
    tx_id = signed_txn.transaction_id
    print(f"Sending transaction {tx_id}...")
    client.send_transaction(signed_txn)

    # Wait for confirmation
    wait_for_confirmation(client, tx_id, 4)
    
    # Get App ID
    tx_response = client.pending_transaction_info(tx_id)
    app_id = tx_response['application-index']
    print(f"Deployed Vesting Contract App ID: {app_id}")
    return app_id

if __name__ == "__main__":
    deploy_vesting()
