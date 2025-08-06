#!/usr/bin/env python3
"""
Fund the keyless account with a small amount of APT
"""

import asyncio
from aptos_sdk.async_client import RestClient
from aptos_sdk.account import Account
from aptos_sdk.transactions import EntryFunction, TransactionArgument, TransactionPayload
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.bcs import Serializer

async def fund_keyless_account():
    """Transfer APT to the keyless account"""
    
    # Sponsor account (source of funds)
    sponsor_private_key = "0xdd56c3ae858e4e625ee6c225a5ebc8b8a9385873a0f76f129ff83823a30297b5"
    sponsor_account = Account.load_key(sponsor_private_key)
    
    # Keyless account (recipient)
    keyless_address = "0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c"
    
    # Amount to transfer (0.01 APT = 1_000_000 octas) - small amount for testing
    amount_apt = 0.01
    amount_octas = int(amount_apt * 1e8)
    
    print(f"Funding Keyless Account")
    print(f"=======================")
    print(f"From: {sponsor_account.address()}")
    print(f"To:   {keyless_address}")
    print(f"Amount: {amount_apt} APT ({amount_octas} octas)")
    
    # Initialize client
    client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
    
    # Check sponsor account info first
    print(f"\nChecking sponsor account...")
    try:
        account_info = await client.account(sponsor_account.address())
        print(f"✅ Sponsor account exists")
        print(f"   Sequence: {account_info.get('sequence_number')}")
    except Exception as e:
        print(f"❌ Failed to get sponsor account: {e}")
        await client.close()
        return
    
    # Check keyless account current status
    print(f"\nChecking keyless account...")
    try:
        keyless_info = await client.account(AccountAddress.from_str(keyless_address))
        print(f"Account exists with sequence: {keyless_info.get('sequence_number')}")
    except Exception as e:
        print(f"Account doesn't exist yet (will be created on first transfer)")
    
    # Transfer APT using aptos_account::transfer
    print(f"\nTransferring {amount_apt} APT...")
    try:
        # Create transaction arguments
        tx_args = [
            TransactionArgument(AccountAddress.from_str(keyless_address), lambda s, v: v.serialize(s)),
            TransactionArgument(amount_octas, lambda s, v: s.u64(v))
        ]
        
        # Create entry function for APT transfer
        entry_function = EntryFunction.natural(
            module="0x1::aptos_account",
            function="transfer",
            ty_args=[],
            args=tx_args
        )
        
        # Get current sequence number
        account_info = await client.account(sponsor_account.address())
        sequence_number = int(account_info.get('sequence_number', 0))
        
        # Submit transaction
        signed_txn = await client.create_bcs_signed_transaction(
            sender=sponsor_account,
            payload=TransactionPayload(entry_function)
        )
        
        tx_hash = await client.submit_bcs_transaction(signed_txn)
        print(f"✅ Transaction submitted!")
        print(f"   Hash: {tx_hash}")
        
        # Wait for transaction
        print(f"\nWaiting for transaction...")
        try:
            await client.wait_for_transaction(tx_hash)
            print(f"✅ Transaction confirmed!")
        except Exception as e:
            print(f"Warning: Could not wait for transaction: {e}")
            print(f"Check transaction status at: https://explorer.aptoslabs.com/txn/{tx_hash}?network=testnet")
        
        # Check new balance by looking at resources
        print(f"\nChecking new balance...")
        try:
            resources = await client.account_resources(AccountAddress.from_str(keyless_address))
            for resource in resources:
                if resource['type'] == '0x1::coin::CoinStore<0x1::aptos_coin::AptosCoin>':
                    balance = int(resource['data']['coin']['value'])
                    print(f"✅ Keyless account balance: {balance / 1e8} APT")
                    break
        except Exception as e:
            print(f"Could not check balance: {e}")
        
        print(f"\n🎉 Successfully funded keyless account!")
        print(f"   Address: {keyless_address}")
        print(f"   View on explorer: https://explorer.aptoslabs.com/account/{keyless_address}?network=testnet")
        
    except Exception as e:
        print(f"❌ Transfer failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(fund_keyless_account())