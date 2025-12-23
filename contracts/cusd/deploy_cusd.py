#!/usr/bin/env python3
"""
Deploy cUSD contract to Algorand testnet
Website: https://confio.lat
"""

import os
import json
import sys
import subprocess
import base64
from pathlib import Path

# Ensure project root is on sys.path for `contracts.*` and `blockchain.*` imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import ApplicationCreateTxn, ApplicationUpdateTxn, OnComplete, StateSchema, wait_for_confirmation
from algosdk.transaction import AssetConfigTxn, PaymentTxn, AssetTransferTxn
from algosdk.logic import get_application_address
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, TransactionWithSigner, TransactionSigner
from algosdk.abi import Contract
from algosdk.transaction import ApplicationCallTxn

# Try to import KMSSigner
try:
    from blockchain.kms_manager import KMSSigner
except ImportError:
    KMSSigner = None

BASE_DIR = Path(__file__).resolve().parent
NETWORK = os.environ.get("ALGORAND_NETWORK", "testnet")

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

# Initialize Algod client
algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

# Generic signer wrapper for ATC
class GenericSigner(TransactionSigner):
    def __init__(self, signer_fn):
        self.signer_fn = signer_fn
    
    def sign_transactions(self, txns, indexes):
        # signer_fn expects a single transaction object and returns signed object
        return [self.signer_fn(txns[i]) for i in indexes]

def get_deployer_account():
    """Get deployer account signer from KMS if enabled, else from mnemonic/local creation."""
    use_kms = os.environ.get('USE_KMS_SIGNING', '').lower() == 'true'
    
    if use_kms:
        if KMSSigner is None:
            print("Error: USE_KMS_SIGNING=True but blockchain.kms_manager not found")
            sys.exit(1)
            
        region = os.environ.get('KMS_REGION', 'eu-central-2')
        alias = os.environ.get('KMS_KEY_ALIAS') # For cUSD deployer/sponsor
        
        if not alias:
            print("Error: KMS_KEY_ALIAS required when USE_KMS_SIGNING=True")
            sys.exit(1)
            
        print(f"Using KMS Signer: {alias} ({region})")
        kms_signer = KMSSigner(alias, region_name=region)
        # kms_signer.sign_transaction returns specific signed object, unrelated to "private key"
        return kms_signer.address, kms_signer.sign_transaction, True
    
    # Fallback to Mnemonic
    mnemonic_phrase = os.getenv("ALGORAND_SPONSOR_MNEMONIC")
    if mnemonic_phrase:
        print("Using existing account from ALGORAND_SPONSOR_MNEMONIC")
        private_key = mnemonic.to_private_key(mnemonic_phrase)
        address = account.address_from_private_key(private_key)
        
        def sign_fn(txn):
            return txn.sign(private_key)
            
        return address, sign_fn, False
    else:
        # Create new account (LocalNet flow)
        print("No ALGORAND_SPONSOR_MNEMONIC found. Creating new account...")
        private_key, address = account.generate_account()
        mn = mnemonic.from_private_key(private_key)
        
        print("=" * 60)
        print("NEW ACCOUNT CREATED")
        print("=" * 60)
        print(f"Address: {address}")
        print(f"Mnemonic: {mn}")
        print("=" * 60)
        
        def sign_fn(txn):
            return txn.sign(private_key)
            
        return address, sign_fn, False

def check_balance(address):
    """Check account balance"""
    try:
        account_info = algod_client.account_info(address)
        balance = account_info.get('amount') / 1000000  # Convert microAlgos to Algos
        print(f"Account balance: {balance:.6f} ALGO")
        return balance
    except Exception as e:
        print(f"Error checking balance: {e}")
        return 0

def compile_program(client, source_code):
    """Compile TEAL program"""
    compile_response = client.compile(source_code)
    return base64.b64decode(compile_response['result'])

def deploy_cusd_contract(signer, deployer_address):
    """Deploy the cUSD contract"""
    
    # Read compiled TEAL programs
    with open(BASE_DIR / "cusd_approval.teal", "r") as f:
        approval_source = f.read()
    
    with open(BASE_DIR / "cusd_clear.teal", "r") as f:
        clear_source = f.read()
    
    print("\nCompiling TEAL programs...")
    approval_program = compile_program(algod_client, approval_source)
    clear_program = compile_program(algod_client, clear_source)
    
    global_schema = StateSchema(num_uints=9, num_byte_slices=3)
    local_schema = StateSchema(num_uints=2, num_byte_slices=0)
    
    params = algod_client.suggested_params()
    create_method_selector = bytes.fromhex("4c5c61ba")
    
    txn = ApplicationCreateTxn(
        sender=deployer_address,
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=[create_method_selector],
        extra_pages=3
    )
    
    # Sign transaction
    signed_txn = signer(txn)
    
    print("\nDeploying contract...")
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Transaction ID: {tx_id}")
    
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    app_id = confirmed_txn['application-index']
    app_address = get_application_address(app_id)
    
    print(f"\n✅ Contract deployed successfully!")
    print(f"Application ID: {app_id}")
    print(f"Application Address: {app_address}")
    
    return app_id, app_address

