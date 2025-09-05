#!/usr/bin/env python3
"""
Simple test for auto opt-in functionality without database access.
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

async def test_auto_optin():
    """Test auto opt-in for a specific user address"""
    logger.info("Testing auto opt-in functionality...")
    
    # Test address from previous logs - the user who was supposed to get auto opt-in
    test_address = "FH2J7K6LYYKMTKYAT6WNANMM7DRXCY2DASTCRVNJBBT6O3N4UPQ2CJZFZM"
    confio_asset_id = 3198329568  # From .env file
    
    logger.info(f"Testing auto opt-in for address: {test_address[:10]}...")
    logger.info(f"CONFIO Asset ID: {confio_asset_id}")
    
    try:
        # Check current opt-in status first
        account_info = algorand_sponsor_service.algod.account_info(test_address)
        current_assets = [asset['asset-id'] for asset in account_info.get('assets', [])]
        logger.info(f"Currently opted into assets: {current_assets}")
        
        if confio_asset_id in current_assets:
            logger.info(f"✅ User is already opted into CONFIO (Asset ID: {confio_asset_id})")
        else:
            logger.info(f"❌ User is NOT opted into CONFIO - this is the issue we're fixing")
        
        # Test the execute_server_side_opt_in method
        logger.info("Testing server-side opt-in method...")
        result = await algorand_sponsor_service.execute_server_side_opt_in(
            user_address=test_address,
            asset_id=confio_asset_id
        )
        
        logger.info("=== EXECUTE SERVER-SIDE OPT-IN RESULT ===")
        logger.info(f"Success: {result.get('success')}")
        logger.info(f"Already opted in: {result.get('already_opted_in')}")
        logger.info(f"Requires user signature: {result.get('requires_user_signature')}")
        logger.info(f"Error: {result.get('error')}")
        logger.info(f"Asset ID: {result.get('asset_id')}")
        
        if result.get('success'):
            if result.get('already_opted_in'):
                logger.info("✅ User was already opted in (that's good!)")
                return True
            elif result.get('requires_user_signature'):
                logger.info("✅ Sponsor service created opt-in transaction for user to sign")
                logger.info("This is expected behavior for Web3Auth users")
                return True
            else:
                logger.info("✅ Server-side opt-in completed successfully")
                return True
        else:
            logger.error(f"❌ Server-side opt-in failed: {result.get('error')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    result = asyncio.run(test_auto_optin())
    if result:
        logger.info("🎉 Auto opt-in test passed!")
    else:
        logger.error("💥 Auto opt-in test failed!")