#!/usr/bin/env python3
"""
Test sponsored transaction using the official SDK pattern from aptos-ts-sdk examples
"""

import asyncio
import httpx
import json
import base64
import os
import sys
import django
from decimal import Decimal

# Setup Django
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from aptos_sdk.account import Account
from aptos_sdk.async_client import RestClient
from aptos_sdk.transactions import (
    TransactionArgument,
    EntryFunction,
    TransactionPayload,
    RawTransaction,
    FeePayerRawTransaction,
    SignedTransaction
)
from aptos_sdk.authenticator import (
    Authenticator,
    Ed25519Authenticator,
    FeePayerAuthenticator
)
from aptos_sdk.bcs import Serializer


async def test_sdk_pattern_sponsored():
    """Test sponsored transaction using SDK pattern"""
    
    print("🧪 Testing Sponsored Transaction with Official SDK Pattern")
    print("=" * 70)
    
    # Initialize Aptos client
    aptos_client = RestClient("https://fullnode.testnet.aptoslabs.com/v1")
    
    # Create test accounts
    sender = Account.generate()
    sponsor = Account.load_key(os.environ.get('APTOS_SPONSOR_PRIVATE_KEY'))
    
    print(f"👤 Sender: {sender.address()}")
    print(f"💰 Sponsor: {sponsor.address()}")
    
    # Fund the sender account (normally would have CONFIO tokens)
    print("\n💵 Funding sender account...")
    # Use the faucet endpoint directly
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://faucet.testnet.aptoslabs.com/mint",
            params={
                "address": str(sender.address()),
                "amount": 100_000_000
            }
        )
        if response.status_code == 200:
            print("✅ Account funded")
    
    recipient = "0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36"
    amount = 1_000_000  # 0.01 APT for testing
    
    print(f"\n📤 Transfer details:")
    print(f"   From: {sender.address()}")
    print(f"   To: {recipient}")
    print(f"   Amount: {amount / 100_000_000} APT")
    
    try:
        # Build the raw transaction
        print("\n🔨 Building transaction...")
        
        # Get sender's sequence number
        sender_info = await aptos_client.account(sender.address())
        sequence_number = int(sender_info.get("sequence_number", 0))
        
        # Create the transfer payload
        from aptos_sdk.account_address import AccountAddress
        payload = TransactionPayload(
            EntryFunction.natural(
                "0x1::aptos_account",
                "transfer",
                [],
                [
                    TransactionArgument(AccountAddress.from_str(recipient), Serializer.struct),
                    TransactionArgument(amount, Serializer.u64)
                ]
            )
        )
        
        # Build raw transaction
        raw_txn = RawTransaction(
            sender=sender.address(),
            sequence_number=sequence_number,
            payload=payload,
            max_gas_amount=100_000,
            gas_unit_price=100,
            expiration_timestamps_secs=int(asyncio.get_event_loop().time()) + 600,
            chain_id=2,  # Testnet
        )
        
        # Create fee payer transaction
        fee_payer_raw_txn = FeePayerRawTransaction(
            raw_txn,
            [],  # No secondary signers
            sponsor.address()
        )
        
        print("✅ Transaction built with fee payer")
        
        # Sender signs the transaction
        print("\n✍️ Signing transaction...")
        sender_signature = sender.sign(fee_payer_raw_txn.keyed())
        
        # Sponsor signs as fee payer
        sponsor_signature = sponsor.sign(fee_payer_raw_txn.keyed())
        
        print("✅ Both signatures created")
        
        # Create authenticators
        from aptos_sdk.authenticator import AccountAuthenticator
        sender_account_auth = AccountAuthenticator(
            Ed25519Authenticator(sender.public_key(), sender_signature)
        )
        
        sponsor_account_auth = AccountAuthenticator(
            Ed25519Authenticator(sponsor.public_key(), sponsor_signature)
        )
        
        # Create the complete authenticator
        fee_payer_auth = FeePayerAuthenticator(
            sender_account_auth,
            [],  # No secondary signers
            (sponsor.address(), sponsor_account_auth)  # fee_payer tuple
        )
        
        # Submit the transaction
        print("\n📡 Submitting sponsored transaction...")
        
        # Create signed transaction
        signed_txn = SignedTransaction(fee_payer_raw_txn, Authenticator(fee_payer_auth))
        
        # Serialize the complete signed transaction
        serializer = Serializer()
        signed_txn.serialize(serializer)
        signed_txn_bytes = bytes(serializer.output())
        
        # Submit via REST API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{aptos_client.base_url}/transactions",
                headers={
                    "Content-Type": "application/x.aptos.signed_transaction+bcs"
                },
                content=signed_txn_bytes
            )
            
            if response.status_code == 202:  # Accepted
                result = response.json()
                tx_hash = result.get('hash')
                print(f"✅ Transaction submitted: {tx_hash}")
                
                # Wait for confirmation
                await aptos_client.wait_for_transaction(tx_hash)
                final_tx = await aptos_client.transaction_by_hash(tx_hash)
                
                if final_tx.get('success'):
                    print(f"\n🎉 SPONSORED TRANSACTION SUCCESSFUL!")
                    print(f"💫 Transaction hash: {tx_hash}")
                    print(f"⛽ Gas used: {final_tx.get('gas_used')}")
                    print(f"💰 Gas paid by sponsor: {sponsor.address()}")
                else:
                    print(f"\n❌ Transaction failed: {final_tx.get('vm_status')}")
            else:
                print(f"\n❌ Submission failed: {response.status_code}")
                print(f"Response: {response.text}")
                
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_sdk_pattern_sponsored())