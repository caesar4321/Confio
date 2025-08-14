#!/usr/bin/env python
"""
Test script to verify the 4-txn payment group fix
"""
import os
import sys
import django
import json
import base64

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.payment_mutations import CreateSponsoredPaymentMutation
from blockchain.models import Payment
from users.models import User, Account, Business

def test_payment_fix():
    """Test that CreateSponsoredPaymentMutation only returns user transactions"""
    
    print("Testing payment fix...")
    
    # Check what CreateSponsoredPaymentMutation returns
    # The fix should ensure only 2 user transactions are returned, not 4
    
    # Mock a payment creation to see the structure
    from blockchain.payment_transaction_builder import PaymentTransactionBuilder
    from django.conf import settings
    
    builder = PaymentTransactionBuilder()
    
    # Create a test transaction group with valid addresses
    # Use the sponsor address as sender for testing
    test_sender = "PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY"
    # Use the payment app address as recipient for testing
    from algosdk import logic
    test_recipient = logic.get_application_address(settings.BLOCKCHAIN_CONFIG['ALGORAND_PAYMENT_APP_ID'])
    test_amount = 1000000  # 1 cUSD
    
    try:
        result = builder.build_sponsored_payment_cusd_style(
            sender_address=test_sender,
            recipient_address=test_recipient,
            amount=test_amount,
            asset_id=settings.BLOCKCHAIN_CONFIG['ALGORAND_CUSD_ASSET_ID'],
            payment_id=None,
            note="Test payment"
        )
        
        if result['success']:
            print(f"✓ Transaction builder succeeded")
            print(f"  - User transactions to sign: {len(result.get('transactions_to_sign', []))}")
            print(f"  - Sponsor transactions: {len(result.get('sponsor_transactions', []))}")
            
            # Verify we have exactly 2 user transactions (merchant and fee AXFERs)
            user_txns = result.get('transactions_to_sign', [])
            if len(user_txns) == 2:
                print("✓ Correct: Exactly 2 user transactions (merchant and fee AXFERs)")
            else:
                print(f"✗ Error: Expected 2 user transactions, got {len(user_txns)}")
            
            # Verify we have exactly 2 sponsor transactions (payment and app call)
            sponsor_txns = result.get('sponsor_transactions', [])
            if len(sponsor_txns) == 2:
                print("✓ Correct: Exactly 2 sponsor transactions (payment and app call)")
                # Check indexes
                indexes = [st.get('index') for st in sponsor_txns]
                if 0 in indexes and 3 in indexes:
                    print("✓ Correct: Sponsor transactions at indexes 0 and 3")
                else:
                    print(f"✗ Error: Sponsor transactions at wrong indexes: {indexes}")
            else:
                print(f"✗ Error: Expected 2 sponsor transactions, got {len(sponsor_txns)}")
            
            # Simulate what the mutation will return to the client
            # After the fix, it should only return user transactions
            transaction_data = []
            for i, user_txn in enumerate(user_txns):
                transaction_data.append({
                    'index': i,
                    'type': 'asset_transfer',
                    'transaction': base64.b64encode(user_txn['txn']).decode() if isinstance(user_txn['txn'], bytes) else user_txn['txn'],
                    'signed': False,
                    'needs_signature': True,
                    'message': user_txn.get('message', f'Transaction {i+1}')
                })
            
            print(f"\nClient will receive {len(transaction_data)} transactions:")
            for td in transaction_data:
                print(f"  - Index {td['index']}: {td['type']} (needs_signature={td['needs_signature']})")
            
            if len(transaction_data) == 2:
                print("✓ SUCCESS: Client receives only 2 user transactions as expected!")
            else:
                print(f"✗ FAILURE: Client receives {len(transaction_data)} transactions instead of 2")
            
        else:
            print(f"✗ Transaction builder failed: {result.get('error')}")
            
    except Exception as e:
        print(f"✗ Error during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_payment_fix()