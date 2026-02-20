#!/usr/bin/env python3
"""
Check Mainnet Presale State
"""

import os
import sys
import json
import base64
from algosdk.v2client import algod

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Load mainnet env
    env_path = os.path.join(repo_root, '.env.mainnet')
    load_dotenv(env_path)
except Exception:
    pass

# Configuration
ALGOD_ADDRESS = os.getenv("ALGORAND_ALGOD_ADDRESS", "https://mainnet-api.4160.nodely.dev")
ALGOD_TOKEN = os.getenv("ALGORAND_ALGOD_TOKEN", "")
PRESALE_APP_ID = int(os.getenv('ALGORAND_PRESALE_APP_ID', '3353218127'))

def get_presale_state(algod_client, app_id):
    """Get current presale state"""
    app_info = algod_client.application_info(app_id)
    state = {}

    for item in app_info['params']['global-state']:
        key = base64.b64decode(item['key']).decode('utf-8', errors='ignore')
        value_obj = item['value']

        if value_obj['type'] == 2:  # uint
            state[key] = value_obj.get('uint', 0)

    return state

def main():
    print("=" * 60)
    print("CHECKING PRESALE STATE")
    print("=" * 60)
    print(f"App ID: {PRESALE_APP_ID}")
    
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    try:
        state = get_presale_state(client, PRESALE_APP_ID)
        max_addr = state.get('max_addr', 0)
        price = state.get('price', 0)
        
        print(f"\nCurrent State:")
        print(f"   Max Per Address: {max_addr / 10**6:,.2f} cUSD")
        print(f"   Price: {price / 10**6:.2f} cUSD per CONFIO")
        
        expected_max = 10000.0
        if abs((max_addr / 10**6) - expected_max) < 0.01:
            print("\n✅ SUCCESS: Max address is updated to 10,000 cUSD")
        else:
            print(f"\n⚠️  STATUS: Max address is {max_addr / 10**6:,.2f} cUSD (Expected: {expected_max:,.2f})")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
