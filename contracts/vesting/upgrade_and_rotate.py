#!/usr/bin/env python3
import sys
import os
import time
import base64
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from algosdk import account, transaction, encoding
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCreateTxn, ApplicationNoOpTxn, AssetTransferTxn, 
    PaymentTxn, StateSchema, OnComplete
)
from blockchain.kms_manager import KMSSigner
from contracts.vesting.confio_vesting_pool import compile_vesting_pool

# Load Mainnet Env
load_dotenv(ROOT / ".env.mainnet", override=True)

class Accounts:
    def __init__(self, sponsor_addr, sponsor_signer, admin_addr, admin_signer):
        self.sponsor_addr = sponsor_addr
        self.sponsor_signer = sponsor_signer
        self.admin_addr = admin_addr
        self.admin_signer = admin_signer

def init_accounts():
    kms_enabled = os.getenv("USE_KMS_SIGNING", "").lower() == "true"
    if kms_enabled:
        region = os.getenv("KMS_REGION", "eu-central-2")
        sponsor_alias = os.getenv("KMS_KEY_ALIAS", "confio-mainnet-sponsor")
        sponsor_kms = KMSSigner(sponsor_alias, region_name=region)
        return Accounts(
            sponsor_addr=sponsor_kms.address,
            sponsor_signer=sponsor_kms.sign_transaction,
            admin_addr=sponsor_kms.address,
            admin_signer=sponsor_kms.sign_transaction
        )
    else:
        print("Error: Mainnet deployment requires KMS signing.")
        sys.exit(1)

def get_client():
    address = os.getenv("ALGORAND_ALGOD_ADDRESS")
    token = os.getenv("ALGORAND_ALGOD_TOKEN", "")
    return algod.AlgodClient(token, address)

def wait_for_confirmation(client, txid):
    last_round = client.status().get('last-round')
    txinfo = client.pending_transaction_info(txid)
    while not (txinfo.get('confirmed-round') and txinfo.get('confirmed-round') > 0):
        print("Waiting for confirmation...")
        last_round += 1
        client.status_after_block(last_round)
        txinfo = client.pending_transaction_info(txid)
    return txinfo

