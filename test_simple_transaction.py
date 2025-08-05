#!/usr/bin/env python3
"""
Test simple Aptos transaction without keyless authentication to isolate ULEB128 error
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

from aptos_sdk.async_client import RestClient
from aptos_sdk.account import Account
from aptos_sdk.transactions import (
    TransactionPayload,
    EntryFunction,
    RawTransaction,
    SignedTransaction
)
from aptos_sdk.authenticator import Authenticator, Ed25519Authenticator
from aptos_sdk.account_address import AccountAddress
import time


async def test_simple_transaction():
    """Test simple transaction with regular Ed25519 account to isolate ULEB128 error"""
    
    print("🧪 Testing Simple Aptos Transaction (No Keyless)")
    print("=" * 60)
    
    # Use sponsor account for this test
    sponsor_private_key = os.getenv('APTOS_SPONSOR_PRIVATE_KEY')
    if not sponsor_private_key:
        print("❌ APTOS_SPONSOR_PRIVATE_KEY not set")
        return
    
    print("✅ Found sponsor private key")
    
    # Create account from private key
    sponsor_account = Account.load_key(sponsor_private_key)
    print(f"📤 Sponsor address: {sponsor_account.address()}")
    
    # Test client connection
    aptos_client = RestClient("https://fullnode.testnet.aptoslabs.com")
    
    try:
        # Get account info
        account_info = await aptos_client.account(sponsor_account.address())
        sequence_number = int(account_info["sequence_number"])
        print(f"✅ Account found, sequence: {sequence_number}")
    except Exception as e:
        print(f"❌ Failed to get account info: {e}")
        return
    
    # Create a simple coin transfer transaction
    recipient = "0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36"
    amount = 1000000  # 0.01 APT (in octas)
    
    print(f"💰 Testing transfer of {amount} octas to {recipient[:16]}...")
    
    try:
        # Create entry function for APT transfer
        function = EntryFunction.natural(
            "0x1",
            "aptos_account", 
            "transfer",
            [],
            [AccountAddress.from_str(recipient), amount]
        )
        
        payload = TransactionPayload(function)
        
        # Create raw transaction with minimal parameters
        current_time = int(time.time())
        expiration = current_time + 300  # 5 minutes
        
        raw_txn = RawTransaction(
            sender=sponsor_account.address(),
            sequence_number=sequence_number,
            payload=payload,
            max_gas_amount=2000,
            gas_unit_price=100,
            expiration_timestamp_secs=expiration,
            chain_id=2
        )
        
        print(f"✅ Raw transaction created")
        print(f"   - Sender: {sponsor_account.address()}")
        print(f"   - Sequence: {sequence_number}")
        print(f"   - Gas limit: 2000")
        print(f"   - Gas price: 100")
        print(f"   - Amount: {amount} octas")
        print(f"   - Expiration: {expiration}")
        
        # Test BCS serialization
        try:
            from aptos_sdk.bcs import Serializer
            serializer = Serializer()
            raw_txn.serialize(serializer)
            serialized_bytes = serializer.output()
            print(f"✅ BCS serialization successful ({len(serialized_bytes)} bytes)")
        except Exception as serialize_error:
            print(f"❌ BCS serialization failed: {serialize_error}")
            return
        
        # Sign the transaction
        try:
            signature = sponsor_account.sign(raw_txn)
            authenticator = Authenticator(Ed25519Authenticator(sponsor_account.public_key(), signature))
            
            signed_txn = SignedTransaction(raw_txn, authenticator)
            print(f"✅ Transaction signed successfully")
            
        except Exception as sign_error:
            print(f"❌ Transaction signing failed: {sign_error}")
            return
        
        # Try to submit the transaction
        print(f"\n🚀 Attempting to submit transaction...")
        
        try:
            tx_hash = await aptos_client.submit_bcs_transaction(signed_txn)
            print(f"✅ Transaction submitted successfully!")
            print(f"   Transaction hash: {tx_hash}")
            
            # Wait for transaction to be processed
            await aptos_client.wait_for_transaction(tx_hash)
            print(f"✅ Transaction confirmed on blockchain")
            
        except Exception as submit_error:
            print(f"❌ Transaction submission failed: {submit_error}")
            
            # Check if it's the same ULEB128 error
            if "ULEB128" in str(submit_error):
                print(f"⚠️  Same ULEB128 error occurs with regular transactions!")
                print(f"   This suggests the issue is not specific to keyless accounts")
            else:
                print(f"   Different error type - may be account-specific issue")
        
    except Exception as e:
        print(f"❌ Transaction creation failed: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n📊 Test completed")


if __name__ == "__main__":
    asyncio.run(test_simple_transaction())