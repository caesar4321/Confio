#!/usr/bin/env python3
"""
Test the two-phase sponsored transaction flow through Django
"""

import asyncio
import os
import sys
import django
import base64
import json
from decimal import Decimal

# Setup Django
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.aptos_sponsor_service import AptosSponsorService
from aptos_sdk.account import Account
from aptos_sdk.async_client import RestClient
from aptos_sdk.transactions import (
    TransactionArgument,
    EntryFunction,
    TransactionPayload,
    RawTransaction,
    Serializer
)
from aptos_sdk.authenticator import AccountAuthenticator, Ed25519Authenticator
from aptos_sdk.account_address import AccountAddress


async def test_two_phase_flow():
    """Test the two-phase sponsored transaction flow"""
    
    print("🧪 Testing Two-Phase Sponsored Transaction Flow")
    print("=" * 70)
    
    # Use the sponsor account itself as sender (we know it exists on chain)
    sponsor_private_key = os.environ.get('APTOS_SPONSOR_PRIVATE_KEY')
    if not sponsor_private_key:
        print("❌ APTOS_SPONSOR_PRIVATE_KEY not set")
        return
        
    sender_account = Account.load_key(sponsor_private_key)
    sender_address = str(sender_account.address())
    recipient_address = '0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36'
    amount = Decimal('10.0')  # 10 CONFIO
    
    print(f"👤 Sender: {sender_address}")
    print(f"📬 Recipient: {recipient_address}")
    print(f"💰 Amount: {amount} CONFIO")
    
    # ========================================
    # PHASE 1: Build transaction for signing
    # ========================================
    print(f"\n📋 PHASE 1: Preparing transaction for signing...")
    
    try:
        # Call Django to prepare the transaction
        prepare_result = await AptosSponsorService.prepare_sponsored_confio_transfer(
            sender_address=sender_address,
            recipient_address=recipient_address,
            amount=amount
        )
        
        if not prepare_result.get('success'):
            print(f"❌ Failed to prepare transaction: {prepare_result.get('error')}")
            return
            
        print(f"✅ Transaction prepared successfully")
        transaction_data = prepare_result.get('transaction', '')
        sponsor_auth = prepare_result.get('sponsor_authenticator', '')
        print(f"   Transaction hex: {str(transaction_data)[:50]}...")
        print(f"   Sponsor authenticator: {str(sponsor_auth)[:50]}...")
        print(f"   Sponsor address: {prepare_result.get('sponsor_address')}")
        
        # Extract the transaction for signing
        transaction_hex = prepare_result.get('transaction')
        if not transaction_hex:
            print("❌ No transaction data returned")
            return
            
        # ========================================
        # FRONTEND SIMULATION: Sign the transaction
        # ========================================
        print(f"\n🖊️  FRONTEND: Signing transaction...")
        
        # Decode the transaction hex
        transaction_bytes = bytes.fromhex(transaction_hex.replace('0x', ''))
        
        # Sign the transaction (simulating what frontend would do)
        # In reality, the frontend would use the keyless account to sign
        signature = sender_account.sign(transaction_bytes)
        
        # Create authenticator
        authenticator = AccountAuthenticator(
            Ed25519Authenticator(sender_account.public_key(), signature)
        )
        
        # Serialize the authenticator
        serializer = Serializer()
        authenticator.serialize(serializer)
        authenticator_bytes = bytes(serializer.output())
        authenticator_base64 = base64.b64encode(authenticator_bytes).decode('utf-8')
        
        print(f"✅ Transaction signed")
        print(f"   Authenticator: {len(authenticator_bytes)} bytes")
        print(f"   Base64: {authenticator_base64[:50]}...")
        
        # ========================================
        # PHASE 2: Submit signed transaction
        # ========================================
        print(f"\n📡 PHASE 2: Submitting signed transaction...")
        
        # Call Django to submit the signed transaction
        submit_result = await AptosSponsorService.submit_sponsored_confio_transfer(
            sender_address=sender_address,
            recipient_address=recipient_address,
            amount=amount,
            sender_authenticator_base64=authenticator_base64
        )
        
        print(f"\n📊 Transaction result:")
        print(f"   Success: {submit_result.get('success')}")
        
        if submit_result.get('success'):
            print(f"   ✅ SPONSORED TRANSACTION SUCCESSFUL!")
            print(f"   💫 Transaction hash: {submit_result.get('digest')}")
            print(f"   💰 Gas used: {submit_result.get('gas_used')}")
            print(f"   📝 Note: {submit_result.get('note')}")
            
            # Verify on chain
            tx_hash = submit_result.get('digest')
            if tx_hash:
                print(f"\n🔍 Verifying transaction on chain...")
                aptos_client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
                await asyncio.sleep(2)  # Wait for confirmation
                try:
                    tx_data = await aptos_client.transaction_by_hash(tx_hash)
                    print(f"   ✅ Transaction confirmed on blockchain!")
                    print(f"   Success: {tx_data.get('success')}")
                    print(f"   Gas used: {tx_data.get('gas_used')}")
                    print(f"   VM status: {tx_data.get('vm_status')}")
                except Exception as e:
                    print(f"   ⚠️ Could not verify: {e}")
        else:
            print(f"   ❌ Error: {submit_result.get('error')}")
            
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n📈 Summary of Two-Phase Flow:")
    print(f"1. Django calls TypeScript bridge to build transaction")
    print(f"2. Bridge returns transaction + sponsor signature")
    print(f"3. Frontend signs the exact same transaction")
    print(f"4. Frontend sends authenticator back to Django")
    print(f"5. Django submits via TypeScript bridge with both signatures")
    print(f"6. Transaction succeeds because signatures match!")


if __name__ == "__main__":
    asyncio.run(test_two_phase_flow())