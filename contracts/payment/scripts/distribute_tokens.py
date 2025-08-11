#!/usr/bin/env python3
"""
Distribute CONFIO, Mock USDC, and cUSD tokens to users with valid Algorand addresses.
Assumes users have already opted in to assets during sign-in.
Distributes integer amounts only.
"""

import os
import sys
import django

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from algosdk.v2client import algod
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation
from algosdk.encoding import is_valid_address
from users.models import Account
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN
from contracts.config.new_token_config import (
    CONFIO_ASSET_ID,
    CONFIO_CREATOR_ADDRESS,
    CONFIO_CREATOR_PRIVATE_KEY,
    MOCK_USDC_ASSET_ID,
    CUSD_ASSET_ID,
)
from contracts.config.confio_token_config import (
    CONFIO_CREATOR_ADDRESS as MOCK_USDC_CREATOR,
    CONFIO_CREATOR_PRIVATE_KEY as MOCK_USDC_KEY
)

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

# Token distribution amounts (integer values)
DISTRIBUTION_AMOUNTS = {
    'CONFIO': 1000,      # 1000 CONFIO tokens
    'MOCK_USDC': 5000,   # 5000 Mock USDC tokens  
}

def validate_algorand_address(address):
    """Validate if a string is a valid Algorand address"""
    if not address:
        return False
    try:
        return is_valid_address(address)
    except:
        return False

def check_asset_balance(address, asset_id):
    """Check if account has opted in and get balance"""
    try:
        account_info = algod_client.account_info(address)
        for asset in account_info.get("assets", []):
            if asset["asset-id"] == asset_id:
                return True, asset["amount"] / 1_000_000
        return False, 0
    except Exception as e:
        print(f"    ❌ Error checking balance: {e}")
        return False, 0

def distribute_token(address, asset_id, amount, sender_address, sender_key, token_name):
    """Distribute tokens to an address that has already opted in"""
    try:
        # Check if opted in and current balance
        opted_in, current_balance = check_asset_balance(address, asset_id)
        
        if not opted_in:
            print(f"    ⚠️  Not opted in to {token_name} - skipping")
            return False
        
        if current_balance > 0:
            print(f"    ℹ️  Already has {current_balance:.0f} {token_name}")
        
        # Send tokens
        params = algod_client.suggested_params()
        transfer_txn = AssetTransferTxn(
            sender=sender_address,
            sp=params,
            receiver=address,
            amt=amount * 1_000_000,  # Convert to micro-units (6 decimals)
            index=asset_id
        )
        signed = transfer_txn.sign(sender_key)
        txid = algod_client.send_transaction(signed)
        wait_for_confirmation(algod_client, txid, 4)
        
        new_balance = current_balance + amount
        print(f"    ✅ Sent {amount} {token_name} (balance: {new_balance:.0f})")
        return True
        
    except Exception as e:
        print(f"    ❌ Failed to send {token_name}: {e}")
        return False

def distribute_tokens_to_user(account):
    """Distribute tokens to a single user account"""
    address = account.algorand_address
    username = account.user.username
    account_type = account.get_account_type_display()
    
    print(f"\n👤 User: {username} ({account_type} account)")
    print(f"   Address: {address[:20]}...{address[-10:]}")
    
    stats = {'distributed': 0, 'skipped': 0, 'failed': 0}
    
    # Distribute CONFIO
    result = distribute_token(
        address, 
        CONFIO_ASSET_ID, 
        DISTRIBUTION_AMOUNTS['CONFIO'],
        CONFIO_CREATOR_ADDRESS,
        CONFIO_CREATOR_PRIVATE_KEY,
        "CONFIO"
    )
    if result:
        stats['distributed'] += 1
    elif result is False:
        stats['failed'] += 1
    else:
        stats['skipped'] += 1
    
    # Distribute Mock USDC
    result = distribute_token(
        address,
        MOCK_USDC_ASSET_ID,
        DISTRIBUTION_AMOUNTS['MOCK_USDC'],
        MOCK_USDC_CREATOR,
        MOCK_USDC_KEY,
        "Mock USDC"
    )
    if result:
        stats['distributed'] += 1
    elif result is False:
        stats['failed'] += 1
    else:
        stats['skipped'] += 1
    
    # Note about cUSD
    print(f"    ℹ️  cUSD requires collateral - mint via contract")
    
    return stats

def main():
    print("=" * 60)
    print("TOKEN DISTRIBUTION TO DATABASE USERS")
    print("=" * 60)
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"\nConnected to LocalNet (round {status.get('last-round', 0)})")
    except Exception as e:
        print(f"Error connecting to LocalNet: {e}")
        print("Make sure LocalNet is running: algokit localnet start")
        sys.exit(1)
    
    print("\n📊 Distribution Configuration:")
    print(f"  Network: LocalNet")
    print(f"  CONFIO (Asset {CONFIO_ASSET_ID}): {DISTRIBUTION_AMOUNTS['CONFIO']} tokens")
    print(f"  Mock USDC (Asset {MOCK_USDC_ASSET_ID}): {DISTRIBUTION_AMOUNTS['MOCK_USDC']} tokens")
    print(f"  cUSD (Asset {CUSD_ASSET_ID}): Requires collateral minting")
    
    # Get all accounts with valid Algorand addresses
    accounts = Account.objects.filter(
        algorand_address__isnull=False
    ).exclude(
        algorand_address=''
    ).select_related('user')
    
    valid_accounts = []
    invalid_count = 0
    
    for account in accounts:
        if validate_algorand_address(account.algorand_address):
            valid_accounts.append(account)
        else:
            invalid_count += 1
            print(f"\n⚠️  Invalid address for {account.user.username}: {account.algorand_address[:20]}...")
    
    if not valid_accounts:
        print("\n❌ No valid Algorand addresses found in database!")
        return
    
    print(f"\n📝 Processing {len(valid_accounts)} valid accounts")
    if invalid_count > 0:
        print(f"   ({invalid_count} invalid addresses skipped)")
    
    # Distribute tokens to each user
    total_stats = {'distributed': 0, 'skipped': 0, 'failed': 0}
    
    for account in valid_accounts:
        stats = distribute_tokens_to_user(account)
        total_stats['distributed'] += stats['distributed']
        total_stats['skipped'] += stats['skipped']
        total_stats['failed'] += stats['failed']
    
    # Summary
    print("\n" + "=" * 60)
    print("DISTRIBUTION SUMMARY")
    print("=" * 60)
    print(f"\n📊 Results:")
    print(f"  ✅ Tokens distributed: {total_stats['distributed']}")
    print(f"  ⚠️  Tokens skipped (not opted in): {total_stats['skipped']}")
    if total_stats['failed'] > 0:
        print(f"  ❌ Failed distributions: {total_stats['failed']}")
    
    print(f"\n📝 Total users processed: {len(valid_accounts)}")
    
    print("\n💡 Next steps:")
    print("1. Users need to opt-in to assets during sign-in")
    print("2. Run this script again after users have opted in")
    print("3. Users can mint cUSD by depositing Mock USDC as collateral")

if __name__ == "__main__":
    main()