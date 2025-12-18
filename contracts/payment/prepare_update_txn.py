
import base64
import os
import sys
from pathlib import Path
from algosdk import encoding
from algosdk.v2client import algod
from algosdk.transaction import ApplicationCallTxn, OnComplete, write_to_file

# Add project root to path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from contracts.payment.payment import app as payment_app

# Configurations
ALGOD_ADDRESS = "https://mainnet-api.algonode.cloud"
ALGOD_TOKEN = ""
APP_ID = 3353227747
MULTISIG_ADDRESS = "MAI35ABWYNKUOW5QMESNZB3WDOFZ2XPHUXGBI4WNL6AI5XLBLF7IUVOYRI"

def main():
    print(f"Preparing update transaction for App {APP_ID} on Mainnet...")
    
    # Initialize Algod client
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    # Build contract
    print("Building contract...")
    app_spec = payment_app.build()
    
    # Compile programs
    print("Compiling approval program...")
    approval_result = client.compile(app_spec.approval_program)
    approval_program = base64.b64decode(approval_result['result'])
    
    print("Compiling clear program...")
    clear_result = client.compile(app_spec.clear_program)
    clear_program = base64.b64decode(clear_result['result'])
    
    print(f"Approval size: {len(approval_program)} bytes")
    print(f"Clear size: {len(clear_program)} bytes")
    
    # Get suggested params
    params = client.suggested_params()
    
    # Get update method selector
    update_method = app_spec.contract.get_method_by_name("update")
    update_selector = update_method.get_selector()
    print(f"Update selector: {update_selector.hex()}")
    
    # Create Update Transaction
    # Sender must be the admin (multisig address)
    txn = ApplicationCallTxn(
        sender=MULTISIG_ADDRESS,
        sp=params,
        index=APP_ID,
        on_complete=OnComplete.UpdateApplicationOC,
        approval_program=approval_program,
        clear_program=clear_program,
        app_args=[update_selector]
    )
    
    # Save to file
    output_file = "payment_update_mainnet.msgpack"
    write_to_file([txn], output_file)
    print(f"Transaction saved to {output_file}")
    
if __name__ == "__main__":
    main()
