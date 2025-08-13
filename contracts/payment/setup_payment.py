#!/usr/bin/env python3
"""
Setup script for existing Payment Contract
Configures assets and sponsor for an already deployed payment contract
"""

import os
import sys
from pathlib import Path
from algosdk import account, mnemonic, logic
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCallTxn,
    PaymentTxn,
    OnComplete,
    wait_for_confirmation,
    assign_group_id
)
from algosdk.abi import Method, Returns, Argument
from algosdk.encoding import decode_address

# Network configuration
NETWORK = os.environ.get('ALGORAND_NETWORK', 'testnet')

if NETWORK == 'testnet':
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
else:  # localnet
    ALGOD_ADDRESS = "http://localhost:4001"
    ALGOD_TOKEN = "a" * 64

# Contract and Asset IDs
PAYMENT_APP_ID = int(os.environ.get('ALGORAND_PAYMENT_APP_ID', '0'))
CUSD_ASSET_ID = int(os.environ.get('ALGORAND_CUSD_ASSET_ID', '744192921'))
CONFIO_ASSET_ID = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', '744150851'))

def get_admin_account():
    """Get admin account from environment"""
    admin_mnemonic = os.environ.get('ALGORAND_ADMIN_MNEMONIC', os.environ.get('ALGORAND_SPONSOR_MNEMONIC'))
    if not admin_mnemonic:
        print("Error: ALGORAND_ADMIN_MNEMONIC not set in environment")
        sys.exit(1)
    
    admin_private_key = mnemonic.to_private_key(admin_mnemonic)
    admin_address = account.address_from_private_key(admin_private_key)
    
    return admin_address, admin_private_key

def get_sponsor_account():
    """Get sponsor account from environment"""
    sponsor_mnemonic = os.environ.get('ALGORAND_SPONSOR_MNEMONIC')
    if not sponsor_mnemonic:
        print("Warning: ALGORAND_SPONSOR_MNEMONIC not set - sponsor features will be disabled")
        return None, None
    
    sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
    sponsor_address = account.address_from_private_key(sponsor_private_key)
    
    return sponsor_address, sponsor_private_key

