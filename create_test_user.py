#!/usr/bin/env python
"""
Create a fresh test user account for USDC collateral testing
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

from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import PaymentTxn, AssetTransferTxn, wait_for_confirmation


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def create_test_user():
    """Create and fund a test user account"""
    
    print("\n" + "="*60)
    print("CREATING TEST USER FOR COLLATERAL TESTING")
    print("="*60)
    
    # Generate new account
    test_private_key, test_address = account.generate_account()
    test_mnemonic = mnemonic.from_private_key(test_private_key)
    
    print(f"\n🆕 Generated Test Account:")
    print(f"   Address: {test_address}")
    print(f"   Mnemonic: {test_mnemonic}")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Get admin account to fund the test user
    admin_mnemonic = os.environ.get("ALGORAND_CONFIO_CREATOR_MNEMONIC")
    if not admin_mnemonic:
        print("\n❌ No admin mnemonic found")
        return
    
    admin_private_key = mnemonic.to_private_key(admin_mnemonic)
    admin_address = account.address_from_private_key(admin_private_key)
    
    print(f"\n💰 Funding test account from admin...")
    print(f"   Admin: {admin_address}")
    
    # Fund with 1 ALGO (enough for testing)
    params = algod_client.suggested_params()
    fund_txn = PaymentTxn(
        sender=admin_address,
        receiver=test_address,
        amt=1_000_000,  # 1 ALGO
        sp=params
    )
    
    try:
        signed_fund = fund_txn.sign(admin_private_key)
        fund_tx_id = algod_client.send_transaction(signed_fund)
        wait_for_confirmation(algod_client, fund_tx_id, 4)
        
        print(f"✅ Test account funded with 1 ALGO")
        print(f"   Transaction ID: {fund_tx_id}")
        
        # Save test account info
        test_account_info = {
            "address": test_address,
            "mnemonic": test_mnemonic,
            "private_key": test_private_key.hex(),
            "purpose": "USDC collateral testing"
        }
        
        with open("test_user_account.json", "w") as f:
            json.dump(test_account_info, f, indent=2)
        
        print(f"\n📝 Test account info saved to test_user_account.json")
        
        print(f"\n📋 Next Steps:")
        print(f"   1. Use this address for Circle USDC faucet: {test_address}")
        print(f"   2. Get testnet USDC from: https://faucet.circle.com")
        print(f"   3. Run: python test_collateral_with_test_user.py")
        
        return test_address
        
    except Exception as e:
        print(f"❌ Failed to fund test account: {e}")
        return None


if __name__ == "__main__":
    create_test_user()