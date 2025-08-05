#!/usr/bin/env python3
"""
Mint new cUSD tokens and send to specified address
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

async def mint_and_send_cusd():
    """Mint new cUSD tokens and send to specified address"""
    
    # Initialize client for testnet
    client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
    
    # Get sponsor account details
    sponsor_address = settings.APTOS_SPONSOR_ADDRESS
    sponsor_private_key = os.environ.get('APTOS_SPONSOR_PRIVATE_KEY')
    
    if not sponsor_private_key:
        print("ERROR: APTOS_SPONSOR_PRIVATE_KEY environment variable not set!")
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
    
    # Target address and amount
    target_address = "0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c"
    amount = "200"  # 200 cUSD tokens
    amount_units = int(Decimal(amount) * Decimal(10**6))  # 6 decimals
    
    print(f"Target address: {target_address}")
    print(f"Amount to mint and send: {amount} cUSD ({amount_units} units)")
    
    # Token contract module
    cusd_module = "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::cusd"
    
    print("\n--- Minting and transferring cUSD tokens directly ---")
    try:
        # Create transaction arguments for mint_and_transfer
        # Function signature: mint_and_transfer(&signer, u64, address, address)
        # Parameters: amount, from_address, to_address
        tx_args = [
            TransactionArgument(amount_units, lambda s, v: s.u64(v)),
            TransactionArgument(AccountAddress.from_str(sponsor_address), lambda s, v: v.serialize(s)),
            TransactionArgument(AccountAddress.from_str(target_address), lambda s, v: v.serialize(s))
        ]
        
        # Create entry function for cUSD mint_and_transfer
        entry_function = EntryFunction.natural(
            module=cusd_module,
            function="mint_and_transfer",
            ty_args=[],
            args=tx_args
        )
        
        # Get current sequence number
        account_info = await client.account(sponsor_account.address())
        sequence_number = int(account_info.get('sequence_number', 0))
        print(f"Current sequence number: {sequence_number}")
        
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
        print(f"Mint and transfer transaction submitted: {tx_hash}")
        
        # Wait for confirmation
        await client.wait_for_transaction(tx_hash)
        print(f"✅ Successfully minted and sent {amount} cUSD to {target_address[:16]}...!")
        
    except Exception as e:
        print(f"❌ Error minting and transferring cUSD: {e}")
    
    print(f"\n=== Summary ===")
    print(f"Minted and sent {amount} cUSD tokens to {target_address}")
    print(f"The address should now have both cUSD and CONFIO tokens!")
    
    # Close client
    await client.close()


if __name__ == "__main__":
    asyncio.run(mint_and_send_cusd())