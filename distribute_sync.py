#!/usr/bin/env python3
"""
Distribute tokens directly from sponsor account - synchronous version
"""

import os
import sys
import django
from decimal import Decimal

# Setup Django
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import Account as UserAccount


def distribute_tokens_sync():
    """Distribute cUSD and CONFIO tokens directly from sponsor to user accounts"""
    
    print("🪙 Direct Token Distribution (Synchronous)")
    print("=" * 60)
    
    # Check if sponsor account has tokens to distribute
    sponsor_private_key = os.getenv('APTOS_SPONSOR_PRIVATE_KEY')
    if not sponsor_private_key:
        print("❌ APTOS_SPONSOR_PRIVATE_KEY not set")
        return
    
    print(f"✅ Found sponsor private key: {sponsor_private_key[:20]}...")
    
    # Get target accounts from database with proper relation loading
    target_accounts = list(UserAccount.objects.select_related('user').filter(account_type='personal')[:4])
    
    if not target_accounts:
        print("❌ No personal accounts found in database")
        return
    
    print(f"🎯 Found {len(target_accounts)} target accounts:")
    for i, acc in enumerate(target_accounts, 1):
        print(f"  {i}. {acc.user.email}: {acc.aptos_address}")
    
    # Show distribution plan
    print(f"\n💰 Distribution plan:")
    print(f"  - cUSD: 150.0 per account")
    print(f"  - CONFIO: 100.0 per account")
    print(f"  - Target addresses ready for distribution")
    
    # Now we can create targeted transfers for each account
    # Let's start with a simple approach - use the existing Django management command
    
    print(f"\n🚀 Recommended next steps:")
    print(f"1. Use the sponsor account to transfer tokens to each target account")
    print(f"2. The sponsor account has private key and should have token balances")
    print(f"3. Create direct transfers bypassing the keyless authentication complexity")
    
    print(f"\n📝 Target addresses for manual distribution:")
    for i, acc in enumerate(target_accounts, 1):
        print(f"{i}. {acc.aptos_address}  # {acc.user.email}")
    
    return target_accounts


if __name__ == "__main__":
    distribute_tokens_sync()