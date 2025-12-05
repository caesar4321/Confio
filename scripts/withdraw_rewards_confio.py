#!/usr/bin/env python3
"""
Withdraw CONFIO from the rewards vault.

This script allows the admin to withdraw excess CONFIO tokens from the rewards
vault after ensuring all outstanding obligations (eligible + unclaimed rewards)
are covered.

Environment variables (use .env.mainnet for mainnet):
    ALGORAND_ALGOD_ADDRESS
    ALGORAND_ALGOD_TOKEN
    ALGORAND_REWARD_APP_ID
    ALGORAND_CONFIO_ASSET_ID
    USE_KMS_SIGNING=true
    KMS_KEY_ALIAS=confio1-sponsor
    KMS_REGION=eu-central-2

Usage:
    # Withdraw specific amount (in micro CONFIO)
    ./myvenv/bin/python scripts/withdraw_rewards_confio.py 100000000

    # Withdraw with auto-confirmation (no prompt)
    ./myvenv/bin/python scripts/withdraw_rewards_confio.py 100000000 --yes

    # Check vault status without withdrawing
    ./myvenv/bin/python scripts/withdraw_rewards_confio.py --status
"""

import base64
import os
import sys
from pathlib import Path

from algosdk import encoding, transaction
from algosdk.logic import get_application_address
from algosdk.v2client import algod
from decouple import Config, RepositoryEnv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from blockchain.kms_manager import KMSSigner


def get_algod_client() -> algod.AlgodClient:
    """Initialize Algorand client from environment."""
    algod_address = os.environ["ALGORAND_ALGOD_ADDRESS"]
    algod_token = os.environ.get("ALGORAND_ALGOD_TOKEN", "")
    return algod.AlgodClient(algod_token, algod_address)


def decode_global_state(state: list[dict]) -> dict[bytes, object]:
    """Decode global state from application info."""
    decoded: dict[bytes, object] = {}
    for entry in state:
        key = base64.b64decode(entry["key"])
        value = entry["value"]
        if value.get("type") == 1:
            decoded[key] = base64.b64decode(value.get("bytes", ""))
        else:
            decoded[key] = value.get("uint", 0)
    return decoded


def wait_for_confirmation(client: algod.AlgodClient, txid: str, timeout: int = 10) -> dict:
    """Wait for transaction confirmation."""
    last_round = client.status().get("last-round")
    start_round = last_round
    current_round = start_round
    while current_round < start_round + timeout:
        pending = client.pending_transaction_info(txid)
        if pending.get("confirmed-round", 0) > 0:
            return pending
        if pending.get("pool-error"):
            raise RuntimeError(f"Transaction {txid} rejected: {pending['pool-error']}")
        current_round += 1
        client.status_after_block(current_round)
    raise TimeoutError(f"Transaction {txid} not confirmed after {timeout} rounds")


