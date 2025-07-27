#!/usr/bin/env python
import os
import sys
import django
from datetime import datetime, timedelta
from decimal import Decimal
import random

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from send.models import SendTransaction
from users.models import Account, Business

User = get_user_model()

def create_deposit_transactions():
    """Create deposit transactions for cUSD and CONFIO from external wallets"""
    
    # Get specific users that can be accessed via zkLogin
    real_users = [
        'julian',  # ID: 6
        'julianmoonluna',  # ID: 8
        '3db2c9a11e2c156',  # ID: 9 (has business account)
    ]
    
    users_to_populate = []
    for username in real_users:
        user = User.objects.filter(username=username).first()
        if user:
            users_to_populate.append(user)
            print(f"Found user: {user.username} (ID: {user.id})")
    
    # Also get users with business accounts
    business_accounts = Account.objects.filter(
        account_type='business', 
        business__isnull=False
    ).select_related('user', 'business')[:3]
    
    for account in business_accounts:
        if account.user not in users_to_populate:
            users_to_populate.append(account.user)
            print(f"Found user with business: {account.user.username} - {account.business.name}")
    
    if not users_to_populate:
        print("No suitable users found!")
        return
    
    # External wallet addresses (simulating deposits from exchanges/other wallets)
    external_wallets = [
        "0x1234567890abcdef1234567890abcdef12345678",
        "0xabcdef1234567890abcdef1234567890abcdef12",
        "0x9876543210fedcba9876543210fedcba98765432",
        "0xfedcba9876543210fedcba9876543210fedcba98",
        "0x1111222233334444555566667777888899990000",
    ]
    
    # Create deposits for each user
    created_count = 0
    for user in users_to_populate:
        print(f"\nCreating deposits for user: {user.username} (ID: {user.id})")
        
        # Get user's personal account
        personal_account = user.accounts.filter(account_type='personal', account_index=0).first()
        if not personal_account:
            print(f"  No personal account found for user {user.username}")
            continue
        
        # Create cUSD deposits
        for i in range(3):  # 3 cUSD deposits per user
            days_ago = random.randint(1, 30)
            amount = Decimal(random.choice([100, 250, 500, 1000, 2500]))
            
            # Create the deposit - note: sender_user is required but we're marking it as external
            deposit = SendTransaction()
            deposit.sender_user = user  # Required field
            deposit.sender_type = 'external'
            deposit.sender_display_name = 'External Wallet'
            deposit.sender_address = random.choice(external_wallets)
            
            deposit.recipient_user = user
            deposit.recipient_type = 'user'
            deposit.recipient_display_name = f"{user.first_name} {user.last_name}".strip() or user.username
            deposit.recipient_address = personal_account.sui_address or ''
            
            deposit.amount = str(amount)
            deposit.token_type = 'cUSD'
            deposit.memo = f'Depósito desde billetera externa'
            deposit.transaction_hash = f"0x{''.join(random.choices('abcdef0123456789', k=64))}"
            deposit.status = 'CONFIRMED'
            
            # Save and then update timestamps
            deposit.save()
            
            # Update timestamps manually
            SendTransaction.objects.filter(pk=deposit.pk).update(
                created_at=datetime.now() - timedelta(days=days_ago),
                updated_at=datetime.now() - timedelta(days=days_ago)
            )
            
            created_count += 1
            print(f"  Created cUSD deposit: {amount} cUSD from {deposit.sender_address[:10]}...")
        
        # Create CONFIO deposits
        for i in range(2):  # 2 CONFIO deposits per user
            days_ago = random.randint(1, 20)
            amount = Decimal(random.choice([50, 100, 200, 500]))
            
            deposit = SendTransaction()
            deposit.sender_user = user  # Required field
            deposit.sender_type = 'external'
            deposit.sender_display_name = 'External Wallet'
            deposit.sender_address = random.choice(external_wallets)
            
            deposit.recipient_user = user
            deposit.recipient_type = 'user'
            deposit.recipient_display_name = f"{user.first_name} {user.last_name}".strip() or user.username
            deposit.recipient_address = personal_account.sui_address or ''
            
            deposit.amount = str(amount)
            deposit.token_type = 'CONFIO'
            deposit.memo = f'Depósito desde billetera externa'
            deposit.transaction_hash = f"0x{''.join(random.choices('abcdef0123456789', k=64))}"
            deposit.status = 'CONFIRMED'
            
            deposit.save()
            
            # Update timestamps manually
            SendTransaction.objects.filter(pk=deposit.pk).update(
                created_at=datetime.now() - timedelta(days=days_ago),
                updated_at=datetime.now() - timedelta(days=days_ago)
            )
            
            created_count += 1
            print(f"  Created CONFIO deposit: {amount} CONFIO from {deposit.sender_address[:10]}...")
        
        # Also create some deposits for business accounts if they exist
        business_account = user.accounts.filter(account_type='business', business__isnull=False).first()
        if business_account:
            print(f"  Creating deposits for business: {business_account.business.name}")
            
            # Create a few business deposits
            for i in range(2):
                days_ago = random.randint(1, 15)
                amount = Decimal(random.choice([500, 1000, 2000, 5000]))
                token = random.choice(['cUSD', 'CONFIO'])
                
                deposit = SendTransaction()
                deposit.sender_user = user  # Required field
                deposit.sender_type = 'external'
                deposit.sender_display_name = 'External Business Wallet'
                deposit.sender_address = random.choice(external_wallets)
                
                deposit.recipient_user = user
                deposit.recipient_business = business_account.business
                deposit.recipient_type = 'business'
                deposit.recipient_display_name = business_account.business.name
                deposit.recipient_address = business_account.sui_address or ''
                
                deposit.amount = str(amount)
                deposit.token_type = token
                deposit.memo = f'Depósito empresarial desde billetera externa'
                deposit.transaction_hash = f"0x{''.join(random.choices('abcdef0123456789', k=64))}"
                deposit.status = 'CONFIRMED'
                
                deposit.save()
                
                # Update timestamps manually
                SendTransaction.objects.filter(pk=deposit.pk).update(
                    created_at=datetime.now() - timedelta(days=days_ago),
                    updated_at=datetime.now() - timedelta(days=days_ago)
                )
                
                created_count += 1
                print(f"    Created business deposit: {amount} {token}")
    
    print(f"\n✅ Created {created_count} deposit transactions successfully!")
    
    # Show summary
    print("\n📊 Summary of deposits created:")
    cusd_deposits = SendTransaction.objects.filter(
        sender_type='external',
        token_type='cUSD',
        created_at__gte=datetime.now() - timedelta(days=30)
    ).count()
    confio_deposits = SendTransaction.objects.filter(
        sender_type='external',
        token_type='CONFIO',
        created_at__gte=datetime.now() - timedelta(days=30)
    ).count()
    print(f"  - cUSD deposits: {cusd_deposits}")
    print(f"  - CONFIO deposits: {confio_deposits}")

if __name__ == "__main__":
    create_deposit_transactions()