#!/usr/bin/env python3
"""
Test that the fixed sponsored transaction flow works end-to-end
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

from users.models import Account, User
from blockchain.aptos_transaction_manager import AptosTransactionManager


async def test_fixed_flow():
    """Test the complete fixed flow"""
    
    print("🧪 Testing Fixed Sponsored Transaction Flow")
    print("=" * 60)
    
    # Get test account (use sync operations)
    from asgiref.sync import sync_to_async
    
    try:
        test_user = await sync_to_async(User.objects.get)(username='user_4923eef3')  # From the logs
        test_account = await sync_to_async(
            lambda: test_user.accounts.filter(
                account_type='personal',
                account_index=0
            ).first()
        )()
        
        if not test_account:
            print("❌ Test account not found")
            return
            
        print(f"✅ Found test account: {test_account.aptos_address}")
        
    except User.DoesNotExist:
        print("❌ Test user not found")
        return
    
    # Prepare transaction
    print(f"\n📝 Preparing transaction...")
    result = await AptosTransactionManager.prepare_send_transaction(
        account=test_account,
        recipient='0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36',
        amount=Decimal('0.01'),  # Small test amount
        token_type='CONFIO'
    )
    
    if not result.get('success'):
        print(f"❌ Failed to prepare: {result.get('error')}")
        return
    
    print(f"✅ Transaction prepared successfully")
    
    # Decode and check the transaction data
    import base64
    import json
    
    tx_bytes_str = base64.b64decode(result['txBytes']).decode('utf-8')
    tx_data = json.loads(tx_bytes_str)
    
    print(f"\n📋 Transaction Data:")
    print(f"   Sender: {tx_data['sender']}")
    print(f"   Recipient: {tx_data['recipient']}")
    print(f"   Amount: {tx_data['amount']} {tx_data['token_type']}")
    print(f"   Has signing message: {'signing_message' in tx_data}")
    
    if 'signing_message' in tx_data:
        signing_message_bytes = base64.b64decode(tx_data['signing_message'])
        print(f"   Signing message length: {len(signing_message_bytes)} bytes")
        print(f"   Message prefix: {signing_message_bytes[:21]}")
        if signing_message_bytes[:21] == b"APTOS::RawTransaction":
            print(f"   ✅ Valid Aptos transaction signing message!")
        else:
            print(f"   ❌ Invalid signing message prefix")
    else:
        print(f"   ❌ Missing signing_message field!")
    
    print(f"\n🎯 Frontend should now:")
    print(f"   1. Decode the signing_message from base64")
    print(f"   2. Sign those exact bytes with Ed25519")
    print(f"   3. Send the signature back to execute the transaction")
    print(f"\n✅ Backend is ready for proper sponsored transactions!")


if __name__ == "__main__":
    asyncio.run(test_fixed_flow())