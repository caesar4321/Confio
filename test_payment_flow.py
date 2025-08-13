#!/usr/bin/env python3
"""
Test script to verify the complete payment flow with blockchain integration
"""

import os
import sys
import json
from decimal import Decimal

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.contrib.auth import get_user_model
from payments.models import Invoice, PaymentTransaction
from users.models import Account, Business
from blockchain.payment_mutations import CreateSponsoredPaymentMutation

User = get_user_model()

def test_payment_flow():
    """Test the complete payment flow"""
    
    print("=" * 60)
    print("Testing Payment Flow with Blockchain Integration")
    print("=" * 60)
    
    # Step 1: Get test users and businesses
    print("\n1. Setting up test entities...")
    
    # Get or create a test payer user
    payer_user, _ = User.objects.get_or_create(
        username='test_payer',
        defaults={
            'email': 'payer@test.com',
            'first_name': 'Test',
            'last_name': 'Payer'
        }
    )
    print(f"   Payer user: {payer_user.username}")
    
    # Get or create payer's personal account
    payer_account, _ = Account.objects.get_or_create(
        user=payer_user,
        account_type='personal',
        account_index=0,
        defaults={
            'algorand_address': 'TESTPAYERADDRESS1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ2345'  # 58 chars
        }
    )
    print(f"   Payer account: {payer_account.algorand_address[:20]}...")
    
    # Get or create a test merchant business
    merchant_user, _ = User.objects.get_or_create(
        username='test_merchant',
        defaults={
            'email': 'merchant@test.com',
            'first_name': 'Test',
            'last_name': 'Merchant'
        }
    )
    
    merchant_business, _ = Business.objects.get_or_create(
        name='Test Coffee Shop',
        defaults={
            'owner': merchant_user,
            'category': 'FOOD',
            'address': '123 Test Street'
        }
    )
    print(f"   Merchant business: {merchant_business.name}")
    
    # Get or create merchant's business account
    merchant_account, _ = Account.objects.get_or_create(
        user=merchant_user,
        business=merchant_business,
        account_type='business',
        account_index=0,
        defaults={
            'algorand_address': 'TESTMERCHANTADDR1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ234'  # 58 chars
        }
    )
    print(f"   Merchant account: {merchant_account.algorand_address[:20]}...")
    
    # Step 2: Create an invoice
    print("\n2. Creating test invoice...")
    
    invoice = Invoice.objects.create(
        created_by_user=merchant_user,
        merchant_account=merchant_account,
        merchant_business=merchant_business,
        amount=Decimal('10.00'),
        token_type='cUSD',
        description='Test coffee purchase',
        status='PENDING'
    )
    print(f"   Invoice ID: {invoice.invoice_id}")
    print(f"   Amount: {invoice.amount} {invoice.token_type}")
    
    # Step 3: Test the payment mutation
    print("\n3. Testing payment mutation with blockchain...")
    
    # Create a mock GraphQL info object
    class MockRequest:
        def __init__(self):
            self.META = {
                'HTTP_AUTHORIZATION': 'Bearer mock_token',
                'HTTP_X_RECIPIENT_BUSINESS_ID': str(merchant_business.id)
            }
            self.user = payer_user
    
    class MockInfo:
        def __init__(self):
            self.context = MockRequest()
    
    mock_info = MockInfo()
    
    # Create a payment transaction
    payment = PaymentTransaction.objects.create(
        payer_user=payer_user,
        payer_account=payer_account,
        merchant_account=merchant_account,
        merchant_business=merchant_business,
        merchant_account_user=merchant_user,
        amount=invoice.amount,
        token_type=invoice.token_type,
        description=invoice.description,
        status='PENDING',
        invoice=invoice,
        payer_address=payer_account.algorand_address,
        merchant_address=merchant_account.algorand_address,
        payment_transaction_id=f'TEST_{invoice.invoice_id}'
    )
    print(f"   Payment transaction: {payment.payment_transaction_id}")
    
    # Step 4: Attempt to create blockchain transactions
    print("\n4. Creating blockchain payment transactions...")
    
    try:
        # Mock JWT context for testing
        def mock_jwt_validation(info, required_permission=None):
            return {
                'account_type': 'personal',
                'account_index': 0,
                'business_id': None,
                'user_id': payer_user.id
            }
        
        # Temporarily replace the JWT validation
        from blockchain import payment_mutations
        original_validation = payment_mutations.get_jwt_business_context_with_validation
        payment_mutations.get_jwt_business_context_with_validation = mock_jwt_validation
        
        # Try to create the payment
        result = CreateSponsoredPaymentMutation.mutate(
            root=None,
            info=mock_info,
            amount=float(invoice.amount),
            asset_type='CUSD',
            payment_id=payment.payment_transaction_id,
            note=f"Payment for invoice {invoice.invoice_id}",
            create_receipt=True
        )
        
        # Restore original validation
        payment_mutations.get_jwt_business_context_with_validation = original_validation
        
        if result.success:
            print("   ✅ Blockchain transactions created successfully!")
            if result.transactions:
                txn_data = json.loads(result.transactions) if isinstance(result.transactions, str) else result.transactions
                print(f"   Transaction count: {len(txn_data)}")
                print(f"   User must sign indexes: {result.user_signing_indexes}")
                print(f"   Gross amount: {result.gross_amount}")
                print(f"   Net amount: {result.net_amount} (after 0.9% fee)")
                print(f"   Fee amount: {result.fee_amount}")
                
                # Update payment with blockchain data
                payment.blockchain_data = {
                    'transactions': txn_data,
                    'user_signing_indexes': result.user_signing_indexes,
                    'group_id': result.group_id,
                    'gross_amount': float(result.gross_amount),
                    'net_amount': float(result.net_amount),
                    'fee_amount': float(result.fee_amount)
                }
                payment.status = 'PENDING_BLOCKCHAIN'
                payment.save()
                print("   Blockchain data saved to payment transaction")
        else:
            print(f"   ❌ Failed to create blockchain transactions: {result.error}")
            
    except Exception as e:
        print(f"   ❌ Error creating blockchain payment: {e}")
        import traceback
        traceback.print_exc()
    
    # Step 5: Summary
    print("\n" + "=" * 60)
    print("Test Summary:")
    print("=" * 60)
    print(f"Invoice created: {invoice.invoice_id}")
    print(f"Payment created: {payment.payment_transaction_id}")
    print(f"Payment status: {payment.status}")
    if payment.blockchain_data:
        print("Blockchain data: ✅ Ready for client signing")
    else:
        print("Blockchain data: ❌ Not created (database-only payment)")
    print("\nNext steps:")
    print("1. Client app receives payment with blockchain_data")
    print("2. Client signs transactions at specified indexes")
    print("3. Client submits signed transactions via submitSponsoredPayment")
    print("4. Payment completes on blockchain with 0.9% fee deducted")
    
    return invoice, payment

if __name__ == '__main__':
    invoice, payment = test_payment_flow()