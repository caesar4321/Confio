#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from send.models import SendTransaction

# Update all external deposits to use "Wallet externa" as display name
external_deposits = SendTransaction.objects.filter(sender_type='external')

print(f"Found {external_deposits.count()} external deposits to update")

# Update display names
updated = external_deposits.update(sender_display_name='Wallet externa')

print(f"Updated {updated} deposits to show 'Wallet externa'")

# Show some examples
print("\nUpdated deposits:")
for d in SendTransaction.objects.filter(sender_type='external')[:5]:
    print(f"  - {d.amount} {d.token_type} to {d.recipient_display_name}")
    print(f"    From: {d.sender_display_name} ({d.sender_address[:10]}...{d.sender_address[-6:]})")