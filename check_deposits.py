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

User = get_user_model()

# Find Wonju Moon
wonju = User.objects.filter(first_name='Wonju', last_name='Moon').first()
if not wonju:
    # Try by username patterns
    wonju = User.objects.get(id=8)  # julianmoonluna
    
print(f"Wonju Moon user: {wonju.username} (ID: {wonju.id})")
print(f"Name: {wonju.first_name} {wonju.last_name}")

# Check deposits for Wonju
deposits = SendTransaction.objects.filter(
    recipient_user=wonju,
    sender_type='external'
).order_by('-created_at')

print(f"\nDeposits for {wonju.username}: {deposits.count()}")
for d in deposits[:5]:
    print(f"  - {d.amount} {d.token_type} from {d.sender_display_name}")
    print(f"    sender_user: {d.sender_user.username if d.sender_user else 'None'}")
    print(f"    recipient_type: {d.recipient_type}")
    print(f"    status: {d.status}")

# Check business deposits
print("\n\nBusiness deposits:")
business_deposits = SendTransaction.objects.filter(
    recipient_type='business',
    sender_type='external'
).order_by('-created_at')

print(f"Total business deposits: {business_deposits.count()}")
for d in business_deposits[:5]:
    print(f"  - {d.amount} {d.token_type} to {d.recipient_display_name}")
    print(f"    recipient_user: {d.recipient_user.username}")
    print(f"    recipient_business: {d.recipient_business.name if d.recipient_business else 'None'}")

# Check how unified view sees these
print("\n\nChecking unified transaction view filtering:")
from users.graphql_views import UnifiedTransaction

# For personal account
personal_txs = UnifiedTransaction.objects.filter(
    sender_user=wonju,
    sender_business__isnull=True
) | UnifiedTransaction.objects.filter(
    counterparty_user=wonju,
    counterparty_business__isnull=True
)

print(f"Personal account transactions for {wonju.username}: {personal_txs.count()}")

# Check if external deposits are in unified view
external_in_unified = UnifiedTransaction.objects.filter(
    transaction_type='send',
    sender_type='external',
    counterparty_user=wonju
)
print(f"External deposits in unified view: {external_in_unified.count()}")