def get_vault_status(client: algod.AlgodClient, app_id: int, confio_asset_id: int) -> dict:
    """Get current vault status including balances and obligations."""
    app_info = client.application_info(app_id)
    app_address = get_application_address(app_id)

    # Decode global state
    state = decode_global_state(app_info["params"].get("global-state", []))

    total_eligible = int(state.get(b"eligible_sum", 0))
    total_claimed = int(state.get(b"claimed_sum", 0))
    total_ref_eligible = int(state.get(b"ref_eligible_sum", 0))
    total_ref_paid = int(state.get(b"ref_sum", 0))

    outstanding_user = total_eligible - total_claimed
    outstanding_ref = total_ref_eligible - total_ref_paid
    total_outstanding = outstanding_user + outstanding_ref

    # Get CONFIO balance
    account_info = client.account_info(app_address)
    confio_balance = 0
    for asset in account_info.get("assets", []):
        if asset["asset-id"] == confio_asset_id:
            confio_balance = asset["amount"]
            break

    # Get admin and sponsor addresses
    admin_bytes = state.get(b"admin")
    sponsor_bytes = state.get(b"sponsor")
    admin_addr = encoding.encode_address(admin_bytes) if admin_bytes else "Unknown"
    sponsor_addr = encoding.encode_address(sponsor_bytes) if sponsor_bytes else "Unknown"

    # Get MBR
    min_balance = account_info["min-balance"]

    # Calculate available for withdrawal
    # Must keep: min_balance + outstanding obligations
    required_balance = min_balance + total_outstanding
    available_withdrawal = max(0, confio_balance - required_balance)

    return {
        "app_id": app_id,
        "app_address": app_address,
        "admin_address": admin_addr,
        "sponsor_address": sponsor_addr,
        "confio_balance": confio_balance,
        "min_balance": min_balance,
        "total_eligible": total_eligible,
        "total_claimed": total_claimed,
        "outstanding_user": outstanding_user,
        "total_ref_eligible": total_ref_eligible,
        "total_ref_paid": total_ref_paid,
        "outstanding_ref": outstanding_ref,
        "total_outstanding": total_outstanding,
        "required_balance": required_balance,
        "available_withdrawal": available_withdrawal,
    }


def print_vault_status(status: dict) -> None:
    """Pretty print vault status."""
    print("\n" + "=" * 70)
    print("CONFÍO REWARDS VAULT STATUS")
    print("=" * 70)
    print(f"App ID:          {status['app_id']}")
    print(f"App Address:     {status['app_address']}")
    print(f"Admin:           {status['admin_address']}")
    print(f"Sponsor:         {status['sponsor_address']}")
    print()
    print("BALANCES (micro CONFIO):")
    print(f"  Total Balance:        {status['confio_balance']:>15,}")
    print(f"  Min Balance (MBR):    {status['min_balance']:>15,}")
    print()
    print("OBLIGATIONS:")
    print(f"  Total Eligible:       {status['total_eligible']:>15,}")
    print(f"  Total Claimed:        {status['total_claimed']:>15,}")
    print(f"  Outstanding (User):   {status['outstanding_user']:>15,}")
    print()
    print(f"  Ref Eligible:         {status['total_ref_eligible']:>15,}")
    print(f"  Ref Paid:             {status['total_ref_paid']:>15,}")
    print(f"  Outstanding (Ref):    {status['outstanding_ref']:>15,}")
    print()
    print(f"  TOTAL OUTSTANDING:    {status['total_outstanding']:>15,}")
    print()
    print("AVAILABLE FOR WITHDRAWAL:")
    print(f"  Available:            {status['available_withdrawal']:>15,} micro CONFIO")
    print(f"  Available:            {status['available_withdrawal'] / 1_000_000:>15,.2f} CONFIO")
    print("=" * 70)
    print()


def withdraw_confio(
    client: algod.AlgodClient,
    app_id: int,
    admin_signer: KMSSigner,
    amount: int,
    confio_asset_id: int,
    destination: str | None = None,
) -> str:
    """
    Withdraw CONFIO from the rewards vault.

    Args:
        client: Algorand client
        app_id: Rewards app ID
        admin_signer: KMS signer for admin
        amount: Amount to withdraw in micro CONFIO
        confio_asset_id: CONFIO asset ID
        destination: Optional destination address (defaults to admin)

    Returns:
        Transaction ID
    """
    params = client.suggested_params()
    # Cover fee for inner asset transfer transaction
    params.flat_fee = True
    params.fee = max(params.min_fee, 1000) * 2  # Cover outer + inner txn

    app_args = [
        b"withdraw",
        amount.to_bytes(8, "big"),
    ]

    # Build accounts array
    accounts = []
    if destination:
        accounts.append(destination)

    txn = transaction.ApplicationNoOpTxn(
        sender=admin_signer.address,
        index=app_id,
        sp=params,
        app_args=app_args,
        accounts=accounts,
        foreign_assets=[confio_asset_id],
    )

    signed = admin_signer.sign_transaction(txn)
    txid = client.send_transaction(signed)

    print(f"[+] Withdrawal transaction sent: {txid}")
    print(f"[+] Waiting for confirmation...")

    wait_for_confirmation(client, txid)

    print(f"[✓] Withdrawal confirmed!")
    return txid


