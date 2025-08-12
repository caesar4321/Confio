#!/usr/bin/env python
"""
Distribute CONFIO tokens to specified addresses on Algorand testnet
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
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation
from django.conf import settings


def distribute_confio_tokens():
    """Distribute CONFIO tokens to specified addresses"""
    
    # Recipients
    recipients = [
        ("N3T5WQVBAVMTSIVYNBLIEE4XNFLDYLY3SIIP6B6HENADL6UH7HA56MZSDE", 100000),  # 100,000 CONFIO
        ("PRDNNWOGMD63J6YMENUYD5Q5H7Q3GQ75QUIJVH3Z2XCPQV7LGRUGBUBRIA", 100000),  # 100,000 CONFIO
    ]
    
    # Configuration
    ALGOD_ADDRESS = os.environ.get("ALGOD_ADDRESS", "https://testnet-api.algonode.cloud")
    ALGOD_TOKEN = os.environ.get("ALGOD_TOKEN", "")
    
    print("=" * 60)
    print("CONFIO TOKEN DISTRIBUTION ON TESTNET")
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
    
    # Get CONFIO asset ID from settings
    asset_id = settings.ALGORAND_CONFIO_ASSET_ID
    if not asset_id:
        print("\n✗ CONFIO asset ID not configured in settings")
        print("  Please run create_confio_token_algorand.py first")
        return
    
    print(f"\nCONFIO Asset ID: {asset_id}")
    
    # Get sponsor account (holds the CONFIO tokens)
    sponsor_mnemonic = os.environ.get('ALGORAND_SPONSOR_MNEMONIC')
    if not sponsor_mnemonic:
        print("\n✗ Sponsor mnemonic not found in environment")
        print("  Set ALGORAND_SPONSOR_MNEMONIC environment variable")
        return
    
    sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
    sponsor_address = account.address_from_private_key(sponsor_private_key)
    print(f"Sponsor address: {sponsor_address}")
    
    # Check sponsor's CONFIO balance
    try:
        sponsor_info = algod_client.account_asset_info(sponsor_address, asset_id)
        sponsor_balance = sponsor_info["asset-holding"]["amount"]
        decimals = 6  # CONFIO has 6 decimals
        sponsor_balance_display = sponsor_balance / (10 ** decimals)
        print(f"\nSponsor CONFIO balance: {sponsor_balance_display:,.2f} CONFIO")
    except Exception as e:
        print(f"\n✗ Failed to check sponsor balance: {e}")
        return
    
    # Calculate total needed
    total_needed = sum(amount for _, amount in recipients)
    total_needed_base = total_needed * (10 ** decimals)
    
    if sponsor_balance < total_needed_base:
        print(f"\n✗ Insufficient CONFIO balance")
        print(f"  Needed: {total_needed:,.2f} CONFIO")
        print(f"  Available: {sponsor_balance_display:,.2f} CONFIO")
        return
    
    print(f"\nTotal to distribute: {total_needed:,.2f} CONFIO")
    
    # Process each recipient
    print("\n" + "-" * 60)
    print("DISTRIBUTING TOKENS")
    print("-" * 60)
    
    for recipient_address, amount in recipients:
        amount_base = amount * (10 ** decimals)
        print(f"\n→ Sending {amount:,.2f} CONFIO to {recipient_address[:10]}...")
        
        # Check if recipient has opted in
        try:
            recipient_info = algod_client.account_asset_info(recipient_address, asset_id)
            print(f"  ✓ Recipient has opted in to CONFIO")
        except:
            print(f"  ⚠️  Recipient has NOT opted in to CONFIO (Asset ID: {asset_id})")
            print(f"     They must opt in before receiving tokens")
            print(f"     Skipping this recipient...")
            continue
        
        # Create and send transfer transaction
        try:
            params = algod_client.suggested_params()
            
            txn = AssetTransferTxn(
                sender=sponsor_address,
                sp=params,
                receiver=recipient_address,
                amt=amount_base,
                index=asset_id
            )
            
            signed_txn = txn.sign(sponsor_private_key)
            tx_id = algod_client.send_transaction(signed_txn)
            
            print(f"  Transaction ID: {tx_id}")
            print(f"  Waiting for confirmation...")
            
            confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
            print(f"  ✅ Confirmed in round: {confirmed_txn.get('confirmed-round')}")
            
            # Verify recipient balance
            try:
                recipient_info = algod_client.account_asset_info(recipient_address, asset_id)
                new_balance = recipient_info["asset-holding"]["amount"] / (10 ** decimals)
                print(f"  Recipient's new balance: {new_balance:,.2f} CONFIO")
            except Exception as e:
                print(f"  Could not verify recipient balance: {e}")
                
        except Exception as e:
            print(f"  ✗ Failed to send tokens: {e}")
    
    # Check final sponsor balance
    print("\n" + "-" * 60)
    print("DISTRIBUTION COMPLETE")
    print("-" * 60)
    
    try:
        sponsor_info = algod_client.account_asset_info(sponsor_address, asset_id)
        final_balance = sponsor_info["asset-holding"]["amount"] / (10 ** decimals)
        print(f"\nSponsor's final balance: {final_balance:,.2f} CONFIO")
        print(f"Total distributed: {sponsor_balance_display - final_balance:,.2f} CONFIO")
    except Exception as e:
        print(f"\nCould not check final balance: {e}")
    
    print("\n✅ Distribution complete!")
    print(f"\nView transactions on Algorand Explorer:")
    print(f"https://testnet.algoexplorer.io/address/{sponsor_address}")


if __name__ == "__main__":
    distribute_confio_tokens()