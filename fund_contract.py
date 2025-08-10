#!/usr/bin/env python
"""
Fund the cUSD contract with ALGO so it can opt-in to assets
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
from algosdk.transaction import PaymentTxn, wait_for_confirmation


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def fund_contract():
    """Fund the contract with minimum ALGO"""
    
    print("\n" + "="*60)
    print("FUNDING cUSD CONTRACT")
    print("="*60)
    
    # Load deployment info
    with open("cusd_deployment.json", "r") as f:
        deployment = json.load(f)
    
    app_address = deployment["app_address"]
    
    print(f"\nContract Address: {app_address}")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Check current balance
    account_info = algod_client.account_info(app_address)
    current_balance = account_info.get('amount', 0) / 1_000_000
    print(f"Current balance: {current_balance:.6f} ALGO")
    
    if current_balance >= 0.5:
        print("✅ Contract already has sufficient balance")
        return
    
    # Get funder account
    mnemonic_phrase = os.environ.get("ALGORAND_CONFIO_CREATOR_MNEMONIC")
    if not mnemonic_phrase:
        print("\n❌ No mnemonic found. Set ALGORAND_CONFIO_CREATOR_MNEMONIC")
        return
    
    private_key = mnemonic.to_private_key(mnemonic_phrase)
    address = account.address_from_private_key(private_key)
    
    print(f"\nUsing funder account: {address}")
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    # Send 0.5 ALGO to the contract
    amount = 500_000  # 0.5 ALGO in microAlgos
    
    txn = PaymentTxn(
        sender=address,
        receiver=app_address,
        amt=amount,
        sp=params
    )
    
    # Sign and send
    signed_txn = txn.sign(private_key)
    
    print(f"\nSending {amount/1_000_000:.6f} ALGO to contract...")
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Transaction ID: {tx_id}")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    
    print(f"\n✅ Contract funded!")
    print(f"   Confirmed in round: {confirmed_txn.get('confirmed-round')}")
    
    # Check new balance
    account_info = algod_client.account_info(app_address)
    new_balance = account_info.get('amount', 0) / 1_000_000
    print(f"   New balance: {new_balance:.6f} ALGO")


if __name__ == "__main__":
    fund_contract()