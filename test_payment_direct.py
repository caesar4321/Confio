#!/usr/bin/env python3
"""Test payment mutation directly"""

import os
import sys
import django
import json
from datetime import datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.utils import timezone
from django.test import RequestFactory
from graphql_jwt.shortcuts import get_token
from users.models import User
from payments.models import Invoice
from payments.schema import PayInvoice

# Create a test invoice
invoice = Invoice.objects.create(
    created_by_user_id=9,
    merchant_account_id=28,
    merchant_business_id=19,
    merchant_type='business',
    merchant_display_name='Salud de Julian',
    amount='0.75',
    token_type='cUSD',
    description='Direct test payment',
    expires_at=timezone.now() + timedelta(hours=24),
    status='PENDING'
)

print(f'Created invoice: {invoice.invoice_id}')
print(f'Amount: {invoice.amount} {invoice.token_type}')

# Get payer
payer_user = User.objects.get(id=8)
jwt_token = get_token(payer_user, context={'account_type': 'personal', 'account_index': 0})

# Create mock request
request = RequestFactory().post('/graphql')
request.user = payer_user
request.META['HTTP_AUTHORIZATION'] = f'JWT {jwt_token}'

class MockInfo:
    def __init__(self, context):
        self.context = context

info = MockInfo(request)

print('\nCalling PayInvoice mutation...')
idempotency_key = f'test_{datetime.now().timestamp()}'

# Suppress debug output temporarily
import logging
logging.getLogger('payments.schema').setLevel(logging.ERROR)
logging.getLogger('jwt_context').setLevel(logging.ERROR)
logging.getLogger('payment_mutations').setLevel(logging.ERROR)

result = PayInvoice.mutate(
    root=None,
    info=info,
    invoice_id=invoice.invoice_id,
    idempotency_key=idempotency_key
)

print(f'\n✅ Payment Result:')
print(f'Success: {result.success}')

if result.success and result.payment_transaction:
    payment = result.payment_transaction
    print(f'Payment ID: {payment.payment_transaction_id}')
    print(f'Status: {payment.status}')
    print(f'Has blockchain_data: {bool(payment.blockchain_data)}')
    
    if payment.blockchain_data:
        print(f'\n🎉 BLOCKCHAIN DATA EXISTS!')
        print(f'Type of blockchain_data: {type(payment.blockchain_data)}')
        
        # Test JSON serialization (what GraphQL would do)
        try:
            if isinstance(payment.blockchain_data, dict):
                json_str = json.dumps(payment.blockchain_data)
                print(f'JSON serialized length: {len(json_str)} chars')
                print(f'First 200 chars: {json_str[:200]}...')
            else:
                print(f'Already a string: {str(payment.blockchain_data)[:200]}...')
        except Exception as e:
            print(f'JSON serialization error: {e}')
    else:
        print('\n❌ No blockchain data!')
else:
    print(f'Errors: {result.errors}')