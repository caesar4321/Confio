#!/usr/bin/env python3
"""
Deploy/Update script for Payment Contract
Builds and deploys a fresh payment app, configures assets/sponsor/fee recipient,
and can also update an existing app's approval/clear programs (merge of update_contract.py).
"""

import os
import sys
import base64
from pathlib import Path
# Ensure project root on sys.path for blockchain imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
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
from blockchain.kms_manager import KMSSigner

# Strict verification helper placed before runtime use
def verify_post_deploy(algod_client, app_id: int, app_address: str, expected_cusd: int, expected_confio: int, expected_sponsor: str):
    import base64
    app = algod_client.application_info(app_id)
    gs = {base64.b64decode(kv['key']).decode('utf-8','ignore'): kv['value'] for kv in app.get('params',{}).get('global-state',[])}
    def get_uint(k):
        v=gs.get(k)
        return int(v.get('uint',0)) if v and v.get('type')==2 else 0
    cusd_id=get_uint('cusd_asset_id'); confio_id=get_uint('confio_asset_id')
    sp=gs.get('sponsor_address'); addr=None
    if sp and sp.get('type')==1:
        from algosdk import encoding as e
        addr=e.encode_address(base64.b64decode(sp.get('bytes','')))
    if cusd_id!=expected_cusd or confio_id!=expected_confio:
        raise SystemExit(f"Verification failed: asset IDs mismatch (got {cusd_id}/{confio_id}, expected {expected_cusd}/{expected_confio})")
    if addr!=expected_sponsor:
        raise SystemExit(f"Verification failed: sponsor mismatch (got {addr}, expected {expected_sponsor})")
    aset_ids={a.get('asset-id') for a in algod_client.account_info(app_address).get('assets',[])}
    missing=[aid for aid in (expected_cusd, expected_confio) if aid not in aset_ids]
    if missing:
        raise SystemExit(f"Verification failed: app not opted into assets {missing}")
    print('✓ Payment app verification passed')
# Add payment dir and project root to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from payment import app as payment_app

# Network configuration
NETWORK = os.environ.get('ALGORAND_NETWORK', 'testnet')

# Prefer explicit environment overrides for Algod endpoint/token
ALGOD_ADDRESS = os.environ.get('ALGORAND_ALGOD_ADDRESS')
ALGOD_TOKEN = os.environ.get('ALGORAND_ALGOD_TOKEN', '')

if not ALGOD_ADDRESS:
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
    """Get admin account signer from KMS if enabled, else from mnemonic."""
    use_kms = os.environ.get('USE_KMS_SIGNING', '').lower() == 'true'
    if use_kms:
        region = os.environ.get('KMS_REGION', 'eu-central-2')
        alias = os.environ.get('KMS_ADMIN_KEY_ALIAS') or os.environ.get('KMS_KEY_ALIAS')
        if not alias:
            print("Error: KMS_ADMIN_KEY_ALIAS or KMS_KEY_ALIAS required when USE_KMS_SIGNING=True")
            sys.exit(1)
        kms_signer = KMSSigner(alias, region_name=region)
        return kms_signer.address, kms_signer.sign_transaction

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
    
    return admin_address, lambda txn: txn.sign(admin_private_key)

def get_required_sponsor_address():
    """Read required sponsor address (no private key needed)."""
    sponsor_address = os.environ.get('ALGORAND_SPONSOR_ADDRESS', '').strip()
    if not sponsor_address:
        print("Error: ALGORAND_SPONSOR_ADDRESS not set in environment")
        sys.exit(1)
    return sponsor_address

