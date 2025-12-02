import sys
import os
import base64
from algosdk.v2client import algod

# Add root to path to import payroll contract
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from contracts.payroll.payroll import app

ALGOD_ADDRESS = "https://testnet-api.4160.nodely.dev"
ALGOD_TOKEN = ""
APP_ID = 750526198

def main():
    print(f"Checking bytecode for App ID {APP_ID}...")
    
    # 1. Compile local source
    print("Compiling local source...")
    approval_teal = app.build().approval_program
    # We need to compile TEAL to bytecode using algod
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    try:
        local_compiled = client.compile(approval_teal)
        local_bytes = base64.b64decode(local_compiled['result'])
        print(f"Local bytecode length: {len(local_bytes)}")
    except Exception as e:
        print(f"Error compiling local source: {e}")
        return

    # 2. Fetch deployed bytecode
    print("Fetching deployed bytecode...")
    try:
        app_info = client.application_info(APP_ID)
        deployed_b64 = app_info['params']['approval-program']
        deployed_bytes = base64.b64decode(deployed_b64)
        print(f"Deployed bytecode length: {len(deployed_bytes)}")
    except Exception as e:
        print(f"Error fetching deployed bytecode: {e}")
        return

    # 3. Compare
    if local_bytes == deployed_bytes:
        print("\n✅ Bytecode MATCHES!")
    else:
        print("\n❌ Bytecode MISMATCH!")
        # Find first difference
        limit = min(len(local_bytes), len(deployed_bytes))
        for i in range(limit):
            if local_bytes[i] != deployed_bytes[i]:
                print(f"First difference at byte {i}: local={local_bytes[i]}, deployed={deployed_bytes[i]}")
                break
        if len(local_bytes) != len(deployed_bytes):
            print(f"Length difference: local={len(local_bytes)}, deployed={len(deployed_bytes)}")

if __name__ == "__main__":
    main()
