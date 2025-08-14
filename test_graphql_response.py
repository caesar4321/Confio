#!/usr/bin/env python3
"""Test actual GraphQL response format"""

import os
import sys
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from graphene.test import Client

from config.schema import schema
from django.test import RequestFactory
from graphql_jwt.shortcuts import get_token
from users.models import User
from payments.models import PaymentTransaction

# Get a payment with blockchain data
payment = PaymentTransaction.objects.filter(
    blockchain_data__isnull=False,
    status='PENDING_BLOCKCHAIN'
).first()

if not payment:
    print("No payment with blockchain data found")
    sys.exit(1)

print(f"Testing payment: {payment.payment_transaction_id}")
print(f"Status: {payment.status}")
print(f"Has blockchain_data in DB: {bool(payment.blockchain_data)}")

# Create GraphQL client
client = Client(schema)

# Get JWT token
user = User.objects.get(id=8)
jwt_token = get_token(user, context={'account_type': 'personal', 'account_index': 0})

# Create request with JWT
request = RequestFactory().post('/graphql')
request.user = user
request.META['HTTP_AUTHORIZATION'] = f'JWT {jwt_token}'

# Query for the payment transaction
query = """
query GetPaymentTransaction($id: ID!) {
  paymentTransaction(id: $id) {
    id
    paymentTransactionId
    status
    blockchainData
  }
}
"""

# Note: This query might not exist, let's try a different approach
# Query through invoice instead
query = """
query {
  paymentTransactions {
    id
    paymentTransactionId
    status
    blockchainData
  }
}
"""

result = client.execute(query, context=request)

print("\nGraphQL Response:")
print(json.dumps(result, indent=2))

if 'data' in result and 'paymentTransactions' in result['data']:
    transactions = result['data']['paymentTransactions']
    # Find our payment
    for txn in transactions:
        if txn['paymentTransactionId'] == payment.payment_transaction_id:
            print(f"\nFound our payment in response!")
            print(f"Has blockchainData: {bool(txn.get('blockchainData'))}")
            if txn.get('blockchainData'):
                print(f"Type of blockchainData: {type(txn['blockchainData'])}")
                if isinstance(txn['blockchainData'], str):
                    print("blockchainData is a string (needs parsing)")
                    try:
                        parsed = json.loads(txn['blockchainData'])
                        print(f"Parsed successfully, has {len(parsed.get('transactions', []))} transactions")
                    except:
                        print("Failed to parse as JSON")
                elif isinstance(txn['blockchainData'], dict):
                    print("blockchainData is already a dict (good!)")
                    print(f"Has {len(txn['blockchainData'].get('transactions', []))} transactions")
            break
    else:
        print(f"\nPayment {payment.payment_transaction_id} not found in response")