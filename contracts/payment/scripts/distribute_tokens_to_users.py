#!/usr/bin/env python3
"""
Distribute CONFIO, Mock USDC, and cUSD tokens to users with valid Algorand addresses in the database.
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
from algosdk.transaction import AssetTransferTxn, PaymentTxn, wait_for_confirmation, ApplicationCallTxn, OnComplete
from algosdk.encoding import decode_address, is_valid_address
from algosdk.abi import Method, Returns
from users.models import Account
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN
from contracts.config.new_token_config import (
    CONFIO_ASSET_ID,
    CONFIO_CREATOR_ADDRESS,
    CONFIO_CREATOR_PRIVATE_KEY,
    MOCK_USDC_ASSET_ID,
    CUSD_ASSET_ID,
    CUSD_APP_ID
)
from contracts.config.confio_token_config import (
    CONFIO_CREATOR_ADDRESS as MOCK_USDC_CREATOR,
    CONFIO_CREATOR_PRIVATE_KEY as MOCK_USDC_KEY
)
from contracts.config.localnet_accounts import ADMIN_ADDRESS, ADMIN_PRIVATE_KEY

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

# Token distribution amounts (integer values)
DISTRIBUTION_AMOUNTS = {
    'CONFIO': 1000,      # 1000 CONFIO tokens
    'MOCK_USDC': 5000,   # 5000 Mock USDC tokens  
    'CUSD': 100          # 100 cUSD tokens
}

def validate_algorand_address(address):
    """Validate if a string is a valid Algorand address"""
    if not address:
        return False
    try:
        return is_valid_address(address)
    except:
        return False

def fund_account_with_algo(address):
    """Fund an account with minimum ALGO for transactions"""
    try:
        # Check current balance
        account_info = algod_client.account_info(address)
        balance = account_info.get('amount', 0) / 1_000_000
        
        if balance < 1:  # If less than 1 ALGO
            print(f"    Funding with 2 ALGO...")
            params = algod_client.suggested_params()
            fund_txn = PaymentTxn(
                sender=ADMIN_ADDRESS,
                sp=params,
                receiver=address,
                amt=2_000_000  # 2 ALGO
            )
            signed = fund_txn.sign(ADMIN_PRIVATE_KEY)
            txid = algod_client.send_transaction(signed)
            wait_for_confirmation(algod_client, txid, 4)
            print(f"    ✅ Funded with 2 ALGO")
        else:
            print(f"    ℹ️  Already has {balance:.2f} ALGO")
        return True
    except Exception as e:
        print(f"    ❌ Failed to fund: {e}")
        return False

def opt_in_to_asset(address, asset_id, asset_name):
    """Check if account is opted in to asset, return True if already opted in"""
    try:
        account_info = algod_client.account_info(address)
        for asset in account_info.get("assets", []):
            if asset["asset-id"] == asset_id:
                print(f"    ℹ️  Already opted in to {asset_name}")
                return True
        return False
    except Exception as e:
        print(f"    ❌ Failed to check opt-in: {e}")
        return False

def distribute_token(address, asset_id, amount, sender_address, sender_key, token_name):
    """Distribute tokens to an address"""
    try:
        # Check if already opted in
        if not opt_in_to_asset(address, asset_id, token_name):
            print(f"    ⚠️  User needs to opt-in to {token_name} (Asset {asset_id})")
            print(f"    ℹ️  Skipping {token_name} distribution - user must opt-in from their wallet")
            return False
        
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
        
        print(f"    ✅ Sent {amount} {token_name}")
        return True
        
    except Exception as e:
        print(f"    ❌ Failed to send {token_name}: {e}")
        return False

def mint_cusd_for_user(address, amount):
    """Mint cUSD for a user using the contract (requires collateral)"""
    try:
        print(f"    ℹ️  cUSD requires collateral - skipping automatic minting")
        print(f"    ℹ️  User can mint cUSD by depositing Mock USDC as collateral")
        return False
        
    except Exception as e:
        print(f"    ❌ Failed to prepare cUSD: {e}")
        return False

def distribute_tokens_to_user(account):
    """Distribute all tokens to a single user account"""
    address = account.algorand_address
    username = account.user.username
    account_type = account.get_account_type_display()
    
    print(f"\n👤 User: {username} ({account_type} account)")
    print(f"   Address: {address}")
    
    # Fund with ALGO first
    if not fund_account_with_algo(address):
        print("   ⚠️  Skipping user - funding failed")
        return False
    
    success = True
    
    # Distribute CONFIO
    if not distribute_token(
        address, 
        CONFIO_ASSET_ID, 
        DISTRIBUTION_AMOUNTS['CONFIO'],
        CONFIO_CREATOR_ADDRESS,
        CONFIO_CREATOR_PRIVATE_KEY,
        "CONFIO"
    ):
        success = False
    
    # Distribute Mock USDC
    if not distribute_token(
        address,
        MOCK_USDC_ASSET_ID,
        DISTRIBUTION_AMOUNTS['MOCK_USDC'],
        MOCK_USDC_CREATOR,
        MOCK_USDC_KEY,
        "Mock USDC"
    ):
        success = False
    
    # Note about cUSD
    mint_cusd_for_user(address, DISTRIBUTION_AMOUNTS['CUSD'])
    
    return success

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
    
    print("\n📊 Distribution Amounts:")
    print(f"  CONFIO: {DISTRIBUTION_AMOUNTS['CONFIO']} tokens")
    print(f"  Mock USDC: {DISTRIBUTION_AMOUNTS['MOCK_USDC']} tokens")
    print(f"  cUSD: {DISTRIBUTION_AMOUNTS['CUSD']} tokens (requires collateral)")
    
    # Get all accounts with valid Algorand addresses
    accounts = Account.objects.filter(
        algorand_address__isnull=False
    ).exclude(
        algorand_address=''
    ).select_related('user')
    
    valid_accounts = []
    for account in accounts:
        if validate_algorand_address(account.algorand_address):
            valid_accounts.append(account)
        else:
            print(f"\n⚠️  Invalid address for {account.user.username}: {account.algorand_address}")
    
    if not valid_accounts:
        print("\n❌ No valid Algorand addresses found in database!")
        print("ℹ️  Users need to have valid Algorand addresses set in their accounts")
        return
    
    print(f"\n📝 Found {len(valid_accounts)} accounts with valid Algorand addresses")
    
    # Distribute tokens to each user
    successful = 0
    failed = 0
    
    for account in valid_accounts:
        if distribute_tokens_to_user(account):
            successful += 1
        else:
            failed += 1
    
    # Summary
    print("\n" + "=" * 60)
    print("DISTRIBUTION COMPLETE")
    print("=" * 60)
    print(f"\n✅ Successful: {successful} accounts")
    if failed > 0:
        print(f"❌ Failed: {failed} accounts")
    
    print("\n📝 Notes:")
    print("1. Users must opt-in to assets from their wallets before receiving tokens")
    print("2. cUSD requires Mock USDC collateral to mint")
    print("3. Each user received 2 ALGO for transaction fees")
    
    print("\n🔧 To update LocalNet configuration in Django:")
    print("   python contracts/scripts/setup_localnet_config.py")
    print("   python manage.py runserver")

if __name__ == "__main__":
    main()