#!/usr/bin/env python3
"""
Deploy escrow contracts to Algorand LocalNet/Testnet
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from algosdk.v2client import algod
from algosdk.transaction import ApplicationCreateTxn, StateSchema, wait_for_confirmation
from pyteal import compileTeal, Mode
from contracts.p2p_escrow import p2p_escrow_contract
from contracts.payment_router import payment_router_contract
from contracts.invite_pool import invite_pool_contract
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN
from contracts.config.localnet_accounts import ADMIN_ADDRESS, ADMIN_PRIVATE_KEY

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

def compile_contract(contract_func):
    """Compile a PyTeal contract to TEAL"""
    program = contract_func()
    return compileTeal(program, Mode.Application, version=8)

def deploy_contract(approval_program, clear_program, global_schema, local_schema, app_args=None):
    """Deploy a smart contract to Algorand"""
    
    # Get suggested parameters
    params = algod_client.suggested_params()
    
    # Create application transaction
    txn = ApplicationCreateTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        on_complete=0,  # NoOp
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=app_args
    )
    
    # Sign transaction
    signed_txn = txn.sign(ADMIN_PRIVATE_KEY)
    
    # Send transaction
    txid = algod_client.send_transaction(signed_txn)
    
    # Wait for confirmation
    confirmed = wait_for_confirmation(algod_client, txid, 4)
    app_id = confirmed["application-index"]
    
    return app_id

def deploy_payment_router(vault_address):
    """Deploy the payment router contract"""
    print("\n📦 Deploying Payment Router...")
    
    # Compile contracts
    approval = compile_contract(payment_router_contract)
    clear = compile_contract(lambda: Return(Int(1)))  # Simple clear program
    
    # Deploy with vault address as argument
    app_id = deploy_contract(
        approval.encode(),
        clear.encode(),
        StateSchema(5, 2),  # 5 ints, 2 bytes global
        StateSchema(0, 0),  # No local state
        app_args=[vault_address.encode()]
    )
    
    print(f"✅ Payment Router deployed: App ID {app_id}")
    return app_id

def deploy_invite_pool(cusd_asset_id, confio_asset_id):
    """Deploy the invite pool contract"""
    print("\n📦 Deploying Invite Pool...")
    
    # Compile contracts
    approval = compile_contract(invite_pool_contract)
    clear = compile_contract(lambda: Return(Int(1)))
    
    # Deploy with asset IDs as arguments
    app_id = deploy_contract(
        approval.encode(),
        clear.encode(),
        StateSchema(6, 2),  # 6 ints, 2 bytes global
        StateSchema(0, 0),  # No local state
        app_args=[
            cusd_asset_id.to_bytes(8, 'big'),
            confio_asset_id.to_bytes(8, 'big')
        ]
    )
    
    print(f"✅ Invite Pool deployed: App ID {app_id}")
    print("   ⚠️  Remember to opt-in the pool to assets before use")
    return app_id

def deploy_p2p_escrow_factory():
    """Deploy a factory contract for P2P escrows (optional)"""
    print("\n📦 P2P Escrow Information:")
    print("   P2P Escrows are deployed per-trade")
    print("   Use p2p_escrow.py to deploy individual escrows")
    print("   Each escrow requires ~0.3 ALGO during trade")
    print("   ALGO is recovered when trade completes")

def main():
    print("=" * 60)
    print("DEPLOYING ESCROW CONTRACTS")
    print("=" * 60)
    
    # Check connection
    try:
        status = algod_client.status()
        print(f"\nConnected to network (round {status.get('last-round', 0)})")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Get network configuration
    network = os.environ.get('ALGORAND_NETWORK', 'localnet')
    
    # Asset IDs (from environment or defaults)
    if network == 'localnet':
        cusd_asset_id = int(os.environ.get('ALGORAND_CUSD_ASSET_ID', 1036))
        confio_asset_id = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', 1057))
        vault_address = ADMIN_ADDRESS  # For testing
    else:
        cusd_asset_id = int(os.environ.get('ALGORAND_CUSD_ASSET_ID', 0))
        confio_asset_id = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', 743890784))
        vault_address = os.environ.get('VAULT_ADDRESS', ADMIN_ADDRESS)
    
    print(f"\n📊 Configuration:")
    print(f"   Network: {network}")
    print(f"   cUSD Asset: {cusd_asset_id}")
    print(f"   CONFIO Asset: {confio_asset_id}")
    print(f"   Vault: {vault_address}")
    
    # Deploy contracts
    try:
        # Payment Router
        router_app_id = deploy_payment_router(vault_address)
        
        # Invite Pool
        pool_app_id = deploy_invite_pool(cusd_asset_id, confio_asset_id)
        
        # P2P Escrow info
        deploy_p2p_escrow_factory()
        
        # Save configuration
        config_file = os.path.join(
            os.path.dirname(__file__), 
            "../config/escrow_config.py"
        )
        
        with open(config_file, "w") as f:
            f.write(f"# Escrow Contract Configuration\n\n")
            f.write(f"# Network: {network}\n")
            f.write(f"PAYMENT_ROUTER_APP_ID = {router_app_id}\n")
            f.write(f"INVITE_POOL_APP_ID = {pool_app_id}\n")
            f.write(f"VAULT_ADDRESS = '{vault_address}'\n\n")
            f.write(f"# Asset IDs\n")
            f.write(f"CUSD_ASSET_ID = {cusd_asset_id}\n")
            f.write(f"CONFIO_ASSET_ID = {confio_asset_id}\n")
        
        print(f"\n✅ Configuration saved to: {config_file}")
        
        print("\n" + "=" * 60)
        print("DEPLOYMENT COMPLETE!")
        print("=" * 60)
        print("\n📝 Next Steps:")
        print("1. Opt-in Invite Pool to assets using opt_in_pool.py")
        print("2. Test Payment Router with test_payment_router.py")
        print("3. Deploy P2P escrows on-demand using create_p2p_trade.py")
        
    except Exception as e:
        print(f"\n❌ Deployment failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()