from algosdk import account, mnemonic, encoding
from algosdk.v2client import algod
from algosdk.future.transaction import ApplicationCreateTxn, StateSchema, wait_for_confirmation
import base64
import os
import sys
from dotenv import load_dotenv

# Add path for contract import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from confio_vesting_pool import compile_vesting_pool

load_dotenv()

def deploy_vesting_pool():
    algod_address = "https://testnet-api.algonode.cloud" 
    algod_token = ""
    if os.getenv("ALGORAND_NETWORK") == "mainnet":
         algod_address = "https://mainnet-api.algonode.cloud"

    client = algod.AlgodClient(algod_token, algod_address)

    # Get Admin Account
    mnemonic_secret = os.getenv("DEPLOYER_MNEMONIC")
    if not mnemonic_secret:
        print("Please set DEPLOYER_MNEMONIC in env")
        return

    admin_key = mnemonic.to_private_key(mnemonic_secret)
    admin_addr = account.address_from_private_key(admin_key)
    print(f"Deploying Pool from: {admin_addr}")

    # Compile
    approval_teal = compile_vesting_pool()
    clear_teal = "#pragma version 8\nint 1"
    
    approval_res = client.compile(approval_teal)
    approval_prog = base64.b64decode(approval_res["result"])
    clear_res = client.compile(clear_teal)
    clear_prog = base64.b64decode(clear_res["result"])

    # Global Schema
    # 5 Ints: confio_id, duration, start_time, total_pool_locked
    # 2 Bytes: admin, confio_id (key) -- wait, code uses 5 ints, 1 byte (admin).
    # Let's check confio_vesting_pool.py:
    # Ints: globalPut(confio_id, ...), globalPut(duration, ...), globalPut(start, ...), globalPut(total_pool, ...) => 4 ints?
    # Wait, keys are Bytes. Mappings:
    # admin (bytes) -> value (bytes address)
    # confio_id (bytes) -> value (int)
    # duration (bytes) -> value (int)
    # start (bytes) -> value (int)
    # total_pool (bytes) -> value (int)
    # So 4 Ints, 1 Byte Slice.
    # To be safe, verify:
    # App.globalPut(admin_address, Txn.sender()) -> Byte
    # App.globalPut(confio_asset_id, confio_id_arg) -> Int
    # App.globalPut(vesting_duration, duration_arg) -> Int
    # App.globalPut(vesting_start_time, Int(0)) -> Int
    # App.globalPut(total_pool_locked, Int(0)) -> Int
    # Total: 4 Ints, 1 Byte.
    
    global_schema = StateSchema(num_uints=4, num_byte_slices=1)
    local_schema = StateSchema(num_uints=0, num_byte_slices=0) # No local state
    
    # Args
    confio_id = int(os.getenv("CONFIO_ASSET_ID", "123456"))
    duration = int(os.getenv("VESTING_DURATION", "63072000")) 
    
    app_args = [
        confio_id.to_bytes(8, 'big'),
        duration.to_bytes(8, 'big')
    ]
    
    sp = client.suggested_params()
    txn = ApplicationCreateTxn(
        sender=admin_addr,
        sp=sp,
        on_complete=0,
        approval_program=approval_prog,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=app_args,
        boxes=[(0, b"")] # Enable boxes? No, create txn doesn't need box ref yet.
    )
    
    signed = txn.sign(admin_key)
    txid = client.send_transaction(signed)
    print(f"Sending Deploy Tx: {txid}")
    
    wait_for_confirmation(client, txid, 4)
    info = client.pending_transaction_info(txid)
    app_id = info['application-index']
    print(f"Vesting Pool Deployed: {app_id}")
    return app_id

if __name__ == "__main__":
    deploy_vesting_pool()
