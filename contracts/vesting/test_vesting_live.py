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
        self.admin_addr = admin_addr
        self.admin_signer = admin_signer

def init_accounts():
    kms_enabled = os.getenv("USE_KMS_SIGNING", "").lower() == "true"
    if kms_enabled:
        region = os.getenv("KMS_REGION", "eu-central-2")
        sponsor_alias = os.getenv("KMS_KEY_ALIAS", "confio-testnet-sponsor")
        # Admin usually same as sponsor in this setup unless specified
        admin_alias = sponsor_alias 
        
        print(f"Using KMS: {sponsor_alias} ({region})")
        sponsor_kms = KMSSigner(sponsor_alias, region_name=region)
        
        return Accounts(
            sponsor_addr=sponsor_kms.address,
            sponsor_signer=sponsor_kms.sign_transaction,
            admin_addr=sponsor_kms.address,
            admin_signer=sponsor_kms.sign_transaction
        )
    else:
        # Fallback to mnemonics
        print("Using Mnemonics")
        mnemonic_phrase = os.getenv("ALGORAND_SPONSOR_MNEMONIC") or os.getenv("ALGORAND_ADMIN_MNEMONIC")
        if not mnemonic_phrase:
            raise ValueError("No mnemonics found and KMS not enabled")
            
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
    print(f"Transaction {txid} confirmed in round {txinfo.get('confirmed-round')}")
    return txinfo

