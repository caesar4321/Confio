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

def add_salud_de_julian_deposits():
    """Add more deposits for Salud de Julian business account"""
    
    # Get Wonju Moon's business account
    wonju = User.objects.get(id=9)  # 3db2c9a11e2c156
    business_account = wonju.accounts.filter(
        account_type='business', 
        business__name='Salud de Julian'
    ).first()
    
    if not business_account:
        print("Salud de Julian business account not found!")
        return
    
    print(f"Adding deposits for: {business_account.business.name}")
    print(f"Business address: {business_account.aptos_address}")
    
    # External wallet addresses
    external_addresses = [
        "0x7890abcdef1234567890abcdef1234567890abcdef",
        "0xfedcba9876543210fedcba9876543210fedcba98",
        "0x5555666677778888999900001111222233334444",
        "0xaaabbbcccdddeeefff0001112223334445556667",
        "0x9999888877776666555544443333222211110000",
    ]
    
    created_count = 0
    
    # Create various deposits over the past 60 days
    for i in range(10):  # 10 more deposits
        days_ago = random.randint(1, 60)
        amount = random.choice([1000, 2000, 3000, 5000, 10000, 15000])
        token = random.choice(['cUSD', 'CONFIO'])
        
        deposit = SendTransaction.objects.create(
            sender_user=None,  # External deposit
            sender_type='external',
            sender_display_name=random.choice(external_addresses),
            sender_address=random.choice(external_addresses),
            
            recipient_user=wonju,
            recipient_business=business_account.business,
            recipient_type='business',
            recipient_display_name=business_account.business.name,
            recipient_address=business_account.aptos_address or f"0x{wonju.id:064x}",
            
            amount=str(amount),
            token_type=token,
            memo=f'Pago de servicios médicos',
            transaction_hash=f"0x{''.join(random.choices('abcdef0123456789', k=64))}",
            status='CONFIRMED'
        )
        
        # Update timestamp
        SendTransaction.objects.filter(pk=deposit.pk).update(
            created_at=datetime.now() - timedelta(days=days_ago)
        )
        
        created_count += 1
        print(f"  ✓ {amount} {token} from {deposit.sender_address[:10]}...{deposit.sender_address[-6:]} ({days_ago} days ago)")
    
    print(f"\n✅ Created {created_count} deposits for Salud de Julian")
    
    # Show summary
    total_business_deposits = SendTransaction.objects.filter(
        recipient_business__name='Salud de Julian',
        sender_type='external'
    ).count()
    
    print(f"\nTotal external deposits for Salud de Julian: {total_business_deposits}")

if __name__ == "__main__":
    add_salud_de_julian_deposits()