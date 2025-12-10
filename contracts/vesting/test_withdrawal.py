#!/usr/bin/env python3
import sys
import os
import time
import base64
from pathlib import Path
from dotenv import load_dotenv

# Path setup
ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from algosdk import account, mnemonic, transaction, encoding
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCreateTxn, ApplicationNoOpTxn, AssetTransferTxn, 
    PaymentTxn, StateSchema, OnComplete
)
from blockchain.kms_manager import KMSSigner
from contracts.vesting.confio_vesting import compile_vesting

# Load .env.testnet overrides
load_dotenv(ROOT / ".env.testnet", override=True)

class Accounts:
    def __init__(self, sponsor_addr, sponsor_signer, admin_addr, admin_signer):
        self.sponsor_addr = sponsor_addr
        self.sponsor_signer = sponsor_signer
        # In this test we use sponsor as admin for simplicity if not separated
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
    else:
        # Fallback (not expected for user)
        mnemonic_phrase = os.getenv("ALGORAND_SPONSOR_MNEMONIC")
        private_key = mnemonic.to_private_key(mnemonic_phrase)
        address = account.address_from_private_key(private_key)
        signer = lambda txn: txn.sign(private_key)
        return Accounts(address, signer, address, signer)

def get_client():
    address = os.getenv("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.algonode.cloud")
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
    print(f"Transaction confirmed in round {txinfo.get('confirmed-round')}")
    return txinfo

