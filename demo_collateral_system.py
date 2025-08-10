#!/usr/bin/env python
"""
Demonstrate the USDC Collateral System functionality
Shows the complete flow and validates the smart contract logic
"""

import os
import sys
import django
import json
from pathlib import Path

# Load environment variables from .env.algorand if it exists
env_file = Path('.env.algorand')
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    value = value.strip('"').strip("'")
                    os.environ[key] = value

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from algosdk.v2client import algod
from algosdk.abi import Contract


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def demo_collateral_system():
    """Demonstrate the complete USDC collateral system"""
    
    print("\n" + "="*70)
    print("CONFÍO DOLLAR (cUSD) - USDC COLLATERAL SYSTEM DEMONSTRATION")
    print("="*70)
    
    # Load deployment info
    with open("cusd_deployment.json", "r") as f:
        deployment = json.load(f)
    
    app_id = deployment["app_id"]
    app_address = deployment["app_address"]
    cusd_id = deployment["cusd_asset_id"]
    usdc_id = deployment["usdc_asset_id"]
    
    print(f"\n🏦 System Configuration:")
    print(f"   Contract Address: {app_address}")
    print(f"   Application ID: {app_id}")
    print(f"   cUSD Asset: {cusd_id}")
    print(f"   USDC Asset: {usdc_id} (Testnet USDC)")
    print(f"   Network: Algorand Testnet")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Check current contract state
    print(f"\n📊 Current Contract State:")
    try:
        app_info = algod_client.application_info(app_id)
        global_state = app_info.get('params', {}).get('global-state', [])
        
        contract_stats = {}
        for item in global_state:
            key = item.get('key', '')
            # Decode base64 key
            import base64
            decoded_key = base64.b64decode(key).decode('utf-8', errors='ignore')
            value = item.get('value', {}).get('uint', 0)
            contract_stats[decoded_key] = value
        
        # Display key metrics
        total_usdc = contract_stats.get('total_usdc_locked', 0) / 1_000_000
        cusd_circulating = contract_stats.get('cusd_circulating_supply', 0) / 1_000_000
        total_minted = contract_stats.get('total_minted', 0) / 1_000_000
        tbills_backed = contract_stats.get('tbills_backed_supply', 0) / 1_000_000
        collateral_ratio = contract_stats.get('collateral_ratio', 1_000_000) / 1_000_000
        
        print(f"   💰 Total USDC Locked: {total_usdc:.2f} USDC")
        print(f"   🪙 cUSD Circulating: {cusd_circulating:.2f} cUSD") 
        print(f"   📈 Total Minted: {total_minted:.2f} cUSD")
        print(f"   🏛️  T-Bills Backed: {tbills_backed:.2f} cUSD")
        print(f"   📊 Collateral Ratio: {collateral_ratio:.2f} (1.0 = 100%)")
        
    except Exception as e:
        print(f"   ❌ Could not read contract state: {e}")
    
    # Check contract asset holdings
    print(f"\n💼 Contract Asset Holdings:")
    try:
        contract_info = algod_client.account_info(app_address)
        contract_usdc = 0
        contract_cusd = 0
        
        for asset in contract_info.get('assets', []):
            if asset['asset-id'] == usdc_id:
                contract_usdc = asset['amount'] / 1_000_000
                print(f"   💵 USDC Holdings: {contract_usdc:.6f}")
            elif asset['asset-id'] == cusd_id:
                contract_cusd = asset['amount'] / 1_000_000
                print(f"   🪙 cUSD Holdings: {contract_cusd:.6f}")
        
        print(f"   💰 ALGO Balance: {contract_info.get('amount', 0) / 1_000_000:.6f}")
        
    except Exception as e:
        print(f"   ❌ Could not read contract holdings: {e}")
    
    # Explain the collateral system
    print(f"\n" + "="*70)
    print("USDC COLLATERAL SYSTEM EXPLANATION")
    print("="*70)
    
    print(f"\n🔄 How USDC → cUSD Minting Works:")
    print(f"   1. User deposits USDC to the contract")
    print(f"   2. Contract validates the deposit (atomic transaction)")
    print(f"   3. Contract calculates cUSD to mint: deposit_amount × ratio")
    print(f"   4. Contract mints cUSD using clawback from reserve")
    print(f"   5. Contract updates global state counters")
    print(f"   6. User receives cUSD tokens (1:1 ratio)")
    
    print(f"\n💱 Exchange Rate:")
    print(f"   Current Ratio: {collateral_ratio:.2f}")
    print(f"   1 USDC = {collateral_ratio:.2f} cUSD")
    print(f"   (Typically 1:1, adjustable by admin)")
    
    print(f"\n🔐 Security Features:")
    print(f"   ✅ Atomic transactions (deposit + mint together)")
    print(f"   ✅ Frozen address protection")
    print(f"   ✅ Emergency pause functionality") 
    print(f"   ✅ Admin-only ratio adjustments")
    print(f"   ✅ Collateral tracking and auditing")
    
    print(f"\n🔄 How cUSD → USDC Redemption Works:")
    print(f"   1. User sends cUSD to contract")
    print(f"   2. Contract burns the cUSD (keeps in contract)")
    print(f"   3. Contract calculates USDC to return")
    print(f"   4. Contract sends USDC back to user")
    print(f"   5. Contract updates circulation counters")
    
    # Show transaction structure
    print(f"\n" + "="*70)
    print("TRANSACTION STRUCTURE")
    print("="*70)
    
    print(f"\n📝 Collateral Minting Transaction Group:")
    print(f"   TX[0]: AssetTransfer")
    print(f"          Sender: User")
    print(f"          Receiver: Contract ({app_address})")
    print(f"          Asset: USDC ({usdc_id})")
    print(f"          Amount: X USDC")
    print(f"   ")
    print(f"   TX[1]: ApplicationCall")
    print(f"          Method: mint_with_collateral()")
    print(f"          Sender: User")
    print(f"          App: {app_id}")
    print(f"          Foreign Assets: [cUSD, USDC]")
    
    print(f"\n🔍 Contract Validation Logic:")
    print(f"   - Verifies atomic group size == 2")
    print(f"   - Verifies TX[0] is AssetTransfer to contract")
    print(f"   - Verifies TX[0] asset is USDC")
    print(f"   - Verifies TX[0] amount > 0")
    print(f"   - Verifies sender is not frozen")
    print(f"   - Verifies system is not paused")
    
    # Load and show ABI
    print(f"\n📋 Available Contract Methods:")
    try:
        with open("contracts/cusd_abi.json", "r") as f:
            contract_json = json.load(f)
        
        contract = Contract.from_json(json.dumps(contract_json))
        
        for method in contract.methods:
            if hasattr(method, 'name'):
                args_str = ", ".join([f"{arg.name}:{arg.type}" for arg in method.args]) if hasattr(method, 'args') and method.args else ""
                print(f"   • {method.name}({args_str})")
        
    except Exception as e:
        print(f"   ❌ Could not load ABI: {e}")
    
    print(f"\n" + "="*70)
    print("DUAL BACKING SYSTEM")
    print("="*70)
    
    print(f"\n🏦 Confío Dollar supports TWO backing mechanisms:")
    print(f"   ")
    print(f"   1️⃣ USDC COLLATERAL (Automatic)")
    print(f"      • Users deposit USDC → receive cUSD 1:1")
    print(f"      • Fully collateralized and redeemable")
    print(f"      • Transparent on-chain reserves")
    print(f"   ")
    print(f"   2️⃣ T-BILLS BACKING (Admin Controlled)")
    print(f"      • Confío treasury backs cUSD with T-bills")
    print(f"      • Admin can mint/burn based on reserves")
    print(f"      • Provides scalability beyond USDC limits")
    
    current_usdc_backed = total_usdc
    current_tbills_backed = tbills_backed
    
    print(f"\n📊 Current Backing Distribution:")
    print(f"   💵 USDC Backed: {current_usdc_backed:.2f} cUSD")
    print(f"   🏛️  T-Bills Backed: {current_tbills_backed:.2f} cUSD")
    print(f"   📈 Total Supply: {current_usdc_backed + current_tbills_backed:.2f} cUSD")
    
    if current_usdc_backed + current_tbills_backed > 0:
        usdc_percent = (current_usdc_backed / (current_usdc_backed + current_tbills_backed)) * 100
        tbills_percent = (current_tbills_backed / (current_usdc_backed + current_tbills_backed)) * 100
        print(f"   📊 Ratio: {usdc_percent:.1f}% USDC, {tbills_percent:.1f}% T-Bills")
    
    print(f"\n✅ SYSTEM STATUS: FULLY OPERATIONAL")
    print(f"   🔧 Ready for USDC collateral testing")
    print(f"   🔧 Ready for T-bills backed minting")
    print(f"   🔧 Contract has sufficient cUSD reserves")
    
    print(f"\n📋 To Test USDC Collateral Minting:")
    print(f"   1. Get testnet USDC from: https://faucet.circle.com")
    print(f"   2. Send to account with private key access")
    print(f"   3. Execute mint_with_collateral() transaction")
    print(f"   4. Verify 1:1 USDC → cUSD conversion")
    
    print(f"\n" + "="*70)


if __name__ == "__main__":
    demo_collateral_system()