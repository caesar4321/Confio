#!/usr/bin/env python3
"""
Deploy CONFIO token to LocalNet using the corrected specifications.
This script wraps create_confio_token_algorand.py for LocalNet deployment.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from algosdk import account
import subprocess
from algosdk.v2client import algod
from algosdk.transaction import AssetConfigTxn, wait_for_confirmation, PaymentTxn
from contracts.config.algorand_localnet_config import ALGORAND_NODE, ALGORAND_TOKEN
from contracts.config.localnet_accounts import ADMIN_ADDRESS, ADMIN_PRIVATE_KEY
from algosdk import mnemonic

# Initialize client
algod_client = algod.AlgodClient(ALGORAND_TOKEN, ALGORAND_NODE)

def ensure_funded(address, min_algo=2_000_000):
    try:
        info = algod_client.account_info(address)
        if info.get("amount", 0) >= min_algo:
            return
    except Exception:
        pass
    try:
        # Try environment-provided faucet mnemonic first
        faucet_mn = os.getenv("LOCALNET_FAUCET_MNEMONIC")
        if faucet_mn:
            from algosdk import mnemonic as _mn
            from algosdk import account as _acct
            fk = _mn.to_private_key(faucet_mn)
            faddr = _acct.address_from_private_key(fk)
            params = algod_client.suggested_params()
            ptxn = PaymentTxn(sender=faddr, sp=params, receiver=address, amt=max(min_algo, 5_000_000))
            stx = ptxn.sign(fk)
            txid = algod_client.send_transaction(stx)
            wait_for_confirmation(algod_client, txid, 4)
            print("Dispensed from configured faucet mnemonic.")
            return
        
        # Use Algokit faucet if available
        res = subprocess.run(["algokit", "localnet", "dispense", "-a", address], capture_output=True, text=True)
        if res.returncode == 0:
            print("Dispensed via Algokit faucet for admin account.")
            return
        else:
            print(f"Algokit faucet failed (rc={res.returncode}): {res.stderr.strip()}")
    except Exception as e:
        print(f"Algokit faucet not available: {e}")

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
    
    # Fund the account using sponsor account which has funds
    print("\nFunding creator account...")
    params = algod_client.suggested_params()
    
    # Use sponsor account from environment
    sponsor_mnemonic = os.environ.get('ALGORAND_SPONSOR_MNEMONIC')
    if sponsor_mnemonic:
        sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
        sponsor_address = account.address_from_private_key(sponsor_private_key)
        
        funding_txn = PaymentTxn(
            sender=sponsor_address,
            sp=params,
            receiver=address,
            amt=10_000_000  # 10 ALGO
        )
        
        signed_funding = funding_txn.sign(sponsor_private_key)
        txid = algod_client.send_transaction(signed_funding)
        wait_for_confirmation(algod_client, txid, 4)
        print(f"  Funded with 10 ALGO from sponsor account")
    else:
        # Fallback to admin account
        funding_txn = PaymentTxn(
            sender=ADMIN_ADDRESS,
            sp=params,
            receiver=address,
            amt=10_000_000  # 10 ALGO
        )
        
        # Ensure admin has funds to cover this
        ensure_funded(ADMIN_ADDRESS)
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
        manager=address,  # Temporarily, should be finalized to ZERO_ADDR
        reserve="",  # Empty string for ZERO_ADDR
        freeze="",   # Empty string for ZERO_ADDR
        clawback="", # Empty string for ZERO_ADDR
        decimals=6,
        url="https://confio.lat",
        metadata_hash=None,
        strict_empty_address_check=False
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
    
    # Auto-finalize for LocalNet to mirror production behavior
    print("\n🔒 Finalizing token (setting all authorities to ZERO_ADDR)...")
    params = algod_client.suggested_params()
    
    lock_txn = AssetConfigTxn(
        sender=address,
        sp=params,
        index=asset_id,
        manager="",    # ZERO_ADDR - immutable forever
        reserve="",    # ZERO_ADDR
        freeze="",     # ZERO_ADDR
        clawback="",   # ZERO_ADDR
        strict_empty_address_check=False
    )
    
    signed_lock = lock_txn.sign(private_key)
    lock_txid = algod_client.send_transaction(signed_lock)
    wait_for_confirmation(algod_client, lock_txid, 4)
    print("✅ LocalNet token finalized (all authorities = ZERO_ADDR)")
    
    # Save configuration (no private keys)
    config_file = os.path.join(os.path.dirname(__file__), "../config/new_token_config.py")
    
    # Try to preserve existing MOCK_USDC_ASSET_ID if it exists
    mock_usdc_id = None
    if os.path.exists(config_file):
        try:
            with open(config_file, "r") as f:
                content = f.read()
                import re
                match = re.search(r"MOCK_USDC_ASSET_ID = (\d+)", content)
                if match:
                    mock_usdc_id = match.group(1)
        except:
            pass
    
    with open(config_file, "w") as f:
        f.write("# LocalNet Token Configuration\n\n")
        f.write("# CONFIO Token (Governance) - 1B fixed supply\n")
        f.write(f"CONFIO_ASSET_ID = {asset_id}\n")
        f.write(f'CONFIO_CREATOR_ADDRESS = "{address}"\n\n')
        f.write("# Private keys are not persisted. Use env vars or a key manager.\n\n")
        f.write("# Mock USDC (for collateral testing)\n")
        if mock_usdc_id:
            f.write(f"MOCK_USDC_ASSET_ID = {mock_usdc_id}  # Preserved from previous run\n\n")
        else:
            f.write("# MOCK_USDC_ASSET_ID = None  # Run deploy_mock_usdc_localnet.py to create\n\n")
        f.write("# cUSD (Stablecoin)\n")
        f.write("# CUSD_ASSET_ID = None  # Will be set by cUSD deployment\n")
        f.write("# CUSD_APP_ID = None  # Will be set by cUSD deployment\n")
    
    print(f"\nConfiguration saved to: {config_file}")
    
    print("\n📊 Current Setup:")
    print(f"  CONFIO (new): Asset {asset_id} - 1B governance token")
    print(f"  Mock USDC: Asset 1020 - For collateral testing")
    print(f"  cUSD: Asset 1036 - Stablecoin")
    
    # Post-deploy smoke check
    print("\n🔍 Running post-deploy verification...")
    os.environ["ALGORAND_CONFIO_ASSET_ID"] = str(asset_id)
    os.environ["EXPECT_NO_AUTHORITIES"] = "1"  # Expect finalized state
    
    # Run the checker script with absolute path
    import subprocess
    script_dir = os.path.dirname(os.path.abspath(__file__))
    checker_path = os.path.join(script_dir, "check_confio_asset.py")
    
    result = subprocess.run(
        [sys.executable, checker_path, str(asset_id)],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print("❌ Post-deploy check FAILED!")
        print(result.stdout)
        print(result.stderr)
        sys.exit(1)
    else:
        print("✅ Post-deploy verification passed!")

if __name__ == "__main__":
    try:
        status = algod_client.status()
        print(f"Connected to LocalNet (round {status.get('last-round', 0)})")
        main()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
