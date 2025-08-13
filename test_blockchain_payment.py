#!/usr/bin/env python3
"""
Simple test to check if blockchain payment creation works
"""

import os
import sys

# Setup Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from blockchain.payment_transaction_builder import PaymentTransactionBuilder

def test_blockchain_payment():
    """Test if we can create blockchain payment transactions"""
    
    print("Testing Blockchain Payment Creation")
    print("=" * 50)
    
    # Test addresses (58 chars each)
    sender_address = "TESTPAYERADDRESS1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ2345"
    recipient_address = "TESTMERCHANTADDR1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ234"
    
    # Initialize builder
    builder = PaymentTransactionBuilder(network='testnet')
    
    print(f"Payment App ID: {builder.payment_app_id}")
    print(f"cUSD Asset ID: {builder.cusd_asset_id}")
    print(f"CONFIO Asset ID: {builder.confio_asset_id}")
    print(f"App Address: {builder.app_address}")
    print(f"Sponsor Address: {builder.sponsor_address}")
    
    try:
        # Try to build a sponsored payment
        print("\nBuilding sponsored payment transaction...")
        
        transactions, user_signing_indexes = builder.build_sponsored_payment(
            sender_address=sender_address,
            recipient_address=recipient_address,
            amount=1000000,  # 1 cUSD (6 decimals)
            asset_id=builder.cusd_asset_id,
            payment_id="TEST_PAYMENT_001",
            note="Test payment"
        )
        
        print(f"✅ Successfully created {len(transactions)} transactions")
        print(f"User must sign transactions at indexes: {user_signing_indexes}")
        
        for i, txn in enumerate(transactions):
            print(f"  Transaction {i}: {txn.__class__.__name__}")
            if hasattr(txn, 'sender'):
                print(f"    Sender: {txn.sender[:10]}...")
            if hasattr(txn, 'fee'):
                print(f"    Fee: {txn.fee}")
        
    except Exception as e:
        print(f"❌ Failed to create transactions: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_blockchain_payment()