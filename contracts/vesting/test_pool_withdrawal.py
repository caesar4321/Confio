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

load_dotenv(ROOT / ".env.testnet", override=True)

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
        sponsor_alias = os.getenv("KMS_KEY_ALIAS", "confio-testnet-sponsor")
        sponsor_kms = KMSSigner(sponsor_alias, region_name=region)
        return Accounts(
            sponsor_addr=sponsor_kms.address,
            sponsor_signer=sponsor_kms.sign_transaction,
            admin_addr=sponsor_kms.address,
            admin_signer=sponsor_kms.sign_transaction
        )
    return None

def get_client():
    address = os.getenv("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.algonode.cloud")
    token = os.getenv("ALGORAND_ALGOD_TOKEN", "")
    return algod.AlgodClient(token, address)

def wait_for_confirmation(client, txid):
    last_round = client.status().get('last-round')
    txinfo = client.pending_transaction_info(txid)
    while not (txinfo.get('confirmed-round') and txinfo.get('confirmed-round') > 0):
        print("Waiting...")
        last_round += 1
        client.status_after_block(last_round)
        txinfo = client.pending_transaction_info(txid)
    return txinfo

def run_test():
    client = get_client()
    accounts = init_accounts()
    if not accounts:
        print("KMS Required.")
        return

    confio_id = int(os.getenv("ALGORAND_CONFIO_ASSET_ID"))
    print(f"Admin: {accounts.admin_addr}")

    # Compile once
    approval_res = client.compile(compile_vesting_pool())
    approval_prog = base64.b64decode(approval_res["result"])
    clear_prog = base64.b64decode(client.compile("#pragma version 8\nint 1")["result"])
    global_schema = StateSchema(num_uints=4, num_byte_slices=1)
    local_schema = StateSchema(num_uints=0, num_byte_slices=0)
    app_args = [confio_id.to_bytes(8, 'big'), (300).to_bytes(8, 'big')]

    print("-" * 20)
    print("Test 1: Withdraw Before Start (Should Succeed)")
    
    # 1. Deploy
    sp = client.suggested_params()
    txn = ApplicationCreateTxn(
        accounts.admin_addr, sp, OnComplete.NoOpOC, 
        approval_prog, clear_prog, 
        global_schema, local_schema, app_args
    )
    signed = accounts.admin_signer(txn)
    txid = client.send_transaction(signed)
    info = wait_for_confirmation(client, txid)
    app_id = info['application-index']
    from algosdk.logic import get_application_address
    app_addr = get_application_address(app_id)
    print(f"Pool Deployed: {app_id}")

    # 2. Opt-In
    sp = client.suggested_params()
    ptxn = PaymentTxn(accounts.sponsor_addr, sp, app_addr, 500_000)
    sp_inner = client.suggested_params()
    sp_inner.fee = 2000
    sp_inner.flat_fee = True
    atxn = ApplicationNoOpTxn(accounts.admin_addr, sp_inner, app_id, [b"opt_in_asset"], foreign_assets=[confio_id])
    gid = transaction.calculate_group_id([ptxn, atxn])
    ptxn.group = gid
    atxn.group = gid
    client.send_transactions([accounts.sponsor_signer(ptxn), accounts.admin_signer(atxn)])
    wait_for_confirmation(client, atxn.get_txid())
    print("Opted In.")

    # 3. Fund
    amount = 50_000
    sp = client.suggested_params()
    axfer = AssetTransferTxn(accounts.sponsor_addr, sp, app_addr, amount, confio_id)
    call = ApplicationNoOpTxn(accounts.admin_addr, sp, app_id, [b"fund"], foreign_assets=[confio_id])
    gid = transaction.calculate_group_id([axfer, call])
    axfer.group = gid
    call.group = gid
    client.send_transactions([accounts.sponsor_signer(axfer), accounts.admin_signer(call)])
    wait_for_confirmation(client, call.get_txid())
    print(f"Funded {amount}.")

    # 4. Withdraw Pre-Start
    print("Withdrawing Pre-Start...")
    sp = client.suggested_params()
    sp.fee = 2000
    sp.flat_fee = True
    w_txn = ApplicationNoOpTxn(accounts.admin_addr, sp, app_id, [b"withdraw_pre_start"], foreign_assets=[confio_id])
    signed_w = accounts.admin_signer(w_txn)
    txid = client.send_transaction(signed_w)
    wait_for_confirmation(client, txid)
    print("Withdrawal Confirmed.")

    # Verify Balance
    info = client.account_asset_info(app_addr, confio_id)
    bal = info['asset-holding']['amount']
    if bal == 0:
        print("SUCCESS: Balance is 0.")
    else:
        print(f"FAILURE: Balance is {bal}")

    print("-" * 20)
    print("Test 2: Withdraw After Start (Should Fail)")

    # 1. Deploy App 2
    sp = client.suggested_params()
    txn = ApplicationCreateTxn(
        accounts.admin_addr, sp, OnComplete.NoOpOC, 
        approval_prog, clear_prog, 
        global_schema, local_schema, app_args
    )
    signed = accounts.admin_signer(txn)
    txid = client.send_transaction(signed)
    info = wait_for_confirmation(client, txid)
    app_id_2 = info['application-index']
    app_addr_2 = get_application_address(app_id_2)
    print(f"Pool 2 Deployed: {app_id_2}")

    # 2. Opt-In
    sp = client.suggested_params()
    ptxn = PaymentTxn(accounts.sponsor_addr, sp, app_addr_2, 500_000)
    sp_inner = client.suggested_params()
    sp_inner.fee = 2000
    sp_inner.flat_fee = True
    atxn = ApplicationNoOpTxn(accounts.admin_addr, sp_inner, app_id_2, [b"opt_in_asset"], foreign_assets=[confio_id])
    gid = transaction.calculate_group_id([ptxn, atxn])
    ptxn.group = gid
    atxn.group = gid
    client.send_transactions([accounts.sponsor_signer(ptxn), accounts.admin_signer(atxn)])
    wait_for_confirmation(client, atxn.get_txid())

    # 3. Fund
    sp = client.suggested_params()
    axfer = AssetTransferTxn(accounts.sponsor_addr, sp, app_addr_2, amount, confio_id)
    call = ApplicationNoOpTxn(accounts.admin_addr, sp, app_id_2, [b"fund"], foreign_assets=[confio_id])
    gid = transaction.calculate_group_id([axfer, call])
    axfer.group = gid
    call.group = gid
    client.send_transactions([accounts.sponsor_signer(axfer), accounts.admin_signer(call)])
    wait_for_confirmation(client, call.get_txid())
    print("Pool 2 Funded.")

    # 4. Start Timer
    print("Starting Timer...")
    sp = client.suggested_params()
    start_txn = ApplicationNoOpTxn(accounts.admin_addr, sp, app_id_2, [b"start"])
    signed_start = accounts.admin_signer(start_txn)
    client.send_transaction(signed_start)
    wait_for_confirmation(client, start_txn.get_txid())
    print("Timer Started.")

    # 5. Attempt Withdraw
    print("Attempting Withdraw (Expect Failure)...")
    try:
        sp = client.suggested_params()
        sp.fee = 2000
        sp.flat_fee = True
        w_txn = ApplicationNoOpTxn(accounts.admin_addr, sp, app_id_2, [b"withdraw_pre_start"], foreign_assets=[confio_id])
        signed_w = accounts.admin_signer(w_txn)
        client.send_transaction(signed_w)
        print("FAILURE: Withdrawal succeeded!")
    except Exception as e:
        print("SUCCESS: Withdrawal failed as expected.")

if __name__ == "__main__":
    run_test()
