#!/usr/bin/env python3
"""Test GraphQL payment response with blockchain data"""

import os
import sys
import django
import json
import requests
from datetime import datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.utils import timezone
from graphql_jwt.shortcuts import get_token
from users.models import User
from payments.models import Invoice

# Create a test invoice
invoice = Invoice.objects.create(
    created_by_user_id=9,  # Salud de Julian owner
    merchant_account_id=28,  # Salud de Julian account
    merchant_business_id=19,  # Salud de Julian business
    merchant_type='business',
    merchant_display_name='Salud de Julian',
    amount='0.50',
    token_type='cUSD',
    description='GraphQL test payment',
    expires_at=timezone.now() + timedelta(hours=24),
    status='PENDING'
)

print(f'Created invoice: {invoice.invoice_id}')

# Get JWT token for payer
payer_user = User.objects.get(id=8)
jwt_token = get_token(payer_user, context={'account_type': 'personal', 'account_index': 0})

# Make GraphQL request
query = """
mutation PayInvoice($invoiceId: String!, $idempotencyKey: String) {
  payInvoice(invoiceId: $invoiceId, idempotencyKey: $idempotencyKey) {
    invoice {
      id
      invoiceId
      status
      paidAt
    }
    paymentTransaction {
      id
      paymentTransactionId
      amount
      tokenType
      description
      status
      transactionHash
      blockchainData
      createdAt
    }
    success
    errors
  }
}
"""

variables = {
    "invoiceId": invoice.invoice_id,
    "idempotencyKey": f"test_{datetime.now().timestamp()}"
}

# Send request
response = requests.post(
    'http://localhost:8000/graphql',
    json={
        'query': query,
        'variables': variables
    },
    headers={
        'Authorization': f'JWT {jwt_token}',
        'Content-Type': 'application/json'
    }
)

print('\nGraphQL Response:')
print('Status Code:', response.status_code)
print('\nResponse Body:')
response_json = response.json()
print(json.dumps(response_json, indent=2))

# Check if blockchain data is present
if response_json.get('data', {}).get('payInvoice', {}).get('paymentTransaction', {}).get('blockchainData'):
    print('\n✅ BLOCKCHAIN DATA IS PRESENT IN RESPONSE!')
    blockchain_data = response_json['data']['payInvoice']['paymentTransaction']['blockchainData']
    if isinstance(blockchain_data, str):
        blockchain_data = json.loads(blockchain_data)
    print(f'Number of transactions: {len(blockchain_data.get("transactions", []))}')
    print(f'User must sign indexes: {blockchain_data.get("user_signing_indexes", [])}')
else:
    print('\n❌ NO BLOCKCHAIN DATA IN RESPONSE')