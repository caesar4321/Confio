#!/usr/bin/env python
"""
Create CONFIO token on Algorand as an ASA (Algorand Standard Asset)

Token Specifications (from confio.move):
- Name: Confío
- Symbol: CONFIO  
- Decimals: 6
- Total Supply: 1,000,000,000 (1 billion) tokens
- Description: Utility and governance coin for the Confío app
- Website: https://confio.lat
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import AssetConfigTxn, wait_for_confirmation
import json


def create_confio_token():
    """Create CONFIO token on Algorand"""
    
    # Configuration
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    
    print("=" * 60)
    print("CONFIO TOKEN CREATION ON ALGORAND")
    print("=" * 60)
    
    # Initialize Algod client
    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    # Get network status
    try:
        status = algod_client.status()
        print(f"\n✓ Connected to Algorand Testnet")
        print(f"  Current round: {status.get('last-round')}")
    except Exception as e:
        print(f"\n✗ Failed to connect to Algorand: {e}")
        return
    
    # Create or load creator account
    print("\n" + "-" * 60)
    print("CREATOR ACCOUNT SETUP")
    print("-" * 60)
    
    # Check if we have an existing creator account in environment
    creator_mnemonic = os.environ.get('ALGORAND_CONFIO_CREATOR_MNEMONIC')
    
    if creator_mnemonic:
        # Use existing account
        creator_private_key = mnemonic.to_private_key(creator_mnemonic)
        creator_address = account.address_from_private_key(creator_private_key)
        print(f"Using existing creator account: {creator_address}")
    else:
        # Generate new account
        creator_private_key, creator_address = account.generate_account()
        creator_mnemonic = mnemonic.from_private_key(creator_private_key)
        print(f"Generated new creator account: {creator_address}")
        print(f"\n⚠️  IMPORTANT: Save this mnemonic to create the token:")
        print(f"Mnemonic: {creator_mnemonic}")
        print(f"\nSet this in your environment:")
        print(f"export ALGORAND_CONFIO_CREATOR_MNEMONIC=\"{creator_mnemonic}\"")
    
    # Check creator account balance
    try:
        account_info = algod_client.account_info(creator_address)
        balance = account_info.get('amount', 0) / 1_000_000
        print(f"\nCreator account balance: {balance} ALGO")
        
        if balance < 0.2:
            print(f"\n⚠️  Insufficient balance! You need at least 0.2 ALGO to create the token.")
            print(f"Fund this account using the Algorand Testnet Dispenser:")
            print(f"https://dispenser.testnet.aws.algodev.network/")
            print(f"Address to fund: {creator_address}")
            return
    except Exception as e:
        print(f"\n✗ Failed to check balance: {e}")
        return
    
    # Token parameters
    print("\n" + "-" * 60)
    print("TOKEN PARAMETERS")
    print("-" * 60)
    
    token_params = {
        "asset_name": "Confío",
        "unit_name": "CONFIO",
        "total": 1_000_000_000_000_000,  # 1 billion with 6 decimals
        "decimals": 6,
        "default_frozen": False,  # Tokens are not frozen by default
        "url": "https://confio.lat",
        "metadata_hash": b"Utility and governance coin for".ljust(32, b' '),  # Exactly 32 bytes
        "manager": creator_address,  # Can update asset parameters
        "reserve": creator_address,  # Holds uncirculated tokens
        "freeze": "",  # No freeze authority (tokens can't be frozen)
        "clawback": "",  # No clawback (tokens can't be revoked)
        "strict_empty_address_check": False  # Allow empty freeze/clawback
    }
    
    print(f"Name: {token_params['asset_name']}")
    print(f"Symbol: {token_params['unit_name']}")
    print(f"Total Supply: {token_params['total'] / (10 ** token_params['decimals']):,.0f} CONFIO")
    print(f"Decimals: {token_params['decimals']}")
    print(f"URL: {token_params['url']}")
    print(f"Manager: {token_params['manager']}")
    print(f"Reserve: {token_params['reserve']}")
    print(f"Freeze Authority: {token_params['freeze'] or 'None (tokens cannot be frozen)'}")
    print(f"Clawback Authority: {token_params['clawback'] or 'None (tokens cannot be clawed back)'}")
    
    # Auto-confirm for non-interactive mode
    print("\n" + "-" * 60)
    if not sys.stdin.isatty():
        print("Running in non-interactive mode - auto-confirming token creation...")
    else:
        response = input("Do you want to create the CONFIO token? (yes/no): ")
        if response.lower() != 'yes':
            print("Token creation cancelled.")
            return
    
    # Create the token
    print("\nCreating CONFIO token...")
    
    try:
        # Get suggested parameters
        params = algod_client.suggested_params()
        
        # Create asset creation transaction
        txn = AssetConfigTxn(
            sender=creator_address,
            sp=params,
            total=token_params["total"],
            default_frozen=token_params["default_frozen"],
            unit_name=token_params["unit_name"],
            asset_name=token_params["asset_name"],
            manager=token_params["manager"],
            reserve=token_params["reserve"],
            freeze=token_params["freeze"] if token_params["freeze"] else None,
            clawback=token_params["clawback"] if token_params["clawback"] else None,
            url=token_params["url"],
            metadata_hash=token_params["metadata_hash"],
            decimals=token_params["decimals"],
            strict_empty_address_check=False
        )
        
        # Sign transaction
        signed_txn = txn.sign(creator_private_key)
        
        # Submit transaction
        tx_id = algod_client.send_transaction(signed_txn)
        print(f"Transaction ID: {tx_id}")
        
        # Wait for confirmation
        print("Waiting for confirmation...")
        confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
        
        # Get the asset ID
        asset_id = confirmed_txn["asset-index"]
        
        print("\n" + "=" * 60)
        print("✅ CONFIO TOKEN CREATED SUCCESSFULLY!")
        print("=" * 60)
        print(f"\nAsset ID: {asset_id}")
        print(f"Creator: {creator_address}")
        print(f"Transaction ID: {tx_id}")
        print(f"Confirmed in round: {confirmed_txn.get('confirmed-round')}")
        
        # Save configuration
        print("\n" + "-" * 60)
        print("NEXT STEPS:")
        print("-" * 60)
        print(f"\n1. Update your .env file with:")
        print(f"   ALGORAND_CONFIO_ASSET_ID={asset_id}")
        print(f"   ALGORAND_CONFIO_CREATOR_ADDRESS={creator_address}")
        if not os.environ.get('ALGORAND_CONFIO_CREATOR_MNEMONIC'):
            print(f"   ALGORAND_CONFIO_CREATOR_MNEMONIC=\"{creator_mnemonic}\"")
        
        print(f"\n2. View your token on Algorand Explorer:")
        print(f"   https://testnet.algoexplorer.io/asset/{asset_id}")
        
        print(f"\n3. To distribute tokens, users must first opt-in to the asset")
        print(f"   Asset ID to opt-in: {asset_id}")
        
        # Save to file
        config_file = "confio_token_config.json"
        config_data = {
            "network": "testnet",
            "asset_id": asset_id,
            "asset_name": token_params["asset_name"],
            "unit_name": token_params["unit_name"],
            "decimals": token_params["decimals"],
            "total_supply": token_params["total"],
            "creator_address": creator_address,
            "transaction_id": tx_id,
            "url": token_params["url"]
        }
        
        with open(config_file, 'w') as f:
            json.dump(config_data, f, indent=2)
        
        print(f"\n4. Token configuration saved to: {config_file}")
        
        return asset_id
        
    except Exception as e:
        print(f"\n✗ Failed to create token: {e}")
        return None


def check_existing_confio():
    """Check if CONFIO token already exists"""
    from django.conf import settings
    
    if settings.ALGORAND_CONFIO_ASSET_ID:
        print("\n⚠️  CONFIO token already configured!")
        print(f"Asset ID: {settings.ALGORAND_CONFIO_ASSET_ID}")
        
        # Try to get asset info
        try:
            algod_client = algod.AlgodClient("", "https://testnet-api.algonode.cloud")
            asset_info = algod_client.asset_info(settings.ALGORAND_CONFIO_ASSET_ID)
            params = asset_info.get('params', {})
            print(f"Name: {params.get('name')}")
            print(f"Symbol: {params.get('unit_name')}")
            print(f"Total Supply: {params.get('total') / (10 ** params.get('decimals', 0)):,.0f}")
            print(f"Creator: {params.get('creator')}")
            return True
        except:
            print("But asset not found on network. Creating new token...")
            return False
    return False


if __name__ == "__main__":
    print("\nCONFIO Token Creation Script for Algorand")
    print("This will create the CONFIO utility token as an Algorand Standard Asset (ASA)")
    
    # Check if token already exists
    if not check_existing_confio():
        create_confio_token()
    else:
        print("\nTo create a new token, clear ALGORAND_CONFIO_ASSET_ID from settings.")