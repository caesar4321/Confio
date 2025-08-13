#!/usr/bin/env python3

import os
import sys
import django
import json
from datetime import datetime, timedelta
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.utils import timezone
from graphql_jwt.shortcuts import get_token
from users.models import User, Account, Business
from payments.models import Invoice, PaymentTransaction
from django.test import RequestFactory
from payments.schema import PayInvoice

print('Testing complete blockchain payment flow')
print('=' * 60)

# Create a new test invoice
invoice = Invoice.objects.create(
    created_by_user_id=9,  # Salud de Julian owner
    merchant_account_id=28,  # Salud de Julian account
    merchant_business_id=19,  # Salud de Julian business
    merchant_type='business',
    merchant_display_name='Salud de Julian',
    amount='1.50',
    token_type='cUSD',
    description='Blockchain payment test',
    expires_at=timezone.now() + timedelta(hours=24),
    status='PENDING'
)

print(f'Invoice created: {invoice.invoice_id}')
print(f'Amount: {invoice.amount} {invoice.token_type}')
print(f'Merchant: {invoice.merchant_display_name}')

# Test payment
payer_user = User.objects.get(id=8)
payer_token = get_token(payer_user, context={'account_type': 'personal', 'account_index': 0})

request = RequestFactory().post('/graphql')
request.user = payer_user
request.META['HTTP_AUTHORIZATION'] = f'JWT {payer_token}'

class MockInfo:
    def __init__(self, context):
        self.context = context

info = MockInfo(request)

print(f'\nPayer: {payer_user.username}')
payer_account = payer_user.accounts.filter(account_type='personal').first()
print(f'Payer Address: {payer_account.algorand_address[:20]}...')

print(f'\nAttempting payment...')
idempotency_key = f'test_{datetime.now().timestamp()}'

try:
    result = PayInvoice.mutate(
        root=None,
        info=info,
        invoice_id=invoice.invoice_id,
        idempotency_key=idempotency_key
    )
    
    print(f'\n📊 Payment Result:')
    print(f'Success: {result.success}')
    
    if result.success:
        payment = result.payment_transaction
        print(f'Payment ID: {payment.payment_transaction_id}')
        print(f'Status: {payment.status}')
        print(f'Has blockchain_data: {bool(payment.blockchain_data)}')
        
        if payment.blockchain_data:
            print(f'\n🎉 SUCCESS: BLOCKCHAIN PAYMENT CREATED!')
            print(f'\nBlockchain Transaction Details:')
            print(f'  Number of transactions: {len(payment.blockchain_data.get("transactions", []))}')
            print(f'  User must sign indexes: {payment.blockchain_data.get("user_signing_indexes", [])}')
            print(f'  Group ID: {payment.blockchain_data.get("group_id", "None")[:30]}...')
            print(f'  Gross amount: ${payment.blockchain_data.get("gross_amount")} cUSD')
            print(f'  Net amount: ${payment.blockchain_data.get("net_amount")} cUSD (after 0.9% fee)')
            print(f'  Fee amount: ${payment.blockchain_data.get("fee_amount")} cUSD')
            
            print(f'\nTransaction Breakdown:')
            for i, txn in enumerate(payment.blockchain_data.get('transactions', [])):
                txn_type = txn.get('type', 'unknown')
                signed = '✅ Signed' if txn.get('signed') else '❌ Needs Signature'
                print(f'  Transaction {i}: {txn_type} - {signed}')
            
            print(f'\n✅ Payment is ready for client signing and submission!')
            print(f'\nThe React Native app will:')
            print(f'1. Detect the blockchain_data in the response')
            print(f'2. Sign the unsigned transactions with the user\'s key')
            print(f'3. Submit the complete transaction group to the blockchain')
            print(f'4. Update the payment status to CONFIRMED once on-chain')
        else:
            print('\n❌ No blockchain data - payment fell back to database-only')
    else:
        print(f'❌ Errors: {result.errors}')
        
except Exception as e:
    print(f'❌ Exception: {e}')
    import traceback
    traceback.print_exc()

print('\n' + '=' * 60)
print('Test complete!')