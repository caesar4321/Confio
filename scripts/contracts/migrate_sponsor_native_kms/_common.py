"""Shared helpers for the sponsor native-KMS migration scripts.

All scripts in this directory must be invoked under ``aws-vault exec Julian`` so
the AWS SDK can call both the legacy SSM/KMS path (for the old sponsor) and the
native KMS sign path (for the new sponsor). They never accept addresses or key
material as parameters: addresses come from the KMS keys themselves.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running these scripts standalone (without the Django app loaded).
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


ALGOD_ADDRESS = "https://mainnet-api.4160.nodely.dev"
ALGOD_TOKEN = ""

LEGACY_SPONSOR_ALIAS = "confio-mainnet-sponsor"
NATIVE_SPONSOR_ALIAS = "confio-mainnet-sponsor-native-ed25519"
KMS_REGION = "eu-central-2"

# Known addresses (sanity-asserted, not used as inputs)
LEGACY_SPONSOR_ADDRESS = "ZS2HK5N7BZV46ZZGDOQBGFTN3JSXGAFVJFG33WAEP47JQMASSSJIQL7HI4"
NEW_SPONSOR_ADDRESS = "LAOVAXRX75S76NG67EZCBNMGGV4HAZWY7OTL62HQSDGXTVDQSAU2SKQOHU"

# Mainnet asset IDs we want the new sponsor opted into
ASSETS = {
    "USDC": 31566704,
    "cUSD": 3198259450,
    "CONFIO": 3351104258,
}

# Apps the new sponsor needs local state in (subset of the legacy sponsor's
# opt-ins). The legacy presale 3351520941 is intentionally excluded — its
# sponsor stays as the legacy address and the new sponsor does not need to be
# opted in.
SPONSOR_APP_OPTINS = {
    "cusd": 3198259271,
    "presale_prod_3353218127": 3353218127,
}


def get_algod():
    from algosdk.v2client import algod

    return algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)


def get_legacy_signer():
    """Legacy SSM-backed KMS signer for the old sponsor address."""
    from blockchain.kms_manager import KMSSigner

    signer = KMSSigner(LEGACY_SPONSOR_ALIAS, region_name=KMS_REGION)
    if signer.address != LEGACY_SPONSOR_ADDRESS:
        raise SystemExit(
            f"Legacy KMS alias resolved to {signer.address}, expected {LEGACY_SPONSOR_ADDRESS}"
        )
    return signer


def get_native_signer():
    """Native KMS Ed25519 signer for the new sponsor address."""
    from blockchain.kms_manager import NativeKMSSigner

    signer = NativeKMSSigner(NATIVE_SPONSOR_ALIAS, region_name=KMS_REGION)
    if signer.address != NEW_SPONSOR_ADDRESS:
        raise SystemExit(
            f"Native KMS alias resolved to {signer.address}, expected {NEW_SPONSOR_ADDRESS}"
        )
    return signer


def confirm(prompt: str, expected: str) -> None:
    """Block on a typed confirmation. Aborts the script if the user disagrees."""
    answer = input(f"{prompt}\nType exactly {expected!r} to proceed: ").strip()
    if answer != expected:
        print("Aborted by user.")
        raise SystemExit(1)


def print_balances(client, label_to_address):
    print()
    print("=" * 78)
    for label, address in label_to_address.items():
        info = client.account_info(address)
        algo = info["amount"] / 1e6
        mbr = info.get("min-balance", 0) / 1e6
        spendable = max(info["amount"] - info.get("min-balance", 0), 0) / 1e6
        n_apps = len(info.get("apps-local-state", []))
        n_assets = len(info.get("assets", []))
        print(
            f"{label:6s} {address}: ALGO={algo:.6f} (mbr={mbr:.6f}, spendable={spendable:.6f}), "
            f"apps={n_apps}, assets={n_assets}"
        )
        for a in info.get("assets", []):
            print(f"    asset {a['asset-id']}: amount={a['amount']}")
    print("=" * 78)
    print()
