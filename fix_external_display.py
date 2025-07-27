#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from send.models import SendTransaction

# Update all external deposits to use the address as display name
external_deposits = SendTransaction.objects.filter(sender_type='external')

print(f"Found {external_deposits.count()} external deposits to update")

# Update each deposit to use its address as display name
updated = 0
for deposit in external_deposits:
    deposit.sender_display_name = deposit.sender_address
    deposit.save()
    updated += 1

print(f"Updated {updated} deposits to show address as display name")

# Show some examples
print("\nUpdated deposits:")
for d in SendTransaction.objects.filter(sender_type='external')[:5]:
    print(f"  - {d.amount} {d.token_type} to {d.recipient_display_name}")
    print(f"    From: {d.sender_display_name}")