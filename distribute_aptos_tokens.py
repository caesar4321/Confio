#!/usr/bin/env python3
"""
Distribute cUSD and CONFIO tokens from sponsor address to selected accounts
"""
import asyncio
import os
import sys
from pathlib import Path
from decimal import Decimal
from aptos_sdk.async_client import RestClient
from aptos_sdk.account import Account
from aptos_sdk.transactions import EntryFunction, TransactionArgument, TransactionPayload
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.bcs import Serializer

# Setup Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.conf import settings
from users.models import Account as DjangoAccount

async def distribute_tokens():
    """Distribute cUSD and CONFIO tokens to selected accounts"""
    
    # Initialize client for testnet
    client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
    
    # Get sponsor account details
    sponsor_address = settings.APTOS_SPONSOR_ADDRESS
    sponsor_private_key = os.environ.get('APTOS_SPONSOR_PRIVATE_KEY')
    
    if not sponsor_private_key:
        print("ERROR: APTOS_SPONSOR_PRIVATE_KEY environment variable not set!")
        print("Please set it with: export APTOS_SPONSOR_PRIVATE_KEY='your_private_key_here'")
        await client.close()
        return
    
    print(f"Sponsor address: {sponsor_address}")
    
    # Load sponsor account
    try:
        sponsor_account = Account.load_key(sponsor_private_key)
        print(f"Loaded sponsor account: {sponsor_account.address()}")
    except Exception as e:
        print(f"Error loading sponsor account: {e}")
        await client.close()
        return
    
    # Get sponsor account info
    try:
        account_info = await client.account(sponsor_account.address())
        print(f"Sponsor sequence number: {account_info.get('sequence_number', 0)}")
    except Exception as e:
        print(f"Error getting sponsor account info: {e}")
    
    # Select recipient accounts (pick 3-4 accounts with Aptos addresses)
    recipients = [
        ("0xec536ec9495b8f5de7e05e6e987c582a96c14a8f387f0b907f07e956da19b44a", "100"),  # personal_0
        ("0xda4fb7201e9abb2304c3367939914524842e0a41b61b2c305bd64656f3f25792", "150"),  # business_0
        ("0x2b4efedb3d02b5ceeb8b63798c13f1cf616f1c41c0f0b1b36fc5f7b4c1adb7f9", "200"),  # personal_0
        ("0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c", "175"),  # requested address
    ]
    
    print(f"\nDistributing tokens to {len(recipients)} accounts...")
    
    # Token contract addresses
    cusd_module = "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::cusd"
    confio_module = "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::confio"
    
    for recipient_address, amount in recipients:
        print(f"\n--- Distributing to {recipient_address[:16]}... ---")
        
        # Convert amount to units (6 decimals)
        amount_units = int(Decimal(amount) * Decimal(10**6))
        print(f"Amount: {amount} tokens ({amount_units} units)")
        
        # Distribute cUSD
        print("Sending cUSD...")
        try:
            # Create transaction arguments
            tx_args = [
                TransactionArgument(AccountAddress.from_str(recipient_address), lambda s, v: v.serialize(s)),
                TransactionArgument(amount_units, lambda s, v: s.u64(v))
            ]
            
            # Create entry function for cUSD transfer
            entry_function = EntryFunction.natural(
                module=cusd_module,
                function="transfer_cusd",
                ty_args=[],
                args=tx_args
            )
            
            # Get current sequence number
            account_info = await client.account(sponsor_account.address())
            sequence_number = int(account_info.get('sequence_number', 0))
            
            # Create and submit transaction
            raw_txn = await client.create_bcs_transaction(
                sender=sponsor_account,
                payload=TransactionPayload(entry_function),
                sequence_number=sequence_number
            )
            
            # Sign transaction
            authenticator = sponsor_account.sign_transaction(raw_txn)
            from aptos_sdk.transactions import SignedTransaction
            signed_txn = SignedTransaction(raw_txn, authenticator)
            
            # Submit transaction
            tx_hash = await client.submit_bcs_transaction(signed_txn)
            print(f"cUSD transaction submitted: {tx_hash}")
            
            # Wait for confirmation
            await client.wait_for_transaction(tx_hash)
            print("cUSD transfer confirmed!")
            
        except Exception as e:
            print(f"Error sending cUSD: {e}")
        
        # Small delay between transactions
        await asyncio.sleep(1)
        
        # Distribute CONFIO
        print("Sending CONFIO...")
        try:
            # Create transaction arguments
            tx_args = [
                TransactionArgument(AccountAddress.from_str(recipient_address), lambda s, v: v.serialize(s)),
                TransactionArgument(amount_units, lambda s, v: s.u64(v))
            ]
            
            # Create entry function for CONFIO transfer
            entry_function = EntryFunction.natural(
                module=confio_module,
                function="transfer_confio",
                ty_args=[],
                args=tx_args
            )
            
            # Get current sequence number
            account_info = await client.account(sponsor_account.address())
            sequence_number = int(account_info.get('sequence_number', 0))
            
            # Create and submit transaction
            raw_txn = await client.create_bcs_transaction(
                sender=sponsor_account,
                payload=TransactionPayload(entry_function),
                sequence_number=sequence_number
            )
            
            # Sign transaction
            authenticator = sponsor_account.sign_transaction(raw_txn)
            from aptos_sdk.transactions import SignedTransaction
            signed_txn = SignedTransaction(raw_txn, authenticator)
            
            # Submit transaction
            tx_hash = await client.submit_bcs_transaction(signed_txn)
            print(f"CONFIO transaction submitted: {tx_hash}")
            
            # Wait for confirmation
            await client.wait_for_transaction(tx_hash)
            print("CONFIO transfer confirmed!")
            
        except Exception as e:
            print(f"Error sending CONFIO: {e}")
        
        # Small delay between recipients
        await asyncio.sleep(1)
    
    print("\n=== Distribution Complete ===")
    print(f"Distributed cUSD and CONFIO to {len(recipients)} accounts")
    
    # Close client
    await client.close()


if __name__ == "__main__":
    asyncio.run(distribute_tokens())