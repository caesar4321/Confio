#!/usr/bin/env python3
"""
Register CoinStore for the keyless account
This will allow it to receive and use APT in the traditional Coin format
"""

import asyncio
from aptos_sdk.async_client import RestClient
from aptos_sdk.account import Account
from aptos_sdk.transactions import EntryFunction, TransactionArgument, TransactionPayload
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.type_tag import TypeTag, StructTag
from aptos_sdk.bcs import Serializer

async def register_and_fund():
    """Register CoinStore and transfer APT"""
    
    # Sponsor account
    sponsor_private_key = "0xdd56c3ae858e4e625ee6c225a5ebc8b8a9385873a0f76f129ff83823a30297b5"
    sponsor_account = Account.load_key(sponsor_private_key)
    
    # Keyless account
    keyless_address = "0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c"
    
    print(f"Registering CoinStore for Keyless Account")
    print(f"==========================================")
    print(f"Keyless address: {keyless_address}")
    
    # Initialize client
    client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
    
    try:
        # First, let's fund with a regular transfer that should auto-register
        print(f"\nSending APT (this should auto-register CoinStore)...")
        
        # Amount to transfer (0.01 APT)
        amount_octas = 1_000_000  # 0.01 APT
        
        # Create transaction arguments for transfer
        tx_args = [
            TransactionArgument(AccountAddress.from_str(keyless_address), lambda s, v: v.serialize(s)),
            TransactionArgument(amount_octas, lambda s, v: s.u64(v))
        ]
        
        # Use aptos_account::transfer which auto-registers
        entry_function = EntryFunction.natural(
            module="0x1::aptos_account",
            function="transfer",
            ty_args=[],
            args=tx_args
        )
        
        # Submit transaction
        signed_txn = await client.create_bcs_signed_transaction(
            sender=sponsor_account,
            payload=TransactionPayload(entry_function)
        )
        
        tx_hash = await client.submit_bcs_transaction(signed_txn)
        print(f"✅ Transaction submitted: {tx_hash}")
        
        # Wait for confirmation
        print(f"Waiting for transaction...")
        await client.wait_for_transaction(tx_hash)
        print(f"✅ Transaction confirmed!")
        
        # Check if CoinStore was created
        print(f"\nChecking for CoinStore...")
        resources = await client.account_resources(AccountAddress.from_str(keyless_address))
        
        coin_store_found = False
        fungible_store_found = False
        
        for resource in resources:
            if resource['type'] == '0x1::coin::CoinStore<0x1::aptos_coin::AptosCoin>':
                balance = int(resource['data']['coin']['value'])
                print(f"✅ CoinStore found with balance: {balance / 1e8} APT")
                coin_store_found = True
                
        if not coin_store_found:
            print("❌ CoinStore not found")
            print("\nChecking for FungibleStore ownership...")
            
            # The APT might be in a FungibleStore at a different address
            # Let's check the transaction to see where it went
            tx_info = await client.transactions_by_hash(tx_hash)
            changes = tx_info.get('changes', [])
            
            for change in changes:
                if 'FungibleStore' in change.get('data', {}).get('type', ''):
                    addr = change.get('address')
                    print(f"Found FungibleStore at: {addr}")
                    
                    # Check the owner
                    obj_resources = await client.account_resources(AccountAddress.from_str(addr))
                    for res in obj_resources:
                        if res['type'] == '0x1::fungible_asset::FungibleStore':
                            balance = int(res['data']['balance'])
                            print(f"  Balance: {balance / 1e8} APT")
                        if res['type'] == '0x1::object::ObjectCore':
                            owner = res['data']['owner']
                            print(f"  Owner: {owner}")
                            if owner == keyless_address:
                                print(f"  ✅ Owned by keyless account")
                                fungible_store_found = True
        
        print("\n" + "=" * 60)
        if coin_store_found:
            print("✅ Success! CoinStore is registered and funded")
            print(f"The keyless account can now use APT for transactions")
        elif fungible_store_found:
            print("⚠️  APT is in FungibleStore format (new standard)")
            print("The SDK might need special handling for this")
            print("Consider using the primary network APT functions")
        else:
            print("❌ Could not verify APT storage")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(register_and_fund())