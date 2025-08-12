#!/usr/bin/env python3
"""
Finalize CONFIO ASA by setting all authority addresses to ZERO_ADDR
This makes the token truly immutable with no control mechanisms.

CRITICAL: Run this immediately after creating the CONFIO token
to prevent any future rug pull or unauthorized modifications.

This script:
1. Verifies the asset parameters on-chain
2. Sets manager, reserve, freeze, and clawback to ZERO_ADDR
3. Makes the token parameters immutable forever

Usage:
  ALGORAND_CONFIO_ASSET_ID=123456 \
  ALGORAND_CONFIO_CREATOR_MNEMONIC="..." \
  python contracts/confio/finalize_confio_asset.py
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from algosdk.v2client import algod
from algosdk import mnemonic, account
from algosdk.transaction import AssetConfigTxn, wait_for_confirmation

# Algorand's zero address constant
ZERO_ADDR = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ"

def main():
    # Configuration
    ALGOD_ADDRESS = os.getenv("ALGOD_ADDRESS", "https://testnet-api.algonode.cloud")
    ALGOD_TOKEN = os.getenv("ALGOD_TOKEN", "")
    
    # Asset and creator details
    ASSET_ID = os.environ.get("ALGORAND_CONFIO_ASSET_ID")
    CREATOR_MN = os.environ.get("ALGORAND_CONFIO_CREATOR_MNEMONIC")
    
    if not ASSET_ID:
        print("❌ Error: ALGORAND_CONFIO_ASSET_ID environment variable not set")
        sys.exit(1)
    
    if not CREATOR_MN:
        print("❌ Error: ALGORAND_CONFIO_CREATOR_MNEMONIC environment variable not set")
        sys.exit(1)
    
    try:
        ASSET_ID = int(ASSET_ID)
    except ValueError:
        print(f"❌ Error: Invalid asset ID: {ASSET_ID}")
        sys.exit(1)
    
    # Initialize client
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    # Get creator credentials
    creator_pk = mnemonic.to_private_key(CREATOR_MN)
    creator_addr = account.address_from_private_key(creator_pk)
    
    print("=" * 60)
    print("CONFIO ASSET FINALIZATION")
    print("=" * 60)
    print(f"\nNetwork: {ALGOD_ADDRESS}")
    print(f"Asset ID: {ASSET_ID}")
    print(f"Creator: {creator_addr}")
    
    # Get current asset info
    print("\n📊 Checking current asset parameters...")
    try:
        asset_info = client.asset_info(ASSET_ID)
        params = asset_info.get("params", {})
        
        print(f"  Name: {params.get('name')}")
        print(f"  Unit: {params.get('unit-name')}")
        print(f"  Total: {params.get('total'):,}")
        print(f"  Decimals: {params.get('decimals')}")
        print(f"  Manager: {params.get('manager')}")
        print(f"  Reserve: {params.get('reserve', 'ZERO_ADDR')}")
        print(f"  Freeze: {params.get('freeze', 'ZERO_ADDR')}")
        print(f"  Clawback: {params.get('clawback', 'ZERO_ADDR')}")
        
        # Verify we're the manager
        if params.get('manager') != creator_addr:
            print(f"\n❌ Error: Current manager ({params.get('manager')}) doesn't match creator ({creator_addr})")
            print("Only the current manager can finalize the asset.")
            sys.exit(1)
        
        # Check if already finalized
        if params.get('manager') == ZERO_ADDR:
            print("\n✅ Asset is already finalized (manager = ZERO_ADDR)")
            return
        
    except Exception as e:
        print(f"\n❌ Error getting asset info: {e}")
        sys.exit(1)
    
    # Confirm finalization
    print("\n" + "⚠️ " * 20)
    print("WARNING: This action is IRREVERSIBLE!")
    print("After finalization:")
    print("  ❌ No one can change asset parameters")
    print("  ❌ No one can freeze accounts")
    print("  ❌ No one can clawback tokens")
    print("  ❌ No one can set a reserve address")
    print("  ✅ Token becomes truly decentralized")
    print("⚠️ " * 20)
    
    if sys.stdin.isatty():
        response = input("\nType 'FINALIZE' to proceed: ")
        if response != "FINALIZE":
            print("Finalization cancelled.")
            sys.exit(0)
    else:
        print("\nRunning in non-interactive mode - proceeding with finalization...")
    
    # Create finalization transaction
    print("\n🔒 Creating finalization transaction...")
    
    try:
        sp = client.suggested_params()
        
        # Set all authorities to None (becomes ZERO_ADDR on-chain)
        txn = AssetConfigTxn(
            sender=creator_addr,
            sp=sp,
            index=ASSET_ID,
            manager=None,    # Lock forever - no more changes possible
            reserve=None,    # No reserve authority
            freeze=None,     # No freeze authority
            clawback=None    # No clawback authority
        )
        
        # Sign and send
        signed_txn = txn.sign(creator_pk)
        txid = client.send_transaction(signed_txn)
        
        print(f"  Transaction ID: {txid}")
        print("  Waiting for confirmation...")
        
        # Wait for confirmation
        confirmed = wait_for_confirmation(client, txid, 4)
        
        print(f"  Confirmed in round: {confirmed.get('confirmed-round')}")
        
    except Exception as e:
        print(f"\n❌ Error during finalization: {e}")
        sys.exit(1)
    
    # Verify finalization
    print("\n✅ Verifying finalization...")
    
    try:
        asset_info = client.asset_info(ASSET_ID)
        params = asset_info.get("params", {})
        
        manager = params.get('manager', ZERO_ADDR)
        reserve = params.get('reserve', ZERO_ADDR)
        freeze = params.get('freeze', ZERO_ADDR)
        clawback = params.get('clawback', ZERO_ADDR)
        
        if (manager == ZERO_ADDR and 
            reserve == ZERO_ADDR and 
            freeze == ZERO_ADDR and 
            clawback == ZERO_ADDR):
            
            print("\n" + "=" * 60)
            print("✅ CONFIO ASSET SUCCESSFULLY FINALIZED!")
            print("=" * 60)
            print(f"\nAsset ID {ASSET_ID} is now:")
            print("  • Immutable (no parameter changes possible)")
            print("  • Unfreezable (tokens can't be frozen)")
            print("  • Non-clawbackable (tokens can't be revoked)")
            print("  • Truly decentralized")
            print(f"\nView on explorer: https://testnet.algoexplorer.io/asset/{ASSET_ID}")
            
        else:
            print(f"\n⚠️ Warning: Finalization may be incomplete")
            print(f"  Manager: {manager}")
            print(f"  Reserve: {reserve}")
            print(f"  Freeze: {freeze}")
            print(f"  Clawback: {clawback}")
            
    except Exception as e:
        print(f"\n⚠️ Warning: Could not verify finalization: {e}")
    
    print("\n📝 Next steps:")
    print("  1. Update check_confio_asset.py to verify manager = ZERO_ADDR")
    print("  2. Document that the token is finalized and immutable")
    print("  3. Remove any references to token modification capabilities")

if __name__ == "__main__":
    main()