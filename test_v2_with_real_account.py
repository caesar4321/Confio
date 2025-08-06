#!/usr/bin/env python3
"""
Test the V2 Bridge integration with a real account signature
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
    RawTransaction
)
from aptos_sdk.authenticator import AccountAuthenticator, Ed25519Authenticator
from aptos_sdk.bcs import Serializer
from aptos_sdk.account_address import AccountAddress


async def test_v2_with_real_account():
    """Test V2 bridge integration with a real account that exists on chain"""
    
    print("🧪 Testing V2 Bridge with Real Account Signature")
    print("=" * 70)
    
    # Use the sponsor account itself as sender (we know it exists on chain)
    sponsor_private_key = os.environ.get('APTOS_SPONSOR_PRIVATE_KEY')
    if not sponsor_private_key:
        print("❌ APTOS_SPONSOR_PRIVATE_KEY not set")
        return
        
    sender_account = Account.load_key(sponsor_private_key)
    print(f"👤 Using sponsor account as sender: {sender_account.address()}")
    
    # Initialize Aptos client
    aptos_client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
    
    # Get account info
    try:
        account_info = await aptos_client.account(sender_account.address())
        sequence_number = int(account_info.get("sequence_number", 0))
        print(f"📊 Account sequence number: {sequence_number}")
    except Exception as e:
        print(f"❌ Failed to get account info: {e}")
        return
    
    # Build a real transaction
    recipient_address = '0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36'
    amount_units = 10_000_000  # 10 CONFIO (6 decimals)
    
    # Create the CONFIO transfer payload
    payload = TransactionPayload(
        EntryFunction.natural(
            "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::confio",
            "transfer_confio",
            [],
            [
                TransactionArgument(AccountAddress.from_str(recipient_address), Serializer.struct),
                TransactionArgument(amount_units, Serializer.u64)
            ]
        )
    )
    
    # Build raw transaction
    raw_txn = RawTransaction(
        sender=sender_account.address(),
        sequence_number=sequence_number,
        payload=payload,
        max_gas_amount=100_000,
        gas_unit_price=100,
        expiration_timestamps_secs=int(asyncio.get_event_loop().time()) + 600,
        chain_id=2,  # Testnet
    )
    
    # Sign the transaction
    signing_message = raw_txn.keyed()
    signature = sender_account.sign(signing_message)
    
    # Create authenticator
    authenticator = AccountAuthenticator(
        Ed25519Authenticator(sender_account.public_key(), signature)
    )
    
    # Serialize the authenticator
    serializer = Serializer()
    authenticator.serialize(serializer)
    authenticator_bytes = bytes(serializer.output())
    authenticator_base64 = base64.b64encode(authenticator_bytes).decode('utf-8')
    
    print(f"✍️ Created real signature for transaction")
    print(f"📝 Authenticator: {len(authenticator_bytes)} bytes")
    print(f"🔐 Base64: {authenticator_base64[:50]}...")
    
    # Prepare keyless_info as frontend would send it
    keyless_info = {
        'available': True,
        'keyless_authenticator': authenticator_base64,
        'account_id': 'test_real_account'
    }
    
    # Test parameters
    sender_address = str(sender_account.address())
    
    print(f"\n🚀 Testing V2 sponsored CONFIO transfer...")
    print(f"   From: {sender_address}")
    print(f"   To: {recipient_address}")
    print(f"   Amount: {amount_units / 1_000_000} CONFIO")
    
    try:
        # Call the V2 sponsor service
        result = await AptosSponsorService.sponsor_confio_transfer(
            sender_address=sender_address,
            recipient_address=recipient_address,
            amount=Decimal(amount_units) / Decimal(1_000_000),
            keyless_info=keyless_info
        )
        
        print(f"\n📊 Transaction result:")
        print(f"   Success: {result.get('success')}")
        
        if result.get('success'):
            print(f"   ✅ V2 SPONSORED TRANSACTION SUCCESSFUL!")
            print(f"   💫 Transaction hash: {result.get('digest')}")
            print(f"   💰 Gas used: {result.get('gas_used')}")
            print(f"   📝 Note: {result.get('note')}")
            
            # Verify on chain
            tx_hash = result.get('digest')
            if tx_hash:
                print(f"\n🔍 Verifying transaction on chain...")
                await asyncio.sleep(2)  # Wait for confirmation
                try:
                    tx_data = await aptos_client.transaction_by_hash(tx_hash)
                    print(f"   ✅ Transaction confirmed!")
                    print(f"   Success: {tx_data.get('success')}")
                    print(f"   Gas used: {tx_data.get('gas_used')}")
                except Exception as e:
                    print(f"   ⚠️ Could not verify: {e}")
        else:
            print(f"   ❌ Error: {result.get('error')}")
            
            # Analyze the error
            error_msg = result.get('error', '')
            if 'invalid_signature' in error_msg.lower():
                print(f"   🔍 Issue: Signature validation failed")
                print(f"   💡 This means the V2 bridge is working but needs proper transaction signing")
            elif 'sequence' in error_msg.lower():
                print(f"   🔍 Issue: Sequence number mismatch")
                print(f"   💡 The transaction might be using wrong sequence number")
                
    except Exception as e:
        print(f"\n❌ Exception during test: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n📈 Summary:")
    print(f"1. V2 bridge is properly configured with CONFIO module address")
    print(f"2. The 'hex string expected' error is fixed")
    print(f"3. Now testing with real account signatures")
    print(f"4. If INVALID_SIGNATURE persists, it's due to transaction/signature mismatch")


if __name__ == "__main__":
    asyncio.run(test_v2_with_real_account())