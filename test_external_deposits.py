#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from send.models import SendTransaction
from users.models import Account
from users.graphql_views import UnifiedTransaction

User = get_user_model()

# Test with Wonju Moon
wonju = User.objects.get(id=9)  # 3db2c9a11e2c156
print(f"Testing with user: {wonju.username} - {wonju.first_name} {wonju.last_name}")

# Get personal account
personal_account = wonju.accounts.filter(account_type='personal', account_index=0).first()
print(f"Personal account address: {personal_account.sui_address}")

# Create a test external deposit
deposit = SendTransaction.objects.create(
    sender_user=None,  # NULL for external
    sender_type='external',
    sender_display_name='Binance Wallet',
    sender_address='0xbinance1234567890abcdef1234567890abcdef12',
    
    recipient_user=wonju,
    recipient_type='user',
    recipient_display_name=f"{wonju.first_name} {wonju.last_name}",
    recipient_address=personal_account.sui_address,
    
    amount='1000',
    token_type='cUSD',
    memo='Test deposit from Binance',
    transaction_hash='0xtest123',
    status='CONFIRMED'
)
print(f"\nCreated test deposit: {deposit.amount} {deposit.token_type}")

# Test if it appears in unified transactions
# Personal account filter
personal_txs = UnifiedTransaction.objects.filter(
    counterparty_user=wonju,
    counterparty_business__isnull=True
)

print(f"\nTransactions for personal account: {personal_txs.count()}")

# Check if our deposit is there
external_deposits = personal_txs.filter(
    transaction_type='send',
    sender_type='external'
)
print(f"External deposits found: {external_deposits.count()}")

if external_deposits.exists():
    for dep in external_deposits[:3]:
        print(f"  - {dep.amount} {dep.token_type} from {dep.sender_display_name}")
        print(f"    Direction: {dep.get_direction_for_address(personal_account.sui_address)}")