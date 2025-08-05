#!/usr/bin/env python3
"""
Check sponsor's token balances and mint if needed
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
import time

async def check_and_mint():
    """Check balances and mint tokens to sponsor"""
    
    print("🔍 Checking Sponsor Token Balances")
    print("=" * 60)
    
    # Load sponsor account
    sponsor_private_key = "0xdd56c3ae858e4e625ee6c225a5ebc8b8a9385873a0f76f129ff83823a30297b5"
    sponsor_account = Account.load_key(sponsor_private_key)
    print(f"💰 Sponsor: {sponsor_account.address()}")
    
    # Initialize client
    client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
    
    # Contract address
    CONTRACT = "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c"
    
    # Get sequence number
    import aiohttp
    async with aiohttp.ClientSession() as session:
        url = f"https://fullnode.testnet.aptoslabs.com/v1/accounts/{sponsor_account.address()}"
        async with session.get(url) as resp:
            if resp.status == 200:
                account_info = await resp.json()
                sequence = int(account_info.get("sequence_number", 0))
                print(f"📊 Sequence: {sequence}")
    
    # Check APT balance
    try:
        balance = await client.account_balance(sponsor_account.address())
        print(f"\n💎 APT Balance: {balance / 1e8} APT")
    except:
        print(f"❌ Failed to check APT balance")
    
    # TODO: Check cUSD and CONFIO balances via view functions
    # For now, let's just mint tokens
    
    print("\n🏭 Minting tokens to sponsor...")
    
    # Mint cUSD
    try:
        print("\n💵 Minting 10,000 cUSD...")
        payload = TransactionPayload(
            EntryFunction.natural(
                f"{CONTRACT}::cusd",
                "mint_cusd",
                [],
                [
                    TransactionArgument(sponsor_account.address(), Serializer.struct),
                    TransactionArgument(10000_000000, Serializer.u64)  # 10,000 cUSD
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
        
        account_auth = sponsor_account.sign_transaction(raw_txn)
        signed_txn = SignedTransaction(raw_txn, account_auth)
        
        tx_hash = await client.submit_bcs_transaction(signed_txn)
        await client.wait_for_transaction(tx_hash)
        print(f"✅ cUSD minted! Hash: {tx_hash}")
        sequence += 1
    except Exception as e:
        print(f"❌ cUSD mint failed: {e}")
    
    # Mint CONFIO
    try:
        print("\n🪙 Minting 5,000 CONFIO...")
        payload = TransactionPayload(
            EntryFunction.natural(
                f"{CONTRACT}::confio",
                "mint_confio",
                [],
                [
                    TransactionArgument(sponsor_account.address(), Serializer.struct),
                    TransactionArgument(5000_000000, Serializer.u64)  # 5,000 CONFIO
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
        
        account_auth = sponsor_account.sign_transaction(raw_txn)
        signed_txn = SignedTransaction(raw_txn, account_auth)
        
        tx_hash = await client.submit_bcs_transaction(signed_txn)
        await client.wait_for_transaction(tx_hash)
        print(f"✅ CONFIO minted! Hash: {tx_hash}")
        sequence += 1
    except Exception as e:
        print(f"❌ CONFIO mint failed: {e}")
    
    print("\n✅ Token minting complete!")
    print(f"   Final sequence: {sequence}")


if __name__ == "__main__":
    asyncio.run(check_and_mint())