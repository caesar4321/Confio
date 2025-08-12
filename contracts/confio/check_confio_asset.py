#!/usr/bin/env python3
"""
Simple sanity checker for the CONFIO ASA deployment.

Checks on-chain asset parameters against expected values:
- unit name, asset name, decimals, total supply
- creator address and authorities (manager/reserve/freeze/clawback)

Usage:
  python contracts/confio/check_confio_asset.py [ASSET_ID]

Sources for configuration (in order):
  1) Command-line ASSET_ID argument
  2) Env var ALGORAND_CONFIO_ASSET_ID
  3) contracts/confio/confio_token_config.CONFIO_ASSET_ID (if > 0)

Env vars:
  ALGOD_ADDRESS (default: https://testnet-api.algonode.cloud)
  ALGOD_TOKEN   (default: empty)

Optional expectation overrides via env (defaults shown):
  EXPECT_UNIT_NAME=CONFIO
  EXPECT_ASSET_NAME=Confío
  EXPECT_DECIMALS=6
  EXPECT_TOTAL=1000000000000000   # 1_000_000_000 with 6 decimals
  EXPECT_NO_AUTHORITIES=1         # enforce reserve/freeze/clawback = zero address
  EXPECT_CREATOR_ADDRESS=<addr>   # if set, verify creator matches
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT)

from algosdk.v2client import algod

ZERO_ADDR = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ"


def read_asset_id_from_config():
    try:
        from contracts.confio.confio_token_config import CONFIO_ASSET_ID
        if isinstance(CONFIO_ASSET_ID, int) and CONFIO_ASSET_ID > 0:
            return CONFIO_ASSET_ID
    except Exception:
        pass
    return None


def get_asset_id(argv):
    if len(argv) > 1 and argv[1].isdigit():
        return int(argv[1])
    env_id = os.environ.get("ALGORAND_CONFIO_ASSET_ID")
    if env_id and env_id.isdigit():
        return int(env_id)
    cfg_id = read_asset_id_from_config()
    if cfg_id:
        return cfg_id
    raise SystemExit("Provide ASSET_ID arg or set ALGORAND_CONFIO_ASSET_ID/confio_token_config.CONFIO_ASSET_ID")


def main(argv):
    asset_id = get_asset_id(argv)

    algod_address = os.environ.get("ALGOD_ADDRESS", "https://testnet-api.algonode.cloud")
    algod_token = os.environ.get("ALGOD_TOKEN", "")
    client = algod.AlgodClient(algod_token, algod_address)

    print(f"Checking asset {asset_id} on {algod_address}")

    info = client.asset_info(asset_id)
    params = info.get("params", {})

    expected = {
        "unit_name": os.environ.get("EXPECT_UNIT_NAME", "CONFIO"),
        "asset_name": os.environ.get("EXPECT_ASSET_NAME", "Confío"),
        "decimals": int(os.environ.get("EXPECT_DECIMALS", "6")),
        "total": int(os.environ.get("EXPECT_TOTAL", str(1_000_000_000_000_000))),
        "no_authorities": os.environ.get("EXPECT_NO_AUTHORITIES", "1") == "1",
        "creator": os.environ.get("EXPECT_CREATOR_ADDRESS", params.get("creator")),
    }

    failures = []

    # Basic params - using correct JSON keys with dashes
    if params.get("unit-name") != expected["unit_name"]:
        failures.append(f"unit_name: expected {expected['unit_name']}, got {params.get('unit-name')}")
    if params.get("name") != expected["asset_name"]:
        failures.append(f"asset_name: expected {expected['asset_name']}, got {params.get('name')}")
    if int(params.get("decimals", -1)) != expected["decimals"]:
        failures.append(f"decimals: expected {expected['decimals']}, got {params.get('decimals')}")
    if int(params.get("total", -1)) != expected["total"]:
        failures.append(f"total: expected {expected['total']}, got {params.get('total')}")

    # Authorities
    manager = params.get("manager")
    reserve = params.get("reserve", ZERO_ADDR)
    freeze = params.get("freeze", ZERO_ADDR)
    clawback = params.get("clawback", ZERO_ADDR)
    creator = params.get("creator")

    # Check creator if specified
    if expected["creator"] and creator != expected["creator"]:
        failures.append(f"creator: expected {expected['creator']}, got {creator}")

    # For truly immutable token, manager should be ZERO_ADDR
    # If not finalized yet, manager should be creator
    if expected["no_authorities"]:
        if manager != ZERO_ADDR:
            if manager == creator:
                failures.append(f"⚠️  manager: token not finalized! Run finalize_confio_asset.py to lock forever")
            else:
                failures.append(f"manager: expected ZERO_ADDR (finalized), got {manager}")

    if expected["no_authorities"]:
        if reserve != ZERO_ADDR:
            failures.append(f"reserve: expected ZERO, got {reserve}")
        if freeze != ZERO_ADDR:
            failures.append(f"freeze: expected ZERO, got {freeze}")
        if clawback != ZERO_ADDR:
            failures.append(f"clawback: expected ZERO, got {clawback}")

    # Report
    print("\nOn-chain parameters:")
    print(f"  name      : {params.get('name')}")
    print(f"  unit_name : {params.get('unit-name')}")  # Fixed: use dash
    print(f"  total     : {params.get('total'):,}")
    print(f"  decimals  : {params.get('decimals')}")
    print(f"  creator   : {creator}")
    print(f"  manager   : {manager}")
    print(f"  reserve   : {reserve}")
    print(f"  freeze    : {freeze}")
    print(f"  clawback  : {clawback}")

    if failures:
        print("\n❌ Sanity check failed:")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
    else:
        print("\n✅ Sanity check passed: asset matches expectations.")


if __name__ == "__main__":
    main(sys.argv)

