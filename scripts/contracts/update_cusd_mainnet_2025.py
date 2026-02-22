#!/usr/bin/env python3
"""
cUSD Contract Upgrade Script for Mainnet (Feb 2025)
Removes group_size restriction to allow atomic burn+send groups.

Signs with multisig keys 3, 4, 5 (3-of-5 threshold).
Based on /Users/Julian/Documents/kms/kms_algorand_multisig/sign_cusd_upgrade_2025.py
"""

import os
import json
import boto3
import base64
from pathlib import Path
from algosdk import encoding, transaction
from algosdk.v2client import algod
from algosdk.transaction import Multisig, MultisigTransaction, ApplicationUpdateTxn, wait_for_confirmation

# Configuration
ALGOD_ADDRESS = "https://mainnet-api.algonode.cloud"
ALGOD_TOKEN = ""
CONFIG_FILE = Path("/Users/Julian/Documents/kms/kms_algorand_multisig/config/multisig_config.json")

# cUSD Mainnet App ID
CUSD_APP_ID = 3198259271

# Path to compiled TEAL files
CONFIO_ROOT = Path("/Users/julian/Confio")
APPROVAL_TEAL = CONFIO_ROOT / "contracts/cusd/cusd_approval.teal"
CLEAR_TEAL = CONFIO_ROOT / "contracts/cusd/cusd_clear.teal"

# Enable aws-vault credential process support if needed
os.environ['AWS_SDK_LOAD_CONFIG'] = '1'

# Map account IDs to profiles
ACCOUNT_TO_PROFILE = {
    "452470898957": "confio1",
    "646671391733": "confio2",
    "951122816113": "confio3",
    "783411994047": "confio4",
    "525089404951": "confio5",
}

def decrypt_key_from_ssm(param_name: str, region: str, profile: str) -> str:
    """Retrieve and decrypt Ed25519 private key from SSM."""
    try:
        session = boto3.Session(region_name=region, profile_name=profile)
        ssm = session.client('ssm')
        response = ssm.get_parameter(Name=param_name, WithDecryption=True)
        return response['Parameter']['Value']
    except Exception as e:
        print(f"Warning: Failed with profile {profile}, retrying with default session: {e}")
        try:
            session = boto3.Session(region_name=region)
            ssm = session.client('ssm')
            response = ssm.get_parameter(Name=param_name, WithDecryption=True)
            return response['Parameter']['Value']
        except Exception:
            raise e

def compile_teal(client: algod.AlgodClient, teal_path: Path) -> bytes:
    """Compile TEAL source to bytecode."""
    with open(teal_path, 'r') as f:
        teal_source = f.read()
    
    compile_response = client.compile(teal_source)
    return base64.b64decode(compile_response['result'])

def main():
    print("=" * 60)
    print("CUSD CONTRACT UPGRADE - MAINNET")
    print("Remove group_size restriction for atomic burn+send")
    print("=" * 60)
    
    # Load multisig config
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
        
    multisig_address = config['multisig_address']
    threshold = config['threshold']
    keys = config['keys']
    
    print(f"Multisig Address: {multisig_address}")
    print(f"Threshold: {threshold}-of-{len(keys)}")
    print(f"cUSD App ID: {CUSD_APP_ID}")
    print()
    
    # Connect to Mainnet
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    # Verify TEAL files exist
    print("Verifying TEAL files...")
    if not APPROVAL_TEAL.exists():
        print(f"ERROR: {APPROVAL_TEAL} not found!")
        return
    if not CLEAR_TEAL.exists():
        print(f"ERROR: {CLEAR_TEAL} not found!")
        return
    print(f"✅ Approval: {APPROVAL_TEAL}")
    print(f"✅ Clear: {CLEAR_TEAL}")
    print()
    
    # Compile TEAL
    print("Compiling TEAL programs...")
    approval_program = compile_teal(client, APPROVAL_TEAL)
    clear_program = compile_teal(client, CLEAR_TEAL)
    print(f"✅ Approval program: {len(approval_program)} bytes")
    print(f"✅ Clear program: {len(clear_program)} bytes")
    print()
    
    # Get suggested params
    sp = client.suggested_params()
    
    # Create Application Update Transaction
    print("Creating Application Update Transaction...")
    update_txn = ApplicationUpdateTxn(
        sender=multisig_address,
        sp=sp,
        index=CUSD_APP_ID,
        approval_program=approval_program,
        clear_program=clear_program,
        app_args=[bytes.fromhex("a0e81872")],  # ABI selector for update()void
    )
    
    print(f"Transaction ID: {update_txn.get_txid()}")
    print()
    
    # Create multisig object
    addresses = [key['address'] for key in keys]
    msig = Multisig(version=1, threshold=threshold, addresses=addresses)
    
    # Sign with keys 3, 4, 5 (indices 2, 3, 4)
    signer_indices = [2, 3, 4]
    
    mtx = MultisigTransaction(update_txn, msig)
    
    for idx in signer_indices:
        key_info = keys[idx]
        print(f"Key {idx+1}: Signing with {key_info['region']} ({key_info['kms_alias']})...")
        
        profile = ACCOUNT_TO_PROFILE.get(key_info['account_id'])
        
        try:
            private_key = decrypt_key_from_ssm(
                key_info['ssm_param'],
                key_info['region'],
                profile
            )
            
            ret = mtx.sign(private_key)
            if ret is not None:
                mtx = ret
            print("  ✅ Signed")
            
        except Exception as e:
            print(f"  ❌ Failed: {e}")
            return
            
    # Confirm before submission
    print()
    print("=" * 60)
    print("READY TO SUBMIT TO MAINNET")
    print("=" * 60)
    print(f"App ID: {CUSD_APP_ID}")
    print(f"Approval Size: {len(approval_program)} bytes")
    print(f"Clear Size: {len(clear_program)} bytes")
    print(f"Signers: Keys 3, 4, 5")
    print()
    
    confirm = input("Type 'UPGRADE' to proceed: ")
    if confirm != "UPGRADE":
        print("Aborted.")
        return
    
    # Submit
    print("\nSubmitting to Mainnet...")
    
    try:
        txid = client.send_transaction(mtx)
        print(f"Transaction submitted: {txid}")
        
        print("Waiting for confirmation...")
        confirmed = wait_for_confirmation(client, txid, 4)
        print(f"✅ UPGRADE CONFIRMED in round {confirmed['confirmed-round']}")
        print(f"✅ cUSD Contract App ID {CUSD_APP_ID} has been upgraded!")
        
    except Exception as e:
        print(f"❌ Submission failed: {e}")
        
if __name__ == "__main__":
    main()
