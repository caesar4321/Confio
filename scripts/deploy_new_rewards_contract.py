#!/usr/bin/env python3
"""
Deploy a NEW CONFIO rewards application with the latest approval TEAL.

This deploys a completely new contract with updated code including:
- Fallback logic for claim_referrer using application_args[1]
- Proper UpdateApplication handler for future updates

Usage:
    ALGORAND_CONFIO_ASSET_ID=749148838 \
    ALGORAND_ADMIN_MNEMONIC="your 25-word mnemonic" \
    python scripts/deploy_new_rewards_contract.py
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from algosdk import account, mnemonic, transaction
from algosdk.v2client import algod


def env(key: str, default: str | None = None) -> str:
    """Get environment variable or raise error if not found."""
    value = os.environ.get(key, default)
    if value is None:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


def load_teal(path: Path) -> str:
    """Load TEAL source code from file."""
    if not path.exists():
        raise FileNotFoundError(f"TEAL file not found: {path}")
    return path.read_text()


def main() -> None:
    # Get configuration from environment
    confio_asset_id = int(env("ALGORAND_CONFIO_ASSET_ID"))
    admin_mnemonic = env("ALGORAND_ADMIN_MNEMONIC")
    algod_url = env("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev")
    algod_token = env("ALGORAND_ALGOD_TOKEN", "")

    # Load TEAL files
    base_dir = Path(__file__).resolve().parents[1]
    approval_path = base_dir / "contracts" / "rewards" / "approval.teal"
    clear_path = base_dir / "contracts" / "rewards" / "clear.teal"

    print(f"Loading TEAL from:")
    print(f"  Approval: {approval_path}")
    print(f"  Clear:    {clear_path}")

    approval_teal = load_teal(approval_path)
    clear_teal = load_teal(clear_path)

    # Initialize algod client
    client = algod.AlgodClient(algod_token, algod_url)

    # Compile TEAL
    print("\nCompiling TEAL...")
    approval_result = client.compile(approval_teal)
    clear_result = client.compile(clear_teal)

    approval_bin = base64.b64decode(approval_result["result"])
    clear_bin = base64.b64decode(clear_result["result"])

    print(f"  Approval program: {len(approval_bin)} bytes")
    print(f"  Clear program:    {len(clear_bin)} bytes")

    # Get admin account
    admin_private_key = mnemonic.to_private_key(admin_mnemonic)
    admin_address = account.address_from_private_key(admin_private_key)

    print(f"\nDeploying new rewards contract:")
    print(f"  Admin address: {admin_address}")
    print(f"  CONFIO asset:  {confio_asset_id}")

    # Get suggested params
    params = client.suggested_params()

    # Define global and local schema
    # Global state:
    # - admin (bytes)
    # - confio_asset_id (uint64)
    # - box_price (uint64)
    # - referee_reward_amount (uint64)
    # - referrer_reward_amount (uint64)
    # - paused (uint64)
    global_schema = transaction.StateSchema(num_uints=5, num_byte_slices=1)

    # No local state
    local_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

    # Create the application
    create_txn = transaction.ApplicationCreateTxn(
        sender=admin_address,
        sp=params,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval_bin,
        clear_program=clear_bin,
        global_schema=global_schema,
        local_schema=local_schema,
    )

    # Sign and send
    signed = create_txn.sign(admin_private_key)
    tx_id = client.send_transaction(signed)

    print(f"\nSubmitted create transaction {tx_id}")
    print("Waiting for confirmation...")

    # Wait for confirmation
    result = transaction.wait_for_confirmation(client, tx_id, 6)
    app_id = result.get("application-index")
    confirmed_round = result.get("confirmed-round")

    print(f"\n{'='*80}")
    print(f"✅ NEW REWARDS CONTRACT DEPLOYED SUCCESSFULLY!")
    print(f"{'='*80}")
    print(f"Application ID: {app_id}")
    print(f"Confirmed in round: {confirmed_round}")
    print(f"Admin address: {admin_address}")
    print(f"\nNext steps:")
    print(f"1. Bootstrap the contract with:")
    print(f"   ALGORAND_REWARD_APP_ID={app_id} \\")
    print(f"   ALGORAND_CONFIO_ASSET_ID={confio_asset_id} \\")
    print(f"   ALGORAND_ADMIN_MNEMONIC=\"...\" \\")
    print(f"   python scripts/bootstrap_rewards_contract.py")
    print(f"\n2. Update backend .env.testnet:")
    print(f"   ALGORAND_REWARD_APP_ID={app_id}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ERROR: {e}", file=sys.stderr)
        sys.exit(1)
