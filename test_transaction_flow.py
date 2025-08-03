#!/usr/bin/env python3
"""
Test the complete transaction flow
"""
import asyncio
import os
import sys
import django
from decimal import Decimal

# Setup Django
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.sponsor_service_pysui import SponsorServicePySui
from users.models import Account
from asgiref.sync import sync_to_async

async def test_transaction_flow():
    """Test the transaction flow without dry run"""
    
    try:
        # Check sponsor health first
        print("Checking sponsor health...")
        health = await SponsorServicePySui.check_sponsor_health()
        print(f"Sponsor healthy: {health['healthy']}")
        print(f"Sponsor balance: {health['balance']} SUI")
        print(f"Can sponsor: {health['can_sponsor']}")
        
        if not health['can_sponsor']:
            print("ERROR: Sponsor cannot sponsor transactions")
            return
        
        # Get a test account
        print("\nGetting test account...")
        account = await sync_to_async(lambda: Account.objects.filter(
            sui_address__isnull=False,
            sui_address__gt=''
        ).first())()
        
        if not account:
            print("ERROR: No account with Sui address found")
            return
            
        print(f"Using account: {account.id}")
        print(f"Sui address: {account.sui_address}")
        
        # Prepare a send transaction
        print("\nPreparing send transaction...")
        result = await SponsorServicePySui.prepare_send_transaction(
            account=account,
            recipient="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            amount=Decimal("0.01"),  # Small amount
            token_type="CUSD"
        )
        
        print(f"\nTransaction preparation result:")
        print(f"Success: {result.get('success')}")
        print(f"Requires user signature: {result.get('requiresUserSignature', False)}")
        
        if result.get('success'):
            print(f"TX Bytes length: {len(result.get('txBytes', ''))} chars")
            print(f"Sponsor signature: {result.get('sponsorSignature', '')[:50]}...")
            print(f"Message: {result.get('message', '')}")
        else:
            print(f"Error: {result.get('error')}")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_transaction_flow())