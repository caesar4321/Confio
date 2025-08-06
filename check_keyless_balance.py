#!/usr/bin/env python3
"""
Check the actual balance of the keyless account
"""

import asyncio
from aptos_sdk.async_client import RestClient
from aptos_sdk.account_address import AccountAddress

async def check_balance():
    """Check keyless account balance and status"""
    
    keyless_address = "0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c"
    
    # Initialize client
    client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
    
    print(f"Checking Keyless Account: {keyless_address}")
    print("=" * 60)
    
    try:
        # Check if account exists
        print("\n1. Account Info:")
        account_info = await client.account(AccountAddress.from_str(keyless_address))
        print(f"   ✅ Account exists")
        print(f"   Sequence number: {account_info.get('sequence_number', 0)}")
        print(f"   Authentication key: {account_info.get('authentication_key', 'N/A')}")
        
        # Check resources
        print("\n2. Account Resources:")
        resources = await client.account_resources(AccountAddress.from_str(keyless_address))
        
        # Find APT coin store
        apt_balance = 0
        for resource in resources:
            if resource['type'] == '0x1::coin::CoinStore<0x1::aptos_coin::AptosCoin>':
                apt_balance = int(resource['data']['coin']['value'])
                print(f"   ✅ APT CoinStore found")
                print(f"   Balance: {apt_balance} octas ({apt_balance / 1e8} APT)")
                print(f"   Frozen: {resource['data']['frozen']}")
                
                # Check if balance is sufficient for basic transaction
                min_gas = 100000 * 100  # max_gas_amount * gas_unit_price
                print(f"\n3. Transaction Feasibility:")
                print(f"   Minimum gas needed: {min_gas} octas ({min_gas / 1e8} APT)")
                print(f"   Current balance: {apt_balance} octas ({apt_balance / 1e8} APT)")
                print(f"   Can pay for gas: {'✅ Yes' if apt_balance >= min_gas else '❌ No'}")
                
        if apt_balance == 0:
            print("   ❌ No APT balance found")
            
        # Check account modules (if any)
        print("\n4. Account Modules:")
        try:
            modules = await client.account_modules(AccountAddress.from_str(keyless_address))
            if modules:
                print(f"   Found {len(modules)} modules")
            else:
                print("   No modules (normal for regular accounts)")
        except:
            print("   No modules (normal for regular accounts)")
            
    except Exception as e:
        print(f"❌ Error checking account: {e}")
    finally:
        await client.close()
    
    print("\n" + "=" * 60)
    print("Note: Keyless accounts may have special requirements.")
    print("If balance is sufficient but transactions fail, check:")
    print("1. Proof is properly fetched")
    print("2. JWT hasn't expired")
    print("3. Ephemeral key pair is valid")
    print("4. Pepper is correct")


if __name__ == "__main__":
    asyncio.run(check_balance())