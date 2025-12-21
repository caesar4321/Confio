#!/usr/bin/env python3
"""
Bootstrap and fund the CONFIO rewards vault.

This script:
1. Bootstraps the vault (opts it into the CONFIO asset)
2. Funds it with a specified amount of CONFIO

Environment variables (use .env.mainnet for mainnet):
    ALGORAND_ALGOD_ADDRESS
    ALGORAND_ALGOD_TOKEN
    ALGORAND_REWARD_APP_ID
    ALGORAND_CONFIO_ASSET_ID
    USE_KMS_SIGNING=true
    KMS_KEY_ALIAS=confio-mainnet-sponsor
    KMS_REGION=eu-central-2

Usage:
    # Bootstrap and fund with 7.4M CONFIO
    aws-vault exec Julian -- ./myvenv/bin/python scripts/bootstrap_and_fund_rewards.py 7400000

    # Bootstrap and fund with auto-confirmation
    aws-vault exec Julian -- ./myvenv/bin/python scripts/bootstrap_and_fund_rewards.py 7400000 --yes

    # Just bootstrap (no funding)
    aws-vault exec Julian -- ./myvenv/bin/python scripts/bootstrap_and_fund_rewards.py --bootstrap-only
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


def check_bootstrap_status(client: algod.AlgodClient, app_id: int) -> bool:
    """Check if vault is already bootstrapped."""
    app_info = client.application_info(app_id)
    state = decode_global_state(app_info["params"].get("global-state", []))
    boot_flag = int(state.get(b"boot", 0))
    return boot_flag == 1


def bootstrap_vault(
    client: algod.AlgodClient,
    app_id: int,
    confio_asset_id: int,
    sponsor_signer: KMSSigner,
    admin_signer: KMSSigner,
    payment_amount: int = 350_000,
) -> str:
    """
    Bootstrap the vault by opting it into the CONFIO asset.

    Returns:
        Transaction ID of the bootstrap transaction
    """
    app_address = get_application_address(app_id)

    print(f"[+] Bootstrapping vault...")
    print(f"    App ID: {app_id}")
    print(f"    App Address: {app_address}")
    print(f"    CONFIO Asset ID: {confio_asset_id}")

    # Build atomic group: Payment + AppCall
    params = client.suggested_params()

    # Payment from sponsor to app (for ASA opt-in MBR)
    payment_txn = transaction.PaymentTxn(
        sender=sponsor_signer.address,
        receiver=app_address,
        amt=payment_amount,
        sp=params,
    )

    # AppCall to bootstrap
    app_call_params = client.suggested_params()
    app_call_params.flat_fee = True
    app_call_params.fee = max(app_call_params.min_fee, 1000) * 2  # Cover inner txn

    app_call_txn = transaction.ApplicationNoOpTxn(
        sender=admin_signer.address,
        index=app_id,
        app_args=[b"bootstrap"],
        foreign_assets=[confio_asset_id],
        sp=app_call_params,
    )

    # Assign group ID
    transaction.assign_group_id([payment_txn, app_call_txn])

    # Sign transactions
    signed_payment = sponsor_signer.sign_transaction(payment_txn)
    signed_app_call = admin_signer.sign_transaction(app_call_txn)

    # Send atomic group
    txid = client.send_transactions([signed_payment, signed_app_call])

    print(f"[+] Bootstrap transaction sent: {txid}")
    print(f"[+] Waiting for confirmation...")

    wait_for_confirmation(client, txid)

    print(f"[✓] Vault bootstrapped successfully!")
    return txid


def fund_vault(
    client: algod.AlgodClient,
    app_id: int,
    confio_asset_id: int,
    sponsor_signer: KMSSigner,
    amount: int,
) -> str:
    """
    Fund the vault with CONFIO tokens.

    Args:
        amount: Amount in whole CONFIO (will be converted to micro units)

    Returns:
        Transaction ID of the funding transaction
    """
    app_address = get_application_address(app_id)
    amount_micro = amount * 1_000_000  # Convert to micro CONFIO

    print(f"[+] Funding vault...")
    print(f"    Amount: {amount:,.2f} CONFIO ({amount_micro:,} micro CONFIO)")
    print(f"    From: {sponsor_signer.address}")
    print(f"    To: {app_address}")

    params = client.suggested_params()

    txn = transaction.AssetTransferTxn(
        sender=sponsor_signer.address,
        sp=params,
        receiver=app_address,
        amt=amount_micro,
        index=confio_asset_id,
    )

    signed = sponsor_signer.sign_transaction(txn)
    txid = client.send_transaction(signed)

    print(f"[+] Funding transaction sent: {txid}")
    print(f"[+] Waiting for confirmation...")

    wait_for_confirmation(client, txid)

    print(f"[✓] Vault funded successfully!")
    return txid


def main() -> None:
    """Main entry point."""
    # Parse arguments
    bootstrap_only = "--bootstrap-only" in sys.argv
    auto_confirm = "--yes" in sys.argv or "-y" in sys.argv

    if not bootstrap_only:
        if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
            print("Error: Missing funding amount (in whole CONFIO)")
            print()
            print(__doc__)
            sys.exit(1)

        try:
            funding_amount = float(sys.argv[1])
        except ValueError:
            print("Error: Funding amount must be a number")
            print()
            print(__doc__)
            sys.exit(1)
    else:
        funding_amount = 0

    # Load environment - prefer .env.mainnet if it exists
    env_file = project_root / ".env.mainnet"
    if not env_file.exists():
        env_file = project_root / ".env"

    if env_file.exists():
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

    # Initialize KMS signers
    kms_alias = os.environ.get("KMS_KEY_ALIAS", "confio-mainnet-sponsor")
    kms_region = os.environ.get("KMS_REGION", "eu-central-2")

    print("=" * 70)
    print("BOOTSTRAP AND FUND REWARDS VAULT")
    print("=" * 70)
    print(f"[+] Initializing KMS signers...")
    print(f"    Alias:  {kms_alias}")
    print(f"    Region: {kms_region}")
    print()

    sponsor_signer = KMSSigner(kms_alias, region_name=kms_region)
    admin_signer = sponsor_signer  # Same signer for admin

    print(f"[+] Sponsor/Admin address: {sponsor_signer.address}")
    print(f"[+] Rewards App ID: {app_id}")
    print(f"[+] Rewards App Address: {get_application_address(app_id)}")
    print(f"[+] CONFIO Asset ID: {confio_asset_id}")
    print()

    # Check if already bootstrapped
    is_bootstrapped = check_bootstrap_status(client, app_id)

    if is_bootstrapped:
        print("[!] Vault is already bootstrapped (opted into CONFIO)")
        print()
    else:
        print("[+] Vault is NOT bootstrapped. Proceeding with bootstrap...")
        print()

        # Confirm bootstrap
        if not auto_confirm:
            response = input("Proceed with bootstrap? [y/N] ")
            if response.lower() != "y":
                print("Aborted.")
                sys.exit(0)
        else:
            print("[+] Auto-confirming bootstrap (--yes flag provided)")

        print()
        bootstrap_txid = bootstrap_vault(
            client,
            app_id,
            confio_asset_id,
            sponsor_signer,
            admin_signer,
        )

        print()
        print(f"[✓] Bootstrap transaction: https://allo.info/tx/{bootstrap_txid}")
        print()

    # Fund vault if requested
    if not bootstrap_only and funding_amount > 0:
        print(f"[+] Preparing to fund vault with {funding_amount:,.2f} CONFIO")
        print()

        # Confirm funding
        if not auto_confirm:
            response = input(f"Proceed with funding {funding_amount:,.2f} CONFIO? [y/N] ")
            if response.lower() != "y":
                print("Aborted.")
                sys.exit(0)
        else:
            print("[+] Auto-confirming funding (--yes flag provided)")

        print()
        funding_txid = fund_vault(
            client,
            app_id,
            confio_asset_id,
            sponsor_signer,
            int(funding_amount),
        )

        print()
        print(f"[✓] Funding transaction: https://allo.info/tx/{funding_txid}")
        print()

    print("=" * 70)
    print("[✓] COMPLETE!")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
