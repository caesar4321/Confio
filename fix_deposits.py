#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from send.models import SendTransaction

# Fix external deposits - sender_user should be NULL for external deposits
external_deposits = SendTransaction.objects.filter(
    sender_type='external'
)

print(f"Found {external_deposits.count()} external deposits to fix")

# Update them to have NULL sender_user
fixed = external_deposits.update(sender_user=None)

print(f"Fixed {fixed} deposits to have NULL sender_user")

# Verify
still_wrong = SendTransaction.objects.filter(
    sender_type='external',
    sender_user__isnull=False
).count()

print(f"Deposits still with sender_user: {still_wrong}")

# Show some examples
print("\nExample fixed deposits:")
for d in SendTransaction.objects.filter(sender_type='external')[:5]:
    print(f"  - {d.amount} {d.token_type} to {d.recipient_display_name}")
    print(f"    sender_user: {d.sender_user}")
    print(f"    sender_type: {d.sender_type}")
    print(f"    sender_display_name: {d.sender_display_name}")