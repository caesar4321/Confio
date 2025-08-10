#!/usr/bin/env python
"""
Transfer cUSD from reserve to contract so it can mint
This is a workaround because the old contract tries to send from its own balance
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
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def transfer_cusd():
    """Transfer cUSD to contract"""
    
    print("\n" + "="*60)
    print("TRANSFERRING cUSD TO CONTRACT")
    print("="*60)
    
    # Load deployment info
    with open("cusd_deployment.json", "r") as f:
        deployment = json.load(f)
    
    app_address = deployment["app_address"]
    cusd_id = deployment["cusd_asset_id"]
    
    print(f"\nContract Address: {app_address}")
    print(f"cUSD Asset ID: {cusd_id}")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Get reserve account
    mnemonic_phrase = os.environ.get("ALGORAND_CONFIO_CREATOR_MNEMONIC")
    if not mnemonic_phrase:
        print("\n❌ No mnemonic found. Set ALGORAND_CONFIO_CREATOR_MNEMONIC")
        return
    
    private_key = mnemonic.to_private_key(mnemonic_phrase)
    reserve_address = account.address_from_private_key(private_key)
    
    print(f"Reserve Address: {reserve_address}")
    
    # Transfer 1 million cUSD to contract (for testing)
    amount = 1_000_000_000_000  # 1 million cUSD with 6 decimals
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    # Create asset transfer
    txn = AssetTransferTxn(
        sender=reserve_address,
        sp=params,
        receiver=app_address,
        amt=amount,
        index=cusd_id
    )
    
    # Sign and send
    signed_txn = txn.sign(private_key)
    
    print(f"\nTransferring {amount/1_000_000:.2f} cUSD to contract...")
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Transaction ID: {tx_id}")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    
    print(f"\n✅ Transfer successful!")
    print(f"   Confirmed in round: {confirmed_txn.get('confirmed-round')}")
    
    # Check contract balance
    account_info = algod_client.account_info(app_address)
    for asset in account_info.get('assets', []):
        if asset['asset-id'] == cusd_id:
            balance = asset['amount'] / 1_000_000
            print(f"   Contract cUSD Balance: {balance:.2f} cUSD")
            break
    
    print("\n📝 Contract now has cUSD to mint!")
    print("   The old contract sends from its own balance")
    print("   This is a workaround until we deploy the fixed contract")


if __name__ == "__main__":
    transfer_cusd()