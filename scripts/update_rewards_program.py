#!/usr/bin/env python3
"""
Update the deployed CONFIO rewards application with the latest approval TEAL.

Usage:
    ALGORAND_REWARD_APP_ID=123 \
    ALGORAND_REWARD_ADMIN_MNEMONIC=\"your 25-word mnemonic\" \
    python scripts/update_rewards_program.py

Optional environment variables:
    ALGORAND_ALGOD_URL      (defaults to https://testnet-api.4160.nodely.dev)
    ALGORAND_ALGOD_TOKEN    (defaults to empty string)

Make sure contracts/rewards/approval.teal has been freshly generated from
contracts/rewards/confio_rewards.py before running this script.
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from algosdk import account, mnemonic, transaction
from algosdk.v2client import algod


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_teal(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"TEAL file not found: {path}")
    return path.read_text()


def main() -> None:
    app_id = int(env("ALGORAND_REWARD_APP_ID"))
    admin_mnemonic = env("ALGORAND_REWARD_ADMIN_MNEMONIC")
    algod_url = env("ALGORAND_ALGOD_URL", "https://testnet-api.4160.nodely.dev")
    algod_token = env("ALGORAND_ALGOD_TOKEN", "")

    base_dir = Path(__file__).resolve().parents[1]
    approval_path = base_dir / "contracts" / "rewards" / "approval.teal"
    clear_path = base_dir / "contracts" / "rewards" / "clear.teal"

    approval_teal = load_teal(approval_path)
    clear_teal = load_teal(clear_path)

    client = algod.AlgodClient(algod_token, algod_url)

    approval_bin = base64.b64decode(client.compile(approval_teal)["result"])
    clear_bin = base64.b64decode(client.compile(clear_teal)["result"])

    admin_private_key = mnemonic.to_private_key(admin_mnemonic)
    admin_address = account.address_from_private_key(admin_private_key)

    print(f"Updating rewards app {app_id} from sender {admin_address}")
    params = client.suggested_params()

    update_txn = transaction.ApplicationUpdateTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        approval_program=approval_bin,
        clear_program=clear_bin,
    )

    signed = update_txn.sign(admin_private_key)
    tx_id = client.send_transaction(signed)
    print(f"Submitted update transaction {tx_id}, waiting for confirmation...")

    result = transaction.wait_for_confirmation(client, tx_id, 6)
    confirmed_round = result.get("confirmed-round")
    print(f"✅ Rewards app {app_id} updated in round {confirmed_round}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
