#!/usr/bin/env python
import os
import sys

# FORCE TESTNET BEFORE ANYTHING ELSE
os.environ['ALGORAND_NETWORK'] = 'testnet'
os.environ['CONFIO_ENV'] = 'testnet'
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

import django
from django.conf import settings

# Setup Django
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
django.setup()

import asyncio
from algosdk.v2client import algod
from algosdk.transaction import PaymentTxn, AssetTransferTxn, wait_for_confirmation
from algosdk import mnemonic, account

# Configuration
TARGET_ADDRESS = "P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU"
CONFIO_ASSET_ID = 751116135
CUSD_ASSET_ID = 744368179
ALGOD_ADDRESS = os.environ.get('ALGORAND_ALGOD_ADDRESS', 'https://testnet-api.4160.nodely.dev')
# ... imports ...
from blockchain.algorand_sponsor_service import algorand_sponsor_service


async def fund_with_kms():
    # Double check network via settings
    if settings.ALGORAND_NETWORK != 'testnet':
        print(f"❌ FATAL: Settings indicate {settings.ALGORAND_NETWORK}. Aborting.")
        return

    target = TARGET_ADDRESS
    sponsor_addr = algorand_sponsor_service.sponsor_address
    client = algorand_sponsor_service.algod
    
    print(f"Funding Source (KMS): {sponsor_addr}")
    print(f"Target: {target}")

    # 1. Send ALGO (Use built-in method)
    try:
        print("\n--- Sending 2 ALGO ---")
        # fund_account sends microAlgos
        res = await algorand_sponsor_service.fund_account(target, 2_000_000)
        print(f"Result: {res}")
    except Exception as e:
        print(f"Failed to send ALGO: {e}")

    # Helper to send asset via KMS
    async def send_asset_kms(asset_id, amount):
        params = client.suggested_params()
        txn = AssetTransferTxn(sponsor_addr, params, target, amount, asset_id)
        
        # Sign with KMS
        # _sign_transaction is Async? Wait, checking signature...
        # The tool output for view_file_outline showed:
        # AlgorandSponsorService._sign_transaction(self, txn: Transaction)
        # It didn't explicitly say "async def", but if calling it resulted in a coroutine warning, it MUST be async.
        
        signed_txn_b64 = await algorand_sponsor_service._sign_transaction(txn)
        if not signed_txn_b64:
            raise Exception("KMS Signing failed")
            
        print(f"DEBUG: Signed Txn Type: {type(signed_txn_b64)}")
        print(f"DEBUG: Signed Txn Preview: {str(signed_txn_b64)[:50]}...")
        
        # Submit
        import base64
        import binascii
        
        try:
            # Check if it's already bytes
            if isinstance(signed_txn_b64, bytes):
                signed_txn_bytes = signed_txn_b64
            else:
                s = signed_txn_b64.strip()
                # Ensure padding
                missing_padding = len(s) % 4
                if missing_padding:
                    s += '=' * (4 - missing_padding)
                
                try:
                    signed_txn_bytes = base64.b64decode(s)
                except binascii.Error:
                    # Try urlsafe just in case
                    signed_txn_bytes = base64.urlsafe_b64decode(s)

            # Use send_raw_transaction for pre-signed bytes
            tx_id = client.send_raw_transaction(signed_txn_bytes)
            print(f"Sent Asset {asset_id} Amount {amount}. TxID: {tx_id}")
            wait_for_confirmation(client, tx_id)
            print("Confirmed.")
        except Exception as e:
            print(f"Submission Error: {e}")
            if "receiver" in str(e).lower() and "opt" in str(e).lower():
                print("❌ CRITICAL: Receiver likely NOT opted in.")

    # 2. Send CONFIO
    try:
        print("\n--- Sending 100 CONFIO ---")
        await send_asset_kms(CONFIO_ASSET_ID, 100_000_000)
    except Exception as e:
        print(f"Failed to send CONFIO: {e}")

    # 3. Send cUSD
    try:
        print("\n--- Sending 100 cUSD ---")
        await send_asset_kms(CUSD_ASSET_ID, 100_000_000)
    except Exception as e:
        print(f"Failed to send cUSD: {e}")

if __name__ == "__main__":
    asyncio.run(fund_with_kms())
