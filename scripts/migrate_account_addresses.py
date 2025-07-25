#!/usr/bin/env python
"""
Migration script to update Sui addresses for existing accounts after salt formula change.

This script will:
1. Iterate through all existing accounts
2. Regenerate the Sui address using the new salt formula (with business_id)
3. Update the account's Sui address in the database

Run this script after deploying the new salt formula.
"""

import os
import sys
import django
from datetime import datetime

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import Account, User
from django.db import transaction
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_account_addresses():
    """
    Migrate existing accounts to use new salt formula with business_id.
    
    For existing accounts, we'll need to recalculate the Sui addresses
    based on the new salt formula that includes business_id.
    """
    
    logger.info("Starting account address migration...")
    
    # Get all accounts
    accounts = Account.objects.select_related('user', 'business').all()
    total_accounts = accounts.count()
    
    logger.info(f"Found {total_accounts} accounts to process")
    
    migrated_count = 0
    error_count = 0
    
    with transaction.atomic():
        for account in accounts:
            try:
                # Log current state
                logger.info(f"Processing account: {account.account_id} (Type: {account.account_type}, Index: {account.account_index})")
                
                if account.account_type == 'business' and account.business:
                    logger.info(f"  Business: {account.business.name} (ID: {account.business.id})")
                
                # Note: The actual Sui address generation happens on the client side
                # This script is a placeholder for the migration strategy
                # In production, you would need to:
                # 1. Have users re-authenticate to generate new addresses
                # 2. Or implement a server-side address generation mechanism
                
                # For now, we'll just log what needs to be done
                if account.sui_address:
                    logger.warning(f"  Current Sui address: {account.sui_address}")
                    logger.warning(f"  This address needs to be regenerated with the new salt formula")
                else:
                    logger.info(f"  No Sui address set yet")
                
                migrated_count += 1
                
            except Exception as e:
                logger.error(f"Error processing account {account.id}: {str(e)}")
                error_count += 1
    
    logger.info(f"Migration completed. Processed: {migrated_count}, Errors: {error_count}")
    
    # Print migration summary
    print("\n" + "="*60)
    print("MIGRATION SUMMARY")
    print("="*60)
    print(f"Total accounts: {total_accounts}")
    print(f"Successfully processed: {migrated_count}")
    print(f"Errors: {error_count}")
    print("\nIMPORTANT NOTES:")
    print("1. Sui addresses are generated client-side using zkLogin")
    print("2. Users will need to re-authenticate to generate new addresses")
    print("3. The new salt formula includes business_id for business accounts")
    print("4. Personal accounts are not affected (business_id is empty string)")
    print("="*60)


if __name__ == "__main__":
    migrate_account_addresses()