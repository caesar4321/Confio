#!/usr/bin/env python3
"""
Debug ULEB128 serialization error in Aptos transactions
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
    TransactionArgument,
    RawTransaction,
    SignedTransaction,
    FeePayerRawTransaction,
    ModuleId
)
from aptos_sdk.authenticator import Authenticator, Ed25519Authenticator
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.ed25519 import PublicKey, Signature
import time


async def test_uleb128_values():
    """Test different values to identify ULEB128 overflow source"""
    
    print("🔍 Debugging ULEB128 serialization error")
    print("=" * 50)
    
    # Test client connection
    aptos_client = RestClient("https://fullnode.testnet.aptoslabs.com")
    
    # Test different parameter combinations
    test_cases = [
        {"gas": 100, "amount": 1000000, "description": "Minimal values"},
        {"gas": 500, "amount": 5000000, "description": "Small values"},
        {"gas": 1000, "amount": 25000000, "description": "Current values"},
        {"gas": 2000, "amount": 50000000, "description": "Medium values"},
    ]
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n{i}. Testing {case['description']}")
        print(f"   Gas: {case['gas']}, Amount: {case['amount']}")
        
        try:
            # Create a simple transaction to test BCS serialization
            user_address = "0x2a2549df49ec0e820b6c580c3af95b502ca7e2d956729860872fbc5de570795b"
            
            # Get account info
            try:
                account_info = await aptos_client.account(user_address)
                sequence_number = int(account_info["sequence_number"])
                print(f"   Account sequence: {sequence_number}")
            except Exception as e:
                print(f"   ⚠️  Account fetch error: {e}")
                sequence_number = 0
            
            # Create entry function
            function = EntryFunction.natural(
                "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c",
                "confio",
                "transfer_confio",
                [],
                [
                    AccountAddress.from_str("0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36"),
                    case["amount"]
                ]
            )
            
            payload = TransactionPayload(function)
            
            # Create raw transaction with test parameters
            current_time = int(time.time())
            expiration = current_time + 300  # 5 minutes
            
            raw_txn = RawTransaction(
                sender=AccountAddress.from_str(user_address),
                sequence_number=sequence_number,
                payload=payload,
                max_gas_amount=case["gas"],
                gas_unit_price=1,
                expiration_timestamp_secs=expiration,
                chain_id=2
            )
            
            print(f"   ✅ Raw transaction created successfully")
            print(f"   - Sender: {user_address[:16]}...")
            print(f"   - Sequence: {sequence_number}")
            print(f"   - Gas limit: {case['gas']}")
            print(f"   - Gas price: 1")
            print(f"   - Amount: {case['amount']}")
            print(f"   - Expiration: {expiration}")
            
            # Test BCS serialization
            try:
                from aptos_sdk.bcs import Serializer
                serializer = Serializer()
                raw_txn.serialize(serializer)
                serialized_bytes = serializer.output()
                print(f"   ✅ BCS serialization successful ({len(serialized_bytes)} bytes)")
                
                # Check individual ULEB128 values
                print(f"   🔍 ULEB128 analysis:")
                print(f"      - Sequence number: {sequence_number} ({'OK' if sequence_number < 2**32 else 'TOO LARGE'})")
                print(f"      - Gas limit: {case['gas']} ({'OK' if case['gas'] < 2**32 else 'TOO LARGE'})")
                print(f"      - Gas price: 1 (OK)")
                print(f"      - Amount: {case['amount']} ({'OK' if case['amount'] < 2**64 else 'TOO LARGE'})")
                print(f"      - Expiration: {expiration} ({'OK' if expiration < 2**64 else 'TOO LARGE'})")
                
            except Exception as serialize_error:
                print(f"   ❌ BCS serialization failed: {serialize_error}")
                
        except Exception as e:
            print(f"   ❌ Transaction creation failed: {e}")
    
    print(f"\n📊 Summary:")
    print(f"- All test values should be within u64 range (< 18,446,744,073,709,551,616)")
    print(f"- Gas values should be reasonable (< 1,000,000)")
    print(f"- Token amounts should be in base units (with decimals)")


if __name__ == "__main__":
    asyncio.run(test_uleb128_values())