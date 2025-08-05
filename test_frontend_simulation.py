#!/usr/bin/env python3
"""
Simulate frontend signing and execution of sponsored transaction
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

from users.models import Account, User
from blockchain.aptos_transaction_manager import AptosTransactionManager

# Import Ed25519 for signing
try:
    import ed25519
except ImportError:
    print("Installing ed25519 package...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "ed25519"])
    import ed25519


async def test_frontend_flow():
    """Test the complete frontend flow with actual signing"""
    
    print("🧪 Testing Frontend Simulation Flow")
    print("=" * 60)
    
    # Get test account
    from asgiref.sync import sync_to_async
    
    try:
        test_user = await sync_to_async(User.objects.get)(username='user_4923eef3')
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
    
    # Step 1: Prepare transaction
    print(f"\n📝 Step 1: Preparing transaction...")
    result = await AptosTransactionManager.prepare_send_transaction(
        account=test_account,
        recipient='0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36',
        amount=Decimal('0.01'),
        token_type='CONFIO'
    )
    
    if not result.get('success'):
        print(f"❌ Failed to prepare: {result.get('error')}")
        return
    
    print(f"✅ Transaction prepared")
    tx_bytes = result['txBytes']
    
    # Decode transaction data
    tx_bytes_str = base64.b64decode(tx_bytes).decode('utf-8')
    tx_data = json.loads(tx_bytes_str)
    
    print(f"\n📋 Transaction Details:")
    print(f"   Sender: {tx_data['sender']}")
    print(f"   Recipient: {tx_data['recipient']}")
    print(f"   Amount: {tx_data['amount']} {tx_data['token_type']}")
    
    # Step 2: Simulate frontend signing
    print(f"\n🔐 Step 2: Simulating frontend signing...")
    
    # Get signing message
    signing_message_b64 = tx_data['signing_message']
    signing_message = base64.b64decode(signing_message_b64)
    
    print(f"   Signing message length: {len(signing_message)} bytes")
    print(f"   Message prefix: {signing_message[:21]}")
    
    # Generate a test ephemeral key pair (in real app, this would be the user's ephemeral key)
    import os
    private_key_bytes = os.urandom(32)
    ephemeral_private_key = ed25519.SigningKey(private_key_bytes)
    ephemeral_public_key = ephemeral_private_key.get_verifying_key()
    
    # Sign the message
    signature = ephemeral_private_key.sign(signing_message)
    
    print(f"   ✅ Created Ed25519 signature: {signature.hex()[:64]}...")
    print(f"   ✅ Ephemeral public key: {ephemeral_public_key.to_bytes().hex()}")
    
    # Create the signature object that frontend would send
    signature_obj = {
        'keyless_signature_type': 'aptos_keyless_real_signature',
        'ephemeral_signature': list(signature),  # Convert to list for JSON
        'ephemeral_public_key': '0x' + ephemeral_public_key.to_bytes().hex(),
        'account_address': test_account.aptos_address,
        'transaction_hash': signing_message.hex(),
        'signed_transaction_bytes': signing_message_b64,
        'jwt': 'mock_jwt_for_testing'  # In real app, this would be the Google JWT
    }
    
    # Encode as base64 (like frontend does)
    keyless_signature = base64.b64encode(json.dumps(signature_obj).encode()).decode()
    
    print(f"\n📤 Step 3: Executing transaction with signature...")
    
    # Execute the transaction
    exec_result = await AptosTransactionManager.execute_transaction_with_signatures(
        tx_bytes=tx_bytes,
        sponsor_signature='sponsor_ready',
        user_signature=keyless_signature,
        account_id=test_account.id
    )
    
    if exec_result.get('success'):
        print(f"\n✅ Transaction successful!")
        print(f"   Digest: {exec_result.get('digest')}")
        print(f"   Sponsored: {exec_result.get('sponsored')}")
        print(f"   Gas saved: {exec_result.get('gas_saved')}")
    else:
        print(f"\n❌ Transaction failed: {exec_result.get('error')}")
        if 'details' in exec_result:
            print(f"   Details: {json.dumps(exec_result['details'], indent=2)}")


if __name__ == "__main__":
    asyncio.run(test_frontend_flow())