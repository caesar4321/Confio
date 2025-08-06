#!/usr/bin/env python3
"""
Test the V2 Bridge integration with Django backend
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
from aptos_sdk.authenticator import AccountAuthenticator, Ed25519Authenticator
from aptos_sdk.bcs import Serializer


async def test_v2_integration():
    """Test V2 bridge integration with Django"""
    
    print("🧪 Testing V2 Bridge Integration with Django Backend")
    print("=" * 70)
    
    # Create a test account (simulating a keyless account)
    test_account = Account.generate()
    print(f"👤 Test account: {test_account.address()}")
    
    # Create a mock authenticator (simulating what frontend would send)
    # In reality, this would be a keyless authenticator from the frontend
    mock_signature = test_account.sign(b"test_message")
    authenticator = AccountAuthenticator(
        Ed25519Authenticator(test_account.public_key(), mock_signature)
    )
    
    # Serialize the authenticator
    serializer = Serializer()
    authenticator.serialize(serializer)
    authenticator_bytes = bytes(serializer.output())
    authenticator_base64 = base64.b64encode(authenticator_bytes).decode('utf-8')
    
    print(f"📝 Created mock authenticator: {len(authenticator_bytes)} bytes")
    print(f"🔐 Base64 encoded: {authenticator_base64[:50]}...")
    
    # Prepare keyless_info as frontend would send it
    keyless_info = {
        'available': True,
        'keyless_authenticator': authenticator_base64,
        'account_id': 'test_v2_integration'
    }
    
    # Test parameters
    sender_address = str(test_account.address())
    recipient_address = '0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36'
    amount = Decimal('10.0')  # 10 CONFIO tokens
    
    print(f"\n🚀 Testing V2 sponsored CONFIO transfer...")
    print(f"   From: {sender_address}")
    print(f"   To: {recipient_address}")
    print(f"   Amount: {amount} CONFIO")
    
    try:
        # Call the updated sponsor_confio_transfer that now uses V2
        result = await AptosSponsorService.sponsor_confio_transfer(
            sender_address=sender_address,
            recipient_address=recipient_address,
            amount=amount,
            keyless_info=keyless_info
        )
        
        print(f"\n📊 Transaction result:")
        print(f"   Success: {result.get('success')}")
        
        if result.get('success'):
            print(f"   ✅ V2 SPONSORED TRANSACTION SUCCESSFUL!")
            print(f"   💫 Transaction hash: {result.get('digest')}")
            print(f"   💰 Gas used: {result.get('gas_used')}")
            print(f"   📝 Note: {result.get('note')}")
        else:
            print(f"   ❌ Error: {result.get('error')}")
            
            # Analyze the error
            error_msg = result.get('error', '')
            if 'deserialize' in error_msg.lower():
                print(f"   🔍 Issue: Deserialization error")
                print(f"   💡 Solution: Check authenticator format compatibility")
            elif 'v2' in error_msg.lower():
                print(f"   🔍 Issue: V2 endpoint problem")
                print(f"   💡 Solution: Ensure TypeScript bridge is running with V2 endpoints")
            elif 'connection' in error_msg.lower():
                print(f"   🔍 Issue: Cannot connect to TypeScript bridge")
                print(f"   💡 Solution: Start the bridge service with 'npm start'")
            else:
                print(f"   🔍 Check the error details above")
                
    except Exception as e:
        print(f"\n❌ Exception during test: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n📈 Summary:")
    print(f"1. Django backend now uses V2 bridge endpoints")
    print(f"2. sponsor_confio_transfer() calls submit_via_typescript_bridge_v2()")
    print(f"3. V2 uses simplified SDK pattern instead of manual BCS construction")
    print(f"4. This should resolve INVALID_SIGNATURE errors")


if __name__ == "__main__":
    asyncio.run(test_v2_integration())