def run_test():
    client = get_client()
    accounts = init_accounts()
    
    print(f"Admin/Sponsor: {accounts.admin_addr}")
    
    # Config
    confio_id = int(os.getenv("ALGORAND_CONFIO_ASSET_ID"))
    print(f"CONFIO Asset ID: {confio_id}")
    
    # 1. Create Ephemeral Beneficiary
    ben_key, ben_addr = account.generate_account()
    print(f"Beneficiary: {ben_addr}")
    
    # 2. Fund Beneficiary with ALGO (for opt-in fees)
    print("Funding beneficiary...")
    params = client.suggested_params()
    pay_txn = PaymentTxn(accounts.sponsor_addr, params, ben_addr, 2_000_000) # 2 ALGO
    signed_pay = accounts.sponsor_signer(pay_txn)
    txid = client.send_transaction(signed_pay)
    wait_for_confirmation(client, txid)
    
    # 3. Beneficiary Opt-in to CONFIO
    print("Beneficiary opting into CONFIO...")
    params = client.suggested_params()
    optin_txn = AssetTransferTxn(ben_addr, params, ben_addr, 0, confio_id)
    signed_optin = optin_txn.sign(ben_key)
    txid = client.send_transaction(signed_optin)
    wait_for_confirmation(client, txid)
    
    # 4. Deploy Vesting Contract
    print("Deploying Vesting Contract...")
    # Compile
    approval_teal = compile_vesting()
    approval_prog = base64.b64decode(client.compile(approval_teal)["result"])
    clear_prog = base64.b64decode(client.compile("#pragma version 8\nint 1")["result"])
    
    # Short duration: 300 seconds (5 mins)
    duration = 300
    
    global_schema = StateSchema(num_uints=5, num_byte_slices=2)
    local_schema = StateSchema(num_uints=0, num_byte_slices=0)
    
    app_args = [
        confio_id.to_bytes(8, 'big'),
        encoding.decode_address(ben_addr),
        duration.to_bytes(8, 'big')
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
    app_addr = txinfo['application-index'] # No, logic.get_application_address(app_id)
    from algosdk.logic import get_application_address
    app_addr = get_application_address(app_id)
    print(f"Vesting App Deployed: {app_id} ({app_addr})")
    
    # 5. Admin opts-in App to CONFIO
    print("Opting App into CONFIO...")
    # Need to fund App with ALGO for MBR (0.1 for account + 0.1 for ASA = 0.2 min)
    # Let's send 1 ALGO to be safe
    params = client.suggested_params()
    fund_algo_txn = PaymentTxn(accounts.sponsor_addr, params, app_addr, 1_000_000)
    
    # Opt-in call
    params.fee = 2000 # Double fee for inner txn
    app_optin_txn = ApplicationNoOpTxn(
        accounts.admin_addr, params, app_id, [b"opt_in_asset"], foreign_assets=[confio_id]
    )
    
    # Group them? No, app opt-in logic in contract uses inner txn, so it needs ALGO first.
    # The `opt_in_asset` method in contract does `InnerTxnBuilder`. 
    # It requires the contract to have ALGO balance to pay for inner txn fee?
    # Actually, the caller pays fees. 
    # Contract: `opt_in_asset`: `Itxn fee: 0`. implies pooled fees.
    # So the outer txn must cover it.
    
    # Issue: Contract needs Minimum Balance Requirement (MBR) to OptIn.
    # 100k (Base) + 100k (ASA) = 200k microAlgo.
    # So we MUST send ALGO first.
    
    # Group: [Payment(Sponsor->App), AppCall(Admin->App)]
    # Note: `opt_in_asset` checks `Txn.sender() == admin`.
    
    # Construct group
    params = client.suggested_params()
    p_txn = PaymentTxn(accounts.sponsor_addr, params, app_addr, 500_000) # 0.5 Algo
    
    params.fee = 2000 # Cover inner txn
    a_txn = ApplicationNoOpTxn(accounts.admin_addr, params, app_id, [b"opt_in_asset"], foreign_assets=[confio_id])
    
    gid = transaction.calculate_group_id([p_txn, a_txn])
    p_txn.group = gid
    a_txn.group = gid
    
    s_p = accounts.sponsor_signer(p_txn)
    s_a = accounts.admin_signer(a_txn)
    
    client.send_transactions([s_p, s_a])
    wait_for_confirmation(client, s_a.get_txid())
    print("App Opted In.")
    
    # 6. Admin funds App with CONFIO (Lock tokens)
    print("Funding Vesting Vault...")
    amount_confio = 100_000 # 0.1 CONFIO (assuming 6 decimals)
    
    params = client.suggested_params()
    # Group: [Axfer(Sponsor->App), AppCall(fund)]
    # Contract `fund_vault` checks: `Gtxn[GroupIndex-1]` is Axfer.
    
    axfer_txn = AssetTransferTxn(accounts.sponsor_addr, params, app_addr, amount_confio, confio_id)
    fund_call_txn = ApplicationNoOpTxn(accounts.admin_addr, params, app_id, [b"fund"], foreign_assets=[confio_id])
    
    gid = transaction.calculate_group_id([axfer_txn, fund_call_txn])
    axfer_txn.group = gid
    fund_call_txn.group = gid
    
    s_axfer = accounts.sponsor_signer(axfer_txn)
    s_fund = accounts.admin_signer(fund_call_txn)
    
    client.send_transactions([s_axfer, s_fund])
    wait_for_confirmation(client, s_fund.get_txid())
    print(f"Vault Funded: {amount_confio}")
    
    # 7. Start Timer
    print("Starting Timer...")
    params = client.suggested_params()
    start_txn = ApplicationNoOpTxn(accounts.admin_addr, params, app_id, [b"start"])
    s_start = accounts.admin_signer(start_txn)
    client.send_transaction(s_start)
    wait_for_confirmation(client, s_start.get_txid())
    print("Timer Started.")
    
    # 8. Wait for vesting
    print("Waiting 15 seconds for partial vesting...")
    time.sleep(15)
    
    # 9. Claim
    print("Beneficiary Claiming...")
    # Claim formula: total * elapsed / duration
    # elapsed ~ 15s. duration = 300s.
    # vested ~ 100k * 15/300 = 100k * 0.05 = 5000 units.
    
    params = client.suggested_params()
    params.fee = 2000 # Cover inner txn
    claim_txn = ApplicationNoOpTxn(ben_addr, params, app_id, [b"claim"], foreign_assets=[confio_id])
    s_claim = claim_txn.sign(ben_key)
    
    try:
        txid = client.send_transaction(s_claim)
        info = wait_for_confirmation(client, txid)
        if "logs" in info and len(info["logs"]) > 0:
            print(f"Logs: {info['logs']}")
        print(f"Claim Successful! TxID: {txid}")
        
        # Check balance
        info = client.account_asset_info(ben_addr, confio_id)
        print(f"Beneficiary Balance: {info['asset-holding']['amount']}")
        
    except Exception as e:
        print(f"Claim Failed: {e}")
        # Debug logs
        if hasattr(e, 'transaction'):
             print(e)
             
if __name__ == "__main__":
    run_test()