def update_cusd_contract(app_id, signer, admin_address):
    """Update an existing cUSD contract"""
    
    with open(BASE_DIR / "cusd_approval.teal", "r") as f:
        approval_source = f.read()
    
    with open(BASE_DIR / "cusd_clear.teal", "r") as f:
        clear_source = f.read()
    
    print("\nCompiling TEAL programs for update...")
    approval_program = compile_program(algod_client, approval_source)
    clear_program = compile_program(algod_client, clear_source)
    
    print(f"Approval program size: {len(approval_program)} bytes")
    print(f"Clear program size: {len(clear_program)} bytes")
    
    params = algod_client.suggested_params()
    update_selector = bytes.fromhex("a0e81872")  # update()void
    
    txn = ApplicationUpdateTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        approval_program=approval_program,
        clear_program=clear_program,
        app_args=[update_selector]
    )
    
    signed_txn = signer(txn)
    
    print("\nUpdating contract...")
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Transaction ID: {tx_id}")
    
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    
    print(f"\n✅ Contract updated successfully!")
    print(f"Update confirmed in round: {confirmed_txn.get('confirmed-round', 0)}")
    
    return True

def set_sponsor_address(app_id, signer, admin_address, sponsor_address=None):
    """Set the sponsor address in the contract"""
    from algosdk.abi import Method, Returns, Argument
    from algosdk import encoding
    
    if sponsor_address is None:
        sponsor_address = admin_address
    
    print(f"\nSetting sponsor address to: {sponsor_address}")
    
    params = algod_client.suggested_params()
    
    method = Method(
        name="set_sponsor_address",
        args=[Argument(arg_type="address", name="sponsor")],
        returns=Returns("void")
    )
    
    selector = method.get_selector()
    sponsor_bytes = encoding.decode_address(sponsor_address)
    
    txn = ApplicationCallTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        on_complete=0,
        app_args=[selector, sponsor_bytes]
    )
    
    signed_txn = signer(txn)
    tx_id = algod_client.send_transaction(signed_txn)
    
    print(f"Set sponsor transaction sent: {tx_id}")
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    print(f"✅ Sponsor address set successfully in round {confirmed_txn.get('confirmed-round', 0)}")
    return True

def create_cusd_asset(signer, creator_address, app_address):
    """Create the cUSD asset (ASA) with app holding all reserve"""
    
    params = algod_client.suggested_params()
    MAX_UINT64 = 18_446_744_073_709_551_615
    
    txn = AssetConfigTxn(
        sender=creator_address,
        sp=params,
        total=MAX_UINT64,
        default_frozen=False,
        unit_name="cUSD",
        asset_name="Confío Dollar",
        manager=creator_address,
        reserve=app_address,
        freeze=app_address,
        clawback=app_address,
        url="https://confio.lat",
        decimals=6
    )
    
    signed_txn = signer(txn)
    
    print("\nCreating cUSD asset...")
    tx_id = algod_client.send_transaction(signed_txn)
    print(f"Transaction ID: {tx_id}")
    
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 4)
    asset_id = confirmed_txn['asset-index']
    
    print(f"\n✅ cUSD asset created successfully! Asset ID: {asset_id}")
    
    return asset_id

def setup_assets(app_id, app_address, cusd_asset_id, usdc_asset_id, signer, admin_address):
    """Call setup_assets on the contract to configure asset IDs"""
    
    print("\nSetting up assets in contract...")
    
    with open(BASE_DIR / "cusd.json", "r") as f:
        abi_json = json.load(f)
    
    contract = Contract.from_json(json.dumps(abi_json))
    params = algod_client.suggested_params()
    atc = AtomicTransactionComposer()
    
    payment_txn = PaymentTxn(
        sender=admin_address,
        sp=params,
        receiver=app_address,
        amt=600000 
    )
    
    atc_signer = GenericSigner(signer)
    atc.add_transaction(TransactionWithSigner(payment_txn, atc_signer))
    
    method_params = algod_client.suggested_params()
    method_params.flat_fee = True
    method_params.fee = 3000
    
    atc.add_method_call(
        app_id=app_id,
        method=contract.get_method_by_name("setup_assets"),
        sender=admin_address,
        sp=method_params,
        signer=atc_signer,
        method_args=[cusd_asset_id, usdc_asset_id],
        foreign_assets=[cusd_asset_id, usdc_asset_id]
    )
    
    result = atc.execute(algod_client, 4)
    print(f"✅ Assets configured successfully! Transaction IDs: {result.tx_ids}")
    return result