def upgrade_and_rotate():
    print("=== UPGRADE VESTING POOL & ROTATE ADMINS ===")
    
    client = get_client()
    accounts = init_accounts()
    confio_id = int(os.getenv("ALGORAND_CONFIO_ASSET_ID"))
    
    # 1. Configuration
    OLD_POOL_APP_ID = 3359289796
    SUSY_APP_ID = 3359297921
    JULIAN_APP_ID = 3359301443
    
    NEW_ADMIN = "MAI35ABWYNKUOW5QMESNZB3WDOFZ2XPHUXGBI4WNL6AI5XLBLF7IUVOYRI"
    
    print(f"Network: {os.getenv('ALGORAND_NETWORK')}")
    print(f"Current Admin: {accounts.admin_addr}")
    print("--- Scope ---")
    print(f"1. Withdraw Old Pool Funds ({OLD_POOL_APP_ID})")
    print(f"2. Deploy & Fund NEW Pool")
    print(f"3. Rotate Admin -> {NEW_ADMIN} for:")
    print(f"   - NEW Pool")
    print(f"   - Susy ({SUSY_APP_ID})")
    print(f"   - Julian ({JULIAN_APP_ID})")
    
    confirm = input("Are you sure? (type 'yes' to proceed): ")
    if confirm != "yes":
        print("Aborted.")
        return

    # ---------------------------------------------------------
    # STEP 1: Withdraw from Old Pool
    # ---------------------------------------------------------
    print(f"\n[1/6] Withdrawing from Old Pool {OLD_POOL_APP_ID}...")
    try:
        sp = client.suggested_params()
        sp.fee = 2000
        sp.flat_fee = True
        w_txn = ApplicationNoOpTxn(accounts.admin_addr, sp, OLD_POOL_APP_ID, [b"withdraw_pre_start"], foreign_assets=[confio_id])
        signed_w = accounts.admin_signer(w_txn)
        txid = client.send_transaction(signed_w)
        wait_for_confirmation(client, txid)
        print("Withdrawal Confirmed.")
    except Exception as e:
        print(f"Withdrawal Failed: {e}")
        # Could fail if balance is 0 or already withdrawn. Prompt to continue?
        c = input("Withdrawal may have failed or was unnecessary. Continue deployment? (yes/no): ")
        if c != "yes": return

    # ---------------------------------------------------------
    # STEP 2: Deploy New Pool
    # ---------------------------------------------------------
    print("\n[2/6] Deploying NEW Vesting Pool...")
    duration = 7776000 # 90 days
    funding_amount = 15_000_000_000_000 # 15M CONFIO
    
    approval_res = client.compile(compile_vesting_pool())
    approval_prog = base64.b64decode(approval_res["result"])
    clear_prog = base64.b64decode(client.compile("#pragma version 8\nint 1")["result"])
    global_schema = StateSchema(num_uints=4, num_byte_slices=1)
    local_schema = StateSchema(num_uints=0, num_byte_slices=0)
    app_args = [confio_id.to_bytes(8, 'big'), duration.to_bytes(8, 'big')]
    
    sp = client.suggested_params()
    txn = ApplicationCreateTxn(
        accounts.admin_addr, sp, OnComplete.NoOpOC, approval_prog, clear_prog, global_schema, local_schema, app_args
    )
    signed = accounts.admin_signer(txn)
    txid = client.send_transaction(signed)
    info = wait_for_confirmation(client, txid)
    NEW_POOL_APP_ID = info['application-index']
    from algosdk.logic import get_application_address
    new_pool_addr = get_application_address(NEW_POOL_APP_ID)
    print(f"NEW Pool Deployed: {NEW_POOL_APP_ID}")

    # ---------------------------------------------------------
    # STEP 3: Fund New Pool
    # ---------------------------------------------------------
    print("\n[3/6] Funding NEW Pool...")
    # Opt-In
    sp = client.suggested_params()
    ptxn = PaymentTxn(accounts.sponsor_addr, sp, new_pool_addr, 1_000_000)
    sp_inner = client.suggested_params()
    sp_inner.fee = 2000
    sp_inner.flat_fee = True
    atxn = ApplicationNoOpTxn(accounts.admin_addr, sp_inner, NEW_POOL_APP_ID, [b"opt_in_asset"], foreign_assets=[confio_id])
    gid = transaction.calculate_group_id([ptxn, atxn])
    ptxn.group = gid
    atxn.group = gid
    client.send_transactions([accounts.sponsor_signer(ptxn), accounts.admin_signer(atxn)])
    wait_for_confirmation(client, atxn.get_txid())
    
    # Fund
    sp = client.suggested_params()
    axfer = AssetTransferTxn(accounts.sponsor_addr, sp, new_pool_addr, funding_amount, confio_id)
    call = ApplicationNoOpTxn(accounts.admin_addr, sp, NEW_POOL_APP_ID, [b"fund"], foreign_assets=[confio_id])
    gid = transaction.calculate_group_id([axfer, call])
    axfer.group = gid
    call.group = gid
    client.send_transactions([accounts.sponsor_signer(axfer), accounts.admin_signer(call)])
    wait_for_confirmation(client, call.get_txid())
    print("Funding Complete.")

    # ---------------------------------------------------------
    # STEP 4: Rotate New Pool Admin
    # ---------------------------------------------------------
    print(f"\n[4/6] Rotate New Pool ({NEW_POOL_APP_ID}) Admin -> {NEW_ADMIN}...")
    sp = client.suggested_params()
    txn = ApplicationNoOpTxn(accounts.admin_addr, sp, NEW_POOL_APP_ID, [b"update_admin", encoding.decode_address(NEW_ADMIN)])
    client.send_transaction(accounts.admin_signer(txn))
    wait_for_confirmation(client, txn.get_txid())
    print("Success.")

    # ---------------------------------------------------------
    # STEP 5: Rotate Susy Admin
    # ---------------------------------------------------------
    print(f"\n[5/6] Rotate Susy ({SUSY_APP_ID}) Admin -> {NEW_ADMIN}...")
    sp = client.suggested_params()
    txn = ApplicationNoOpTxn(accounts.admin_addr, sp, SUSY_APP_ID, [b"update_admin", encoding.decode_address(NEW_ADMIN)])
    client.send_transaction(accounts.admin_signer(txn))
    wait_for_confirmation(client, txn.get_txid())
    print("Success.")

    # ---------------------------------------------------------
    # STEP 6: Rotate Julian Admin
    # ---------------------------------------------------------
    print(f"\n[6/6] Rotate Julian ({JULIAN_APP_ID}) Admin -> {NEW_ADMIN}...")
    sp = client.suggested_params()
    txn = ApplicationNoOpTxn(accounts.admin_addr, sp, JULIAN_APP_ID, [b"update_admin", encoding.decode_address(NEW_ADMIN)])
    client.send_transaction(accounts.admin_signer(txn))
    wait_for_confirmation(client, txn.get_txid())
    print("Success.")

    print("\n=== MIGRATION COMPLETE ===")
    print(f"NEW Vesting Pool App ID: {NEW_POOL_APP_ID}")
    print("Use this to update .env.mainnet")

if __name__ == "__main__":
    upgrade_and_rotate()
