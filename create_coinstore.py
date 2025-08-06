#!/usr/bin/env python3
"""
Try to register a CoinStore for APT on the keyless account
This might allow the SDK to see the balance properly
"""

import asyncio
from aptos_sdk.async_client import RestClient
from aptos_sdk.account import Account
from aptos_sdk.transactions import EntryFunction, TransactionArgument, TransactionPayload
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.type_tag import TypeTag, StructTag

async def register_apt_coinstore():
    """Register APT CoinStore for keyless account"""
    
    # Sponsor account (will pay gas)
    sponsor_private_key = "0xdd56c3ae858e4e625ee6c225a5ebc8b8a9385873a0f76f129ff83823a30297b5"
    sponsor_account = Account.load_key(sponsor_private_key)
    
    # Keyless account
    keyless_address = "0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c"
    
    print(f"Attempting to register APT CoinStore")
    print(f"====================================")
    print(f"For account: {keyless_address}")
    print(f"Using sponsor: {sponsor_account.address()}")
    
    # Initialize client
    client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
    
    try:
        # Check if CoinStore already exists
        print(f"\nChecking existing resources...")
        resources = await client.account_resources(AccountAddress.from_str(keyless_address))
        
        has_coinstore = False
        for resource in resources:
            if resource['type'] == '0x1::coin::CoinStore<0x1::aptos_coin::AptosCoin>':
                has_coinstore = True
                balance = int(resource['data']['coin']['value'])
                print(f"✅ CoinStore already exists with {balance / 1e8} APT")
                break
                
        if not has_coinstore:
            print("❌ No CoinStore found")
            
            # Try to register CoinStore manually
            print(f"\nAttempting to register CoinStore...")
            
            # Build transaction to register coin
            entry_function = EntryFunction.natural(
                module="0x1::managed_coin",
                function="register",
                ty_args=[
                    TypeTag(StructTag.from_str("0x1::aptos_coin::AptosCoin"))
                ],
                args=[]
            )
            
            # Submit as fee payer transaction (sponsor pays, keyless account receives)
            print("This requires the keyless account to sign the transaction...")
            print("Since we don't have the keyless private key, this won't work.")
            print("The keyless account needs to register its own CoinStore.")
            
        # Alternative approach: Transfer APT to force CoinStore creation
        print(f"\nAlternative: Send APT to force CoinStore creation...")
        
        # Send a tiny amount to trigger CoinStore creation
        amount_octas = 1  # 0.00000001 APT
        
        tx_args = [
            TransactionArgument(AccountAddress.from_str(keyless_address), lambda s, v: v.serialize(s)),
            TransactionArgument(amount_octas, lambda s, v: s.u64(v))
        ]
        
        # Use aptos_account::transfer which should auto-register
        entry_function = EntryFunction.natural(
            module="0x1::aptos_account",
            function="transfer",
            ty_args=[],
            args=tx_args
        )
        
        signed_txn = await client.create_bcs_signed_transaction(
            sender=sponsor_account,
            payload=TransactionPayload(entry_function)
        )
        
        tx_hash = await client.submit_bcs_transaction(signed_txn)
        print(f"✅ Sent micro-transfer: {tx_hash}")
        
        # Wait for confirmation
        await client.wait_for_transaction(tx_hash)
        print(f"✅ Transaction confirmed")
        
        # Check again
        print(f"\nChecking resources after transfer...")
        resources = await client.account_resources(AccountAddress.from_str(keyless_address))
        
        for resource in resources:
            if resource['type'] == '0x1::coin::CoinStore<0x1::aptos_coin::AptosCoin>':
                balance = int(resource['data']['coin']['value'])
                print(f"✅ CoinStore now exists with {balance / 1e8} APT")
                break
        else:
            print("❌ CoinStore still not found - APT went to FungibleStore again")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(register_apt_coinstore())