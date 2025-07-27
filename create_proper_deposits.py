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
from users.models import Account

User = get_user_model()

def create_proper_deposits():
    """Create proper external deposits for accessible users"""
    
    # External wallet sources
    external_sources = [
        ('Binance', '0xbinance1234567890abcdef1234567890abcdef12'),
        ('Coinbase', '0xcoinbase234567890abcdef1234567890abcdef12'),
        ('Kraken', '0xkraken34567890abcdef1234567890abcdef1234'),
        ('External Wallet', '0x1234567890abcdef1234567890abcdef12345678'),
        ('Hardware Wallet', '0xledger567890abcdef1234567890abcdef123456'),
    ]
    
    # Get accessible users
    users_data = [
        (6, 'julian'),  # Julian Moon
        (8, 'julianmoonluna'),  # Has business: Sabor de Chicha
        (9, '3db2c9a11e2c156'),  # Wonju Moon, has business: Salud de Julian
    ]
    
    created_count = 0
    
    for user_id, username in users_data:
        user = User.objects.get(id=user_id)
        print(f"\nCreating deposits for: {user.username} - {user.first_name} {user.last_name}")
        
        # Personal account deposits
        personal_account = user.accounts.filter(account_type='personal', account_index=0).first()
        if personal_account:
            # Create cUSD deposits
            for i in range(3):
                days_ago = random.randint(1, 30)
                amount = random.choice([100, 250, 500, 1000, 2500])
                source_name, source_address = random.choice(external_sources)
                
                deposit = SendTransaction.objects.create(
                    sender_user=None,  # NULL for external
                    sender_type='external',
                    sender_display_name=source_name,
                    sender_address=source_address,
                    
                    recipient_user=user,
                    recipient_type='user',
                    recipient_display_name=f"{user.first_name} {user.last_name}".strip() or user.username,
                    recipient_address=personal_account.sui_address or f"0x{user.id:064x}",
                    
                    amount=str(amount),
                    token_type='cUSD',
                    memo=f'Depósito desde {source_name}',
                    transaction_hash=f"0x{''.join(random.choices('abcdef0123456789', k=64))}",
                    status='CONFIRMED'
                )
                
                # Update timestamp
                SendTransaction.objects.filter(pk=deposit.pk).update(
                    created_at=datetime.now() - timedelta(days=days_ago)
                )
                
                created_count += 1
                print(f"  ✓ Personal: {amount} cUSD from {source_name} ({days_ago} days ago)")
            
            # Create CONFIO deposits
            for i in range(2):
                days_ago = random.randint(1, 20)
                amount = random.choice([50, 100, 200, 500])
                source_name, source_address = random.choice(external_sources)
                
                deposit = SendTransaction.objects.create(
                    sender_user=None,
                    sender_type='external',
                    sender_display_name=source_name,
                    sender_address=source_address,
                    
                    recipient_user=user,
                    recipient_type='user',
                    recipient_display_name=f"{user.first_name} {user.last_name}".strip() or user.username,
                    recipient_address=personal_account.sui_address or f"0x{user.id:064x}",
                    
                    amount=str(amount),
                    token_type='CONFIO',
                    memo=f'Depósito desde {source_name}',
                    transaction_hash=f"0x{''.join(random.choices('abcdef0123456789', k=64))}",
                    status='CONFIRMED'
                )
                
                SendTransaction.objects.filter(pk=deposit.pk).update(
                    created_at=datetime.now() - timedelta(days=days_ago)
                )
                
                created_count += 1
                print(f"  ✓ Personal: {amount} CONFIO from {source_name} ({days_ago} days ago)")
        
        # Business account deposits
        business_account = user.accounts.filter(account_type='business', business__isnull=False).first()
        if business_account:
            print(f"  Business: {business_account.business.name}")
            
            for i in range(2):
                days_ago = random.randint(1, 15)
                amount = random.choice([500, 1000, 2000, 5000])
                token = random.choice(['cUSD', 'CONFIO'])
                source_name = 'Corporate Treasury'
                source_address = '0xcorp567890abcdef1234567890abcdef12345678'
                
                deposit = SendTransaction.objects.create(
                    sender_user=None,
                    sender_type='external',
                    sender_display_name=source_name,
                    sender_address=source_address,
                    
                    recipient_user=user,
                    recipient_business=business_account.business,
                    recipient_type='business',
                    recipient_display_name=business_account.business.name,
                    recipient_address=business_account.sui_address or f"0x{user.id:064x}",
                    
                    amount=str(amount),
                    token_type=token,
                    memo=f'Depósito corporativo',
                    transaction_hash=f"0x{''.join(random.choices('abcdef0123456789', k=64))}",
                    status='CONFIRMED'
                )
                
                SendTransaction.objects.filter(pk=deposit.pk).update(
                    created_at=datetime.now() - timedelta(days=days_ago)
                )
                
                created_count += 1
                print(f"  ✓ Business: {amount} {token} from {source_name} ({days_ago} days ago)")
    
    print(f"\n✅ Created {created_count} deposits successfully!")
    
    # Summary
    print("\n📊 Summary:")
    total_external = SendTransaction.objects.filter(sender_type='external').count()
    print(f"Total external deposits: {total_external}")

if __name__ == "__main__":
    create_proper_deposits()