def deploy_payment_contract():
    """Deploy the payment contract"""
    
    print(f"Deploying Payment Contract to {NETWORK}...")
    
    # Get accounts
    admin_address, admin_signer = get_admin_account()
    sponsor_address = get_required_sponsor_address()
    
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
    print("\nBuilding contract (approval + clear)...")
    app_spec = payment_app.build()
    contract = app_spec.contract
    
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
    signed_txn = admin_signer(create_txn)
    
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
        
        # Payment to fund app with exact amount required by setup_assets (2 * 0.1 ALGO)
        fund_txn = PaymentTxn(
            sender=admin_address,
            sp=params,
            receiver=app_address,
            amt=300_000  # Base (0.1) + 2 ASA opt-ins (0.2) = 0.3 ALGO
        )
        
        # Setup assets call
        # Create method selector for setup_assets
        method = contract.get_method_by_name("setup_assets")
        
        params.flat_fee = True
        params.fee = 3000  # Base + 2 inner transactions
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
        signed_fund = admin_signer(fund_txn)
        signed_setup = admin_signer(setup_txn)

        # Send grouped transaction
        tx_id = algod_client.send_transactions([signed_fund, signed_setup])
        print(f"Setup transaction sent: {tx_id}")
        
        # Wait for confirmation
        wait_for_confirmation(algod_client, tx_id, 10)
        print("✅ Assets setup complete")
    
    # Pause -> Set sponsor -> Unpause (contract requires paused state)
    print(f"\nPausing contract to set sponsor...")
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = params.min_fee
    pause_method = contract.get_method_by_name("pause")
    pause_txn = ApplicationCallTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        on_complete=OnComplete.NoOpOC,
        app_args=[pause_method.get_selector()],
    )
    signed_pause = admin_signer(pause_txn)
    algod_client.send_transaction(signed_pause)
    wait_for_confirmation(algod_client, signed_pause.transaction.get_txid(), 10)

    print("\nSetting sponsor address...")
    method = contract.get_method_by_name("set_sponsor")
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = params.min_fee
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
    signed_txn = admin_signer(sponsor_txn)
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Set sponsor transaction sent: {tx_id}")
    wait_for_confirmation(algod_client, tx_id, 10)
    print("✅ Sponsor address set")

    print("\nUnpausing contract...")
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = params.min_fee
    unpause_method = contract.get_method_by_name("unpause")
    unpause_txn = ApplicationCallTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        on_complete=OnComplete.NoOpOC,
        app_args=[unpause_method.get_selector()],
    )
    signed_unpause = admin_signer(unpause_txn)
    algod_client.send_transaction(signed_unpause)
    wait_for_confirmation(algod_client, signed_unpause.transaction.get_txid(), 10)
    print("✅ Contract unpaused")
    
    # Set fee recipient (use admin as default)
    print(f"\nSetting fee recipient...")
    
    # Create method selector for update_fee_recipient
    method = contract.get_method_by_name("update_fee_recipient")
    
    params = algod_client.suggested_params()
    params.flat_fee = True
    params.fee = params.min_fee
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
    signed_txn = admin_signer(fee_txn)
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
        
        signed_emergency = admin_signer(emergency_txn)
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
    
    verify_post_deploy(algod_client, app_id, app_address, CUSD_ASSET_ID, CONFIO_ASSET_ID, sponsor_address)
    print(f"\n🎉 Payment contract deployed successfully!")
    print(f"   App ID: {app_id}")
    print(f"   App Address: {app_address}")
    
    return app_id, app_address


def update_payment_contract(app_id: int):
    """Update an existing payment app with freshly built approval/clear programs.

    Mirrors the functionality previously in update_contract.py.
    """
    print(f"Updating Payment Contract app_id={app_id} on {NETWORK}...")

    admin_address, admin_signer = get_admin_account()
    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    # Build and compile latest programs
    print("Building latest approval/clear TEAL...")
    app_spec = payment_app.build()
    approval_result = algod_client.compile(app_spec.approval_program)
    approval_program = base64.b64decode(approval_result['result'])
    clear_result = algod_client.compile(app_spec.clear_program)
    clear_program = base64.b64decode(clear_result['result'])
    print(f"Approval size: {len(approval_program)} bytes, Clear size: {len(clear_program)} bytes")

    # Suggested params
    params = algod_client.suggested_params()

    # Get update method selector from the contract spec
    update_method = app_spec.contract.get_method_by_name("update")
    update_selector = update_method.get_selector()

    # Create UpdateApplication transaction with selector
    update_txn = ApplicationCallTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        on_complete=OnComplete.UpdateApplicationOC,
        approval_program=approval_program,
        clear_program=clear_program,
        app_args=[update_selector],
    )


    signed_update = admin_signer(update_txn)
    tx_id = algod_client.send_transaction(signed_update)
    print(f"Update transaction sent: {tx_id}")
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
    print(f"✅ Contract updated in round {confirmed_txn.get('confirmed-round', 0)}")

    return app_id


