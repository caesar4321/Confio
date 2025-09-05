#!/usr/bin/env python3
"""
Test script to verify sponsor service authentication fix.
"""
import os
import django
import asyncio
import logging

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_sponsor_auth():
    """Test sponsor service can authenticate with Algorand node"""
    logger.info("Testing sponsor service authentication...")
    
    try:
        # Test basic health check - this will use algod client
        health = await algorand_sponsor_service.check_sponsor_health()
        
        logger.info("=== SPONSOR SERVICE HEALTH CHECK ===")
        logger.info(f"Healthy: {health.get('healthy')}")
        logger.info(f"Balance: {health.get('balance')}")
        logger.info(f"Can sponsor: {health.get('can_sponsor')}")
        logger.info(f"Error: {health.get('error')}")
        
        if health.get('healthy'):
            logger.info("✅ AUTHENTICATION FIX WORKING! Sponsor service can connect to Algorand")
            
            # Test if we can also check an account (this tests algod further)
            test_address = "PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY"
            logger.info(f"Testing account info retrieval for {test_address[:10]}...")
            
            try:
                account_info = algorand_sponsor_service.algod.account_info(test_address)
                balance = account_info.get('amount', 0) / 1_000_000
                logger.info(f"✅ Account lookup successful! Balance: {balance:.2f} ALGO")
                return True
            except Exception as e:
                logger.error(f"❌ Account lookup failed: {e}")
                return False
        else:
            logger.error("❌ AUTHENTICATION STILL FAILING")
            return False
            
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    result = asyncio.run(test_sponsor_auth())
    if result:
        logger.info("🎉 All tests passed! Authentication fix successful!")
    else:
        logger.error("💥 Tests failed! Authentication still has issues.")