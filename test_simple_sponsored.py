#!/usr/bin/env python3
"""
Test simplest possible sponsored transaction
"""

import asyncio
import os
import sys
import django

# Setup Django
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from aptos_sdk.async_client import RestClient
from aptos_sdk.account import Account
from aptos_sdk.transactions import (
    RawTransaction,
    FeePayerRawTransaction,
    SignedTransaction,
    TransactionPayload,
    EntryFunction,
    TransactionArgument
)
from aptos_sdk.authenticator import (
    Authenticator,
    Ed25519Authenticator,
    FeePayerAuthenticator,
    AccountAuthenticator
)
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.bcs import Serializer
import time


async def test_simple_sponsored():
    """Test the simplest possible sponsored transaction"""
    
    print("🧪 Testing Simple Sponsored Transaction")
    print("=" * 60)
    
    # Load sponsor account
    sponsor_private_key = os.getenv('APTOS_SPONSOR_PRIVATE_KEY')
    if not sponsor_private_key:
        print("❌ APTOS_SPONSOR_PRIVATE_KEY not set")
        return
    
    sponsor_account = Account.load_key(sponsor_private_key)
    print(f"💰 Sponsor: {sponsor_account.address()}")
    
    # Create test user account
    user_account = Account.generate()
    print(f"👤 User: {user_account.address()}")
    
    # Initialize client
    client = RestClient("https://fullnode.testnet.aptoslabs.com")
    
    # Get sponsor sequence number
    try:
        # Use the correct account method
        sponsor_info = await client.account(str(sponsor_account.address()))
        sponsor_sequence = int(sponsor_info.get("sequence_number", 0))
        print(f"✅ Sponsor sequence: {sponsor_sequence}")
    except Exception as e:
        print(f"❌ Failed to get sponsor info: {e}")
        # Try manual request
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://fullnode.testnet.aptoslabs.com/v1/accounts/{sponsor_account.address()}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    sponsor_sequence = int(data.get("sequence_number", 0))
                    print(f"✅ Sponsor sequence (manual): {sponsor_sequence}")
                else:
                    print(f"❌ Manual request also failed: {resp.status}")
                    return
    
    # Build a simple APT transfer transaction
    # User sends 0.01 APT to a test address
    recipient = "0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36"
    amount = 1000000  # 0.01 APT in octas
    
    print(f"\n📤 Building transfer:")
    print(f"   From: {user_account.address()}")
    print(f"   To: {recipient}")
    print(f"   Amount: {amount} octas (0.01 APT)")
    print(f"   Gas paid by: {sponsor_account.address()}")
    
    # Create entry function
    payload = TransactionPayload(
        EntryFunction.natural(
            "0x1::aptos_account",
            "transfer",
            [],
            [
                TransactionArgument(
                    AccountAddress.from_str(recipient),
                    lambda s, v: s.struct(v)
                ),
                TransactionArgument(
                    amount,
                    lambda s, v: s.u64(v)
                )
            ]
        )
    )
    
    # Build raw transaction
    raw_txn = RawTransaction(
        sender=user_account.address(),
        sequence_number=0,  # New account
        payload=payload,
        max_gas_amount=10000,  # Lower gas limit
        gas_unit_price=100,
        expiration_timestamps_secs=int(time.time()) + 600,
        chain_id=2
    )
    
    print(f"\n🔧 Transaction built:")
    print(f"   Sender: {user_account.address()}")
    print(f"   Gas limit: 10,000")
    print(f"   Gas price: 100")
    
    # Create fee payer transaction
    fee_payer_txn = FeePayerRawTransaction(
        raw_transaction=raw_txn,
        secondary_signers=[],
        fee_payer=sponsor_account.address()
    )
    
    # User signs the fee payer transaction
    print(f"\n🔐 Creating signatures...")
    
    # Serialize fee payer transaction for signing
    serializer = Serializer()
    fee_payer_txn.serialize(serializer)
    txn_bytes = serializer.output()
    
    # Sign with prefix
    signing_message = b"APTOS::RawTransaction" + txn_bytes
    
    # User signs
    user_signature = user_account.sign(signing_message)
    user_auth = AccountAuthenticator(
        Ed25519Authenticator(user_account.public_key(), user_signature)
    )
    
    # Sponsor signs the same message
    sponsor_signature = sponsor_account.sign(signing_message)
    sponsor_auth = AccountAuthenticator(
        Ed25519Authenticator(sponsor_account.public_key(), sponsor_signature)
    )
    
    print(f"   ✅ User signature created")
    print(f"   ✅ Sponsor signature created")
    
    # Create fee payer authenticator
    fee_payer_auth = FeePayerAuthenticator(
        sender=user_auth,
        secondary_signers=[],
        fee_payer=(sponsor_account.address(), sponsor_auth)
    )
    
    # Create signed transaction
    signed_txn = SignedTransaction(
        transaction=fee_payer_txn,
        authenticator=Authenticator(fee_payer_auth)
    )
    
    print(f"\n🚀 Submitting sponsored transaction...")
    
    try:
        # Submit with correct endpoint
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # Serialize signed transaction
            serializer = Serializer()
            signed_txn.serialize(serializer)
            bcs_txn = serializer.output()
            
            # Submit to correct endpoint
            headers = {"Content-Type": "application/x.aptos.signed_transaction+bcs"}
            async with session.post(
                "https://fullnode.testnet.aptoslabs.com/v1/transactions",
                data=bcs_txn,
                headers=headers
            ) as resp:
                if resp.status == 202:
                    result = await resp.json()
                    tx_hash = result.get("hash")
                    print(f"✅ SUCCESS! Transaction hash: {tx_hash}")
                else:
                    error = await resp.text()
                    raise Exception(f"Submit failed: {error}")
        print(f"✅ SUCCESS! Transaction hash: {tx_hash}")
        
        # Wait for confirmation
        await client.wait_for_transaction(tx_hash)
        print(f"✅ Transaction confirmed on blockchain")
        
    except Exception as e:
        print(f"❌ Failed: {e}")
        
        # Analyze error
        error_str = str(e)
        if "ULEB128" in error_str:
            print(f"\n🔍 ULEB128 Error Details:")
            print(f"   - All integer values are within range")
            print(f"   - Gas limit: 10,000 (well within u64)")
            print(f"   - Amount: 1,000,000 (well within u64)")
            print(f"   - Sequence: 0 (minimal)")
            print(f"   - This suggests a structural issue with BCS encoding")
        elif "INSUFFICIENT_BALANCE" in error_str:
            print(f"\n💰 User account needs APT balance first")
        elif "SEQUENCE_NUMBER" in error_str:
            print(f"\n🔢 Sequence number mismatch")


if __name__ == "__main__":
    asyncio.run(test_simple_sponsored())