#!/usr/bin/env python3
"""
Utility to withdraw a specific net amount of cUSD from the presale vault.

Because the smart contract only exposes a "withdraw everything" opcode,
this script automates the pattern of:
  1. withdrawing the full cUSD balance to the sponsor/admin account, then
  2. redepositing the excess so the contract ends up down by the requested amount.

Requirements:
  * .env must contain the Algorand admin mnemonic + sponsor address (same as production).
  * Run from the repository root so the contracts package is on the PYTHONPATH.
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values
from algosdk import mnemonic, account
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation

# Ensure project root on PYTHONPATH before importing PresaleAdmin.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

# Prefer Algonode when no API token is configured (Nodely requires X-API-Key).
FALLBACK_ALGOD = "https://mainnet-api.algonode.cloud"


def load_env(env_path: Path) -> dict[str, str]:
    env_vars = dotenv_values(str(env_path))
    if not env_vars:
        raise RuntimeError(f"Unable to load environment file at {env_path}")
    required = [
        "ALGORAND_PRESALE_APP_ID",
        "ALGORAND_CONFIO_ASSET_ID",
        "ALGORAND_CUSD_ASSET_ID",
        "ALGORAND_SPONSOR_ADDRESS",
        "ALGORAND_ADMIN_MNEMONIC",
    ]
    missing = [name for name in required if not env_vars.get(name)]
    if missing:
        raise RuntimeError(f"Missing required env values: {', '.join(missing)}")
    return env_vars


def ensure_algod_env(env_vars: dict[str, str]) -> None:
    algod_address = env_vars.get("ALGORAND_ALGOD_ADDRESS") or FALLBACK_ALGOD
    algod_token = env_vars.get("ALGORAND_ALGOD_TOKEN", "")

    os.environ["ALGORAND_ALGOD_ADDRESS"] = algod_address
    os.environ["ALGORAND_ALGOD_TOKEN"] = algod_token


def to_micro(amount: Decimal) -> int:
    return int((amount * Decimal("1000000")).to_integral_value(rounding=ROUND_DOWN))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Withdraw net cUSD from the presale vault")
    parser.add_argument(
        "--amount",
        type=Decimal,
        default=Decimal("10"),
        help="Amount of cUSD to leave withdrawn from the vault (default: 10)",
    )
    parser.add_argument(
        "--env-file",
        default=str(REPO_ROOT / ".env"),
        help="Path to .env file with Algorand credentials (default: %(default)s)",
    )
    parser.add_argument(
        "--receiver",
        default=None,
        help="Optional receiver for the withdrawal (defaults to sponsor address)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.amount <= 0:
        raise SystemExit("Amount must be positive.")

    env_vars = load_env(Path(args.env_file))
    ensure_algod_env(env_vars)

    from contracts.presale.admin_presale import PresaleAdmin  # noqa: E402

    app_id = int(env_vars["ALGORAND_PRESALE_APP_ID"])
    confio_id = int(env_vars["ALGORAND_CONFIO_ASSET_ID"])
    cusd_id = int(env_vars["ALGORAND_CUSD_ASSET_ID"])
    sponsor_address = args.receiver or env_vars["ALGORAND_SPONSOR_ADDRESS"]
    admin_sk = mnemonic.to_private_key(env_vars["ALGORAND_ADMIN_MNEMONIC"])
    admin_address = account.address_from_private_key(admin_sk)

    print(f"Admin address:    {admin_address}")
    print(f"Sponsor receiver: {sponsor_address}")
    if admin_address != sponsor_address:
        print("⚠️  WARNING: admin and sponsor differ; ensure receiver is correct.")

    desired_micro = to_micro(args.amount)
    admin = PresaleAdmin(app_id, confio_id, cusd_id)

    print("\n1) Withdrawing entire cUSD balance from presale app...")
    withdraw_result: Optional[dict] = admin.withdraw_cusd(
        admin_address,
        admin_sk,
        receiver=sponsor_address,
    )
    if not withdraw_result:
        raise SystemExit("No cUSD withdrawn (balance was zero).")

    withdrawn_micro = withdraw_result.get("amount", 0) or 0
    withdrawn_human = Decimal(withdrawn_micro) / Decimal("1000000")
    print(f"   Withdrawn: {withdrawn_human:,.6f} cUSD")

    if withdrawn_micro < desired_micro:
        raise SystemExit(
            f"Requested {args.amount} cUSD but only {withdrawn_human:,.6f} was available."
        )

    excess_micro = withdrawn_micro - desired_micro
    if excess_micro > 0:
        print(f"\n2) Redepositing excess {Decimal(excess_micro)/Decimal('1000000'):,.6f} cUSD back...")
        client = admin.algod_client
        params = client.suggested_params()
        params.flat_fee = True
        params.fee = max(getattr(params, "min_fee", 1000), 1000)

        redeposit_txn = AssetTransferTxn(
            sender=sponsor_address,
            sp=params,
            receiver=admin.app_addr,
            amt=excess_micro,
            index=cusd_id,
        )
        signed = redeposit_txn.sign(admin_sk)
        redeposit_txid = client.send_transaction(signed)
        wait_for_confirmation(client, redeposit_txid, 4)
        print(f"   Redeposit txid: {redeposit_txid}")
    else:
        print("\nNo excess to redeposit; vault is now empty.")

    info = admin.algod_client.account_info(admin.app_addr)
    current_micro = next(
        (a["amount"] for a in info.get("assets", []) if a["asset-id"] == cusd_id),
        0,
    )
    current_human = Decimal(current_micro) / Decimal("1000000")
    print(f"\n✅ Done. Current presale cUSD balance: {current_human:,.6f} cUSD")


if __name__ == "__main__":
    main()
