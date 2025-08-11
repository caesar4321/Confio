#!/usr/bin/env python3
"""
Read-only tests of cUSD contract state
Tests that don't require private keys
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import base64
from algosdk.v2client import algod
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

# Load configuration
try:
    from localnet_test_config import (
        APP_ID, APP_ADDRESS, CUSD_ID, USDC_ID,
        ADMIN_ADDRESS, USER1_ADDRESS, USER2_ADDRESS
    )
    print(f"Loaded config: App {APP_ID}, cUSD {CUSD_ID}, USDC {USDC_ID}")
except ImportError:
    print("Error: Run complete_localnet_test.py first")
    sys.exit(1)

def get_balance(address, asset_id):
    """Get asset balance"""
    try:
        account_info = algod_client.account_info(address)
        for asset in account_info.get("assets", []):
            if asset["asset-id"] == asset_id:
                return asset["amount"] / 1_000_000
    except:
        pass
    return 0

def get_algo_balance(address):
    """Get ALGO balance"""
    try:
        account_info = algod_client.account_info(address)
        return account_info["amount"] / 1_000_000
    except:
        return 0

def test_balances():
    """Test reading all balances"""
    print("\n" + "=" * 60)
    print("TEST 1: Account Balances")
    print("=" * 60)
    
    print("\nALGO Balances:")
    print(f"  Admin: {get_algo_balance(ADMIN_ADDRESS):,.6f} ALGO")
    print(f"  User1: {get_algo_balance(USER1_ADDRESS):,.6f} ALGO")
    print(f"  User2: {get_algo_balance(USER2_ADDRESS):,.6f} ALGO")
    print(f"  App:   {get_algo_balance(APP_ADDRESS):,.6f} ALGO")
    
    print("\ncUSD Balances:")
    print(f"  Admin: {get_balance(ADMIN_ADDRESS, CUSD_ID):,.2f} cUSD")
    print(f"  User1: {get_balance(USER1_ADDRESS, CUSD_ID):,.2f} cUSD")
    print(f"  User2: {get_balance(USER2_ADDRESS, CUSD_ID):,.2f} cUSD")
    print(f"  App:   {get_balance(APP_ADDRESS, CUSD_ID):,.2f} cUSD")
    
    print("\nUSDC Balances:")
    print(f"  Admin: {get_balance(ADMIN_ADDRESS, USDC_ID):,.2f} USDC")
    print(f"  User1: {get_balance(USER1_ADDRESS, USDC_ID):,.2f} USDC")
    print(f"  User2: {get_balance(USER2_ADDRESS, USDC_ID):,.2f} USDC")
    print(f"  App:   {get_balance(APP_ADDRESS, USDC_ID):,.2f} USDC")

def test_contract_state():
    """Test reading contract global state"""
    print("\n" + "=" * 60)
    print("TEST 2: Contract Global State")
    print("=" * 60)
    
    app_info = algod_client.application_info(APP_ID)
    global_state = app_info['params']['global-state']
    
    state_dict = {}
    for item in global_state:
        key = base64.b64decode(item['key']).decode('utf-8', errors='ignore')
        if item['value']['type'] == 1:  # bytes
            value = base64.b64decode(item['value']['bytes'])
            # Try to decode as address
            try:
                from algosdk import encoding
                value = encoding.encode_address(value)
            except:
                value = value.hex()
        else:  # uint
            value = item['value']['uint']
        state_dict[key] = value
    
    print("\nGlobal State Variables:")
    for key, value in sorted(state_dict.items()):
        if isinstance(value, int):
            if key in ['total_minted', 'total_burned', 'total_usdc_locked', 
                      'cusd_circulating_supply', 'tbills_backed_supply', 
                      'cusd_asset_id', 'usdc_asset_id']:
                if key.endswith('_id'):
                    print(f"  {key}: {value}")
                else:
                    print(f"  {key}: {value/1_000_000:,.2f}")
            elif key == 'collateral_ratio':
                print(f"  {key}: {value/1_000_000:.2f} (1:{value/1_000_000:.2f})")
            elif key == 'is_paused':
                print(f"  {key}: {'Yes' if value else 'No'}")
            else:
                print(f"  {key}: {value}")
        else:
            print(f"  {key}: {value}")

def test_asset_info():
    """Test reading asset information"""
    print("\n" + "=" * 60)
    print("TEST 3: Asset Information")
    print("=" * 60)
    
    # cUSD info
    cusd_info = algod_client.asset_info(CUSD_ID)
    cusd_params = cusd_info['params']
    
    print("\ncUSD Asset:")
    print(f"  Name: {cusd_params.get('name', 'N/A')}")
    print(f"  Unit: {cusd_params.get('unit-name', 'N/A')}")
    print(f"  Total Supply: {cusd_params['total'] / 1_000_000:,.2f}")
    print(f"  Decimals: {cusd_params['decimals']}")
    print(f"  Manager: {cusd_params['manager'][:8]}...")
    print(f"  Reserve: {cusd_params['reserve'][:8]}...")
    print(f"  Clawback: {cusd_params['clawback'][:8]}...")
    print(f"  Freeze: {cusd_params['freeze'][:8]}...")
    
    # USDC info
    usdc_info = algod_client.asset_info(USDC_ID)
    usdc_params = usdc_info['params']
    
    print("\nTest USDC Asset:")
    print(f"  Name: {usdc_params.get('name', 'N/A')}")
    print(f"  Unit: {usdc_params.get('unit-name', 'N/A')}")
    print(f"  Total Supply: {usdc_params['total'] / 1_000_000:,.2f}")
    print(f"  Decimals: {usdc_params['decimals']}")
    print(f"  Manager: {usdc_params['manager'][:8]}...")

def test_app_info():
    """Test reading application information"""
    print("\n" + "=" * 60)
    print("TEST 4: Application Information")
    print("=" * 60)
    
    app_info = algod_client.application_info(APP_ID)
    app_params = app_info['params']
    
    print(f"\nApp ID: {APP_ID}")
    print(f"App Address: {APP_ADDRESS}")
    print(f"Creator: {app_params['creator'][:8]}...")
    print(f"Approval Program Size: {len(base64.b64decode(app_params['approval-program']))} bytes")
    print(f"Clear Program Size: {len(base64.b64decode(app_params['clear-state-program']))} bytes")
    print(f"Extra Pages: {app_params.get('extra-program-pages', 0)}")
    
    # Schema info
    global_schema = app_params['global-state-schema']
    local_schema = app_params['local-state-schema']
    
    print(f"\nState Schema:")
    print(f"  Global: {global_schema['num-uint']} uints, {global_schema['num-byte-slice']} byte slices")
    print(f"  Local: {local_schema['num-uint']} uints, {local_schema['num-byte-slice']} byte slices")

def test_user_local_state():
    """Test reading user local state"""
    print("\n" + "=" * 60)
    print("TEST 5: User Local State")
    print("=" * 60)
    
    for name, address in [("User1", USER1_ADDRESS), ("User2", USER2_ADDRESS)]:
        try:
            account_info = algod_client.account_info(address)
            apps_local_state = account_info.get('apps-local-state', [])
            
            for app_state in apps_local_state:
                if app_state['id'] == APP_ID:
                    print(f"\n{name} Local State:")
                    kv = app_state.get('key-value', [])
                    if not kv:
                        print("  No local state variables set")
                    for item in kv:
                        key = base64.b64decode(item['key']).decode('utf-8', errors='ignore')
                        if item['value']['type'] == 1:  # bytes
                            value = base64.b64decode(item['value']['bytes']).hex()
                        else:  # uint
                            value = item['value']['uint']
                        
                        if key == 'is_frozen':
                            print(f"  {key}: {'Yes' if value else 'No'}")
                        elif key == 'is_vault':
                            print(f"  {key}: {'Yes' if value else 'No'}")
                        else:
                            print(f"  {key}: {value}")
                    break
            else:
                print(f"\n{name}: Not opted into app")
        except Exception as e:
            print(f"\n{name}: Error reading local state - {e}")

def calculate_statistics():
    """Calculate and display statistics"""
    print("\n" + "=" * 60)
    print("TEST 6: Statistics & Analysis")
    print("=" * 60)
    
    # Total supply vs circulating
    admin_cusd = get_balance(ADMIN_ADDRESS, CUSD_ID)
    user1_cusd = get_balance(USER1_ADDRESS, CUSD_ID)
    user2_cusd = get_balance(USER2_ADDRESS, CUSD_ID)
    app_cusd = get_balance(APP_ADDRESS, CUSD_ID)
    
    total_in_circulation = user1_cusd + user2_cusd
    total_in_reserve = admin_cusd
    total_burned = app_cusd
    
    print(f"\nSupply Analysis:")
    print(f"  Total Supply: 100,000,000.00 cUSD")
    print(f"  In Reserve (Admin): {total_in_reserve:,.2f} cUSD")
    print(f"  In Circulation: {total_in_circulation:,.2f} cUSD")
    print(f"  Burned (in App): {total_burned:,.2f} cUSD")
    print(f"  Accounted For: {(total_in_reserve + total_in_circulation + total_burned):,.2f} cUSD")
    
    # USDC collateral analysis
    app_usdc = get_balance(APP_ADDRESS, USDC_ID)
    print(f"\nCollateral Analysis:")
    print(f"  USDC Locked in App: {app_usdc:,.2f} USDC")
    print(f"  Collateral Ratio: 1:1")
    print(f"  Max cUSD Mintable with Current USDC: {app_usdc:,.2f} cUSD")

def main():
    print("=" * 60)
    print("cUSD CONTRACT READ-ONLY TESTS")
    print("=" * 60)
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"\nConnected to LocalNet (round {status.get('last-round', 0)})")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Run tests
    try:
        test_balances()
        test_contract_state()
        test_asset_info()
        test_app_info()
        test_user_local_state()
        calculate_statistics()
        
        print("\n" + "=" * 60)
        print("ALL READ-ONLY TESTS COMPLETED! 🎉")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()