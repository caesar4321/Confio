#!/usr/bin/env python3
"""
Test script to verify auto opt-in functionality works correctly.
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from users.models import Account
from blockchain.algorand_account_manager import AlgorandAccountManager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_auto_optin():
    """Test auto opt-in functionality"""
    User = get_user_model()
    
    # Find a user with an existing account (user ID 4 from logs)
    try:
        user = User.objects.get(id=4)
        logger.info(f"Testing with user: {user.email}")
        
        # Get their account
        account = Account.objects.filter(user=user, account_type='personal').first()
        if not account or not account.algorand_address:
            logger.error("User doesn't have an Algorand address")
            return
            
        algorand_address = account.algorand_address
        logger.info(f"Testing auto opt-in for address: {algorand_address}")
        
        # Test the AlgorandAccountManager.get_or_create_algorand_account method
        result = AlgorandAccountManager.get_or_create_algorand_account(user, algorand_address)
        
        logger.info("=== AUTO OPT-IN RESULT ===")
        logger.info(f"Account created: {result.get('created', False)}")
        logger.info(f"Opted in assets: {result.get('opted_in_assets', [])}")
        logger.info(f"Errors: {result.get('errors', [])}")
        
        if result.get('opted_in_assets'):
            logger.info("✅ AUTO OPT-IN WORKING!")
        else:
            logger.info("ℹ️ No new assets opted in (may already be opted in)")
            
    except User.DoesNotExist:
        logger.error("User not found")
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_auto_optin()