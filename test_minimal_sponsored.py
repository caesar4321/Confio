#!/usr/bin/env python3
"""
Test sponsored transaction with minimal parameters to isolate ULEB128 issue
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
import json
import base64


def create_minimal_signature():
    """Create minimal test signature with small values"""
    
    ephemeral_account = Account.generate()
    message_to_sign = b"minimal_test"
    signature = ephemeral_account.sign(message_to_sign)
    
    signature_data = {
        'transaction_hash': message_to_sign.hex(),
        'ephemeral_signature': list(signature.data()),
        'ephemeral_public_key': f"0x{ephemeral_account.public_key()}",
        'account_address': str(ephemeral_account.address()),
        'jwt': 'test.jwt.token',
        'keyless_signature_type': 'aptos_keyless_real_signature'
    }
    
    signature_json = json.dumps(signature_data)
    signature_base64 = base64.b64encode(signature_json.encode('utf-8')).decode('utf-8')
    
    return signature_base64, ephemeral_account


async def test_minimal_sponsored():
    """Test with minimal parameters to isolate ULEB128 issue"""
    
    print("🧪 Minimal Sponsored Transaction Test")
    print("=" * 50)
    
    signature_base64, ephemeral_account = create_minimal_signature()
    
    keyless_info = {
        'available': True,
        'keyless_authenticator': signature_base64,
        'account_id': 'minimal_test'
    }
    
    print(f"📤 Testing with minimal 1.0 CONFIO transfer")
    print(f"   From: {ephemeral_account.address()}")
    print(f"   To: 0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36")
    print(f"   Amount: 1.0 CONFIO (1000000 base units)")
    
    try:
        result = await AptosSponsorService.sponsor_confio_transfer(
            sender_address=str(ephemeral_account.address()),
            recipient_address='0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36',
            amount=Decimal('1.0'),  # Minimal amount
            keyless_info=keyless_info
        )
        
        print(f"\n📊 Result: {result.get('success')}")
        if not result.get('success'):
            print(f"❌ Error: {result.get('error')}")
            
            # Check if ULEB128 error persists with minimal values
            if 'ULEB128' in result.get('error', ''):
                print(f"\n🔍 ULEB128 error persists even with minimal values!")
                print(f"   Gas limit: 100,000 (should be fine)")
                print(f"   Gas price: 100 (should be fine)")
                print(f"   Amount: 1,000,000 (should be fine)")
                print(f"   Sequence: 0 (should be fine)")
                print(f"\n💡 The issue might be in the BCS serialization itself")
                print(f"   or in the FeePayerRawTransaction structure")
        else:
            print(f"✅ SUCCESS! Transaction submitted")
            
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    print(f"\n🔍 Debug Information:")
    print(f"   • All parameters are within u64 range")
    print(f"   • Using proper Ed25519 signatures")
    print(f"   • Fixed field name: expiration_timestamp_secs")
    print(f"   • Standard gas price: 100")
    print(f"   • Reasonable gas limit: 100,000")


if __name__ == "__main__":
    asyncio.run(test_minimal_sponsored())