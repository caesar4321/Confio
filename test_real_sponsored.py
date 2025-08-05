#!/usr/bin/env python3
"""
Test sponsored transaction with real accounts (not keyless) to verify the flow works
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


def create_real_account_signature(user_private_key, transaction_data):
    """Create a real Ed25519 signature from an actual account"""
    
    # For this test, we'll create a temporary account
    user_account = Account.load_key(user_private_key)
    
    # Create authenticator data that mimics what the frontend would send
    # but uses a real account signature instead of keyless
    import json
    import base64
    
    # This simulates what a real frontend would send for a regular account
    signature_data = {
        'account_address': str(user_account.address()),
        'signature_type': 'ed25519_real_signature',  # Not keyless
        'transaction_hash': transaction_data.get('hash', 'test_hash'),
        'public_key': str(user_account.public_key()),
        'signature': 'mock_signature_placeholder'  # Would be real signature
    }
    
    # Encode as base64 JSON (same format as frontend)
    signature_json = json.dumps(signature_data)
    signature_base64 = base64.b64encode(signature_json.encode('utf-8')).decode('utf-8')
    
    return signature_base64, user_account


async def test_real_sponsored():
    """Test sponsored transaction with real accounts"""
    
    print("🧪 Testing Sponsored Transaction with Real Ed25519 Accounts")
    print("=" * 70)
    
    # Create a temporary user account for testing
    user_account = Account.generate()
    user_private_key = str(user_account.private_key)
    
    print(f"👤 Created test user account: {user_account.address()}")
    print(f"🔑 User private key: {user_private_key[:20]}...")
    
    # Create mock signature data
    transaction_data = {'hash': 'test_transaction_hash_123'}
    signature_base64, _ = create_real_account_signature(user_private_key, transaction_data)
    
    print(f"✅ Created signature: {signature_base64[:50]}...")
    
    # Prepare account info for sponsor service
    account_info = {
        'available': True,
        'keyless_authenticator': signature_base64,  # Using the field name the service expects
        'account_id': 'test_account_001'
    }
    
    print(f"\n🚀 Testing sponsored CONFIO transfer...")
    print(f"   From: {user_account.address()}")
    print(f"   To: 0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36")
    print(f"   Amount: 25.0 CONFIO")
    
    try:
        result = await AptosSponsorService.sponsor_confio_transfer(
            sender_address=str(user_account.address()),
            recipient_address='0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36',
            amount=Decimal('25.0'),
            keyless_info=account_info
        )
        
        print(f"\n📊 Transaction result:")
        print(f"   Success: {result.get('success')}")
        
        if result.get('success'):
            print(f"   ✅ SPONSORED TRANSACTION SUCCESSFUL!")
            print(f"   💫 Transaction hash: {result.get('digest')}")
            print(f"   💰 Gas saved: {result.get('gas_saved')} APT")
            print(f"   🏦 Sponsor: {result.get('sponsor')}")
        else:
            print(f"   ❌ Error: {result.get('error')}")
            
            # Analyze the error
            error_msg = result.get('error', '')
            if 'keyless authenticator' in error_msg.lower():
                print(f"   🔍 Issue: Still trying to parse as keyless account")
                print(f"   💡 Solution: Modify backend to handle regular Ed25519 accounts")
            elif 'uleb128' in error_msg.lower():
                print(f"   🔍 Issue: ULEB128 serialization error persists")
                print(f"   💡 Solution: Check transaction parameter sizes")
            elif 'sequence' in error_msg.lower():
                print(f"   🔍 Issue: Account sequence number problem")
                print(f"   💡 Solution: Account may not exist on blockchain yet")
            else:
                print(f"   🔍 Unexpected error type")
                
    except Exception as e:
        print(f"\n❌ Exception during test: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n📈 Next Steps:")
    print(f"1. Modify AptosSponsorService to handle regular Ed25519 accounts")
    print(f"2. Add account type detection (keyless vs regular)")
    print(f"3. Use appropriate authenticator based on account type")
    print(f"4. Test with real accounts that exist on blockchain")


if __name__ == "__main__":
    asyncio.run(test_real_sponsored())