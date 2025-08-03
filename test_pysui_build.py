#!/usr/bin/env python3
"""
Test pysui transaction building methods
"""
from pysui import SyncClient, SuiConfig
from pysui.sui.sui_txn.sync_transaction import SuiTransaction
from pysui.sui.sui_types import SuiAddress
import base64

def test_build_methods():
    """Test different build methods"""
    
    # Create a sync client
    config = SuiConfig.default_config()
    client = SyncClient(config)
    
    try:
        # Create a simple transaction
        txn = SuiTransaction(client=client)
        
        # Set sender first
        txn.sender = SuiAddress("0xed36f82d851c5b54ebc8b58a71ea6473823e073a01ce8b6a5c04a4bcebaf6aef")
        txn.gas_budget = 10000000
        
        # Add a simple transfer
        txn.transfer_objects(
            transfers=[txn.gas],
            recipient=SuiAddress("0x0000000000000000000000000000000000000000000000000000000000000001")
        )
        
        # Check available methods
        print("Available transaction methods:")
        for attr in dir(txn):
            if not attr.startswith('_') and 'build' in attr or 'serialize' in attr:
                print(f"  - {attr}")
        
        # Try build_for_dryrun
        if hasattr(txn, 'build_for_dryrun'):
            try:
                dry_run_data = txn.build_for_dryrun()
                print(f"\nbuild_for_dryrun result:")
                print(f"Type: {type(dry_run_data)}")
                print(f"Value: {dry_run_data[:100]}..." if len(str(dry_run_data)) > 100 else dry_run_data)
            except Exception as e:
                print(f"build_for_dryrun error: {e}")
        
        # Try build
        if hasattr(txn, 'build'):
            try:
                build_result = txn.build()
                print(f"\nbuild result:")
                print(f"Type: {type(build_result)}")
                print(f"Value: {build_result}")
            except Exception as e:
                print(f"build error: {e}")
                
        # Check for build_and_sign
        if hasattr(txn, 'build_and_sign'):
            print("\nbuild_and_sign is available but requires signing capability")
            
        # Check if we can get transaction data
        if hasattr(txn, 'transaction_data'):
            print(f"\ntransaction_data: {txn.transaction_data}")
            
        # Check raw_kind
        if hasattr(txn, 'raw_kind'):
            try:
                raw = txn.raw_kind()
                print(f"\nraw_kind result: {type(raw)}")
            except Exception as e:
                print(f"raw_kind error: {e}")
                
    finally:
        client.close()


if __name__ == "__main__":
    test_build_methods()