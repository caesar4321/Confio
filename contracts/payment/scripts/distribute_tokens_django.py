#!/usr/bin/env python3
"""
Distribute CONFIO, USDC, and cUSD tokens to users with valid Algorand addresses.
Uses Django settings for all configuration.
Assumes users have already opted in to assets during sign-in.
"""

import os
import sys
import django

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation
from algosdk.encoding import is_valid_address
from users.models import Account
from blockchain.algorand_config import (
    get_algod_client,
    get_network,
    get_asset_ids,
    get_localnet_creators
)
from decouple import config

# Get configuration from Django settings
algod_client = get_algod_client()
network = get_network()
asset_ids = get_asset_ids()

# Token distribution amounts (integer values)
DISTRIBUTION_AMOUNTS = {
    'CONFIO': config('DISTRIBUTION_CONFIO', default=1000, cast=int),
    'USDC': config('DISTRIBUTION_USDC', default=5000, cast=int),
}

def get_token_sources():
    """Get token source accounts based on network"""
    if network == 'localnet':
        # For LocalNet, use the creator accounts from environment
        creators = get_localnet_creators()
        return {
            'CONFIO': {
                'address': creators['CONFIO']['address'],
                'key': creators['CONFIO']['private_key'],
            },
            'USDC': {
                'address': creators['USDC']['address'],
                'key': creators['USDC']['private_key'],
            }
        }
    else:
        # For testnet/mainnet, use sponsor account
        sponsor = config('ALGORAND_SPONSOR_ADDRESS', default='')
        sponsor_key = config('ALGORAND_SPONSOR_PRIVATE_KEY', default='')
        
        if not sponsor or not sponsor_key:
            raise ValueError("Sponsor account not configured for testnet/mainnet")
        
        return {
            'CONFIO': {
                'address': sponsor,
                'key': sponsor_key,
            },
            'USDC': {
                'address': sponsor,
                'key': sponsor_key,
            }
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

def distribute_token(address, token_name, amount):
    """Distribute tokens to an address that has already opted in"""
    try:
        asset_id = asset_ids.get(token_name.upper().replace(' ', '_').replace('MOCK_', ''))
        if not asset_id:
            print(f"    ⚠️  {token_name} not configured - skipping")
            return None
        
        # Get token source
        sources = get_token_sources()
        token_key = token_name.upper().replace(' ', '_').replace('MOCK_', '')
        if token_key not in sources:
            print(f"    ⚠️  No source configured for {token_name} - skipping")
            return None
        
        source = sources[token_key]
        if not source['address'] or not source['key']:
            print(f"    ⚠️  Source account not configured for {token_name} - skipping")
            return None
        
        # Check if opted in and current balance
        opted_in, current_balance = check_asset_balance(address, asset_id)
        
        if not opted_in:
            print(f"    ⚠️  Not opted in to {token_name} (Asset {asset_id}) - skipping")
            return False
        
        if current_balance > 0:
            print(f"    ℹ️  Already has {current_balance:.0f} {token_name}")
        
        # Send tokens
        params = algod_client.suggested_params()
        transfer_txn = AssetTransferTxn(
            sender=source['address'],
            sp=params,
            receiver=address,
            amt=amount * 1_000_000,  # Convert to micro-units (6 decimals)
            index=asset_id
        )
        signed = transfer_txn.sign(source['key'])
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
    result = distribute_token(address, "CONFIO", DISTRIBUTION_AMOUNTS['CONFIO'])
    if result is True:
        stats['distributed'] += 1
    elif result is False:
        stats['failed'] += 1
    else:
        stats['skipped'] += 1
    
    # Distribute USDC (Mock USDC on LocalNet, real USDC on testnet)
    usdc_name = "Mock USDC" if network == 'localnet' else "USDC"
    result = distribute_token(address, usdc_name, DISTRIBUTION_AMOUNTS['USDC'])
    if result is True:
        stats['distributed'] += 1
    elif result is False:
        stats['failed'] += 1
    else:
        stats['skipped'] += 1
    
    # Note about cUSD
    if asset_ids.get('CUSD'):
        print(f"    ℹ️  cUSD (Asset {asset_ids['CUSD']}) requires collateral - mint via contract")
    else:
        print(f"    ℹ️  cUSD not configured on {network}")
    
    return stats

def main():
    print("=" * 60)
    print("TOKEN DISTRIBUTION TO DATABASE USERS")
    print("=" * 60)
    
    # Show configuration
    print(f"\n📊 Configuration from Django settings:")
    print(f"  Network: {network}")
    print(f"  Algod: {settings.ALGORAND_ALGOD_ADDRESS}")
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"  Connected (round {status.get('last-round', 0)})")
    except Exception as e:
        print(f"\n❌ Error connecting to {network}: {e}")
        if network == 'localnet':
            print("Make sure LocalNet is running: algokit localnet start")
        sys.exit(1)
    
    print(f"\n📊 Asset IDs from Django settings:")
    for name, asset_id in asset_ids.items():
        if asset_id:
            print(f"  {name}: Asset {asset_id}")
        else:
            print(f"  {name}: Not configured")
    
    print(f"\n📊 Distribution Amounts:")
    for token, amount in DISTRIBUTION_AMOUNTS.items():
        print(f"  {token}: {amount} tokens")
    print(f"  cUSD: Requires collateral minting")
    
    # Check token sources
    try:
        sources = get_token_sources()
        print(f"\n📊 Token Sources:")
        for token, source in sources.items():
            if source['address']:
                print(f"  {token}: {source['address'][:20]}...")
            else:
                print(f"  {token}: Not configured")
    except Exception as e:
        print(f"\n❌ Error getting token sources: {e}")
        print("Please configure LOCALNET_*_CREATOR or ALGORAND_SPONSOR in .env")
        sys.exit(1)
    
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
    print(f"  ⚠️  Tokens skipped (not configured/opted in): {total_stats['skipped']}")
    if total_stats['failed'] > 0:
        print(f"  ❌ Failed distributions: {total_stats['failed']}")
    
    print(f"\n📝 Total users processed: {len(valid_accounts)}")
    
    print("\n💡 Configuration:")
    print("  Asset IDs are configured in .env file")
    print("  Network is set via ALGORAND_NETWORK in .env")
    print("  Distribution amounts via DISTRIBUTION_* in .env")

if __name__ == "__main__":
    main()