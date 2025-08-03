#!/usr/bin/env python3
"""
Distribute cUSD to test accounts for testing the send feature
"""

import os
import sys
import django

# Setup Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import Account
from blockchain.models import Balance
from decimal import Decimal
import django.db.models

def distribute_cusd():
    """Distribute 100 cUSD to each test account in the database"""
    
    # Get all accounts (not soft-deleted)
    accounts = Account.objects.filter(deleted_at__isnull=True)
    
    print(f"Found {accounts.count()} accounts")
    
    for account in accounts:
        # Check if account has cUSD balance
        cusd_balance, created = Balance.objects.get_or_create(
            account=account,
            token='CUSD',
            defaults={'amount': Decimal('0')}
        )
        
        if created or cusd_balance.amount == 0:
            # Give 100 cUSD
            cusd_balance.amount = Decimal('100.000000')
            cusd_balance.save()
            print(f"✓ Gave 100 cUSD to {account.account_id} (User: {account.user.username})")
        else:
            print(f"- Account {account.account_id} already has {cusd_balance.amount} cUSD")
    
    # Show summary
    print("\nSummary:")
    total_cusd = Balance.objects.filter(token='CUSD').aggregate(
        total=django.db.models.Sum('amount')
    )['total'] or 0
    print(f"Total cUSD in database: {total_cusd}")
    
    # Show accounts with Sui addresses
    accounts_with_sui = accounts.exclude(sui_address__isnull=True).exclude(sui_address='')
    print(f"\nAccounts with Sui addresses: {accounts_with_sui.count()}")
    for account in accounts_with_sui:
        cusd_balance = Balance.objects.filter(account=account, token='CUSD').first()
        balance = cusd_balance.amount if cusd_balance else 0
        print(f"  - {account.account_id}: {account.sui_address[:16]}... (Balance: {balance} cUSD)")

if __name__ == "__main__":
    distribute_cusd()