#!/usr/bin/env python
"""
Test to understand duplicate push notifications
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from notifications.models import Notification, FCMDeviceToken
from datetime import datetime, timedelta

# Check recent notifications
print("=== Recent Notifications ===")
recent_notifications = Notification.objects.filter(
    created_at__gte=datetime.now() - timedelta(hours=1)
).order_by('-created_at')[:10]

for n in recent_notifications:
    print(f"ID: {n.id}, Type: {n.notification_type}, User: {n.user.email if n.user else 'None'}")
    print(f"  Title: {n.title}")
    print(f"  Push sent: {n.push_sent}, Push sent at: {n.push_sent_at}")
    print()

# Check FCM tokens
print("\n=== FCM Tokens ===")
all_tokens = FCMDeviceToken.objects.filter(is_active=True)
print(f"Total active FCM tokens: {all_tokens.count()}")

# Group by user
from collections import defaultdict
users_tokens = defaultdict(list)
for token in all_tokens:
    users_tokens[token.user.email].append(token)

for email, tokens in users_tokens.items():
    print(f"\n{email}: {len(tokens)} tokens")
    for t in tokens:
        print(f"  - {t.device_type} - {t.device_name} - ID: {t.device_id}")
        print(f"    Token: {t.token[:20]}... (truncated)")
        print(f"    Created: {t.created_at}, Updated: {t.updated_at}")

# Check for duplicate tokens
print("\n=== Checking for duplicate tokens ===")
from collections import Counter
token_values = [t.token for t in all_tokens]
token_counts = Counter(token_values)
duplicates = {token: count for token, count in token_counts.items() if count > 1}
if duplicates:
    print(f"Found {len(duplicates)} duplicate token values")
    for token, count in duplicates.items():
        print(f"  Token {token[:20]}... appears {count} times")
else:
    print("No duplicate tokens found")