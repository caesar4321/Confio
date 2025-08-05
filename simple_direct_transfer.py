#!/usr/bin/env python3
"""
Simplest possible direct transfer to test basic functionality
"""

import asyncio
from aptos_sdk.async_client import RestClient
from aptos_sdk.account import Account
from aptos_sdk.transactions import (
    RawTransaction,
    SignedTransaction,
    TransactionPayload,
    EntryFunction,
    TransactionArgument
)
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.bcs import Serializer
from aptos_sdk.type_tag import TypeTag, StructTag
import time

async def simple_transfer():
    """Test the simplest possible transfer"""
    
    print("🎯 Simple Direct Transfer Test")
    print("=" * 60)
    
    # Load sponsor account
    sponsor_private_key = "0xdd56c3ae858e4e625ee6c225a5ebc8b8a9385873a0f76f129ff83823a30297b5"
    sponsor_account = Account.load_key(sponsor_private_key)
    print(f"💰 From: {sponsor_account.address()}")
    
    # Test recipient
    recipient = "0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c"
    print(f"📤 To: {recipient}")
    
    # Initialize client
    client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
    
    # Get sequence number
    import aiohttp
    async with aiohttp.ClientSession() as session:
        url = f"https://fullnode.testnet.aptoslabs.com/v1/accounts/{sponsor_account.address()}"
        async with session.get(url) as resp:
            if resp.status == 200:
                account_info = await resp.json()
                sequence = int(account_info.get("sequence_number", 0))
                print(f"📊 Sequence: {sequence}")
            else:
                sequence = 33  # Fallback
                print(f"📊 Sequence (fallback): {sequence}")
    
    try:
        # First, test simple APT transfer
        print("\n🔧 Testing APT transfer...")
        
        # Build APT transfer transaction with proper serialization
        payload = TransactionPayload(
            EntryFunction.natural(
                "0x1::aptos_account",
                "transfer",
                [],
                [
                    TransactionArgument(AccountAddress.from_str(recipient), Serializer.struct),
                    TransactionArgument(1000000, Serializer.u64)  # 0.01 APT
                ]
            )
        )
        
        raw_txn = RawTransaction(
            sender=sponsor_account.address(),
            sequence_number=sequence,
            payload=payload,
            max_gas_amount=100000,
            gas_unit_price=100,
            expiration_timestamps_secs=int(time.time()) + 600,
            chain_id=2
        )
        
        # Sign and submit
        account_auth = sponsor_account.sign_transaction(raw_txn)
        signed_txn = SignedTransaction(raw_txn, account_auth)
        
        print("📤 Submitting APT transfer...")
        tx_hash = await client.submit_bcs_transaction(signed_txn)
        print(f"✅ APT transfer submitted: {tx_hash}")
        
        await client.wait_for_transaction(tx_hash)
        print(f"✅ APT transfer confirmed!")
        
        sequence += 1
        
    except Exception as e:
        print(f"❌ APT transfer failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Now try custom token transfer
    try:
        print("\n🔧 Testing CONFIO transfer...")
        
        # Try different ways of creating the function
        CONTRACT = "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c"
        
        # Approach 1: Full module path
        print("   Trying full module path...")
        payload = TransactionPayload(
            EntryFunction.natural(
                f"{CONTRACT}::confio",
                "transfer_confio",
                [],
                [
                    TransactionArgument(AccountAddress.from_str(recipient), Serializer.struct),
                    TransactionArgument(10000000, Serializer.u64)  # 10 CONFIO
                ]
            )
        )
        
        raw_txn = RawTransaction(
            sender=sponsor_account.address(),
            sequence_number=sequence,
            payload=payload,
            max_gas_amount=100000,
            gas_unit_price=100,
            expiration_timestamps_secs=int(time.time()) + 600,
            chain_id=2
        )
        
        # Sign and submit
        account_auth = sponsor_account.sign_transaction(raw_txn)
        signed_txn = SignedTransaction(raw_txn, account_auth)
        
        print("📤 Submitting CONFIO transfer...")
        tx_hash = await client.submit_bcs_transaction(signed_txn)
        print(f"✅ CONFIO transfer submitted: {tx_hash}")
        
        await client.wait_for_transaction(tx_hash)
        print(f"✅ CONFIO transfer confirmed!")
        
    except Exception as e:
        print(f"❌ CONFIO transfer failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(simple_transfer())