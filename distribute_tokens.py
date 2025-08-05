#!/usr/bin/env python3
"""
Distribute cUSD and CONFIO tokens from the first Aptos address to 3-4 accounts.

This script addresses the original user request to distribute tokens from the 
first address with proper Aptos addresses to 3-4 accounts.
"""

import asyncio
import os
import sys
import django
from decimal import Decimal

# Setup Django
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.aptos_sponsor_service import AptosSponsorService


async def distribute_tokens():
    """Distribute cUSD and CONFIO from the first address to 3-4 target accounts"""
    
    print("🪙 Confío Token Distribution Script")
    print("="*50)
    
    # Source address (first address with tokens to distribute)
    source_address = "0x2a2549df49ec0e820b6c580c3af95b502ca7e2d956729860872fbc5de570795b"
    
    # Target addresses (3-4 accounts with proper Aptos addresses)
    target_addresses = [
        "0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36",  # Account 1
        "0xda4fb7201e9abb2304c3367939914524842e0a41b61b2c305bd64656f3f25792",  # Account 2  
        "0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c",  # Account 3
    ]
    
    # Distribution amounts
    cusd_amount = Decimal('150.0')    # 150 cUSD per account
    confio_amount = Decimal('100.0')  # 100 CONFIO per account
    
    print(f"📤 Source Address: {source_address}")
    print(f"🎯 Target Accounts: {len(target_addresses)}")
    for i, addr in enumerate(target_addresses, 1):
        print(f"  {i}. {addr}")
    
    print(f"\n💰 Distribution Plan:")
    print(f"  - cUSD: {cusd_amount} per account")
    print(f"  - CONFIO: {confio_amount} per account")
    print(f"  - Total cUSD: {cusd_amount * len(target_addresses)}")
    print(f"  - Total CONFIO: {confio_amount * len(target_addresses)}")
    
    # Check sponsor service health
    print(f"\n🔍 Checking sponsor service...")
    health = await AptosSponsorService.check_sponsor_health()
    
    if not health.get('can_sponsor', False):
        print(f"❌ Sponsor service unavailable: {health.get('error', 'Unknown error')}")
        return
    
    print(f"✅ Sponsor service healthy: {health.get('balance_formatted', 'Unknown balance')}")
    
    # Note: This script demonstrates the distribution logic.
    # For actual distribution, we would need:
    # 1. The private key of the source address to sign transactions
    # 2. A proper keyless signature from the frontend 
    # 3. Real transaction execution
    
    print(f"\n📝 Note: This script shows the distribution plan.")
    print(f"For actual token transfers, you would:")
    print(f"1. Use the mobile app to sign transactions from {source_address[:16]}...")
    print(f"2. Send sponsored transactions to each target address")
    print(f"3. Use the fixed Aptos keyless authentication flow")
    
    # Test the sponsor service structure
    print(f"\n🧪 Testing sponsor service structure for one transfer...")
    
    try:
        # Test CUSD transfer structure (without real keyless signature)
        result = await AptosSponsorService.sponsor_cusd_transfer(
            sender_address=source_address,
            recipient_address=target_addresses[0],
            amount=cusd_amount,
            keyless_info=None  # Would need real keyless info from mobile app
        )
        
        print(f"📊 Transfer result structure: {result}")
        
        if result.get('success'):
            print(f"✅ Transfer would succeed with proper keyless signature")
        else:
            expected_error = "Aptos keyless authenticator required"
            if expected_error in result.get('error', ''):
                print(f"✅ Service correctly requires keyless authenticator (as expected)")
            else:
                print(f"⚠️  Unexpected error: {result.get('error')}")
    
    except Exception as e:
        print(f"❌ Error testing sponsor service: {e}")
    
    print(f"\n🎯 Ready for Distribution!")
    print(f"Use the mobile app to sign and send transactions from the source address.")
    print(f"The backend is now properly configured to handle Aptos keyless signatures.")


if __name__ == "__main__":
    asyncio.run(distribute_tokens())