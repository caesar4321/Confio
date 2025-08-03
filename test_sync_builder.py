#!/usr/bin/env python3
"""
Test sync transaction builder directly
"""
import os
import sys

# Setup Django
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Import Django first
import django
django.setup()

from blockchain.sync_transaction_builder import build_sponsored_transaction_sync

def test_sync_builder():
    """Test sync builder directly"""
    
    try:
        print("Testing sync transaction builder...")
        
        # Simple transaction data
        tx_data = {
            'type': 'moveCall',
            'packageObjectId': '0x2',
            'module': 'pay',
            'function': 'split_and_transfer',
            'typeArguments': ['0x2::sui::SUI'],
            'arguments': [
                '0x1234567890abcdef',
                '1000000',
                '0xabcdef1234567890'
            ]
        }
        
        # Build transaction
        print("Building transaction...")
        tx_bytes = build_sponsored_transaction_sync(
            sender="0x1cf3e01b4879b386002cdadb2463d1635917cdda550658788dd77750f5f3736f",
            sponsor="0xed36f82d851c5b54ebc8b58a71ea6473823e073a01ce8b6a5c04a4bcebaf6aef",
            transactions=[tx_data],
            gas_budget=10000000,
            network='testnet'
        )
        
        print(f"Success! Transaction bytes: {len(tx_bytes)} bytes")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_sync_builder()