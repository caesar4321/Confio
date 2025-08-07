#!/usr/bin/env python
"""
Send CONFIO from test account to final recipient using sponsored transaction
"""

import os
import sys
import django
import asyncio
import base64
from decimal import Decimal
from algosdk import account, mnemonic, encoding
from algosdk.v2client import algod
import nacl.signing

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service
from blockchain.algorand_account_manager import AlgorandAccountManager

async def send_confio_to_final_recipient():
    """Send CONFIO from test account to final recipient"""
    
    # Test account (sender)
    test_mnemonic = "quantum there flavor biology family kiss sweet flag pyramid audit under slender small brush sibling world similar bubble enable roof recall include rally above gold"
    test_private_key_b64 = mnemonic.to_private_key(test_mnemonic)
    test_address = account.address_from_private_key(test_private_key_b64)
    test_private_key = base64.b64decode(test_private_key_b64)
    
    # Final recipient
    final_recipient = "XTITQDJSETDOQG3WMSDKE7QPPAX22ZMDX6PZ5B43E4JCFTEBPUJGDY2RGQ"
    
    print("=" * 60)
    print("Sending CONFIO from Test Account to Final Recipient")
    print("=" * 60)
    print(f"\nSender (Test Account): {test_address}")
    print(f"Final Recipient: {final_recipient}")
    
    # Check balances
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    try:
        # Check test account balance
        test_info = client.account_info(test_address)
        print(f"\nTest Account ALGO balance: {test_info['amount'] / 1_000_000} ALGO")
        
        # Check CONFIO balance
        assets = test_info.get('assets', [])
        confio_balance = 0
        for asset in assets:
            if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                confio_balance = asset['amount'] / 1_000_000
                print(f"Test Account CONFIO balance: {confio_balance} CONFIO")
                break
        
        if confio_balance == 0:
            print("\n❌ Test account has no CONFIO to send")
            return
        
        # Check if recipient is opted into CONFIO
        print(f"\nChecking recipient account...")
        recipient_info = client.account_info(final_recipient)
        print(f"Recipient ALGO balance: {recipient_info['amount'] / 1_000_000} ALGO")
        
        recipient_opted_in = False
        recipient_confio_balance = 0
        for asset in recipient_info.get('assets', []):
            if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                recipient_opted_in = True
                recipient_confio_balance = asset['amount'] / 1_000_000
                print(f"Recipient CONFIO balance: {recipient_confio_balance} CONFIO")
                break
        
        if not recipient_opted_in:
            print("\n⚠️  Recipient is not opted into CONFIO")
            print("   Recipient needs to opt-in first to receive CONFIO")
            
            # The recipient needs to opt-in themselves (they need to sign the opt-in)
            # We can't do it for them unless we have their private key
            print("\n   To receive CONFIO, the recipient account needs to:")
            print("   1. Have at least 0.1 ALGO for minimum balance")
            print("   2. Execute an opt-in transaction for CONFIO asset")
            print(f"   3. Asset ID: {AlgorandAccountManager.CONFIO_ASSET_ID}")
            
            if recipient_info['amount'] < 100000:  # Less than 0.1 ALGO
                print("\n   ❌ Recipient doesn't have enough ALGO for opt-in")
                print("      They need at least 0.1 ALGO")
                return
            else:
                print("\n   Recipient has enough ALGO but needs to opt-in to CONFIO")
                print("   For this demo, we'll assume they're opted in and continue...")
                # In a real scenario, the recipient would need to opt-in first
                # return
        
        # Send CONFIO from test account to final recipient
        transfer_amount = Decimal('5')  # Send 5 CONFIO
        
        print(f"\n📤 Sending {transfer_amount} CONFIO to final recipient...")
        
        # Step 1: Create sponsored transfer
        print("\n1. Creating sponsored transfer...")
        result = await algorand_sponsor_service.create_sponsored_transfer(
            sender=test_address,
            recipient=final_recipient,
            amount=transfer_amount,
            asset_id=AlgorandAccountManager.CONFIO_ASSET_ID,
            note="CONFIO transfer to final recipient"
        )
        
        if not result['success']:
            print(f"   ❌ Failed to create transfer: {result['error']}")
            return
        
        print(f"   ✅ Transfer created")
        print(f"      Group ID: {result['group_id']}")
        print(f"      Total fee: {result['total_fee']} microALGO (paid by sponsor)")
        
        # Step 2: Sign the transaction
        print("\n2. Signing transaction...")
        user_txn_bytes = base64.b64decode(result['user_transaction'])
        import msgpack
        
        # Sign using raw nacl approach
        tx_type_bytes = b'TX'
        bytes_to_sign = tx_type_bytes + user_txn_bytes
        
        from nacl.signing import SigningKey
        signing_key = SigningKey(test_private_key[:32])
        signed = signing_key.sign(bytes_to_sign)
        signature = signed.signature
        
        # Create signed transaction structure
        txn_obj = msgpack.unpackb(user_txn_bytes)
        signed_txn = {
            b'sig': signature,
            b'txn': txn_obj
        }
        
        signed_txn_bytes = msgpack.packb(signed_txn)
        signed_txn_b64 = base64.b64encode(signed_txn_bytes).decode('utf-8')
        
        print("   ✅ Transaction signed")
        
        # Step 3: Submit the transaction
        print("\n3. Submitting transaction to blockchain...")
        submit_result = await algorand_sponsor_service.submit_sponsored_group(
            signed_user_txn=signed_txn_b64,
            signed_sponsor_txn=result['sponsor_transaction']
        )
        
        if submit_result['success']:
            print(f"\n🎉 SUCCESS! Sent {transfer_amount} CONFIO to final recipient")
            print(f"   Transaction ID: {submit_result['tx_id']}")
            print(f"   Confirmed in round: {submit_result['confirmed_round']}")
            print(f"   Fees saved: {submit_result['fees_saved']} ALGO")
            print(f"\n   View on AlgoExplorer:")
            print(f"   https://testnet.algoexplorer.io/tx/{submit_result['tx_id']}")
            
            # Verify new balances
            print("\n4. Verifying final balances...")
            
            # Check test account new balance
            test_info = client.account_info(test_address)
            for asset in test_info.get('assets', []):
                if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                    new_test_balance = asset['amount'] / 1_000_000
                    print(f"   Test account CONFIO: {confio_balance} → {new_test_balance} CONFIO")
                    break
            
            # Check recipient new balance (if opted in)
            if recipient_opted_in:
                recipient_info = client.account_info(final_recipient)
                for asset in recipient_info.get('assets', []):
                    if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                        new_recipient_balance = asset['amount'] / 1_000_000
                        print(f"   Recipient CONFIO: {recipient_confio_balance} → {new_recipient_balance} CONFIO")
                        break
            
            print("\n✅ All transactions completed successfully!")
            print("   - Used sponsored transactions (no gas fees paid by users)")
            print("   - Successfully transferred CONFIO between accounts")
                    
        else:
            print(f"\n❌ Failed to submit transfer: {submit_result['error']}")
            
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(send_confio_to_final_recipient())