def configure_payment_app(app_id: int):
    """Run idempotent configuration steps (assets opt-in, sponsor, fee recipient)."""
    admin_address, admin_signer = get_admin_account()
    sponsor_address, _ = get_sponsor_account()
    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    app_address = logic.get_application_address(app_id)

    # Assets setup if IDs are provided
    if CUSD_ASSET_ID and CONFIO_ASSET_ID:
        print("\n[Configure] Ensuring app is funded and opted-in to assets...")
        app_info = algod_client.account_info(app_address)
        current_balance = app_info.get('amount', 0)
        assets = app_info.get('assets', [])
        opted_in_assets = {a.get('asset-id') for a in assets}

        # Minimal funding + two opt-ins (0.3 ALGO) if needed
        params = algod_client.suggested_params()
        fund_amt = 0
        if CUSD_ASSET_ID not in opted_in_assets or CONFIO_ASSET_ID not in opted_in_assets:
            fund_amt = 300_000
        if fund_amt:
            fund_txn = PaymentTxn(sender=admin_address, sp=params, receiver=app_address, amt=fund_amt)
            stx = admin_signer(fund_txn)
            txid = algod_client.send_transaction(stx)
            wait_for_confirmation(algod_client, txid, 10)

        # Call setup_assets (idempotent in contract)
        params = algod_client.suggested_params()
        method = Method(
            name="setup_assets",
            args=[Argument(arg_type="uint64", name="cusd_id"), Argument(arg_type="uint64", name="confio_id")],
            returns=Returns(arg_type="void"),
        )
        params.fee = 3000
        setup_txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=app_id,
            on_complete=OnComplete.NoOpOC,
            app_args=[method.get_selector(), CUSD_ASSET_ID.to_bytes(8, 'big'), CONFIO_ASSET_ID.to_bytes(8, 'big')],
            foreign_assets=[CUSD_ASSET_ID, CONFIO_ASSET_ID],
        )
        stx = admin_signer(setup_txn)
        txid = algod_client.send_transaction(stx)
        wait_for_confirmation(algod_client, txid, 10)
        print("✅ Assets configured")

    # Sponsor address (optional)
    if sponsor_address:
        print("\n[Configure] Ensuring sponsor address is set...")
        method = Method(
            name="set_sponsor",
            args=[Argument(arg_type="address", name="sponsor")],
            returns=Returns(arg_type="void"),
        )
        params = algod_client.suggested_params()
        sponsor_txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=app_id,
            on_complete=OnComplete.NoOpOC,
            app_args=[method.get_selector(), decode_address(sponsor_address)],
        )
        stx = admin_signer(sponsor_txn)
        txid = algod_client.send_transaction(stx)
        wait_for_confirmation(algod_client, txid, 10)
        print("✅ Sponsor configured")

    # Fee recipient (default to admin)
    print("\n[Configure] Ensuring fee recipient is set...")
    method = Method(
        name="update_fee_recipient",
        args=[Argument(arg_type="address", name="new_recipient")],
        returns=Returns(arg_type="void"),
    )
    params = algod_client.suggested_params()
    fee_txn = ApplicationCallTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        on_complete=OnComplete.NoOpOC,
        app_args=[method.get_selector(), decode_address(admin_address)],
    )
    stx = admin_signer(fee_txn)
    txid = algod_client.send_transaction(stx)
    wait_for_confirmation(algod_client, txid, 10)
    print("✅ Fee recipient configured")

    return app_id


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Deploy or update the Payment contract")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("deploy", help="Deploy a new app and configure it (default)")
    up = sub.add_parser("update", help="Update an existing app's approval/clear and reconfigure")
    up.add_argument("--app-id", type=int, default=int(os.environ.get('ALGORAND_PAYMENT_APP_ID', '0')), help="Existing app id (or env ALGORAND_PAYMENT_APP_ID)")

    args = parser.parse_args()

    cmd = args.command or "deploy"
    if cmd == "deploy":
        app_id, app_addr = deploy_payment_contract()
        print(f"\nDone. App ID: {app_id}, Address: {app_addr}")
    elif cmd == "update":
        if not args.app_id:
            print("--app-id is required (or set ALGORAND_PAYMENT_APP_ID)")
            sys.exit(1)
        app_id = update_payment_contract(args.app_id)
        print(f"\nDone updating app {app_id}.")
    else:
        parser.print_help()

# (verify_post_deploy defined above)
