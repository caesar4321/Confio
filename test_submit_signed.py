#!/usr/bin/env python
"""
Test submitting signed transactions
"""

import os
import sys
import django
import asyncio
import base64

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service

async def test_submit():
    """Test submitting a signed transaction group"""
    
    # These are example base64 encoded signed transactions (won't actually work, just for testing)
    # In reality, these would come from the client after signing
    fake_signed_user = "gqNzaWfEQTestSignedUserTransactionDataHere"
    fake_signed_sponsor = "gqNzaWfEQTestSignedSponsorTransactionDataHere"
    
    print("Testing submit_sponsored_group...")
    
    try:
        result = await algorand_sponsor_service.submit_sponsored_group(
            signed_user_txn=fake_signed_user,
            signed_sponsor_txn=fake_signed_sponsor
        )
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_submit())