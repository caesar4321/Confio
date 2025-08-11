#!/usr/bin/env python3
"""
Deploy CONFIO token to LocalNet
This will be used as the collateral asset for cUSD testing (instead of USDC)
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from algosdk import account
from algosdk.v2client import algod
from algosdk.transaction import AssetConfigTxn, wait_for_confirmation
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

def create_confio_token():
    """Create CONFIO token with maximum supply"""
    print("=" * 60)
    print("DEPLOYING CONFIO TOKEN TO LOCALNET")
    print("=" * 60)
    
    # Generate a new account for CONFIO creator
    private_key, address = account.generate_account()
    
    print(f"\nGenerated CONFIO creator account:")
    print(f"  Address: {address}")
    if os.environ.get("ALLOW_PRINT_PRIVATE_KEYS") == "1":
        print(f"  Private Key: {private_key}")
    else:
        print("  Private Key: [REDACTED] (set ALLOW_PRINT_PRIVATE_KEYS=1 to print)")
    
    # Fund the account first
    print("\nFunding creator account...")
    # In LocalNet, we can use the dispenser or a pre-funded account
    # For now, we'll use the first pre-funded account
    from contracts.config.localnet_accounts import ADMIN_ADDRESS, ADMIN_PRIVATE_KEY
    
    params = algod_client.suggested_params()
    
    # Fund the creator account with 10 ALGO
    from algosdk.transaction import PaymentTxn
    funding_txn = PaymentTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        receiver=address,
        amt=10_000_000  # 10 ALGO
    )
    
    signed_funding = funding_txn.sign(ADMIN_PRIVATE_KEY)
    txid = algod_client.send_transaction(signed_funding)
    wait_for_confirmation(algod_client, txid, 4)
    print(f"  Funded with 10 ALGO (txid: {txid})")
    
    # Create CONFIO token
    print("\nCreating CONFIO token...")
    params = algod_client.suggested_params()
    
    # Maximum possible supply for Algorand ASA
    max_supply = 2**64 - 1  # 18,446,744,073,709,551,615
    
    txn = AssetConfigTxn(
        sender=address,
        sp=params,
        total=max_supply,
        default_frozen=False,
        unit_name="CONFIO",
        asset_name="Confio Token",
        manager=address,      # Can update asset
        reserve=address,       # Holds reserve
        freeze=address,        # Can freeze accounts
        clawback=address,      # Can clawback tokens (for minting)
        decimals=6,
        url="https://confio.lat",
        metadata_hash=None
    )
    
    # Sign and send
    signed_txn = txn.sign(private_key)
    txid = algod_client.send_transaction(signed_txn)
    print(f"  Transaction ID: {txid}")
    
    # Wait for confirmation
    confirmed = wait_for_confirmation(algod_client, txid, 4)
    asset_id = confirmed["asset-index"]
    
    print("\n" + "=" * 60)
    print("CONFIO TOKEN DEPLOYED SUCCESSFULLY!")
    print("=" * 60)
    print(f"\nAsset ID: {asset_id}")
    print(f"Creator: {address}")
    print(f"Total Supply: {max_supply:,} (maximum possible)")
    print(f"Decimals: 6")
    print(f"Unit Name: CONFIO")
    
    # Save configuration (no private keys)
    config_file = os.path.join(os.path.dirname(__file__), "../config/confio_token_config.py")
    with open(config_file, "w") as f:
        f.write("# CONFIO Token Configuration for LocalNet\n")
        f.write(f"CONFIO_ASSET_ID = {asset_id}\n")
        f.write(f'CONFIO_CREATOR_ADDRESS = "{address}"\n')
        f.write(f"CONFIO_TOTAL_SUPPLY = {max_supply}\n")
        f.write("CONFIO_DECIMALS = 6\n")
        f.write("# Private keys are not stored here. Use env vars or a key manager.\n")
    
    print(f"\nConfiguration saved to: {config_file}")
    
    return asset_id, address, private_key

if __name__ == "__main__":
    try:
        # Check connection
        status = algod_client.status()
        print(f"Connected to LocalNet (round {status.get('last-round', 0)})")
        
        # Deploy CONFIO
        asset_id, creator_address, creator_key = create_confio_token()
        
        print("\nNext steps:")
        print("1. Use this CONFIO token as collateral for cUSD")
        print("2. Deploy cUSD contract with CONFIO as the collateral asset")
        print("3. Test minting cUSD with CONFIO collateral")
        
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
