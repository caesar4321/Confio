#!/usr/bin/env python
"""
Test the payment with fixed method signature
"""
import os
import sys
import django
import base64
from algosdk import encoding, mnemonic, account
from algosdk.v2client import algod

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.payment_transaction_builder import PaymentTransactionBuilder
from django.conf import settings

def test_payment():
    """Test a payment with the fixed method signature"""
    
    # Initialize builder
    builder = PaymentTransactionBuilder()
    
    # Test addresses
    test_sender = "PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY"
    test_recipient = "37ENEH4WCOB7G6ASNMQ7A2S5NTWKYQESVRRL2Y77O5TNO7V4QL3XAMD2BA"
    test_amount = 1000000  # 1 cUSD
    
    print("Building payment transaction group...")
    
    try:
        result = builder.build_sponsored_payment_cusd_style(
            sender_address=test_sender,
            recipient_address=test_recipient,
            amount=test_amount,
            asset_id=settings.BLOCKCHAIN_CONFIG['ALGORAND_CUSD_ASSET_ID'],
            payment_id=None,
            note="Test payment with fix"
        )
        
        if result['success']:
            print("✓ Transaction group built successfully")
            
            # Get sponsor mnemonic
            sponsor_mnemonic = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not sponsor_mnemonic:
                print("✗ No sponsor mnemonic configured, cannot sign transactions")
                return
            
            # Sign sponsor transactions
            from algosdk import encoding as algo_encoding
            sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
            
            # Sign user transactions (as sponsor for testing)
            signed_txns = []
            
            # Transaction 0: Sponsor payment (already signed)
            sponsor_txns = result['sponsor_transactions']
            # Decode if it's base64 encoded
            sponsor_signed = sponsor_txns[0]['signed']
            if isinstance(sponsor_signed, str):
                sponsor_signed = base64.b64decode(sponsor_signed)
            elif sponsor_signed is None:
                print("✗ Sponsor payment not signed")
                return
            signed_txns.append(sponsor_signed)  # Index 0
            
            # Transaction 1 & 2: User AXFERs (sign as sponsor for testing)
            user_txns = result['transactions_to_sign']
            for user_txn in user_txns:
                from algosdk.transaction import Transaction
                txn_bytes = user_txn['txn']
                # The txn is already msgpack encoded bytes, not base64
                if isinstance(txn_bytes, bytes):
                    # Decode msgpack directly
                    import msgpack
                    txn = Transaction.undictify(msgpack.unpackb(txn_bytes, raw=False))
                else:
                    # Shouldn't happen but handle str case
                    txn = algo_encoding.msgpack_decode(txn_bytes)
                signed = algo_encoding.msgpack_encode(txn.sign(sponsor_private_key))
                # msgpack_encode returns base64 string, need bytes
                if isinstance(signed, str):
                    signed = base64.b64decode(signed)
                signed_txns.append(signed)
            
            # Transaction 3: App call (already signed)
            app_signed = sponsor_txns[1]['signed']
            if isinstance(app_signed, str):
                app_signed = base64.b64decode(app_signed)
            elif app_signed is None:
                print("✗ App call not signed")
                return
            signed_txns.append(app_signed)  # Index 3
            
            # Combine and submit
            combined_txns = b''.join(signed_txns)
            
            # Submit to network
            algod_client = algod.AlgodClient("", "https://testnet-api.algonode.cloud")
            
            print("Submitting transaction group...")
            tx_id = algod_client.send_raw_transaction(base64.b64encode(combined_txns).decode('utf-8'))
            print(f"✓ Transaction submitted: {tx_id}")
            
            # Wait for confirmation
            from algosdk.transaction import wait_for_confirmation
            try:
                confirmed = wait_for_confirmation(algod_client, tx_id, 10)
                print(f"✓ Transaction confirmed in round {confirmed.get('confirmed-round', 0)}")
            except Exception as e:
                print(f"✗ Transaction failed: {e}")
                
                # Get transaction info for debugging
                try:
                    txn_info = algod_client.pending_transaction_info(tx_id)
                    if 'pool-error' in txn_info:
                        print(f"  Pool error: {txn_info['pool-error']}")
                    if 'logs' in txn_info:
                        print(f"  Logs: {txn_info['logs']}")
                except:
                    pass
                
        else:
            print(f"✗ Failed to build transaction group: {result.get('error')}")
            
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_payment()