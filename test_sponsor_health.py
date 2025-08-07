#!/usr/bin/env python
"""
Test if the sponsor service is properly configured and available
"""

import os
import sys

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Load environment variables before importing Django
from decouple import config
print(f"Environment ALGORAND_SPONSOR_ADDRESS: {config('ALGORAND_SPONSOR_ADDRESS', default='NOT_SET')}")

import django
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service
from django.conf import settings
import asyncio

async def test_sponsor_health():
    """Test sponsor service health"""
    print("Testing sponsor service health...")
    
    # Check Django settings
    print(f"Django settings ALGORAND_SPONSOR_ADDRESS: {getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', 'NOT_SET')}")
    print(f"Django settings BLOCKCHAIN_CONFIG: {getattr(settings, 'BLOCKCHAIN_CONFIG', {}).get('ALGORAND_SPONSOR_ADDRESS', 'NOT_SET')}")
    
    # Check configuration
    print(f"Sponsor address from service: {algorand_sponsor_service.sponsor_address}")
    
    # Check health
    health = await algorand_sponsor_service.check_sponsor_health()
    
    print(f"Health check result:")
    print(f"  Can sponsor: {health.get('can_sponsor', False)}")
    print(f"  Balance: {health.get('balance', 0)} ALGO")
    print(f"  Healthy: {health.get('healthy', False)}")
    
    if 'error' in health:
        print(f"  Error: {health['error']}")
    
    if 'warning' in health:
        print(f"  Warning: {health.get('warning', '')}")
        print(f"  Recommendations: {health.get('recommendations', [])}")
    
    return health

if __name__ == "__main__":
    result = asyncio.run(test_sponsor_health())
    
    if result.get('can_sponsor'):
        print("\n✅ Sponsor service is ready!")
    else:
        print("\n❌ Sponsor service is not available")
        sys.exit(1)