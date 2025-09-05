#!/usr/bin/env python3
"""
Comprehensive test for Algorand authentication across all components.
"""
import os
import django
import asyncio
import logging

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service
from blockchain.account_funding_service import AccountFundingService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_comprehensive_auth():
    """Test authentication across all key blockchain components"""
    logger.info("🔍 Testing comprehensive Algorand authentication...")
    
    all_tests_passed = True
    
    # Test 1: Sponsor Service Authentication
    logger.info("\n=== TEST 1: Sponsor Service ===")
    try:
        health = await algorand_sponsor_service.check_sponsor_health()
        if health.get('healthy'):
            logger.info("✅ Sponsor service authentication working")
            logger.info(f"   Balance: {health.get('balance_formatted')}")
        else:
            logger.error("❌ Sponsor service authentication failed")
            logger.error(f"   Error: {health.get('error')}")
            all_tests_passed = False
    except Exception as e:
        logger.error(f"❌ Sponsor service test failed: {e}")
        all_tests_passed = False
    
    # Test 2: Account Funding Service Authentication
    logger.info("\n=== TEST 2: Account Funding Service ===")
    try:
        funding_service = AccountFundingService()
        test_address = "PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY"
        funding_needed = funding_service.calculate_funding_needed(test_address, for_app_optin=False)
        logger.info("✅ Account funding service authentication working")
        logger.info(f"   Test calculation: {funding_needed} microAlgos needed")
    except Exception as e:
        logger.error(f"❌ Account funding service test failed: {e}")
        all_tests_passed = False
    
    # Test 3: Direct Algorand Client
    logger.info("\n=== TEST 3: Direct Algorand Client ===")
    try:
        from blockchain.algorand_client import get_algod_client
        algod_client = get_algod_client()
        test_address = "PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY"
        account_info = algod_client.account_info(test_address)
        balance = account_info.get('amount', 0) / 1_000_000
        assets = len(account_info.get('assets', []))
        logger.info("✅ Direct Algorand client authentication working")
        logger.info(f"   Test account balance: {balance:.2f} ALGO")
        logger.info(f"   Test account assets: {assets} opted in")
    except Exception as e:
        logger.error(f"❌ Direct Algorand client test failed: {e}")
        all_tests_passed = False
    
    # Test 4: Sponsored Opt-in Creation
    logger.info("\n=== TEST 4: Sponsored Opt-in Creation ===")
    try:
        test_address = "FH2J7K6LYYKMTKYAT6WNANMM7DRXCY2DASTCRVNJBBT6O3N4UPQ2CJZFZM"
        confio_asset_id = 3198329568
        result = await algorand_sponsor_service.execute_server_side_opt_in(
            user_address=test_address,
            asset_id=confio_asset_id
        )
        if result.get('success'):
            logger.info("✅ Sponsored opt-in creation working")
            logger.info(f"   Already opted in: {result.get('already_opted_in', False)}")
            logger.info(f"   Requires user signature: {result.get('requires_user_signature', False)}")
        else:
            logger.error("❌ Sponsored opt-in creation failed")
            logger.error(f"   Error: {result.get('error')}")
            all_tests_passed = False
    except Exception as e:
        logger.error(f"❌ Sponsored opt-in test failed: {e}")
        all_tests_passed = False
    
    # Summary
    logger.info("\n" + "="*50)
    if all_tests_passed:
        logger.info("🎉 ALL AUTHENTICATION TESTS PASSED!")
        logger.info("✅ Auto opt-in should now work correctly")
        return True
    else:
        logger.error("💥 SOME AUTHENTICATION TESTS FAILED!")
        logger.error("❌ Auto opt-in may still have issues")
        return False

if __name__ == '__main__':
    result = asyncio.run(test_comprehensive_auth())
    exit(0 if result else 1)