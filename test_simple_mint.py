#!/usr/bin/env python
"""
Simple test of admin minting - mints to admin's own account
"""

import os
import sys
import django
import json
from pathlib import Path

# Load environment variables from .env.algorand if it exists
env_file = Path('.env.algorand')
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    value = value.strip('"').strip("'")
                    os.environ[key] = value

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer, AccountTransactionSigner
)
from algosdk.abi import Contract


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def test_mint():
    """Test admin minting to admin's own account"""
    
    print("\n" + "="*60)
    print("TESTING ADMIN MINT (SIMPLE)")
    print("="*60)
    
    # Load deployment info
    with open("cusd_deployment.json", "r") as f:
        deployment = json.load(f)
    
    app_id = deployment["app_id"]
    app_address = deployment["app_address"]
    cusd_id = deployment["cusd_asset_id"]
    
    print(f"\nApplication ID: {app_id}")
    print(f"Contract Address: {app_address}")
    print(f"cUSD Asset ID: {cusd_id}")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Get admin account
    mnemonic_phrase = os.environ.get("ALGORAND_CONFIO_CREATOR_MNEMONIC")
    if not mnemonic_phrase:
        print("\n❌ No mnemonic found. Set ALGORAND_CONFIO_CREATOR_MNEMONIC")
        return
    
    private_key = mnemonic.to_private_key(mnemonic_phrase)
    admin_address = account.address_from_private_key(private_key)
    
    print(f"\nAdmin Account: {admin_address}")
    
    # Check contract cUSD balance
    account_info = algod_client.account_info(app_address)
    contract_balance = 0
    for asset in account_info.get('assets', []):
        if asset['asset-id'] == cusd_id:
            contract_balance = asset['amount'] / 1_000_000
            print(f"Contract cUSD Balance: {contract_balance:.2f} cUSD")
            break
    
    if contract_balance == 0:
        print("\n❌ Contract has no cUSD to mint!")
        return
    
    # Check if admin is opted into the app
    admin_info = algod_client.account_info(admin_address)
    opted_in = False
    for app in admin_info.get('apps-local-state', []):
        if app['id'] == app_id:
            opted_in = True
            break
    
    if not opted_in:
        print("\n🔧 Admin needs to opt-in to app first...")
        # Opt-in to the application using the opt_in method
        from algosdk.transaction import ApplicationOptInTxn
        
        # The opt_in method selector
        opt_in_selector = bytes.fromhex("30c6d58a")  # "opt_in()void"
        
        params = algod_client.suggested_params()
        app_opt_in_txn = ApplicationOptInTxn(
            sender=admin_address,
            sp=params,
            index=app_id,
            app_args=[opt_in_selector]  # Call the opt_in method
        )
        signed_app_opt_in = app_opt_in_txn.sign(private_key)
        app_opt_in_tx_id = algod_client.send_transaction(signed_app_opt_in)
        from algosdk.transaction import wait_for_confirmation
        wait_for_confirmation(algod_client, app_opt_in_tx_id, 4)
        print("✅ Admin opted into application")
    
    # Check admin's initial cUSD balance
    initial_balance = 0
    for asset in admin_info.get('assets', []):
        if asset['asset-id'] == cusd_id:
            initial_balance = asset['amount'] / 1_000_000
            print(f"Admin Initial Balance: {initial_balance:.2f} cUSD")
            break
    
    # Load contract ABI
    with open("contracts/cusd_abi.json", "r") as f:
        contract_json = json.load(f)
    
    contract = Contract.from_json(json.dumps(contract_json))
    
    # Create ATC for minting
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(private_key)
    
    # Amount to mint (100 cUSD)
    mint_amount = 100_000_000  # 100 cUSD with 6 decimals
    
    print(f"\n💰 Minting {mint_amount/1_000_000:.2f} cUSD to admin...")
    
    # Call mint_admin
    params = algod_client.suggested_params()
    
    atc.add_method_call(
        app_id=app_id,
        method=contract.get_method_by_name("mint_admin"),
        sender=admin_address,
        sp=params,
        signer=signer,
        method_args=[mint_amount, admin_address],  # Mint to admin's own account
        foreign_assets=[cusd_id],
        accounts=[admin_address]
    )
    
    try:
        # Execute transaction
        result = atc.execute(algod_client, 4)
        tx_id = result.tx_ids[0]
        
        print(f"\n✅ Admin mint successful!")
        print(f"   Transaction ID: {tx_id}")
        
        # Check admin's new balance
        admin_info = algod_client.account_info(admin_address)
        new_balance = 0
        for asset in admin_info.get('assets', []):
            if asset['asset-id'] == cusd_id:
                new_balance = asset['amount'] / 1_000_000
                print(f"   Admin New Balance: {new_balance:.2f} cUSD")
                print(f"   Amount Minted: {new_balance - initial_balance:.2f} cUSD")
                break
        
        # Check contract state
        app_info = algod_client.application_info(app_id)
        global_state = app_info.get('params', {}).get('global-state', [])
        
        print(f"\n📊 Contract State:")
        for item in global_state:
            key = item.get('key', '')
            # Decode base64 key
            import base64
            decoded_key = base64.b64decode(key).decode('utf-8', errors='ignore')
            if 'total_minted' in decoded_key:
                value = item.get('value', {}).get('uint', 0)
                print(f"   Total Minted: {value/1_000_000:.2f} cUSD")
            elif 'tbills_backed' in decoded_key:
                value = item.get('value', {}).get('uint', 0)
                print(f"   T-Bills Backed Supply: {value/1_000_000:.2f} cUSD")
        
    except Exception as e:
        print(f"\n❌ Mint failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_mint()