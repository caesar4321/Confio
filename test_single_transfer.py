#!/usr/bin/env python3
"""
Test a single token transfer with detailed debugging
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
from aptos_sdk.authenticator import Authenticator
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.bcs import Serializer
import time

async def test_transfer():
    """Test a single CONFIO transfer"""
    
    print("🧪 Testing Single Transfer")
    print("=" * 60)
    
    # Load sponsor account
    sponsor_private_key = "0xdd56c3ae858e4e625ee6c225a5ebc8b8a9385873a0f76f129ff83823a30297b5"
    sponsor_account = Account.load_key(sponsor_private_key)
    print(f"💰 Sponsor: {sponsor_account.address()}")
    
    # Test recipient
    recipient = "0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c"
    amount = 10_000000  # 10 CONFIO
    
    # Contract details
    CONTRACT_ADDRESS = "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c"
    
    print(f"\n📋 Transfer details:")
    print(f"   To: {recipient}")
    print(f"   Amount: {amount/1_000000} CONFIO")
    
    # Initialize client
    client = RestClient("https://fullnode.testnet.aptoslabs.com")
    
    # Get sequence number
    import aiohttp
    async with aiohttp.ClientSession() as session:
        url = f"https://fullnode.testnet.aptoslabs.com/v1/accounts/{sponsor_account.address()}"
        async with session.get(url) as resp:
            if resp.status == 200:
                sponsor_info = await resp.json()
                sponsor_sequence = int(sponsor_info.get("sequence_number", 0))
                print(f"   Sequence: {sponsor_sequence}")
    
    try:
        # Build the transaction payload - testing different approaches
        print("\n🔧 Building transaction...")
        
        # Try approach 1: Direct EntryFunction creation
        print("   Trying approach 1: Direct creation...")
        try:
            # Serialize arguments
            ser = Serializer()
            ser.struct(AccountAddress.from_str(recipient))
            recipient_bytes = ser.output()
            
            ser = Serializer()
            ser.u64(amount)
            amount_bytes = ser.output()
            
            # Create entry function
            entry_function = EntryFunction(
                module=AccountAddress.from_str(CONTRACT_ADDRESS),
                function="confio::transfer_confio",
                ty_args=[],
                args=[recipient_bytes, amount_bytes]
            )
            print("   ✅ Direct creation succeeded")
        except Exception as e1:
            print(f"   ❌ Direct creation failed: {e1}")
            
            # Try approach 2: Using EntryFunction.natural
            print("   Trying approach 2: EntryFunction.natural...")
            try:
                entry_function = EntryFunction.natural(
                    f"{CONTRACT_ADDRESS}::confio",
                    "transfer_confio",
                    [],
                    [
                        TransactionArgument(recipient, Serializer.str),
                        TransactionArgument(str(amount), Serializer.str)
                    ]
                )
                print("   ✅ Natural with string args succeeded")
            except Exception as e2:
                print(f"   ❌ Natural with string args failed: {e2}")
                
                # Try approach 3: Different serializer syntax
                print("   Trying approach 3: Lambda serializers...")
                entry_function = EntryFunction.natural(
                    f"{CONTRACT_ADDRESS}::confio",
                    "transfer_confio",
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
                print("   ✅ Lambda serializers succeeded")
        
        # Create payload
        payload = TransactionPayload(entry_function)
        
        # Build raw transaction
        raw_txn = RawTransaction(
            sender=sponsor_account.address(),
            sequence_number=sponsor_sequence,
            payload=payload,
            max_gas_amount=100000,
            gas_unit_price=100,
            expiration_timestamps_secs=int(time.time()) + 600,
            chain_id=2
        )
        
        print("\n📤 Signing transaction...")
        # Sign transaction - sign_transaction returns AccountAuthenticator
        account_auth = sponsor_account.sign_transaction(raw_txn)
        signed_txn = SignedTransaction(raw_txn, account_auth)
        
        print("\n🚀 Submitting transaction...")
        # Submit transaction
        try:
            tx_hash = await client.submit_bcs_transaction(signed_txn)
            print(f"✅ Transaction submitted: {tx_hash}")
            
            # Wait for confirmation
            await client.wait_for_transaction(tx_hash)
            print(f"✅ Transaction confirmed!")
        except Exception as submit_error:
            print(f"❌ Submit error: {str(submit_error)}")
            
            # Try to get more details via direct API call
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Serialize the transaction
                ser = Serializer()
                signed_txn.serialize(ser)
                txn_bytes = ser.output()
                
                headers = {"Content-Type": "application/x.aptos.signed_transaction+bcs"}
                async with session.post(
                    "https://fullnode.testnet.aptoslabs.com/v1/transactions",
                    data=txn_bytes,
                    headers=headers
                ) as resp:
                    error_text = await resp.text()
                    print(f"❌ API Error Response: {error_text}")
                    raise
        
    except Exception as e:
        print(f"\n❌ Transaction failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_transfer())