def run_test():
    client = get_client()
    accounts = init_accounts()
    
    print(f"Admin: {accounts.admin_addr}")
    confio_id = int(os.getenv("ALGORAND_CONFIO_ASSET_ID"))
    
    # 1. Fake Beneficiary
    ben_key, ben_addr = account.generate_account()
    
    # 2. Deploy
    print("Deploying Contract...")
    approval_teal = compile_vesting()
    approval_prog = base64.b64decode(client.compile(approval_teal)["result"])
    clear_prog = base64.b64decode(client.compile("#pragma version 8\nint 1")["result"])
    
    global_schema = StateSchema(num_uints=5, num_byte_slices=2)
    local_schema = StateSchema(num_uints=0, num_byte_slices=0)
    
    app_args = [
        confio_id.to_bytes(8, 'big'),
        encoding.decode_address(ben_addr),
        (300).to_bytes(8, 'big') # Duration irrelevant here
    ]
    
    params = client.suggested_params()
    create_txn = ApplicationCreateTxn(
        accounts.admin_addr, params, OnComplete.NoOpOC, 
        approval_prog, clear_prog, 
        global_schema, local_schema, app_args
    )
    signed_create = accounts.admin_signer(create_txn)
    txid = client.send_transaction(signed_create)
    txinfo = wait_for_confirmation(client, txid)
    app_id = txinfo['application-index']
    from algosdk.logic import get_application_address
    app_addr = get_application_address(app_id)
    print(f"App Deployed: {app_id} ({app_addr})")
    
    # 3. Opt-in App
    print("Opting App in...")
    # Fund App with Algo for MBR
    params = client.suggested_params()
    p_txn = PaymentTxn(accounts.sponsor_addr, params, app_addr, 500_000)
    params.fee = 2000
    a_txn = ApplicationNoOpTxn(accounts.admin_addr, params, app_id, [b"opt_in_asset"], foreign_assets=[confio_id])
    
    gid = transaction.calculate_group_id([p_txn, a_txn])
    p_txn.group = gid
    a_txn.group = gid
    
    client.send_transactions([accounts.sponsor_signer(p_txn), accounts.admin_signer(a_txn)])
    wait_for_confirmation(client, a_txn.get_txid())
    print("App Opted In.")
    
    # 4. Fund Vault
    amount_confio = 50_000 # 0.05 CONFIO
    print(f"Funding {amount_confio} CONFIO...")
    params = client.suggested_params()
    axfer = AssetTransferTxn(accounts.sponsor_addr, params, app_addr, amount_confio, confio_id)
    call = ApplicationNoOpTxn(accounts.admin_addr, params, app_id, [b"fund"], foreign_assets=[confio_id])
    gid = transaction.calculate_group_id([axfer, call])
    axfer.group = gid
    call.group = gid
    client.send_transactions([accounts.sponsor_signer(axfer), accounts.admin_signer(call)])
    wait_for_confirmation(client, call.get_txid())
    
    # Verify balance
    info = client.account_asset_info(app_addr, confio_id)
    bal = info['asset-holding']['amount']
    print(f"App Balance Before Withdraw: {bal}")
    if bal != amount_confio:
        print("Error: Balance mismatch!")
        return

    # 5. Withdraw Before Start
    print("Withdrawing (Pre-start)...")
    # **INTENTIONALLY NOT CALLING START**
    
    params = client.suggested_params()
    params.fee = 2000 # Inner txn fee
    w_txn = ApplicationNoOpTxn(accounts.admin_addr, params, app_id, [b"withdraw_before_start"], foreign_assets=[confio_id])
    signed_w = accounts.admin_signer(w_txn)
    txid = client.send_transaction(signed_w)
    wait_for_confirmation(client, txid)
    print("Withdrawal Confirmed.")
    
    # 6. Verify Balance is 0
    info = client.account_asset_info(app_addr, confio_id)
    bal = info['asset-holding']['amount']
    print(f"App Balance After Withdraw: {bal}")
    
    if bal == 0:
        print("SUCCESS: Funds fully recovered!")
    else:
        print(f"FAILURE: Funds remaining: {bal}")
        
    print("-" * 20)
    print("Test 2: Withdraw AFTER Start (Should Fail)")
    
    # 1. Deploy again
    print("Deploying Contract 2...")
    params = client.suggested_params()
    create_txn = ApplicationCreateTxn(
        accounts.admin_addr, params, OnComplete.NoOpOC, 
        approval_prog, clear_prog, 
        global_schema, local_schema, app_args
    )
    signed_create = accounts.admin_signer(create_txn)
    txid = client.send_transaction(signed_create)
    info = wait_for_confirmation(client, txid)
    app_id_2 = info['application-index']
    app_addr_2 = get_application_address(app_id_2)
    print(f"App 2 Deployed: {app_id_2}")
    
    # 2. Opt-in & Fund
    params = client.suggested_params()
    p_txn = PaymentTxn(accounts.sponsor_addr, params, app_addr_2, 500_000)
    params.fee = 2000
    a_txn = ApplicationNoOpTxn(accounts.admin_addr, params, app_id_2, [b"opt_in_asset"], foreign_assets=[confio_id])
    gid = transaction.calculate_group_id([p_txn, a_txn])
    p_txn.group = gid
    a_txn.group = gid
    client.send_transactions([accounts.sponsor_signer(p_txn), accounts.admin_signer(a_txn)])
    wait_for_confirmation(client, a_txn.get_txid())
    
    params = client.suggested_params()
    axfer = AssetTransferTxn(accounts.sponsor_addr, params, app_addr_2, amount_confio, confio_id)
    call = ApplicationNoOpTxn(accounts.admin_addr, params, app_id_2, [b"fund"], foreign_assets=[confio_id])
    gid = transaction.calculate_group_id([axfer, call])
    axfer.group = gid
    call.group = gid
    client.send_transactions([accounts.sponsor_signer(axfer), accounts.admin_signer(call)])
    wait_for_confirmation(client, call.get_txid())
    print("App 2 Funded.")
    
    # 3. Start Timer
    print("Starting Timer...")
    params = client.suggested_params()
    start_txn = ApplicationNoOpTxn(accounts.admin_addr, params, app_id_2, [b"start"])
    signed_start = accounts.admin_signer(start_txn)
    client.send_transaction(signed_start)
    wait_for_confirmation(client, start_txn.get_txid())
    print("Timer Started.")
    
    # 4. Attempt Withdraw (Should Fail)
    print("Attempting to Withdraw (Expect Failure)...")
    try:
        params = client.suggested_params()
        params.fee = 2000
        fail_txn = ApplicationNoOpTxn(accounts.admin_addr, params, app_id_2, [b"withdraw_before_start"], foreign_assets=[confio_id])
        signed_fail = accounts.admin_signer(fail_txn)
        client.send_transaction(signed_fail)
        print("FAILURE: Withdrawal succeeded but should have failed!")
    except Exception as e:
        print("SUCCESS: Withdrawal failed as expected.")
        # Optional: Check error message content if desired
        # print(e)

if __name__ == "__main__":
    run_test()
