#!/usr/bin/env python3
"""
Check Aptos account status
"""

import asyncio
from aptos_sdk.async_client import RestClient
from aptos_sdk.account import Account

async def check_account():
    """Check if sponsor account exists"""
    
    # Sponsor account details
    sponsor_address = "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c"
    sponsor_private_key = "0xdd56c3ae858e4e625ee6c225a5ebc8b8a9385873a0f76f129ff83823a30297b5"
    
    # Load account
    sponsor_account = Account.load_key(sponsor_private_key)
    print(f"Loaded account address: {sponsor_account.address()}")
    print(f"Expected address: {sponsor_address}")
    print(f"Addresses match: {str(sponsor_account.address()) == sponsor_address}")
    
    # Initialize client
    client = RestClient("https://fullnode.testnet.aptoslabs.com")
    
    # Try different ways to check account
    print("\n1. Checking via client.account()...")
    try:
        account_info = await client.account(str(sponsor_account.address()))
        print(f"✅ Account exists!")
        print(f"   Sequence: {account_info.get('sequence_number')}")
        print(f"   Auth key: {account_info.get('authentication_key')}")
    except Exception as e:
        print(f"❌ client.account() failed: {e}")
    
    print("\n2. Checking via direct HTTP request...")
    import aiohttp
    async with aiohttp.ClientSession() as session:
        url = f"https://fullnode.testnet.aptoslabs.com/v1/accounts/{sponsor_account.address()}"
        async with session.get(url) as resp:
            print(f"   Status: {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"   ✅ Account data: {data}")
            else:
                print(f"   ❌ Response: {await resp.text()}")
    
    print("\n3. Checking APT balance...")
    try:
        # Check APT balance
        balance = await client.account_balance(str(sponsor_account.address()))
        print(f"✅ APT Balance: {balance / 1e8} APT")
    except Exception as e:
        print(f"❌ Balance check failed: {e}")
    
    print("\n4. Checking if account needs to be created...")
    print("Note: On Aptos, accounts are created when they first receive funds")
    print("You may need to fund this account using the Aptos faucet:")
    print(f"https://aptos.dev/en/network/faucet")
    print(f"Address to fund: {sponsor_account.address()}")


if __name__ == "__main__":
    asyncio.run(check_account())