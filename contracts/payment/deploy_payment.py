#!/usr/bin/env python3
"""
Deploy script for Payment Contract
Deploys the payment contract to Algorand network and sets up assets
"""

import os
import sys
import base64
from pathlib import Path
from algosdk import account, mnemonic, logic
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCreateTxn,
    ApplicationCallTxn,
    PaymentTxn,
    OnComplete,
    StateSchema,
    wait_for_confirmation,
    assign_group_id
)
from algosdk.abi import Method, Returns, Argument
from algosdk.encoding import decode_address

# Add payment dir and project root to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from payment import app as payment_app

# Network configuration
NETWORK = os.environ.get('ALGORAND_NETWORK', 'testnet')

if NETWORK == 'testnet':
    ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
elif NETWORK == 'mainnet':
    ALGOD_ADDRESS = "https://mainnet-api.algonode.cloud"
    ALGOD_TOKEN = ""
else:  # localnet
    ALGOD_ADDRESS = "http://localhost:4001"
    ALGOD_TOKEN = "a" * 64

# Asset IDs from environment (with LocalNet fallbacks)
CUSD_ASSET_ID = int(os.environ.get('ALGORAND_CUSD_ASSET_ID', '0'))
CONFIO_ASSET_ID = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', '0'))
if NETWORK == 'localnet':
    if CUSD_ASSET_ID == 0:
        try:
            from contracts.config.localnet_assets import CUSD_ASSET_ID as LN_CUSD
            CUSD_ASSET_ID = LN_CUSD
            print(f"Using LocalNet cUSD asset id from config: {CUSD_ASSET_ID}")
        except Exception:
            pass
    if CONFIO_ASSET_ID == 0:
        # Allow override via env var until we add a localnet config file for CONFIO
        CONFIO_ASSET_ID = int(os.environ.get('LOCALNET_CONFIO_ASSET_ID', '0'))
        if CONFIO_ASSET_ID:
            print(f"Using LocalNet CONFIO asset id from env: {CONFIO_ASSET_ID}")

def get_admin_account():
    """Get admin account from environment"""
    admin_mnemonic = os.environ.get('ALGORAND_ADMIN_MNEMONIC')
    if not admin_mnemonic and NETWORK == 'localnet':
        try:
            from contracts.config.localnet_accounts import ADMIN_MNEMONIC as LN_ADMIN
            admin_mnemonic = LN_ADMIN
            print("Using LocalNet admin mnemonic from config.")
        except Exception:
            pass
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