def main() -> None:
    """Main entry point."""
    # Check for --status flag
    auto_confirm = "--yes" in sys.argv or "-y" in sys.argv

    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        check_status_only = True
        amount_to_withdraw = 0
    elif len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        check_status_only = False
        try:
            amount_to_withdraw = int(sys.argv[1])
        except ValueError:
            print("Error: Amount must be an integer (micro CONFIO)")
            print()
            print(__doc__)
            sys.exit(1)
    else:
        print("Error: Missing amount or --status flag")
        print()
        print(__doc__)
        sys.exit(1)

    # Load environment - prefer .env.mainnet if it exists
    env_file = project_root / ".env.mainnet"
    if not env_file.exists():
        env_file = project_root / ".env"

    if env_file.exists():
        env = Config(RepositoryEnv(str(env_file)))
        # Load into os.environ
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

    # Initialize client and KMS
    client = get_algod_client()

    app_id = int(os.environ["ALGORAND_REWARD_APP_ID"])
    confio_asset_id = int(os.environ["ALGORAND_CONFIO_ASSET_ID"])

    # Initialize KMS signer
    kms_alias = os.environ.get("KMS_KEY_ALIAS", "confio1-sponsor")
    kms_region = os.environ.get("KMS_REGION", "eu-central-2")

    print(f"[+] Initializing KMS signer...")
    print(f"    Alias:  {kms_alias}")
    print(f"    Region: {kms_region}")

    admin_signer = KMSSigner(kms_alias, region_name=kms_region)
    print(f"[+] Admin address: {admin_signer.address}")

    # Get vault status
    print(f"[+] Fetching vault status for app {app_id}...")
    status = get_vault_status(client, app_id, confio_asset_id)

    # Print status
    print_vault_status(status)

    # Verify admin matches
    if admin_signer.address != status["admin_address"]:
        print(f"[!] WARNING: KMS address ({admin_signer.address}) does not match")
        print(f"             on-chain admin ({status['admin_address']})")
        print()
        response = input("Continue anyway? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            sys.exit(1)

    # If status only, exit
    if check_status_only:
        sys.exit(0)

    # Validate withdrawal amount
    if amount_to_withdraw <= 0:
        print("[!] Error: Amount must be positive")
        sys.exit(1)

    if amount_to_withdraw > status["available_withdrawal"]:
        print(f"[!] Error: Requested amount ({amount_to_withdraw:,}) exceeds available")
        print(f"           withdrawal amount ({status['available_withdrawal']:,})")
        sys.exit(1)

    # Confirm withdrawal
    print(f"WITHDRAWAL DETAILS:")
    print(f"  Amount:      {amount_to_withdraw:>15,} micro CONFIO")
    print(f"  Amount:      {amount_to_withdraw / 1_000_000:>15,.2f} CONFIO")
    print(f"  Destination: {admin_signer.address}")
    print()

    if not auto_confirm:
        response = input("Proceed with withdrawal? [y/N] ")
        if response.lower() != "y":
            print("Aborted.")
            sys.exit(0)
    else:
        print("[+] Auto-confirming withdrawal (--yes flag provided)")

    # Execute withdrawal
    txid = withdraw_confio(
        client,
        app_id,
        admin_signer,
        amount_to_withdraw,
        confio_asset_id,
        destination=None,  # Use admin as destination
    )

    print()
    print(f"[✓] Successfully withdrew {amount_to_withdraw:,} micro CONFIO")
    print(f"    ({amount_to_withdraw / 1_000_000:.2f} CONFIO)")
    print(f"[✓] Transaction ID: {txid}")
    print()


if __name__ == "__main__":
    main()
