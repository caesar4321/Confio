#!/usr/bin/env python
"""
Test simple ALGO send from sponsor to verify the sponsor account works
"""

import os
import sys
import django
from algosdk import account, mnemonic, transaction
from algosdk.v2client import algod

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings

def test_simple_send():
    """Test sending a small amount of ALGO from sponsor"""
    
    # Get sponsor details
    sponsor_address = settings.BLOCKCHAIN_CONFIG.get('ALGORAND_SPONSOR_ADDRESS')
    sponsor_mnemonic = settings.BLOCKCHAIN_CONFIG.get('ALGORAND_SPONSOR_MNEMONIC')
    
    if not sponsor_address or not sponsor_mnemonic:
        print("ERROR: Sponsor address or mnemonic not configured")
        return
    
    print(f"Sponsor address: {sponsor_address}")
    
    # Connect to Algorand
    algod_client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    # Check sponsor balance
    account_info = algod_client.account_info(sponsor_address)
    balance = account_info['amount'] / 1_000_000
    print(f"Sponsor balance: {balance} ALGO")
    
    if balance < 1:
        print("ERROR: Sponsor doesn't have enough ALGO")
        return
    
    # Create a test recipient
    test_private_key, test_address = account.generate_account()
    print(f"\nTest recipient: {test_address}")
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    # Create payment transaction (send 0.5 ALGO)
    amount = int(0.5 * 1_000_000)  # 0.5 ALGO in microALGOs
    payment_txn = transaction.PaymentTxn(
        sender=sponsor_address,
        sp=params,
        receiver=test_address,
        amt=amount
    )
    
    print(f"\nSending {amount/1_000_000} ALGO from sponsor to test account...")
    
    # Sign the transaction
    private_key = mnemonic.to_private_key(sponsor_mnemonic)
    signed_txn = payment_txn.sign(private_key)
    
    # Submit the transaction
    try:
        tx_id = algod_client.send_transaction(signed_txn)
        print(f"✓ Transaction submitted: {tx_id}")
        
        # Wait for confirmation
        confirmed_txn = transaction.wait_for_confirmation(algod_client, tx_id, 4)
        print(f"✓ Transaction confirmed in round {confirmed_txn['confirmed-round']}")
        print(f"View on AlgoExplorer: https://testnet.algoexplorer.io/tx/{tx_id}")
        
        # Check recipient balance
        try:
            recipient_info = algod_client.account_info(test_address)
            new_balance = recipient_info['amount'] / 1_000_000
            print(f"\n✅ SUCCESS! Test account now has {new_balance} ALGO")
            print(f"Test account: {test_address}")
            print(f"Mnemonic: {mnemonic.from_private_key(test_private_key)}")
        except:
            print("Note: Recipient balance check failed (may take a moment to update)")
            
    except Exception as e:
        print(f"✗ Error submitting transaction: {e}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_simple_send()