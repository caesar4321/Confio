#!/usr/bin/env python
"""
Create CONFIO token on Algorand as an ASA (Algorand Standard Asset)

⚠️ IMPORTANT: This script DEFINES the actual token parameters!
In Algorand, token parameters are NOT defined in contract files.
They are set during asset creation (AssetConfigTxn) and cannot be changed later.

Token Specifications:
- Name: Confío
- Symbol: CONFIO  
- Decimals: 6
- Total Supply: 1,000,000,000 (1 billion) tokens - FIXED FOREVER
- Description: Utility and governance coin for the Confío app
- Website: https://confio.lat

NOTE: There is NO smart contract for CONFIO token. It's a pure ASA.
The parameters in the AssetConfigTxn below are the ONLY place where token specs are defined.
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
    ALGOD_ADDRESS = os.environ.get("ALGOD_ADDRESS", "https://testnet-api.algonode.cloud")
    ALGOD_TOKEN = os.environ.get("ALGOD_TOKEN", "")
    
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
        if os.environ.get("ALLOW_PRINT_MNEMONIC") == "1":
            print(f"\n⚠️  IMPORTANT: Save this mnemonic to create the token:")
            print(f"Mnemonic: {creator_mnemonic}")
            print(f"\nSet this in your environment:")
            print(f"export ALGORAND_CONFIO_CREATOR_MNEMONIC=\"{creator_mnemonic}\"")
        else:
            print("Mnemonic: [REDACTED] (set ALLOW_PRINT_MNEMONIC=1 to display)")
    
    # Check creator account balance
    try:
        account_info = algod_client.account_info(creator_address)
        balance = account_info.get('amount', 0) / 1_000_000
        print(f"\nCreator account balance: {balance} ALGO")
        
        if balance < 0.5:
            print(f"\n⚠️  Insufficient balance! You need at least 0.5 ALGO for fees + min balance headroom.")
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
    
    # ⚠️ THESE ARE THE ACTUAL TOKEN PARAMETERS - NOT DEFINED ANYWHERE ELSE!
    # In Algorand, these values passed to AssetConfigTxn ARE the token definition.
    # There is no contract file that defines these - this IS the source of truth.
    token_params = {
        "asset_name": "Confío",
        "unit_name": "CONFIO",
        "total": 1_000_000_000_000_000,  # 1 billion with 6 decimals - HARDCODED HERE!
        "decimals": 6,
        "default_frozen": False,  # Tokens are not frozen by default
        "url": "https://confio.lat",
        "metadata_hash": None,  # Safer to omit unless we need a specific hash
        "manager": creator_address,  # Temporarily, will be finalized to ZERO_ADDR
        "reserve": None,  # None becomes ZERO_ADDR on-chain
        "freeze": None,  # None becomes ZERO_ADDR on-chain
        "clawback": None  # None becomes ZERO_ADDR on-chain
    }
    
    print(f"Name: {token_params['asset_name']}")
    print(f"Symbol: {token_params['unit_name']}")
    print(f"Total Supply: {token_params['total'] / (10 ** token_params['decimals']):,.0f} CONFIO")
    print(f"Decimals: {token_params['decimals']}")
    print(f"URL: {token_params['url']}")
    print(f"Manager: {token_params['manager']}")
    print(f"Reserve: {'None (all tokens go to creator)' if token_params['reserve'] is None else token_params['reserve']}")
    print(f"Freeze Authority: {'None (tokens cannot be frozen)' if token_params['freeze'] is None else token_params['freeze']}")
    print(f"Clawback Authority: {'None (tokens cannot be clawed back)' if token_params['clawback'] is None else token_params['clawback']}")
    
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
            freeze=token_params["freeze"],
            clawback=token_params["clawback"],
            url=token_params["url"],
            metadata_hash=token_params["metadata_hash"],
            decimals=token_params["decimals"]
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
        
        # Verify creator holds full supply
        print("\n📊 Verifying creator balance...")
        try:
            creator_info = algod_client.account_asset_info(creator_address, asset_id)
            creator_holding = creator_info["asset-holding"]["amount"]
            
            if creator_holding == token_params["total"]:
                print(f"✅ Creator holds full supply: {creator_holding:,} base units")
                print(f"   = {creator_holding / (10 ** token_params['decimals']):,.0f} CONFIO")
            else:
                print(f"⚠️  WARNING: Creator balance mismatch!")
                print(f"   Expected: {token_params['total']:,}")
                print(f"   Actual: {creator_holding:,}")
                # Don't fail, but warn loudly
        except Exception as e:
            print(f"⚠️  Could not verify creator balance: {e}")
        
        # Save configuration
        print("\n" + "-" * 60)
        print("NEXT STEPS:")
        print("-" * 60)
        print(f"\n1. Update your .env file with:")
        print(f"   ALGORAND_CONFIO_ASSET_ID={asset_id}")
        print(f"   ALGORAND_CONFIO_CREATOR_ADDRESS={creator_address}")
        if not os.environ.get('ALGORAND_CONFIO_CREATOR_MNEMONIC'):
            print(f"   ALGORAND_CONFIO_CREATOR_MNEMONIC=\"{creator_mnemonic}\"")
        
        print(f"\n2. ⚠️  IMMEDIATELY finalize the token to make it immutable:")
        print(f"   ALGORAND_CONFIO_ASSET_ID={asset_id} \\")
        print(f"   ALGORAND_CONFIO_CREATOR_MNEMONIC=\"...\" \\")
        print(f"   python contracts/confio/finalize_confio_asset.py")
        
        print(f"\n3. View your token on Algorand Explorer:")
        print(f"   https://testnet.algoexplorer.io/asset/{asset_id}")
        
        print(f"\n4. To distribute tokens, users must first opt-in to the asset")
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
        
        # Post-deploy smoke check (before finalization)
        print("\n🔍 Running initial verification (pre-finalization)...")
        import subprocess
        os.environ["ALGORAND_CONFIO_ASSET_ID"] = str(asset_id)
        os.environ["EXPECT_NO_AUTHORITIES"] = "0"  # Not finalized yet
        
        # Use absolute path for checker script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        checker_path = os.path.join(script_dir, "check_confio_asset.py")
        
        result = subprocess.run(
            [sys.executable, checker_path, str(asset_id)],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print("⚠️  Initial verification shows issues:")
            print(result.stdout)
        else:
            print("✅ Initial verification passed - now finalize immediately!")
        
        # Optional auto-finalize for zero window of risk
        if os.getenv("FINALIZE_IMMEDIATELY") == "1":
            print("\n🔒 Auto-finalizing token (FINALIZE_IMMEDIATELY=1)...")
            try:
                # Set all authorities to None (becomes ZERO_ADDR on-chain)
                finalize_params = algod_client.suggested_params()
                finalize_txn = AssetConfigTxn(
                    sender=creator_address,
                    sp=finalize_params,
                    index=asset_id,
                    manager=None,    # Lock forever
                    reserve=None,    # No reserve
                    freeze=None,     # No freeze
                    clawback=None    # No clawback
                )
                
                signed_finalize = finalize_txn.sign(creator_private_key)
                finalize_txid = algod_client.send_transaction(signed_finalize)
                
                print(f"  Finalization transaction: {finalize_txid}")
                print("  Waiting for confirmation...")
                
                wait_for_confirmation(algod_client, finalize_txid, 4)
                
                print("\n✅ TOKEN AUTOMATICALLY FINALIZED!")
                print("  All authorities are now ZERO_ADDR")
                print("  Token is immutable forever")
                
                # Run verification again to confirm finalization
                os.environ["EXPECT_NO_AUTHORITIES"] = "1"  # Now expect finalized
                result = subprocess.run(
                    [sys.executable, checker_path, str(asset_id)],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    print("  Post-finalization check: ✅ PASSED")
                else:
                    print("  Post-finalization check: ⚠️  See output above")
                    
            except Exception as e:
                print(f"\n⚠️  Auto-finalization failed: {e}")
                print("  Please run finalize_confio_asset.py manually")
        
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
            print(f"Symbol: {params.get('unit-name')}")  # Fixed: use dash
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
