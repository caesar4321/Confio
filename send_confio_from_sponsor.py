#!/usr/bin/env python
"""
Send CONFIO from sponsor account to test account using sponsored transaction
"""

import os
import sys
import django
import asyncio
import base64
from decimal import Decimal
from algosdk import account, mnemonic, encoding
from algosdk.v2client import algod
import nacl.signing

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service
from blockchain.algorand_account_manager import AlgorandAccountManager
from django.conf import settings

async def send_confio_from_sponsor():
    """Send CONFIO from sponsor to test account"""
    
    # Get sponsor details from settings
    sponsor_address = algorand_sponsor_service.sponsor_address
    sponsor_mnemonic = algorand_sponsor_service.sponsor_mnemonic
    
    if not sponsor_address or not sponsor_mnemonic:
        print("ERROR: Sponsor address or mnemonic not configured")
        return
    
    # Get sponsor private key
    sponsor_private_key_b64 = mnemonic.to_private_key(sponsor_mnemonic)
    sponsor_private_key = base64.b64decode(sponsor_private_key_b64)
    
    # Test account (recipient)
    test_address = "SW3VSGM6DCZEL7WW6LPLTJORGHQD5IMCE4C7IR3WKT5YBCTZABJAGI6D5Q"
    
    print("=" * 60)
    print("Sending CONFIO from Sponsor to Test Account")
    print("=" * 60)
    print(f"\nSponsor: {sponsor_address}")
    print(f"Test Account: {test_address}")
    
    # Check sponsor's CONFIO balance
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    try:
        sponsor_info = client.account_info(sponsor_address)
        print(f"\nSponsor ALGO balance: {sponsor_info['amount'] / 1_000_000} ALGO")
        
        # Check if sponsor has CONFIO
        assets = sponsor_info.get('assets', [])
        confio_balance = 0
        sponsor_has_confio = False
        
        for asset in assets:
            if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                confio_balance = asset['amount'] / 1_000_000  # CONFIO has 6 decimals
                sponsor_has_confio = True
                print(f"Sponsor CONFIO balance: {confio_balance} CONFIO")
                break
        
        if not sponsor_has_confio:
            print("\n⚠️  Sponsor is not opted into CONFIO")
            print("   First, sponsor needs to opt into CONFIO asset")
            
            # Create opt-in for sponsor
            print("\n1. Creating opt-in transaction for sponsor...")
            opt_in_result = await algorand_sponsor_service.create_sponsored_opt_in(
                user_address=sponsor_address,
                asset_id=AlgorandAccountManager.CONFIO_ASSET_ID
            )
            
            if not opt_in_result['success']:
                print(f"   ❌ Failed to create opt-in: {opt_in_result['error']}")
                return
            
            # Sign the opt-in transaction
            user_txn_bytes = base64.b64decode(opt_in_result['user_transaction'])
            import msgpack
            
            # Sign using raw nacl approach
            tx_type_bytes = b'TX'
            bytes_to_sign = tx_type_bytes + user_txn_bytes
            
            from nacl.signing import SigningKey
            signing_key = SigningKey(sponsor_private_key[:32])
            signed = signing_key.sign(bytes_to_sign)
            signature = signed.signature
            
            # Create signed transaction structure
            txn_obj = msgpack.unpackb(user_txn_bytes)
            signed_txn = {
                b'sig': signature,
                b'txn': txn_obj
            }
            
            signed_txn_bytes = msgpack.packb(signed_txn)
            signed_txn_b64 = base64.b64encode(signed_txn_bytes).decode('utf-8')
            
            # Submit opt-in
            print("   Submitting opt-in transaction...")
            submit_result = await algorand_sponsor_service.submit_sponsored_group(
                signed_user_txn=signed_txn_b64,
                signed_sponsor_txn=opt_in_result['sponsor_transaction']
            )
            
            if submit_result['success']:
                print(f"   ✅ Sponsor opted into CONFIO!")
                print(f"      Transaction ID: {submit_result['tx_id']}")
            else:
                print(f"   ❌ Failed to opt-in: {submit_result['error']}")
                return
            
            # Refresh balance
            sponsor_info = client.account_info(sponsor_address)
            assets = sponsor_info.get('assets', [])
            for asset in assets:
                if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                    confio_balance = asset['amount'] / 1_000_000
                    print(f"\n   Updated sponsor CONFIO balance: {confio_balance} CONFIO")
                    break
        
        if confio_balance == 0:
            print("\n⚠️  Sponsor has 0 CONFIO balance")
            print("   Sponsor needs to receive CONFIO tokens first")
            # Check creator account
            creator_address = "KNKFUBM3GHOLF6S7L2O7JU6YDB7PCRV3PKBOBRCABLYHBHXRFXKNDWGAWE"
            print(f"\n   Checking creator account ({creator_address[:10]}...):")
            creator_info = client.account_info(creator_address)
            for asset in creator_info.get('assets', []):
                if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                    creator_balance = asset['amount'] / 1_000_000
                    print(f"   Creator CONFIO balance: {creator_balance:,.2f} CONFIO")
                    print("\n   The creator account has all the CONFIO tokens.")
                    print("   You need to transfer some CONFIO from creator to sponsor first.")
                    break
            return
        
        # Now send CONFIO from sponsor to test account
        transfer_amount = Decimal('10')  # Send 10 CONFIO
        
        print(f"\n2. Sending {transfer_amount} CONFIO to test account...")
        
        # Create sponsored transfer
        result = await algorand_sponsor_service.create_sponsored_transfer(
            sender=sponsor_address,
            recipient=test_address,
            amount=transfer_amount,
            asset_id=AlgorandAccountManager.CONFIO_ASSET_ID,
            note="CONFIO allocation to test account"
        )
        
        if not result['success']:
            print(f"   ❌ Failed to create transfer: {result['error']}")
            return
        
        print(f"   Transfer created. Group ID: {result['group_id']}")
        
        # Sign the transaction
        user_txn_bytes = base64.b64decode(result['user_transaction'])
        import msgpack
        
        # Sign using raw nacl approach
        tx_type_bytes = b'TX'
        bytes_to_sign = tx_type_bytes + user_txn_bytes
        
        from nacl.signing import SigningKey
        signing_key = SigningKey(sponsor_private_key[:32])
        signed = signing_key.sign(bytes_to_sign)
        signature = signed.signature
        
        # Create signed transaction structure
        txn_obj = msgpack.unpackb(user_txn_bytes)
        signed_txn = {
            b'sig': signature,
            b'txn': txn_obj
        }
        
        signed_txn_bytes = msgpack.packb(signed_txn)
        signed_txn_b64 = base64.b64encode(signed_txn_bytes).decode('utf-8')
        
        print("   Transaction signed. Submitting...")
        
        # Submit the transaction
        submit_result = await algorand_sponsor_service.submit_sponsored_group(
            signed_user_txn=signed_txn_b64,
            signed_sponsor_txn=result['sponsor_transaction']
        )
        
        if submit_result['success']:
            print(f"\n✅ SUCCESS! Sent {transfer_amount} CONFIO to test account")
            print(f"   Transaction ID: {submit_result['tx_id']}")
            print(f"   View: https://testnet.algoexplorer.io/tx/{submit_result['tx_id']}")
            
            # Verify new balance
            print("\n3. Verifying balances...")
            
            # Check sponsor new balance
            sponsor_info = client.account_info(sponsor_address)
            for asset in sponsor_info.get('assets', []):
                if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                    new_sponsor_balance = asset['amount'] / 1_000_000
                    print(f"   Sponsor new CONFIO balance: {new_sponsor_balance} CONFIO")
                    break
            
            # Check test account new balance
            test_info = client.account_info(test_address)
            for asset in test_info.get('assets', []):
                if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                    new_test_balance = asset['amount'] / 1_000_000
                    print(f"   Test account new CONFIO balance: {new_test_balance} CONFIO")
                    break
                    
        else:
            print(f"\n❌ Failed to submit transfer: {submit_result['error']}")
            
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(send_confio_from_sponsor())