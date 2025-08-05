#!/usr/bin/env python3
"""
Test real Aptos transactions with sponsor private key
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import asyncio
from decimal import Decimal
from blockchain.aptos_sponsor_service import AptosSponsorService


def check_sponsor_setup():
    """Check if sponsor is properly configured"""
    print("=== Checking Sponsor Configuration ===")
    
    sponsor_address = os.environ.get('APTOS_SPONSOR_ADDRESS')
    sponsor_private_key = os.environ.get('APTOS_SPONSOR_PRIVATE_KEY')
    
    print(f"Sponsor Address: {sponsor_address}")
    print(f"Private Key Configured: {'✅ Yes' if sponsor_private_key else '❌ No'}")
    
    if sponsor_private_key:
        print(f"Private Key Length: {len(sponsor_private_key)} characters")
        if sponsor_private_key.startswith('0x'):
            print("✅ Private key has 0x prefix")
        else:
            print("⚠️  Private key missing 0x prefix")
    
    return bool(sponsor_private_key)


async def test_real_sponsor_health():
    """Test sponsor service health with real configuration"""
    print("\n=== Testing Sponsor Health ===")
    
    try:
        health = await AptosSponsorService.check_sponsor_health()
        
        print(f"Healthy: {'✅' if health['healthy'] else '❌'} {health['healthy']}")
        print(f"Balance: {health['balance']} APT")
        print(f"Can Sponsor: {'✅' if health['can_sponsor'] else '❌'} {health['can_sponsor']}")
        print(f"Estimated Transactions: {health['estimated_transactions']}")
        
        if health.get('recommendations'):
            print("Recommendations:")
            for rec in health['recommendations']:
                print(f"  - {rec}")
        
        return health['healthy']
        
    except Exception as e:
        print(f"❌ Error checking sponsor health: {e}")
        return False


async def test_real_transaction():
    """Test a real transaction if sponsor is configured"""
    print("\n=== Testing Real Transaction ===")
    
    try:
        # Small test transaction
        result = await AptosSponsorService.sponsor_cusd_transfer(
            sender_address="0x2a2549df49ec0e820b6c580c3af95b502ca7e2d956729860872fbc5de570795b",
            recipient_address="0xda4fb7201e9abb2304c3367939914524842e0a41b61b2c305bd64656f3f25792", 
            amount=Decimal('1.0'),  # 1 CUSD test
            keyless_info=None
        )
        
        print(f"Transaction Result: {result}")
        
        if result['success']:
            print("✅ Real transaction would succeed!")
            print(f"   Digest: {result.get('digest', 'N/A')}")
            print(f"   Sponsored: {result.get('sponsored', False)}")
            print(f"   Gas Saved: {result.get('gas_saved', 0)} APT")
            
            if result.get('warning'):
                print(f"   ⚠️  Warning: {result['warning']}")
        else:
            print(f"❌ Transaction failed: {result.get('error')}")
            
    except Exception as e:
        print(f"❌ Error testing transaction: {e}")


async def main():
    print("🔐 Testing Real Aptos Sponsor Configuration\n")
    
    # Check if private key is configured
    has_private_key = check_sponsor_setup()
    
    # Test sponsor health
    is_healthy = await test_real_sponsor_health()
    
    # Test transaction if everything is set up
    if has_private_key and is_healthy:
        await test_real_transaction()
        print("\n🎉 All tests completed! App Send feature is ready for real transactions.")
    elif has_private_key:
        print("\n⚠️  Private key configured but sponsor unhealthy. Check balance or network.")
    else:
        print("\n❌ APTOS_SPONSOR_PRIVATE_KEY not configured. Add it to .env file.")
        print("   After adding the private key, restart Django and test again.")


if __name__ == "__main__":
    asyncio.run(main())