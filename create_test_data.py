#!/usr/bin/env python
"""Create test transactions for development"""

import os
import sys
import django
from decimal import Decimal
from datetime import datetime, timedelta
import random

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone
from users.models import Account, Business
from send.models import SendTransaction
from payments.models import Invoice, PaymentTransaction

User = get_user_model()

def create_test_data():
    # Get or create test users
    user1, _ = User.objects.get_or_create(
        username='test_user_1',
        defaults={
            'email': 'user1@test.com',
            'first_name': 'Juan',
            'last_name': 'Pérez',
            'phone_country': '58',
            'phone_number': '4241234567',
            'firebase_uid': 'test_firebase_uid_1'
        }
    )
    
    user2, _ = User.objects.get_or_create(
        username='test_user_2',
        defaults={
            'email': 'user2@test.com',
            'first_name': 'María',
            'last_name': 'González',
            'phone_country': '58',
            'phone_number': '4149876543',
            'firebase_uid': 'test_firebase_uid_2'
        }
    )
    
    # Create accounts with Sui addresses
    account1, _ = Account.objects.get_or_create(
        user=user1,
        account_type='personal',
        account_index=0,
        defaults={
            'sui_address': '0x984e1ced3883fbd8b1867b0b68b92a223cde7a0f7470b71e260adb39ff1d827e'
        }
    )
    
    account2, _ = Account.objects.get_or_create(
        user=user2,
        account_type='personal',
        account_index=0,
        defaults={
            'sui_address': '0x123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0'
        }
    )
    
    # Create a business for user2
    business, _ = Business.objects.get_or_create(
        name='Arepera La Esquina',
        defaults={
            'category': 'food',
            'description': 'Las mejores arepas de la ciudad',
            'address': 'Av. Principal, Local 5'
        }
    )
    
    # Create business account for user2
    business_account, _ = Account.objects.get_or_create(
        user=user2,
        account_type='business',
        account_index=0,
        defaults={
            'sui_address': '0xbusiness123456789abcdef0123456789abcdef0123456789abcdef01234567',
            'business': business
        }
    )
    
    print(f"Created users: {user1.username}, {user2.username}")
    print(f"Created business: {business.name}")
    
    # Create send transactions
    send_transactions = []
    
    # Transaction 1: user1 sends to user2 (personal)
    tx1 = SendTransaction.objects.create(
        sender_user=user1,
        recipient_user=user2,
        sender_type='user',
        recipient_type='user',
        sender_display_name=f"{user1.first_name} {user1.last_name}",
        recipient_display_name=f"{user2.first_name} {user2.last_name}",
        sender_phone=f"{user1.phone_country}{user1.phone_number}",
        recipient_phone=f"{user2.phone_country}{user2.phone_number}",
        sender_address=account1.sui_address,
        recipient_address=account2.sui_address,
        amount='50.00',
        token_type='cUSD',
        memo='Para el almuerzo',
        status='CONFIRMED',
        transaction_hash=f'test_send_tx_1_{int(timezone.now().timestamp())}',
        created_at=timezone.now() - timedelta(hours=2)
    )
    send_transactions.append(tx1)
    
    # Transaction 2: user2 sends back to user1
    tx2 = SendTransaction.objects.create(
        sender_user=user2,
        recipient_user=user1,
        sender_type='user',
        recipient_type='user',
        sender_display_name=f"{user2.first_name} {user2.last_name}",
        recipient_display_name=f"{user1.first_name} {user1.last_name}",
        sender_phone=f"{user2.phone_country}{user2.phone_number}",
        recipient_phone=f"{user1.phone_country}{user1.phone_number}",
        sender_address=account2.sui_address,
        recipient_address=account1.sui_address,
        amount='25.50',
        token_type='cUSD',
        memo='Devuelto, gracias!',
        status='CONFIRMED',
        transaction_hash=f'test_send_tx_2_{int(timezone.now().timestamp())}',
        created_at=timezone.now() - timedelta(hours=1)
    )
    send_transactions.append(tx2)
    
    # Transaction 3: user1 sends to business
    tx3 = SendTransaction.objects.create(
        sender_user=user1,
        recipient_user=user2,
        sender_type='user',
        recipient_type='business',
        sender_display_name=f"{user1.first_name} {user1.last_name}",
        recipient_display_name=business.name,
        recipient_business=business,
        sender_phone=f"{user1.phone_country}{user1.phone_number}",
        recipient_phone='',  # Businesses don't have phone
        sender_address=account1.sui_address,
        recipient_address=business_account.sui_address,
        amount='15.00',
        token_type='cUSD',
        memo='Pago por arepas',
        status='CONFIRMED',
        transaction_hash=f'test_send_tx_3_{int(timezone.now().timestamp())}',
        created_at=timezone.now() - timedelta(minutes=30)
    )
    send_transactions.append(tx3)
    
    print(f"Created {len(send_transactions)} send transactions")
    
    # Create invoices and payment transactions
    invoices = []
    
    # Invoice 1: Business creates invoice
    invoice1 = Invoice.objects.create(
        created_by_user=user2,
        merchant_business=business,
        merchant_account=business_account,
        merchant_type='business',
        merchant_display_name=business.name,
        amount='20.00',
        token_type='cUSD',
        description='2 Arepas Reina Pepiada',
        status='PENDING',
        expires_at=timezone.now() + timedelta(hours=24)
    )
    invoices.append(invoice1)
    
    # Invoice 2: Already paid
    invoice2 = Invoice.objects.create(
        created_by_user=user2,
        merchant_business=business,
        merchant_account=business_account,
        merchant_type='business',
        merchant_display_name=business.name,
        amount='35.00',
        token_type='cUSD',
        description='Pedido familiar',
        status='PAID',
        expires_at=timezone.now() + timedelta(hours=12),
        paid_by_user=user1,
        paid_at=timezone.now() - timedelta(hours=3)
    )
    invoices.append(invoice2)
    
    # Create payment transaction for paid invoice
    payment_tx = PaymentTransaction.objects.create(
        payer_user=user1,
        payer_account=account1,
        merchant_account=business_account,
        merchant_business=business,
        merchant_account_user=user2,
        payer_type='user',
        merchant_type='business',
        payer_display_name=f"{user1.first_name} {user1.last_name}",
        merchant_display_name=business.name,
        payer_phone=f"{user1.phone_country}{user1.phone_number}",
        payer_address=account1.sui_address,
        merchant_address=business_account.sui_address,
        amount=invoice2.amount,
        token_type=invoice2.token_type,
        description=invoice2.description,
        status='CONFIRMED',
        invoice=invoice2,
        transaction_hash=f'test_pay_tx_1_{int(timezone.now().timestamp())}',
        created_at=invoice2.paid_at
    )
    
    print(f"Created {len(invoices)} invoices")
    print(f"Created 1 payment transaction")
    
    # Add some CONFIO token transactions
    tx4 = SendTransaction.objects.create(
        sender_user=user1,
        recipient_user=user2,
        sender_type='user',
        recipient_type='user',
        sender_display_name=f"{user1.first_name} {user1.last_name}",
        recipient_display_name=f"{user2.first_name} {user2.last_name}",
        sender_phone=f"{user1.phone_country}{user1.phone_number}",
        recipient_phone=f"{user2.phone_country}{user2.phone_number}",
        sender_address=account1.sui_address,
        recipient_address=account2.sui_address,
        amount='100.00',
        token_type='CONFIO',
        memo='Tokens CONFIO',
        status='CONFIRMED',
        transaction_hash=f'test_send_tx_4_{int(timezone.now().timestamp())}',
        created_at=timezone.now() - timedelta(days=1)
    )
    
    print("\nTest data created successfully!")
    print(f"You can now see transactions for user: {user1.username}")
    print(f"Account address: {account1.sui_address}")

if __name__ == '__main__':
    create_test_data()