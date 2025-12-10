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
from contracts.vesting.confio_vesting import compile_vesting

# Load Mainnet Env
load_dotenv(ROOT / ".env.mainnet", override=True)

class Accounts:
    def __init__(self, sponsor_addr, sponsor_signer, admin_addr, admin_signer):
        self.sponsor_addr = sponsor_addr
        self.sponsor_signer = sponsor_signer
        # In this script, we use the admin address as the placeholder beneficiary
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

def deploy_susy_vesting():
    print("=== DEPLOYING SUSY'S VESTING TO MAINNET ===")
    
    client = get_client()
    accounts = init_accounts()
    
    confio_id = int(os.getenv("ALGORAND_CONFIO_ASSET_ID"))
    duration = 63_072_000 # 24 months = 2 * 365 * 24 * 3600
    funding_amount = 10_000_000_000_000 # 10,000,000 CONFIO * 10^6 decimals
    
    # Placeholder Beneficiary = Specific Admin Address
    beneficiary = "ZS2HK5N7BZV46ZZGDOQBGFTN3JSXGAFVJFG33WAEP47JQMASSSJIQL7HI4"
    
    print(f"Network: {os.getenv('ALGORAND_NETWORK')}")
    print(f"Admin: {accounts.admin_addr}")
    print(f"Beneficiary (Placeholder): {beneficiary}")
    print(f"Asset ID: {confio_id}")
    print(f"Duration: {duration} seconds (24 months)")
    print(f"Funding: {funding_amount} microCONFIO (10M CONFIO)")
    
    confirm = input("Are you sure? (type 'yes' to proceed): ")
    if confirm != "yes":
        print("Aborted.")
        return

    # 1. Compile & Deploy
    print("Deploying Contract...")
    approval_res = client.compile(compile_vesting())
    approval_prog = base64.b64decode(approval_res["result"])
    clear_prog = base64.b64decode(client.compile("#pragma version 8\nint 1")["result"])
    
    global_schema = StateSchema(num_uints=5, num_byte_slices=2)
    local_schema = StateSchema(num_uints=0, num_byte_slices=0)
    
    app_args = [
        confio_id.to_bytes(8, 'big'),
        encoding.decode_address(beneficiary),
        duration.to_bytes(8, 'big')
    ]
    
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
    print(f"Susy Vesting Deployed! App ID: {app_id}")
    print(f"App Address: {app_addr}")

    # 2. Opt-In
    print("Opting App into CONFIO...")
    sp = client.suggested_params()
    ptxn = PaymentTxn(accounts.sponsor_addr, sp, app_addr, 500_000) # 0.5 Algo for MBR/Gas
    
    sp_inner = client.suggested_params()
    sp_inner.fee = 2000
    atxn = ApplicationNoOpTxn(accounts.admin_addr, sp_inner, app_id, [b"opt_in_asset"], foreign_assets=[confio_id])
    
    gid = transaction.calculate_group_id([ptxn, atxn])
    ptxn.group = gid
    atxn.group = gid
    client.send_transactions([accounts.sponsor_signer(ptxn), accounts.admin_signer(atxn)])
    wait_for_confirmation(client, atxn.get_txid())
    print("Opt-In Complete.")

    # 3. Fund
    print(f"Funding Vault with 10,000,000 CONFIO...")
    sp = client.suggested_params()
    axfer = AssetTransferTxn(accounts.sponsor_addr, sp, app_addr, funding_amount, confio_id)
    call = ApplicationNoOpTxn(accounts.admin_addr, sp, app_id, [b"fund"], foreign_assets=[confio_id])
    
    gid = transaction.calculate_group_id([axfer, call])
    axfer.group = gid
    call.group = gid
    client.send_transactions([accounts.sponsor_signer(axfer), accounts.admin_signer(call)])
    wait_for_confirmation(client, call.get_txid())
    print("Funding Complete.")
    
    print("Deployment Successful!")
    print(f"Use ALGORAND_VESTING_SUSY_APP_ID={app_id}")
    print("REMINDER: Beneficiary is set to Admin. Update later with 'change_beneficiary'.")
    print("REMINDER: Timer has NOT been started.")

if __name__ == "__main__":
    deploy_susy_vesting()
