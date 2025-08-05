#!/usr/bin/env python3
"""
Test proper sponsored transaction with correct transaction signing

This demonstrates how the frontend should sign the exact transaction bytes
to avoid ULEB128 serialization errors.
"""

import asyncio
import os
import sys
import django
from decimal import Decimal

# Setup Django
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.aptos_sponsor_service import AptosSponsorService
from blockchain.aptos_transaction_builder import AptosTransactionBuilder
from aptos_sdk.account import Account
from aptos_sdk.transactions import RawTransaction
from aptos_sdk.bcs import Serializer
import json
import base64
import time


async def simulate_proper_frontend_signing():
    """
    Simulate the proper frontend signing flow:
    1. Build the exact transaction
    2. Sign the transaction bytes with ephemeral key
    3. Send signature to backend
    """
    
    print("🧪 Testing Proper Transaction Signing Flow")
    print("=" * 80)
    
    # Step 1: Create ephemeral account (simulates frontend)
    ephemeral_account = Account.generate()
    print(f"👤 Ephemeral account: {ephemeral_account.address()}")
    print(f"🔑 Public key: {ephemeral_account.public_key()}")
    
    # Step 2: Build the exact transaction that will be submitted
    sender_address = str(ephemeral_account.address())
    recipient_address = "0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36"
    amount = Decimal("1.0")  # 1 CONFIO
    
    # Build transaction using our builder
    txn_data = AptosTransactionBuilder.prepare_for_frontend(
        transaction_type='sponsored',
        sender_address=sender_address,
        recipient_address=recipient_address,
        amount=amount,
        token_type='CONFIO',
        sponsor_address='0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c'
    )
    
    print(f"\n📋 Transaction prepared for signing:")
    print(f"   Type: {txn_data['type']}")
    print(f"   Sender: {sender_address[:16]}...")
    print(f"   Recipient: {recipient_address[:16]}...")
    print(f"   Amount: {amount} CONFIO")
    print(f"   Sponsor will pay gas")
    
    # Step 3: Sign the exact transaction bytes (this is what frontend must do)
    signing_message_base64 = txn_data['signing_message']
    signing_message = base64.b64decode(signing_message_base64)
    
    print(f"\n🔐 Signing transaction bytes:")
    print(f"   Message length: {len(signing_message)} bytes")
    print(f"   Message prefix: {signing_message[:21]}")  # Should be b"APTOS::RawTransaction"
    
    # Create proper Ed25519 signature of the transaction
    signature = ephemeral_account.sign(signing_message)
    
    print(f"   ✅ Created Ed25519 signature: {len(signature.data())} bytes")
    
    # Step 4: Prepare signature data for backend (simulates frontend response)
    signature_data = {
        'keyless_signature_type': 'aptos_keyless_real_signature',
        'ephemeral_signature': list(signature.data()),  # Convert bytes to list
        'ephemeral_public_key': f"0x{ephemeral_account.public_key()}",
        'account_address': sender_address,
        'transaction_hash': signing_message.hex(),
        'signed_transaction_bytes': signing_message_base64,  # The exact bytes we signed
        'jwt': 'test.jwt.token',  # Would be real JWT in production
    }
    
    # Encode as base64 JSON (same as frontend)
    signature_json = json.dumps(signature_data)
    signature_base64 = base64.b64encode(signature_json.encode('utf-8')).decode('utf-8')
    
    print(f"\n📤 Signature package prepared for backend")
    print(f"   Package size: {len(signature_base64)} characters")
    
    # Step 5: Send to backend sponsor service
    keyless_info = {
        'available': True,
        'keyless_authenticator': signature_base64,
        'account_id': 'proper_signing_test'
    }
    
    print(f"\n🚀 Submitting sponsored transaction...")
    
    try:
        result = await AptosSponsorService.sponsor_confio_transfer(
            sender_address=sender_address,
            recipient_address=recipient_address,
            amount=amount,
            keyless_info=keyless_info
        )
        
        print(f"\n📊 Result: {'SUCCESS' if result.get('success') else 'FAILED'}")
        
        if result.get('success'):
            print(f"   ✅ Transaction submitted successfully!")
            print(f"   💫 Transaction hash: {result.get('digest')}")
            print(f"   💰 Gas saved for user: {result.get('gas_saved')} APT")
            print(f"   🏦 Sponsor paid the gas")
            print(f"\n🎉 Proper transaction signing works!")
        else:
            error = result.get('error', 'Unknown error')
            print(f"   ❌ Error: {error}")
            
            # Analyze the error
            if 'ULEB128' in error:
                print(f"\n🔍 ULEB128 Error Analysis:")
                print(f"   This might mean we're still not signing the exact transaction")
                print(f"   that the backend is trying to submit.")
                print(f"   Frontend and backend must build identical transactions.")
            elif 'sequence' in error.lower():
                print(f"\n🔍 Sequence Error:")
                print(f"   Account might not exist on blockchain yet")
                print(f"   Or sequence number mismatch")
            elif 'insufficient' in error.lower():
                print(f"\n🔍 Balance Error:")
                print(f"   Account needs to be funded first")
            else:
                print(f"\n🔍 Check backend logs for details")
                
            # Show details if available
            if result.get('details'):
                print(f"\n📝 Error Details:")
                for key, value in result['details'].items():
                    print(f"   {key}: {value}")
                    
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n📚 Key Insights:")
    print(f"   1. Frontend must sign the EXACT transaction bytes")
    print(f"   2. Use Ed25519 signatures, not SHA256 hashes")
    print(f"   3. The signature must match the transaction being submitted")
    print(f"   4. Backend reconstructs the same transaction for verification")
    print(f"   5. Sponsored transactions require precise BCS serialization")


if __name__ == "__main__":
    asyncio.run(simulate_proper_frontend_signing())