def lock_manager_zero(asset_id: int, signer, admin_address: str, app_address: str):
    """Reconfigure ASA to lock manager to zero."""
    info = algod_client.asset_info(asset_id)
    params = info.get("params", {})
    current_manager = params.get("manager") or ""
    reserve = params.get("reserve")
    freeze = params.get("freeze")
    clawback = params.get("clawback")

    if not current_manager:
        print(f"Manager already zero for asset {asset_id}; skipping lock.")
        return

    sp = algod_client.suggested_params()
    txn = AssetConfigTxn(
        sender=admin_address,
        sp=sp,
        index=asset_id,
        manager=None,
        reserve=reserve or app_address,
        freeze=freeze or app_address,
        clawback=clawback or app_address,
        strict_empty_address_check=False,
    )
    
    signed_txn = signer(txn)
    tx_id = algod_client.send_transaction(signed_txn)
    
    print(f"Lock manager TX: {tx_id}")
    wait_for_confirmation(algod_client, tx_id, 4)
    print(f"\n🔒 Manager locked to zero address")

def main():
    """Main deployment function"""
    
    # Check command line arguments
    update_mode = len(sys.argv) > 1 and sys.argv[1] == "update"
    
    if update_mode:
        print("\n" + "="*60)
        print("CONFÍO DOLLAR (cUSD) - CONTRACT UPDATE")
        print("="*60)
    else:
        print("\n" + "="*60)
        print(f"CONFÍO DOLLAR (cUSD) - {NETWORK.upper()} DEPLOYMENT")
        print("="*60)
    
    # Get deployer account (address and signer function)
    deployer_address, deployer_signer, is_kms = get_deployer_account()
    
    # Check balance
    balance = check_balance(deployer_address)
    if balance < 0.1:
        if NETWORK == "localnet" and not is_kms:
            print(f"\nAccount underfunded; attempting auto-funding...")
            # Simple subprocess call logic for localnet dispense could be added here if needed
            pass
            
        print(f"\n❌ Insufficient balance. Please fund the account: {deployer_address}")
        return
    
    try:
        if update_mode:
            # Update existing contract
            app_id = int(os.environ.get("ALGORAND_CUSD_APP_ID", "0"))
            if app_id == 0:
                print("❌ ALGORAND_CUSD_APP_ID not set")
                return
            
            print(f"\nUpdating existing contract: {app_id}")
            
            # Update (compile and send update txn)
            if update_cusd_contract(app_id, deployer_signer, deployer_address):
                # Set sponsor address (often same as admin/deployer in simplified setup)
                # sponsor = os.environ.get("ALGORAND_SPONSOR_ADDRESS", deployer_address)
                # set_sponsor_address(app_id, deployer_signer, deployer_address, sponsor)
                print("\n✅ Update complete!")
            return
            
        # --- FRESH DEPLOYMENT FLOW ---
        # Step 1: Deploy contract
        app_id, app_address = deploy_cusd_contract(deployer_signer, deployer_address)
        
        # Step 2: Create cUSD asset
        cusd_asset_id = create_cusd_asset(deployer_signer, deployer_address, app_address)
        
        # Step 3: Setup assets
        usdc_asset_id = int(os.environ.get("ALGORAND_USDC_ASSET_ID", "10458941")) # Default to Testnet USDC
        setup_assets(app_id, app_address, cusd_asset_id, usdc_asset_id, deployer_signer, deployer_address)
        
        # Step 4: Sponsor setup
        sponsor = os.environ.get("ALGORAND_SPONSOR_ADDRESS", deployer_address)
        set_sponsor_address(app_id, deployer_signer, deployer_address, sponsor)
        
        # Step 5: Transfer MAX supply to contract
        print("\nSTEP 4: SECURING RESERVE (Transfer MAX supply to contract)")
        MAX_UINT64 = 18_446_744_073_709_551_615
        params = algod_client.suggested_params()
        
        transfer_txn = AssetTransferTxn(
            sender=deployer_address,
            sp=params,
            receiver=app_address,
            amt=MAX_UINT64,
            index=cusd_asset_id
        )
        
        signed_tx = deployer_signer(transfer_txn)
        tx_id = algod_client.send_transaction(signed_tx)
        print(f"Transfer TX: {tx_id}")
        wait_for_confirmation(algod_client, tx_id, 4)
        print(f"✅ All {MAX_UINT64:,} units transferred to contract!")
        
        # Step 6: Lock manager
        lock_manager_zero(cusd_asset_id, deployer_signer, deployer_address, app_address)
        
        # Save info
        deployment_info = {
            "network": NETWORK,
            "deployer_address": deployer_address,
            "app_id": app_id,
            "app_address": app_address,
            "cusd_asset_id": cusd_asset_id,
            "usdc_asset_id": usdc_asset_id,
            "deployment_status": "Complete"
        }
        
        with open("deployment_info.json", "w") as f:
            json.dump(deployment_info, f, indent=2)
            
        print("\n✅ Deployment info saved to deployment_info.json")

    except Exception as e:
        print(f"\n❌ Deployment failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
