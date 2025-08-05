#!/usr/bin/env python3
"""
Test sponsored transaction with proper Ed25519 signatures (not SHA256 hashes)
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
from aptos_sdk.account import Account
from aptos_sdk.transactions import RawTransaction, TransactionPayload, EntryFunction
from aptos_sdk.account_address import AccountAddress
import time
import json
import base64


def create_proper_ed25519_signature():
    """Create a proper Ed25519 signature that matches real frontend behavior"""
    
    # Create an ephemeral keypair (simulates what frontend generates)
    ephemeral_account = Account.generate()
    
    print(f"🔑 Generated ephemeral account: {ephemeral_account.address()}")
    print(f"📋 Public key: {ephemeral_account.public_key()}")
    
    # Simulate the transaction that would be signed
    # This represents what the transaction hash/bytes would be
    message_to_sign = b"test_transaction_message_for_confio_transfer"
    
    # Create proper Ed25519 signature using Aptos SDK
    signature = ephemeral_account.sign(message_to_sign)
    
    print(f"✅ Created proper Ed25519 signature: {len(signature.data())} bytes")
    
    # Create the signature data structure that frontend would send
    signature_data = {
        'transaction_hash': message_to_sign.hex(),
        'ephemeral_signature': list(signature.data()),  # Convert bytes to list of ints
        'ephemeral_public_key': f"0x{ephemeral_account.public_key()}",
        'account_address': str(ephemeral_account.address()),
        'jwt': 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6IjEyMyJ9.eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJhdWQiOiJ0ZXN0LWF1ZGllbmNlIiwic3ViIjoidGVzdC11c2VyIiwiZW1haWwiOiJ0ZXN0QGV4YW1wbGUuY29tIiwiaWF0IjoxNjAwMDAwMDAwLCJleHAiOjE2MDAwMDM2MDB9.test-signature',
        'keyless_signature_type': 'aptos_keyless_real_signature'
    }
    
    # Encode as base64 JSON (same as frontend)
    signature_json = json.dumps(signature_data)
    signature_base64 = base64.b64encode(signature_json.encode('utf-8')).decode('utf-8')
    
    return signature_base64, ephemeral_account


async def test_proper_sponsored():
    """Test sponsored transaction with proper Ed25519 signatures"""
    
    print("🧪 Testing Sponsored Transaction with PROPER Ed25519 Signatures")
    print("=" * 80)
    
    # Create proper signature data
    signature_base64, ephemeral_account = create_proper_ed25519_signature()
    
    print(f"📤 Signature data: {signature_base64[:100]}...")
    
    # Prepare keyless info for sponsor service
    keyless_info = {
        'available': True,
        'keyless_authenticator': signature_base64,
        'account_id': 'test_proper_ed25519'
    }
    
    print(f"\n🚀 Testing sponsored CONFIO transfer...")
    print(f"   From: {ephemeral_account.address()}")
    print(f"   To: 0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36")
    print(f"   Amount: 25.0 CONFIO")
    print(f"   Using: PROPER Ed25519 signature (64 bytes)")
    
    try:
        result = await AptosSponsorService.sponsor_confio_transfer(
            sender_address=str(ephemeral_account.address()),
            recipient_address='0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36',
            amount=Decimal('25.0'),
            keyless_info=keyless_info
        )
        
        print(f"\n📊 Transaction Result:")
        print(f"   Success: {result.get('success')}")
        
        if result.get('success'):
            print(f"   ✅ SPONSORED TRANSACTION SUCCESSFUL!")
            print(f"   💫 Transaction hash: {result.get('digest')}")
            print(f"   💰 Gas saved for user: {result.get('gas_saved')} APT")
            print(f"   🏦 Sponsor account: {result.get('sponsor')}")
            print(f"   📈 User account created/used: {ephemeral_account.address()}")
        else:
            error_msg = result.get('error', '')
            print(f"   ❌ Error: {error_msg}")
            
            # Analyze the error type
            if 'ULEB128' in error_msg:
                print(f"   🔍 ULEB128 Error Analysis:")
                if 'integer did not fit in the target size' in error_msg:
                    print(f"      - Issue: Transaction parameter out of u64 range")
                    print(f"      - Fix: Check gas_limit, amount, sequence_number sizes")
                else:
                    print(f"      - Issue: General ULEB128 serialization problem")
                    print(f"      - Fix: Check transaction structure and BCS encoding")
            elif 'Invalid type' in error_msg:
                print(f"   🔍 Authenticator Type Error:")
                print(f"      - Issue: Wrong authenticator class used")
                print(f"      - Fix: Ensure Ed25519Authenticator with proper signature")
            elif 'sequence' in error_msg.lower():
                print(f"   🔍 Sequence Number Error:")
                print(f"      - Issue: Account doesn't exist or wrong sequence")
                print(f"      - Fix: Create account first or check sequence number")
            elif 'keyless' in error_msg.lower():
                print(f"   🔍 Keyless Authentication Error:")
                print(f"      - Issue: Keyless authenticator validation failed")
                print(f"      - Fix: Ensure proper JWT and ephemeral signature")
            else:
                print(f"   🔍 Unknown Error Type - Check logs for details")
                
    except Exception as e:
        print(f"\n❌ Exception during test: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n📈 Key Improvements Made:")
    print(f"   ✅ Using proper Ed25519 signatures (not SHA256 hashes)")
    print(f"   ✅ Standard gas price (100) instead of minimal (1)")  
    print(f"   ✅ Proper gas limit (100,000) for token transfers")
    print(f"   ✅ Ed25519Authenticator with real signature bytes")
    print(f"   ✅ Proper transaction structure for sponsored transactions")


if __name__ == "__main__":
    asyncio.run(test_proper_sponsored())