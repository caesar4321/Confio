#!/usr/bin/env python3
"""
Test script to understand transaction serialization format
"""
import base64
import json
from pysui import SyncClient, SuiConfig
from pysui.sui.sui_txn.sync_transaction import SuiTransaction
from pysui.sui.sui_types import SuiAddress
from pysui.sui.sui_crypto import SuiKeyPair

def test_transaction_format():
    """Test what transaction serialization produces"""
    
    # Create a sync client
    config = SuiConfig.default_config()
    client = SyncClient(config)
    
    try:
        # Create a simple transaction
        txn = SuiTransaction(client=client)
        
        # Add a simple transfer
        # The method expects keyword arguments
        txn.transfer_objects(
            transfers=[txn.gas],
            recipient=SuiAddress("0x0000000000000000000000000000000000000000000000000000000000000001")
        )
        
        # Set transaction parameters
        txn.sender = SuiAddress("0xed36f82d851c5b54ebc8b58a71ea6473823e073a01ce8b6a5c04a4bcebaf6aef")
        txn.gas_budget = 10000000
        
        # Try to build the transaction
        print("Building transaction...")
        
        # Check if we can inspect the transaction
        print(f"Transaction type: {type(txn)}")
        print(f"Transaction dict: {txn.__dict__ if hasattr(txn, '__dict__') else 'No dict'}")
        
        # Try serialization
        try:
            tx_bytes = txn.serialize()
            print(f"\nSerialized transaction:")
            print(f"Type: {type(tx_bytes)}")
            print(f"Length: {len(tx_bytes)} bytes")
            print(f"Base64: {base64.b64encode(tx_bytes).decode()}")
            print(f"Hex: {tx_bytes.hex()}")
            
            # Print first 100 bytes in hex for inspection
            print(f"\nFirst 100 bytes (hex): {tx_bytes[:100].hex()}")
            
        except Exception as e:
            print(f"Serialization error: {e}")
            
        # Try to build with the build() method if it exists
        if hasattr(txn, 'build'):
            try:
                built = txn.build()
                print(f"\nBuilt transaction: {built}")
            except Exception as e:
                print(f"Build error: {e}")
                
        # Check for TransactionData
        if hasattr(txn, 'transaction_data'):
            print(f"\nTransaction data: {txn.transaction_data}")
            
    finally:
        client.close()


if __name__ == "__main__":
    test_transaction_format()