def setup_payment_contract():
    """Setup the existing payment contract"""
    
    print(f"Setting up Payment Contract {PAYMENT_APP_ID} on {NETWORK}...")
    
    # Get accounts
    admin_address, admin_private_key = get_admin_account()
    sponsor_address, sponsor_private_key = get_sponsor_account()
    
    print(f"Admin address: {admin_address}")
    if sponsor_address:
        print(f"Sponsor address: {sponsor_address}")
    
    # Initialize Algod client
    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    # Get app address
    app_address = logic.get_application_address(PAYMENT_APP_ID)
    print(f"Application address: {app_address}")
    
    # Check if assets are already set up
    try:
        app_info = algod_client.application_info(PAYMENT_APP_ID)
        global_state = app_info['params']['global-state']
        
        # Check if assets are already configured
        cusd_configured = False
        confio_configured = False
        sponsor_configured = False
        
        for item in global_state:
            key = item['key']
            # Decode base64 keys
            import base64
            decoded_key = base64.b64decode(key).decode('utf-8', errors='ignore')
            
            if 'cusd_asset_id' in decoded_key:
                value = item['value'].get('uint', 0)
                if value > 0:
                    cusd_configured = True
                    print(f"cUSD already configured: {value}")
            elif 'confio_asset_id' in decoded_key:
                value = item['value'].get('uint', 0)
                if value > 0:
                    confio_configured = True
                    print(f"CONFIO already configured: {value}")
            elif 'sponsor_address' in decoded_key:
                value = item['value'].get('bytes', '')
                if value:
                    sponsor_configured = True
                    print(f"Sponsor already configured")
        
        # Setup assets if not configured
        if not cusd_configured or not confio_configured:
            print(f"\nSetting up assets...")
            print(f"  cUSD Asset ID: {CUSD_ASSET_ID}")
            print(f"  CONFIO Asset ID: {CONFIO_ASSET_ID}")
            
            # Fund the app for asset opt-ins (0.2 ALGO for 2 assets)
            params = algod_client.suggested_params()
            
            # Payment to fund app
            fund_txn = PaymentTxn(
                sender=admin_address,
                sp=params,
                receiver=app_address,
                amt=200_000  # 0.2 ALGO for 2 asset opt-ins
            )
            
            # Setup assets call
            # Create method selector for setup_assets
            method = Method(
                name="setup_assets",
                args=[
                    Argument(arg_type="uint64", name="cusd_id"),
                    Argument(arg_type="uint64", name="confio_id")
                ],
                returns=Returns(arg_type="void")
            )
            
            params.fee = 2000  # Cover inner transactions
            setup_txn = ApplicationCallTxn(
                sender=admin_address,
                sp=params,
                index=PAYMENT_APP_ID,
                on_complete=OnComplete.NoOpOC,
                app_args=[
                    method.get_selector(),
                    CUSD_ASSET_ID.to_bytes(8, 'big'),
                    CONFIO_ASSET_ID.to_bytes(8, 'big')
                ],
                foreign_assets=[CUSD_ASSET_ID, CONFIO_ASSET_ID]  # Include assets
            )
            
            # Group transactions
            txns = [fund_txn, setup_txn]
            assign_group_id(txns)
            
            # Sign transactions
            signed_fund = fund_txn.sign(admin_private_key)
            signed_setup = setup_txn.sign(admin_private_key)
            
            # Send grouped transaction
            tx_id = algod_client.send_transactions([signed_fund, signed_setup])
            print(f"Setup transaction sent: {tx_id}")
            
            # Wait for confirmation
            wait_for_confirmation(algod_client, tx_id, 10)
            print("✅ Assets setup complete")
        else:
            print("✅ Assets already configured")
        
        # Set sponsor if available and not configured
        if sponsor_address and not sponsor_configured:
            print(f"\nSetting sponsor address...")
            
            # Create method selector for set_sponsor
            method = Method(
                name="set_sponsor",
                args=[Argument(arg_type="address", name="sponsor")],
                returns=Returns(arg_type="void")
            )
            
            params = algod_client.suggested_params()
            sponsor_txn = ApplicationCallTxn(
                sender=admin_address,
                sp=params,
                index=PAYMENT_APP_ID,
                on_complete=OnComplete.NoOpOC,
                app_args=[
                    method.get_selector(),
                    decode_address(sponsor_address)
                ]
            )
            
            # Sign and send
            signed_txn = sponsor_txn.sign(admin_private_key)
            tx_id = algod_client.send_transaction(signed_txn)
            
            print(f"Set sponsor transaction sent: {tx_id}")
            wait_for_confirmation(algod_client, tx_id, 10)
            print("✅ Sponsor address set")
        elif sponsor_configured:
            print("✅ Sponsor already configured")
        
        # Set fee recipient (use admin as default)
        print(f"\nSetting fee recipient to admin...")
        
        # Create method selector for update_fee_recipient
        method = Method(
            name="update_fee_recipient",
            args=[Argument(arg_type="address", name="new_recipient")],
            returns=Returns(arg_type="void")
        )
        
        params = algod_client.suggested_params()
        fee_txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=PAYMENT_APP_ID,
            on_complete=OnComplete.NoOpOC,
            app_args=[
                method.get_selector(),
                decode_address(admin_address)  # Use admin as fee recipient for now
            ]
        )
        
        # Sign and send
        signed_txn = fee_txn.sign(admin_private_key)
        tx_id = algod_client.send_transaction(signed_txn)
        
        print(f"Set fee recipient transaction sent: {tx_id}")
        wait_for_confirmation(algod_client, tx_id, 10)
        print("✅ Fee recipient set")
        
    except Exception as e:
        print(f"Error: {e}")
        raise
    
    # Update .env file
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        print(f"\nUpdating .env file with ALGORAND_PAYMENT_APP_ID={PAYMENT_APP_ID}")
        
        with open(env_file, 'r') as f:
            lines = f.readlines()
        
        # Update or add ALGORAND_PAYMENT_APP_ID
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('ALGORAND_PAYMENT_APP_ID='):
                lines[i] = f'ALGORAND_PAYMENT_APP_ID={PAYMENT_APP_ID}\n'
                updated = True
                break
        
        if not updated:
            lines.append(f'ALGORAND_PAYMENT_APP_ID={PAYMENT_APP_ID}\n')
        
        with open(env_file, 'w') as f:
            f.writelines(lines)
        
        print("✅ .env file updated")
    
    print(f"\n🎉 Payment contract setup complete!")
    print(f"   App ID: {PAYMENT_APP_ID}")
    print(f"   App Address: {app_address}")
    
    return PAYMENT_APP_ID, app_address

if __name__ == "__main__":
    setup_payment_contract()