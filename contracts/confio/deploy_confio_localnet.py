#!/usr/bin/env python3
"""
Deploy CONFIO token to LocalNet using the corrected specifications.
This script wraps create_confio_token_algorand.py for LocalNet deployment.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from algosdk import account
from algosdk.v2client import algod
from algosdk.transaction import AssetConfigTxn, wait_for_confirmation, PaymentTxn
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN
from contracts.config.localnet_accounts import ADMIN_ADDRESS, ADMIN_PRIVATE_KEY

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

def main():
    print("=" * 60)
    print("DEPLOYING CONFIO TOKEN TO LOCALNET")
    print("Using corrected specifications: 1B supply, no reserve")
    print("=" * 60)
    
    # Generate a new account for CONFIO creator
    private_key, address = account.generate_account()
    
    print(f"\nGenerated CONFIO creator account:")
    print(f"  Address: {address}")
    if os.environ.get("ALLOW_PRINT_PRIVATE_KEYS") == "1":
        print(f"  Private Key: {private_key}")
    else:
        print("  Private Key: [REDACTED] (set ALLOW_PRINT_PRIVATE_KEYS=1 to print)")
    
    # Fund the account
    print("\nFunding creator account...")
    params = algod_client.suggested_params()
    
    funding_txn = PaymentTxn(
        sender=ADMIN_ADDRESS,
        sp=params,
        receiver=address,
        amt=10_000_000  # 10 ALGO
    )
    
    signed_funding = funding_txn.sign(ADMIN_PRIVATE_KEY)
    txid = algod_client.send_transaction(signed_funding)
    wait_for_confirmation(algod_client, txid, 4)
    print(f"  Funded with 10 ALGO")
    
    # Create CONFIO token with CORRECT parameters from the spec
    print("\nCreating CONFIO token...")
    params = algod_client.suggested_params()
    
    # These parameters match create_confio_token_algorand.py
    txn = AssetConfigTxn(
        sender=address,
        sp=params,
        total=1_000_000_000_000_000,  # 1 billion with 6 decimals
        default_frozen=False,
        unit_name="CONFIO",
        asset_name="Confío",
        manager=address,
        reserve="",  # Empty string - no reserve, all to creator
        freeze="",   # Empty string - no freeze
        clawback="", # Empty string - no clawback
        decimals=6,
        url="https://confio.lat",
        metadata_hash=None,
        strict_empty_address_check=False  # Allow empty addresses
    )
    
    signed_txn = txn.sign(private_key)
    txid = algod_client.send_transaction(signed_txn)
    confirmed = wait_for_confirmation(algod_client, txid, 4)
    asset_id = confirmed["asset-index"]
    
    print("\n" + "=" * 60)
    print("CONFIO TOKEN DEPLOYED SUCCESSFULLY!")
    print("=" * 60)
    print(f"\nAsset ID: {asset_id}")
    print(f"Creator: {address}")
    print(f"Total Supply: 1,000,000,000 CONFIO")
    print(f"All tokens in creator account")
    
    # Save configuration (no private keys)
    config_file = os.path.join(os.path.dirname(__file__), "../config/new_token_config.py")
    with open(config_file, "w") as f:
        f.write("# LocalNet Token Configuration\n\n")
        f.write("# CONFIO Token (Governance) - 1B fixed supply\n")
        f.write(f"CONFIO_ASSET_ID = {asset_id}\n")
        f.write(f'CONFIO_CREATOR_ADDRESS = "{address}"\n\n')
        f.write("# Private keys are not persisted. Use env vars or a key manager.\n\n")
        f.write("# Mock USDC (using old CONFIO with max supply)\n")
        f.write("MOCK_USDC_ASSET_ID = 1020\n\n")
        f.write("# cUSD (Stablecoin)\n")
        f.write("CUSD_ASSET_ID = 1036\n")
        f.write("CUSD_APP_ID = 1037\n")
    
    print(f"\nConfiguration saved to: {config_file}")
    
    print("\n📊 Current Setup:")
    print(f"  CONFIO (new): Asset {asset_id} - 1B governance token")
    print(f"  Mock USDC: Asset 1020 - For collateral testing")
    print(f"  cUSD: Asset 1036 - Stablecoin")

if __name__ == "__main__":
    try:
        status = algod_client.status()
        print(f"Connected to LocalNet (round {status.get('last-round', 0)})")
        main()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
