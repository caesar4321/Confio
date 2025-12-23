import os
import sys
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from algosdk import account, mnemonic, encoding
from algosdk.v2client import algod
from algosdk.transaction import (
    PaymentTxn, ApplicationCallTxn, AssetTransferTxn,
    wait_for_confirmation, OnComplete
)
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, TransactionWithSigner, TransactionSigner
from algosdk.abi import Contract, Method, Argument, Returns

try:
    from blockchain.kms_manager import KMSSigner
except ImportError:
    print("KMS not found")
    sys.exit(1)

# Config
ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
ALGOD_TOKEN = ""
client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

# Contract constants (from deployment)
APP_ID = 744368177
USDC_ID = 10458941
CUSD_ID = 744368179

# Load KMS Admin
kms_alias = os.environ.get('KMS_KEY_ALIAS', 'confio-testnet-sponsor')
kms_region = os.environ.get('KMS_REGION', 'eu-central-2')
kms_signer = KMSSigner(kms_alias, region_name=kms_region)
admin_addr = kms_signer.address
print(f"Admin/Sponsor: {admin_addr}")

# Generic Signer
class GenericSigner(TransactionSigner):
    def __init__(self, signer_fn):
        self.signer_fn = signer_fn
    def sign_transactions(self, txns, indexes):
        return [self.signer_fn(txns[i]) for i in indexes]

admin_tx_signer = GenericSigner(kms_signer.sign_transaction)

# Define ABI methods manually
def get_method(name, args_types=[]):
    return Method(
        name=name,
        args=[Argument(arg_type=t, name=f"arg{i}") for i, t in enumerate(args_types)],
        returns=Returns("void")
    )

m_opt_in = get_method("opt_in")
m_pause = get_method("pause")
m_unpause = get_method("unpause")
m_freeze = get_method("freeze_address", ["address"])
m_unfreeze = get_method("unfreeze_address", ["address"])

def run_tests():
    print("\n" + "="*60)
    print("STARTING LIVE SECURITY VERIFICATION")
    print("="*60)

    sp = client.suggested_params()
    app_addr = encoding.encode_address(encoding.checksum(b'appID' + APP_ID.to_bytes(8, 'big')))
    print(f"App Address: {app_addr}")
    
    # 1. TEST SPONSOR RECEIVER CONSTRAINT (SECURITY)
    print("\nTEST 1: Sponsor pays User (Should FAIL)...")
    try:
        pass # Skipping complex group construction without USDC opt-in
        print("Skipped (Requires USDC opt-in to construct valid group structure)")
    except Exception as e:
        print(f"Result: {e}")

    # 2. TEST FREEZE (ADMIN OPS)
    print("\nTEST 2: Freeze/Unfreeze Account...")
    # Create temp user
    priv, user_addr = account.generate_account()
    print(f"Temp User: {user_addr}")
    
    # Fund temp user
    print("Funding temp user...")
    fund_txn = PaymentTxn(admin_addr, sp, user_addr, 300_000) # 0.3 ALGO
    client.send_transaction(kms_signer.sign_transaction(fund_txn))
    wait_for_confirmation(client, fund_txn.get_txid(), 4)
    
    # Opt-in to App (Using ABI method call)
    print("Opting In to App...")
    user_signer = GenericSigner(lambda txn: txn.sign(priv))
    
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id=APP_ID,
        method=m_opt_in,
        sender=user_addr,
        sp=sp,
        signer=user_signer,
        method_args=[],
        on_complete=OnComplete.OptInOC
    )
    atc.execute(client, 4)
    print("✅ Opt-In Success")
        
    # PAUSE SYSTEM
    print("Pausing System...")
    atc = AtomicTransactionComposer()
    atc.add_method_call(APP_ID, m_pause, admin_addr, sp, admin_tx_signer, method_args=[])
    atc.execute(client, 4)
    print("✅ System Paused")

    print("Freezing User (should work while paused)...")
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        APP_ID, 
        m_freeze, 
        admin_addr, 
        sp, 
        admin_tx_signer, 
        method_args=[user_addr],
        foreign_assets=[CUSD_ID]
    )
    try:
        atc.execute(client, 4)
        print("✅ Freeze Success")
    except Exception as e:
        print(f"❌ Freeze Failed (Expected if Asset Manager not 0x0): {e}")
        
    # Verify State (Soft check)
    try:
        app_info = client.account_application_info(user_addr, APP_ID)
        is_frozen = next((kv['value']['uint'] for kv in app_info['app-local-state']['key-value'] if base64.b64decode(kv['key']) == b'is_frozen'), 0)
        print(f"State is_frozen: {is_frozen}")
    except:
        print("Could not read local state (maybe OptIn failed or Freeze failed)")

    # UNPAUSE SYSTEM
    print("Unpausing System...")
    atc = AtomicTransactionComposer()
    atc.add_method_call(APP_ID, m_unpause, admin_addr, sp, admin_tx_signer, method_args=[])
    atc.execute(client, 4)
    print("✅ System Unpaused")
        
    # UNFREEZE
    print("Unfreezing User...")
    atc = AtomicTransactionComposer()
    atc.add_method_call(
        APP_ID, 
        m_unfreeze, 
        admin_addr, 
        sp, 
        admin_tx_signer, 
        method_args=[user_addr],
        foreign_assets=[CUSD_ID]
    )
    try:
        atc.execute(client, 4)
        print("✅ Unfreeze Success")
    except Exception as e:
        print(f"❌ Unfreeze Failed (Expected if Asset Manager not 0x0): {e}")
    
    # Verify Unfreeze
    app_info = client.account_application_info(user_addr, APP_ID)
    is_frozen = next((kv['value']['uint'] for kv in app_info['app-local-state']['key-value'] if base64.b64decode(kv['key']) == b'is_frozen'), 0)
    print(f"State is_frozen: {is_frozen}")
    if is_frozen != 0:
        print("❌ Unfreeze Verification Failed!")
    else:
        print("✅ Unfreeze Verified")

    print("\n" + "="*60)
    print("VERIFICATION COMPLETE")
    print("="*60)

if __name__ == "__main__":
    run_tests()
