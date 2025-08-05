#!/usr/bin/env python3
"""
Direct token distribution from sponsor account to user accounts
This bypasses keyless authentication issues by using the sponsor's private key directly
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
    RawTransaction,
    SignedTransaction,
    TransactionPayload,
    EntryFunction,
    TransactionArgument
)
from aptos_sdk.authenticator import Authenticator, Ed25519Authenticator
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.bcs import Serializer
import time

# Target accounts to distribute to
TARGET_ACCOUNTS = [
    "0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c",
    "0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36",
    "0xef37787babb2d5ad88ea44a9f23b067dffc4dd5db1f0b8e88e07c0a6b89e1c3f",
    "0x7bc0e088ad7a5fb1f6bbeb8b5fa20b94b18c2c890bf6e7caab45fe973c09e061"
]

# Distribution amounts
CUSD_AMOUNT = 100_000000  # 100 cUSD (6 decimals)
CONFIO_AMOUNT = 50_000000  # 50 CONFIO (6 decimals)


async def distribute_tokens():
    """Distribute cUSD and CONFIO tokens to target accounts"""
    
    print("🎯 Direct Token Distribution")
    print("=" * 60)
    
    # Load sponsor account
    sponsor_private_key = os.getenv('APTOS_SPONSOR_PRIVATE_KEY')
    if not sponsor_private_key:
        # Use the key from .env file
        sponsor_private_key = "0xdd56c3ae858e4e625ee6c225a5ebc8b8a9385873a0f76f129ff83823a30297b5"
    
    sponsor_account = Account.load_key(sponsor_private_key)
    print(f"💰 Sponsor: {sponsor_account.address()}")
    
    # Initialize client with /v1 suffix
    client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
    
    # Get sponsor account info using direct HTTP request
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            url = f"https://fullnode.testnet.aptoslabs.com/v1/accounts/{sponsor_account.address()}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    sponsor_info = await resp.json()
                    sponsor_sequence = int(sponsor_info.get("sequence_number", 0))
                    print(f"📊 Sponsor sequence: {sponsor_sequence}")
                else:
                    print(f"❌ Failed to get sponsor info: {resp.status}")
                    return
    except Exception as e:
        print(f"❌ Failed to get sponsor info: {e}")
        return
    
    # Contract addresses
    CONTRACT_ADDRESS = "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c"
    
    print(f"\n🚀 Starting distribution to {len(TARGET_ACCOUNTS)} accounts...")
    
    for i, recipient in enumerate(TARGET_ACCOUNTS):
        print(f"\n📤 Account {i+1}/{len(TARGET_ACCOUNTS)}: {recipient[:16]}...")
        
        # Transfer cUSD
        try:
            print(f"   💵 Sending {CUSD_AMOUNT/1_000000} cUSD...")
            
            # Build cUSD transfer with proper argument serialization
            payload = TransactionPayload(
                EntryFunction.natural(
                    f"{CONTRACT_ADDRESS}::cusd",
                    "transfer_cusd",
                    [],
                    [
                        TransactionArgument(AccountAddress.from_str(recipient), Serializer.struct),
                        TransactionArgument(CUSD_AMOUNT, Serializer.u64)
                    ]
                )
            )
            
            raw_txn = RawTransaction(
                sender=sponsor_account.address(),
                sequence_number=sponsor_sequence,
                payload=payload,
                max_gas_amount=100000,
                gas_unit_price=100,
                expiration_timestamps_secs=int(time.time()) + 600,
                chain_id=2
            )
            
            # Sign and submit
            account_auth = sponsor_account.sign_transaction(raw_txn)
            signed_txn = SignedTransaction(raw_txn, account_auth)
            
            tx_hash = await client.submit_bcs_transaction(signed_txn)
            await client.wait_for_transaction(tx_hash)
            print(f"   ✅ cUSD sent! Hash: {tx_hash}")
            
            sponsor_sequence += 1
            
        except Exception as e:
            print(f"   ❌ cUSD transfer failed: {e}")
        
        # Transfer CONFIO
        try:
            print(f"   🪙 Sending {CONFIO_AMOUNT/1_000000} CONFIO...")
            
            # Build CONFIO transfer with proper argument serialization
            payload = TransactionPayload(
                EntryFunction.natural(
                    f"{CONTRACT_ADDRESS}::confio",
                    "transfer_confio",
                    [],
                    [
                        TransactionArgument(AccountAddress.from_str(recipient), Serializer.struct),
                        TransactionArgument(CONFIO_AMOUNT, Serializer.u64)
                    ]
                )
            )
            
            raw_txn = RawTransaction(
                sender=sponsor_account.address(),
                sequence_number=sponsor_sequence,
                payload=payload,
                max_gas_amount=100000,
                gas_unit_price=100,
                expiration_timestamps_secs=int(time.time()) + 600,
                chain_id=2
            )
            
            # Sign and submit
            account_auth = sponsor_account.sign_transaction(raw_txn)
            signed_txn = SignedTransaction(raw_txn, account_auth)
            
            tx_hash = await client.submit_bcs_transaction(signed_txn)
            await client.wait_for_transaction(tx_hash)
            print(f"   ✅ CONFIO sent! Hash: {tx_hash}")
            
            sponsor_sequence += 1
            
        except Exception as e:
            print(f"   ❌ CONFIO transfer failed: {e}")
    
    print(f"\n✅ Distribution complete!")
    print(f"   Total accounts: {len(TARGET_ACCOUNTS)}")
    print(f"   cUSD per account: {CUSD_AMOUNT/1_000000}")
    print(f"   CONFIO per account: {CONFIO_AMOUNT/1_000000}")


if __name__ == "__main__":
    asyncio.run(distribute_tokens())