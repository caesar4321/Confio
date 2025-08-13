#!/usr/bin/env python
"""
Manually opt-in a user to the cUSD application
"""
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import ApplicationOptInTxn, wait_for_confirmation
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
ALGORAND_NODE_URL = "https://testnet-api.algonode.cloud"
APP_ID = 744151196  # cUSD app ID

def opt_in_to_app(private_key: str, address: str):
    """Opt into the cUSD application"""
    
    # Initialize Algorand client
    algod_client = algod.AlgodClient("", ALGORAND_NODE_URL)
    
    # Check current opt-in status
    account_info = algod_client.account_info(address)
    apps_local_state = account_info.get('apps-local-state', [])
    already_opted_in = any(app['id'] == APP_ID for app in apps_local_state)
    
    if already_opted_in:
        print(f"✓ Account {address} is already opted into app {APP_ID}")
        return True
    
    print(f"Account {address} needs to opt into app {APP_ID}")
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    # Create opt-in transaction
    opt_in_txn = ApplicationOptInTxn(
        sender=address,
        sp=params,
        index=APP_ID
    )
    
    # Sign transaction
    signed_txn = opt_in_txn.sign(private_key)
    
    # Send transaction
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Opt-in transaction sent: {tx_id}")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
    print(f"Transaction confirmed in round {confirmed_txn.get('confirmed-round', 0)}")
    
    # Verify opt-in
    account_info = algod_client.account_info(address)
    apps_local_state = account_info.get('apps-local-state', [])
    opted_in = any(app['id'] == APP_ID for app in apps_local_state)
    
    if opted_in:
        print(f"✓ Successfully opted into app {APP_ID}")
        # Show local state
        for app in apps_local_state:
            if app['id'] == APP_ID:
                print(f"Local state initialized for app {APP_ID}")
                for kv in app.get('key-value', []):
                    print(f"  {kv}")
    else:
        print(f"✗ Failed to opt into app {APP_ID}")
    
    return opted_in

if __name__ == "__main__":
    # Get the user's mnemonic (you'll need to provide this)
    print("Enter the mnemonic phrase for the account to opt-in:")
    user_mnemonic = input().strip()
    
    if not user_mnemonic:
        print("No mnemonic provided. Using test account...")
        # You can hardcode a test mnemonic here for testing
        print("Please provide a mnemonic")
        exit(1)
    
    # Get private key from mnemonic
    private_key = mnemonic.to_private_key(user_mnemonic)
    address = account.address_from_private_key(private_key)
    
    print(f"\nOpting in account: {address}")
    print(f"To cUSD app: {APP_ID}")
    
    success = opt_in_to_app(private_key, address)
    
    if success:
        print("\n✓ Account is now ready to use cUSD conversions!")
    else:
        print("\n✗ Failed to opt into the application")