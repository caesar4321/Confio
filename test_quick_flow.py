#!/usr/bin/env python3
"""
Quick test with timeouts
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

async def quick_test():
    """Quick test with just health check"""
    
    try:
        # Check sponsor health only
        print("Checking sponsor health...")
        health = await asyncio.wait_for(
            SponsorServicePySui.check_sponsor_health(),
            timeout=5.0
        )
        print(f"Sponsor healthy: {health['healthy']}")
        print(f"Sponsor balance: {health['balance']} SUI")
        
        # Test sponsor keypair
        print("\nTesting sponsor keypair...")
        keypair = SponsorServicePySui._get_sponsor_keypair()
        if keypair:
            print("Keypair loaded successfully")
            print(f"Keypair type: {type(keypair)}")
        else:
            print("ERROR: Failed to load keypair")
            
    except asyncio.TimeoutError:
        print("ERROR: Operation timed out")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(quick_test())