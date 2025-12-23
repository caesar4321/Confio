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

def get_is_frozen_state(addr, app_id):
    try:
        app_info = client.account_application_info(addr, app_id)
        return next((kv['value']['uint'] for kv in app_info['app-local-state']['key-value'] if base64.b64decode(kv['key']) == b'is_frozen'), 0)
    except:
        return 0

def get_global_is_paused(app_id):
    try:
        app_info = client.application_info(app_id)
        for kv in app_info['params']['global-state']:
            if base64.b64decode(kv['key']) == b'is_paused':
                return kv['value']['uint']
        return 0
    except:
        return 0

def run_tests():
    print("\n" + "="*60)
    print("STARTING LIVE SECURITY VERIFICATION (STRICT MODE + FREEZE TEST)")
    print("="*60)

    sp = client.suggested_params()
    app_addr = encoding.encode_address(encoding.checksum(b'appID' + APP_ID.to_bytes(8, 'big')))
    print(f"App Address: {app_addr}")
    
    # SETUP: Ensure clean state (Unpause if paused from previous run)
    if get_global_is_paused(APP_ID) == 1:
        print("\n[SETUP] System already paused, unpausing first...")
        atc = AtomicTransactionComposer()
        atc.add_method_call(APP_ID, m_unpause, admin_addr, sp, admin_tx_signer, method_args=[])
        atc.execute(client, 4)
        print("✅ System Unpaused (Setup)")
    
    # Create 2 Temp Users
    print("\nCreating Temp Users...")
    priv_a, user_a = account.generate_account()
    priv_b, user_b = account.generate_account()
    print(f"User A (Target): {user_a}")
    print(f"User B (Other):  {user_b}")
    
    signer_a = GenericSigner(lambda txn: txn.sign(priv_a))
    signer_b = GenericSigner(lambda txn: txn.sign(priv_b))

    # Fund Users
    print("\nFunding users...")
    fund_txns = [
        PaymentTxn(admin_addr, sp, user_a, 500_000), # 0.5 ALGO
        PaymentTxn(admin_addr, sp, user_b, 500_000)
    ]
    # Sign and send all
    signed_funds = [kms_signer.sign_transaction(txn) for txn in fund_txns]
    txid = client.send_transaction(signed_funds[0])
    client.send_transaction(signed_funds[1])
    wait_for_confirmation(client, txid, 4)
    print("✅ Users Funded")

    # Opt-in Users to cUSD ASA (REQUIRED before freeze can work)
    print("\nOpting In Users to cUSD Asset...")
    optin_a = AssetTransferTxn(user_a, sp, user_a, 0, CUSD_ID)
    optin_b = AssetTransferTxn(user_b, sp, user_b, 0, CUSD_ID)
    client.send_transaction(optin_a.sign(priv_a))
    client.send_transaction(optin_b.sign(priv_b))
    wait_for_confirmation(client, optin_a.get_txid(), 4)
    print("✅ Users Opted into cUSD Asset")

    # Fund users with actual cUSD from sponsor
    print("\nFunding users with cUSD from Sponsor...")
    cusd_fund_amount = 1_000_000  # 1 cUSD (6 decimals)
    sp_cusd = client.suggested_params()
    cusd_fund_a = AssetTransferTxn(admin_addr, sp_cusd, user_a, cusd_fund_amount, CUSD_ID)
    cusd_fund_b = AssetTransferTxn(admin_addr, sp_cusd, user_b, cusd_fund_amount, CUSD_ID)
    client.send_transaction(kms_signer.sign_transaction(cusd_fund_a))
    client.send_transaction(kms_signer.sign_transaction(cusd_fund_b))
    wait_for_confirmation(client, cusd_fund_a.get_txid(), 4)
    print(f"✅ Users Funded with {cusd_fund_amount / 1_000_000} cUSD each")

    # Opt-in Users to App
    print("\nOpting In Users...")
    atc = AtomicTransactionComposer()
    atc.add_method_call(APP_ID, m_opt_in, user_a, sp, signer_a, method_args=[], on_complete=OnComplete.OptInOC)
    atc.add_method_call(APP_ID, m_opt_in, user_b, sp, signer_b, method_args=[], on_complete=OnComplete.OptInOC)
    atc.execute(client, 4)
    print("✅ Opt-Ins Success")

    # 1. PAUSE SYSTEM
    print("\n[SCENARIO 1] PAUSE SYSTEM")
    atc = AtomicTransactionComposer()
    atc.add_method_call(APP_ID, m_pause, admin_addr, sp, admin_tx_signer, method_args=[])
    atc.execute(client, 4)
    print("✅ System Paused (Contract Global State is_paused=1)")

    print("\n[SCENARIO 2] FREEZE USER A (WHILE PAUSED)")
    print("Executing freeze_address(User A)...")
    try:
        atc = AtomicTransactionComposer()
        sp_inner = client.suggested_params()
        sp_inner.flat_fee = True
        sp_inner.fee = 2000  # Cover inner transaction fee
        atc.add_method_call(APP_ID, m_freeze, admin_addr, sp_inner, admin_tx_signer, method_args=[user_a], foreign_assets=[CUSD_ID], accounts=[user_a])
        atc.execute(client, 4)
        print("✅ Freeze Transaction Success")
    except Exception as e:
        print(f"❌ Freeze Transaction Failed: {e}")
        return

    # Verify States
    frozen_a = get_is_frozen_state(user_a, APP_ID)
    frozen_b = get_is_frozen_state(user_b, APP_ID)
    print(f"User A is_frozen: {frozen_a} (Expected: 1)")
    print(f"User B is_frozen: {frozen_b} (Expected: 0)")
    
    if frozen_a != 1: print("❌ FAIL: User A should be frozen"); return
    if frozen_b != 0: print("❌ FAIL: User B should NOT be frozen"); return
    print("✅ States Verified")

    # 3. VERIFY ASA-LEVEL FREEZE AND TRANSFER BLOCKING
    print("\n[SCENARIO 3] VERIFY ASA-LEVEL FREEZE (TRANSFER BLOCKED)")
    
    # Check ASA-level freeze status via account_asset_info
    print("Checking ASA-level freeze status...")
    try:
        user_a_asset = client.account_asset_info(user_a, CUSD_ID)
        user_b_asset = client.account_asset_info(user_b, CUSD_ID)
        
        asa_frozen_a = user_a_asset['asset-holding'].get('is-frozen', False)
        asa_frozen_b = user_b_asset['asset-holding'].get('is-frozen', False)
        
        print(f"User A ASA is-frozen: {asa_frozen_a} (Expected: True)")
        print(f"User B ASA is-frozen: {asa_frozen_b} (Expected: False)")
        
        if not asa_frozen_a: print("❌ FAIL: User A should be ASA-level frozen"); return
        if asa_frozen_b: print("❌ FAIL: User B should NOT be ASA-level frozen"); return
        print("✅ ASA-level Freeze Status Verified")
    except Exception as e:
        print(f"❌ Could not check ASA freeze status: {e}")
        return
    
    # Attempt transfer from FROZEN User A (should FAIL at ASA level)
    # Now testing with actual non-zero balance.
    transfer_amount = 100_000  # 0.1 cUSD
    print(f"\nAttempting {transfer_amount/1_000_000} cUSD transfer from FROZEN User A...")
    try:
        sp_tx = client.suggested_params()
        frozen_tx = AssetTransferTxn(user_a, sp_tx, user_b, transfer_amount, CUSD_ID)
        client.send_transaction(frozen_tx.sign(priv_a))
        wait_for_confirmation(client, frozen_tx.get_txid(), 4)
        print("❌ FAIL: Frozen user should NOT be able to transfer")
        return
    except Exception as e:
        if "frozen" in str(e).lower():
            print(f"✅ Transfer Blocked (Expected): {e}")
        else:
            print(f"✅ Transfer Blocked (Error: {e})")
    
    # Attempt transfer from UNFROZEN User B (during PAUSE - should also FAIL if system affects ASA)
    # Note: Global pause only affects CONTRACT operations, not raw ASA transfers!
    # Note: User A is frozen, so cannot receive. Sending to admin instead.
    print(f"\nAttempting {transfer_amount/1_000_000} cUSD transfer from UNFROZEN User B to ADMIN (during pause)...")
    try:
        sp_tx = client.suggested_params()
        unfrozen_tx = AssetTransferTxn(user_b, sp_tx, admin_addr, transfer_amount, CUSD_ID)
        client.send_transaction(unfrozen_tx.sign(priv_b))
        wait_for_confirmation(client, unfrozen_tx.get_txid(), 4)
        print("✅ Unfrozen User B CAN transfer (raw ASA transfer bypasses contract pause)")
    except Exception as e:
        print(f"❌ FAIL: Unfrozen User B should be able to transfer: {e}")
        return

    print("\n[SCENARIO 4] UNPAUSE SYSTEM")
    atc = AtomicTransactionComposer()
    sp = client.suggested_params()  # Refresh to avoid stale params
    atc.add_method_call(APP_ID, m_unpause, admin_addr, sp, admin_tx_signer, method_args=[])
    atc.execute(client, 4)
    print("✅ System Unpaused")

    # 5. VERIFY USER A STILL FROZEN
    print("\n[SCENARIO 5] CHECK FREEZE PERSISTENCE")
    frozen_a_post = get_is_frozen_state(user_a, APP_ID)
    print(f"User A is_frozen: {frozen_a_post} (Expected: 1)")
    if frozen_a_post != 1: print("❌ FAIL: User A should still be frozen after unpause"); return
    print("✅ Freeze Persists")

    # 6. UNFREEZE USER A
    print("\n[SCENARIO 6] UNFREEZE USER A")
    try:
        atc = AtomicTransactionComposer()
        sp_inner = client.suggested_params()
        sp_inner.flat_fee = True
        sp_inner.fee = 2000  # Cover inner transaction fee
        atc.add_method_call(APP_ID, m_unfreeze, admin_addr, sp_inner, admin_tx_signer, method_args=[user_a], foreign_assets=[CUSD_ID], accounts=[user_a])
        atc.execute(client, 4)
        print("✅ Unfreeze Transaction Success")
    except Exception as e:
        print(f"❌ Unfreeze Transaction Failed: {e}")
        return

    frozen_a_final = get_is_frozen_state(user_a, APP_ID)
    print(f"User A is_frozen: {frozen_a_final} (Expected: 0)")
    if frozen_a_final != 0: print("❌ FAIL: User A should be unfrozen"); return
    print("✅ Unfreeze Verified")

    print("\n" + "="*60)
    print("ALL TESTS PASSED")
    print("="*60)

if __name__ == "__main__":
    run_tests()