def deploy_payment_contract():
    """Deploy the payment contract"""
    
    print(f"Deploying Payment Contract to {NETWORK}...")
    
    # Get accounts
    admin_address, admin_private_key = get_admin_account()
    sponsor_address, sponsor_private_key = get_sponsor_account()
    
    print(f"Admin address: {admin_address}")
    if sponsor_address:
        print(f"Sponsor address: {sponsor_address}")
    
    # Initialize Algod client
    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    # Check admin balance
    account_info = algod_client.account_info(admin_address)
    balance = account_info['amount'] / 1_000_000
    print(f"Admin balance: {balance:.6f} ALGO")
    
    if balance < 1.0:
        if NETWORK == 'localnet':
            import subprocess
            print("Admin underfunded; attempting faucet dispense...")
            # Try explicit faucet mnemonic first
            faucet_mn = os.getenv("LOCALNET_FAUCET_MNEMONIC")
            if faucet_mn:
                try:
                    from algosdk import mnemonic as _mn, account as _acct
                    fk = _mn.to_private_key(faucet_mn)
                    faddr = _acct.address_from_private_key(fk)
                    params = algod_client.suggested_params()
                    ptxn = PaymentTxn(sender=faddr, sp=params, receiver=admin_address, amt=5_000_000)
                    stx = ptxn.sign(fk)
                    txid = algod_client.send_transaction(stx)
                    wait_for_confirmation(algod_client, txid, 4)
                    account_info = algod_client.account_info(admin_address)
                    balance = account_info['amount'] / 1_000_000
                    print(f"Admin balance after faucet transfer: {balance:.6f} ALGO")
                except Exception as e:
                    print(f"Faucet mnemonic funding failed: {e}")
            if balance < 1.0:
                print("Attempting Algokit localnet dispense...")
                try:
                    res = subprocess.run(["algokit", "localnet", "dispense", "-a", admin_address], capture_output=True, text=True)
                    if res.returncode == 0:
                        account_info = algod_client.account_info(admin_address)
                        balance = account_info['amount'] / 1_000_000
                        print(f"Admin balance after dispense: {balance:.6f} ALGO")
                    else:
                        print(f"Algokit dispense failed (rc={res.returncode}): {res.stderr.strip()}")
                except Exception as e:
                    print(f"Algokit not available: {e}")
        if balance < 1.0:
            print("Error: Admin account needs at least 1 ALGO for deployment")
            sys.exit(1)
    
    # Build the contract
    print("\nBuilding contract...")
    app_spec = payment_app.build()
    
    # Compile the programs
    approval_result = algod_client.compile(app_spec.approval_program)
    approval_program = base64.b64decode(approval_result['result'])
    
    clear_result = algod_client.compile(app_spec.clear_program)
    clear_program = base64.b64decode(clear_result['result'])
    
    print(f"Approval program size: {len(approval_program)} bytes")
    print(f"Clear program size: {len(clear_program)} bytes")
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    # Create the application
    print("\nCreating application...")
    
    # Global state schema from contract
    global_schema = StateSchema(
        num_uints=11,  # Statistics and counters
        num_byte_slices=3  # admin, fee_recipient, sponsor_address
    )
    
    # No local state for payment contract
    local_schema = StateSchema(
        num_uints=0,
        num_byte_slices=0
    )
    
    # Calculate extra pages needed (each page is 2048 bytes)
    # Approval program needs to fit in initial 2048 + extra pages
    approval_size = len(approval_program)
    extra_pages = 0
    if approval_size > 2048:
        extra_pages = (approval_size - 2048 + 2047) // 2048  # Ceiling division
        print(f"Approval program requires {extra_pages} extra page(s)")
    
    # Get the create method selector for Beaker
    # The contract's @app.create expects "create()void" selector
    create_method_selector = bytes.fromhex("4c5c61ba")  # create()void
    
    # Create application transaction with method selector (like cUSD does)
    create_txn = ApplicationCreateTxn(
        sender=admin_address,
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=[create_method_selector],  # Pass create method selector
        extra_pages=extra_pages  # Use extra pages for large contract
    )
    
    # Sign and send
    signed_txn = create_txn.sign(admin_private_key)
    
    try:
        tx_id = algod_client.send_transaction(signed_txn)
        print(f"Create transaction sent: {tx_id}")
        
        # Wait for confirmation
        confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
        app_id = confirmed_txn['application-index']
    except Exception as e:
        # Check if app was already created in a previous attempt
        print(f"Error during creation: {e}")
        print("Checking for existing deployment...")
        
        # Try to find the app ID from the error message
        import re
        match = re.search(r'app=(\d+)', str(e))
        if match:
            app_id = int(match.group(1))
            print(f"Found existing app ID from error: {app_id}")
        else:
            raise
    
    print(f"✅ Application created with ID: {app_id}")
    
    # Get app address
    app_address = logic.get_application_address(app_id)
    print(f"Application address: {app_address}")
    
    # Setup assets if they exist
    if CUSD_ASSET_ID and CONFIO_ASSET_ID:
        print(f"\nSetting up assets...")
        print(f"  cUSD Asset ID: {CUSD_ASSET_ID}")
        print(f"  CONFIO Asset ID: {CONFIO_ASSET_ID}")
        
        # Use funding service to calculate proper MBR needed
        import sys
        sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from blockchain.account_funding_service import AccountFundingService
        
        # Create funding service instance
        funding_service = AccountFundingService(network=NETWORK)
        
        # Calculate how much funding is needed for the app
        # The app needs MBR for: base account + 2 asset opt-ins
        app_info = algod_client.account_info(app_address)
        current_balance = app_info.get('amount', 0)
        min_balance = app_info.get('min-balance', 0)
        
        # Check if assets are already opted in
        assets = app_info.get('assets', [])
        opted_in_assets = [asset['asset-id'] for asset in assets]
        
        # Calculate target balance based on what's needed
        # Base: 100,000 microAlgos
        # Per asset opt-in: 100,000 microAlgos each
        target_balance = 100_000  # Base MBR
        
        if CUSD_ASSET_ID not in opted_in_assets:
            target_balance += 100_000  # Need to opt-in to cUSD
        
        if CONFIO_ASSET_ID not in opted_in_assets:
            target_balance += 100_000  # Need to opt-in to CONFIO
        
        funding_needed = max(0, target_balance - current_balance)
        
        if funding_needed > 0:
            print(f"App needs {funding_needed} microAlgos (current: {current_balance}, target: {target_balance})")
        else:
            print(f"App already funded (balance: {current_balance} microAlgos)")
        
        params = algod_client.suggested_params()
        
        # Payment to fund app with calculated amount
        fund_txn = PaymentTxn(
            sender=admin_address,
            sp=params,
            receiver=app_address,
            amt=funding_needed if funding_needed > 0 else 100_000  # At least 0.1 ALGO for setup transaction
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
            index=app_id,
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
    
    # Set sponsor if available
    if sponsor_address:
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
            index=app_id,
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
    
    # Set fee recipient (use admin as default)
    print(f"\nSetting fee recipient...")
    
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
        index=app_id,
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
    
    # Final check: Ensure app has sufficient balance for operations
    print(f"\nFinal balance check...")
    final_app_info = algod_client.account_info(app_address)
    final_balance = final_app_info.get('amount', 0)
    final_min_balance = final_app_info.get('min-balance', 0)
    
    print(f"App final balance: {final_balance} microAlgos")
    print(f"App minimum balance required: {final_min_balance} microAlgos")
    
    if final_balance < final_min_balance:
        # Emergency funding if still insufficient
        emergency_fund = final_min_balance - final_balance + 100_000  # Add 0.1 ALGO buffer
        print(f"⚠️ App still needs {emergency_fund} microAlgos, funding...")
        
        params = algod_client.suggested_params()
        emergency_txn = PaymentTxn(
            sender=admin_address,
            sp=params,
            receiver=app_address,
            amt=emergency_fund
        )
        
        signed_emergency = emergency_txn.sign(admin_private_key)
        tx_id = algod_client.send_transaction(signed_emergency)
        print(f"Emergency funding transaction sent: {tx_id}")
        wait_for_confirmation(algod_client, tx_id, 10)
        print("✅ Emergency funding complete")
    else:
        print(f"✅ App has sufficient balance ({final_balance - final_min_balance} microAlgos above minimum)")
    
    # Write deployment info to file
    deployment_info = {
        "network": NETWORK,
        "app_id": app_id,
        "app_address": app_address,
        "admin_address": admin_address,
        "sponsor_address": sponsor_address,
        "cusd_asset_id": CUSD_ASSET_ID,
        "confio_asset_id": CONFIO_ASSET_ID
    }
    
    output_file = Path(__file__).parent / f"deployment_{NETWORK}.json"
    with open(output_file, "w") as f:
        import json
        json.dump(deployment_info, f, indent=2)
    
    print(f"\n✅ Deployment info saved to {output_file}")
    
    # Update .env file
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        print(f"\nUpdating .env file with ALGORAND_PAYMENT_APP_ID={app_id}")
        
        with open(env_file, 'r') as f:
            lines = f.readlines()
        
        # Update or add ALGORAND_PAYMENT_APP_ID
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('ALGORAND_PAYMENT_APP_ID='):
                lines[i] = f'ALGORAND_PAYMENT_APP_ID={app_id}\n'
                updated = True
                break
        
        if not updated:
            lines.append(f'ALGORAND_PAYMENT_APP_ID={app_id}\n')
        
        with open(env_file, 'w') as f:
            f.writelines(lines)
        
        print("✅ .env file updated")
    
    print(f"\n🎉 Payment contract deployed successfully!")
    print(f"   App ID: {app_id}")
    print(f"   App Address: {app_address}")
    
    return app_id, app_address

if __name__ == "__main__":
    deploy_payment_contract()
