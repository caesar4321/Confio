#!/usr/bin/env python
"""Test GraphQL queries for transactions and notifications"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['CONFIO_ENV'] = 'testnet'
sys.path.insert(0, '/Users/julian/Confio')
django.setup()

from django.contrib.auth import get_user_model
from graphene.test import Client
from config.schema import schema
from django.test import RequestFactory
from rest_framework_simplejwt.tokens import RefreshToken
import json

User = get_user_model()

# Get a test user
user = User.objects.filter(phone_number__isnull=False).first()
if not user:
    print("No user found!")
    sys.exit(1)

print(f"Testing with user: {user.username} (id={user.id})")

# Create a JWT token with personal account context
refresh = RefreshToken.for_user(user)
# Add account context to the token
refresh['account_type'] = 'personal'
refresh['account_index'] = 0
refresh['business_id'] = None
token = str(refresh.access_token)
print(f"JWT Token: {token[:50]}...")

# Create a mock request with the token
factory = RequestFactory()
request = factory.get('/graphql')
request.META['HTTP_AUTHORIZATION'] = f'JWT {token}'
request.user = user

# Create GraphQL client
client = Client(schema, context=request)

# Test 1: Current Account Transactions
print("\n=== Testing currentAccountTransactions ===")
query1 = """
    query {
        currentAccountTransactions(limit: 5) {
            id
            transactionType
            amount
            tokenType
            status
            transactionHash
        }
    }
"""
result1 = client.execute(query1)
print(f"Result: {json.dumps(result1, indent=2)}")

# Test 2: Notifications
print("\n=== Testing notifications ===")
query2 = """
    query {
        notifications(first: 5) {
            edges {
                node {
                    id
                    notificationType
                    title
                    message
                    createdAt
                }
            }
            totalCount
            unreadCount
        }
    }
"""
result2 = client.execute(query2)
print(f"Result: {json.dumps(result2, indent=2)}")
