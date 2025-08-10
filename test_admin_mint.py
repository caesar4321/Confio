#!/usr/bin/env python
"""
Test admin minting of cUSD backed by T-bills
Uses clawback to mint (transfer from reserve to recipient)
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
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer, AccountTransactionSigner
)
from algosdk.abi import Contract


def get_algod_client():
    """Get Algod client for testnet"""
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def rekey_to_contract():
    """
    Rekey the cUSD asset clawback to the contract
    This allows the contract to mint (clawback from reserve and send to users)
    """
    print("\n" + "="*60)
    print("REKEYING CLAWBACK TO CONTRACT")
    print("="*60)
    
    # Load deployment info
    with open("cusd_deployment.json", "r") as f:
        deployment = json.load(f)
    
    app_address = deployment["app_address"]
    cusd_id = deployment["cusd_asset_id"]
    
    print(f"\nContract Address: {app_address}")
    print(f"cUSD Asset ID: {cusd_id}")
    
    # Get algod client
    algod_client = get_algod_client()
    
    # Get admin account
    mnemonic_phrase = os.environ.get("ALGORAND_CONFIO_CREATOR_MNEMONIC")
    if not mnemonic_phrase:
        print("\n❌ No mnemonic found. Set ALGORAND_CONFIO_CREATOR_MNEMONIC")
        return False
    
    private_key = mnemonic.to_private_key(mnemonic_phrase)
    address = account.address_from_private_key(private_key)
    
    print(f"Admin/Reserve Account: {address}")
    
    # Check current clawback
    asset_info = algod_client.asset_info(cusd_id)
    current_clawback = asset_info['params'].get('clawback')
    
    if current_clawback == app_address:
        print(f"✅ Clawback already set to contract: {app_address}")
        return True
    
    print(f"Current Clawback: {current_clawback}")
    print(f"Updating clawback to contract address...")
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    # Create asset config transaction to update clawback
    from algosdk.transaction import AssetConfigTxn
    
    txn = AssetConfigTxn(
        sender=address,
        sp=params,
        index=cusd_id,
        manager=address,  # Keep manager as admin
        reserve=address,  # Keep reserve as admin  
        freeze=address,   # Keep freeze as admin
        clawback=app_address,  # Set clawback to contract!
        strict_empty_address_check=False
    )
    
    # Sign and send
    signed_txn = txn.sign(private_key)
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Transaction ID: {tx_id}")
    
    # Wait for confirmation
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    print(f"✅ Clawback updated to contract in round {confirmed_txn.get('confirmed-round')}")
    
    return True


def test_admin_mint():
    """Test admin minting of cUSD"""
    
    print("\n" + "="*60)
    print("TESTING ADMIN MINT (T-BILLS BACKED)")
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
    
    # Create a test recipient account
    test_private_key, test_address = account.generate_account()
    print(f"Test Recipient: {test_address}")
    
    # First, the recipient needs to opt-in to cUSD
    print("\nOpting recipient into cUSD...")
    
    # Fund the test account first
    from algosdk.transaction import PaymentTxn
    
    params = algod_client.suggested_params()
    
    fund_txn = PaymentTxn(
        sender=admin_address,
        receiver=test_address,
        amt=200_000,  # 0.2 ALGO for fees and minimum balance
        sp=params
    )
    signed_fund = fund_txn.sign(private_key)
    fund_tx_id = algod_client.send_transaction(signed_fund)
    wait_for_confirmation(algod_client, fund_tx_id, 4)
    print("✅ Test account funded")
    
    # First opt-in to the application using the opt_in method
    from algosdk.transaction import ApplicationOptInTxn
    
    # The opt_in method selector
    opt_in_selector = bytes.fromhex("30c6d58a")  # "opt_in()void"
    
    app_opt_in_txn = ApplicationOptInTxn(
        sender=test_address,
        sp=params,
        index=app_id,
        app_args=[opt_in_selector]  # Call the opt_in method
    )
    signed_app_opt_in = app_opt_in_txn.sign(test_private_key)
    app_opt_in_tx_id = algod_client.send_transaction(signed_app_opt_in)
    wait_for_confirmation(algod_client, app_opt_in_tx_id, 4)
    print("✅ Recipient opted into application")
    
    # Then opt-in to cUSD asset
    opt_in_txn = AssetTransferTxn(
        sender=test_address,
        sp=params,
        receiver=test_address,
        amt=0,
        index=cusd_id
    )
    signed_opt_in = opt_in_txn.sign(test_private_key)
    opt_in_tx_id = algod_client.send_transaction(signed_opt_in)
    wait_for_confirmation(algod_client, opt_in_tx_id, 4)
    print("✅ Recipient opted into cUSD asset")
    
    # Load contract ABI
    with open("contracts/cusd_abi.json", "r") as f:
        contract_json = json.load(f)
    
    contract = Contract.from_json(json.dumps(contract_json))
    
    # Create ATC for minting
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner(private_key)
    
    # Amount to mint (1000 cUSD)
    mint_amount = 1_000_000_000  # 1000 cUSD with 6 decimals
    
    print(f"\n💰 Minting {mint_amount/1_000_000:.2f} cUSD to {test_address[:10]}...")
    print("   (Backed by T-bills)")
    
    # Call mint_admin
    params = algod_client.suggested_params()
    
    atc.add_method_call(
        app_id=app_id,
        method=contract.get_method_by_name("mint_admin"),
        sender=admin_address,
        sp=params,
        signer=signer,
        method_args=[mint_amount, test_address],
        foreign_assets=[cusd_id],  # Include cUSD in foreign assets
        accounts=[test_address]  # Include recipient in foreign accounts
    )
    
    try:
        # Execute transaction
        result = atc.execute(algod_client, 4)
        tx_id = result.tx_ids[0]
        
        print(f"\n✅ Admin mint successful!")
        print(f"   Transaction ID: {tx_id}")
        
        # Check recipient balance
        account_info = algod_client.account_info(test_address)
        for asset in account_info.get('assets', []):
            if asset['asset-id'] == cusd_id:
                balance = asset['amount'] / 1_000_000
                print(f"   Recipient cUSD Balance: {balance:.2f} cUSD")
        
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
    # First ensure clawback is set to contract
    if rekey_to_contract():
        # Then test minting
        test_admin_mint()
    else:
        print("\n❌ Failed to setup clawback")