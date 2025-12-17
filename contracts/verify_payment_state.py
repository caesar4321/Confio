#!/usr/bin/env python3
import sys
import base64
from algosdk.v2client import algod
from algosdk import encoding

# Payment App ID from .env.mainnet
APP_ID = 3353227747
ALGOD_ADDRESS = 'https://mainnet-api.4160.nodely.dev'
ALGOD_TOKEN = ''

def main():
    print(f"Checking Payment App state for ID: {APP_ID}")
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    try:
        app_info = client.application_info(APP_ID)
        global_state = {}
        for item in app_info['params']['global-state']:
            key = base64.b64decode(item['key']).decode('utf-8', errors='ignore')
            value_obj = item['value']
            if value_obj['type'] == 1:  # bytes
                raw_bytes = base64.b64decode(value_obj.get('bytes', ''))
                # heuristic for address
                if len(raw_bytes) == 32:
                    global_state[key] = encoding.encode_address(raw_bytes)
                else:
                    global_state[key] = raw_bytes
            elif value_obj['type'] == 2:  # uint
                global_state[key] = value_obj.get('uint', 0)
        
        print("\nGlobal State:")
        for k, v in global_state.items():
            print(f"  {k}: {v}")

        # Specific checks
        cusd = global_state.get('cusd_asset_id')
        confio = global_state.get('confio_asset_id')
        paused = global_state.get('is_paused')

        print("\nDiagnostics:")
        if cusd == 0:
            print("  ❌ 'cusd_asset_id' is 0! Assets not setup.")
        else:
            print(f"  ✓ 'cusd_asset_id' = {cusd}")

        if confio == 0:
            print("  ❌ 'confio_asset_id' is 0! Assets not setup.")
        else:
            print(f"  ✓ 'confio_asset_id' = {confio}")
            
        if paused == 1:
            print("  ⚠️ Contract is PAUSED.")
        else:
            print("  ✓ Contract is active (not paused).")

    except Exception as e:
        print(f"Error fetching application info: {e}")

if __name__ == "__main__":
    main()
