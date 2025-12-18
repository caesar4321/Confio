import os
import sys
import django
from django.conf import settings

# Setup Django (for settings)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

# Setup paths for local imports
from .admin_presale import PresaleAdmin
from blockchain.kms_manager import get_kms_signer_from_settings
from algosdk.v2client import algod
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation

def run():
    # 1. Config - Get from Django settings
    APP_ID = getattr(settings, 'ALGORAND_PRESALE_APP_ID', 751406592)
    CONFIO_ID = getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 744368175)
    CUSD_ID = getattr(settings, 'ALGORAND_CUSD_ASSET_ID', 744368179)
    
    
    # Target User
    USER_ADDRESS = "HUMXG7VX5RFOKQM3GJQ3CTIR3SM34TROVNVXG6FQGR6NC2YEIQLD5TBCTU"
    
    print(f"Initializing Presale Admin for App {APP_ID}...")
    print(f"CONFIO ID: {CONFIO_ID}, cUSD ID: {CUSD_ID}")
    admin = PresaleAdmin(APP_ID, CONFIO_ID, CUSD_ID)
    
    # Get signer from Django settings (uses correct KMS config)
    signer = get_kms_signer_from_settings()
    admin_addr = signer.address
    
    def kms_signer(txn):
        print(f"Signing transaction...")
        return signer.sign_transaction(txn)

    print(f"Admin Address: {admin_addr}")
    
    # 3. Withdraw cUSD from Presale to Admin
    print("\n--- Step 1: Withdraw cUSD from Presale ---")
    try:
        # Withdraw to admin itself
        res = admin.withdraw_cusd(admin_addr, kms_signer, receiver=admin_addr)
        if res:
             print(f"Successfully withdrew {res['amount']/1e6} cUSD to {res['receiver']}")
        else:
             print("Nothing to withdraw (balance is 0). Proceeding assuming admin has funds.")
    except Exception as e:
        print(f"Withdrawal failed (maybe empty?): {e}")

    # 4. Transfer 10 cUSD to User
    print("\n--- Step 2: Transfer 10 cUSD to User ---")
    amount_micro = 10_000_000 # 10 cUSD
    
    params = admin.algod_client.suggested_params()
    txn = AssetTransferTxn(
        sender=admin_addr,
        sp=params,
        receiver=USER_ADDRESS,
        amt=amount_micro,
        index=CUSD_ID
    )
    
    signed_txn = signer.sign_transaction(txn)
    tx_id = admin.algod_client.send_transaction(signed_txn)
    print(f"Transfer submitted: {tx_id}")
    wait_for_confirmation(admin.algod_client, tx_id, 4)
    print("✅ Transfer confirmed.")

if __name__ == "__main__":
    run()
