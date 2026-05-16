#!/usr/bin/env python3
"""Phase B2 — Opt the new native sponsor into USDC, cUSD, and CONFIO.

Signed by the new native KMS Ed25519 key. Each ASA opt-in costs the new sponsor
0.001 ALGO in fees plus 0.1 ALGO of min-balance reserve. Skips assets already
opted-in.

Run with::

    aws-vault exec Julian -- myvenv/bin/python \
        scripts/contracts/migrate_sponsor_native_kms/optin_assets.py
"""
from __future__ import annotations

from algosdk import transaction

from _common import (  # type: ignore  # noqa: E402
    ASSETS,
    LEGACY_SPONSOR_ADDRESS,
    NEW_SPONSOR_ADDRESS,
    confirm,
    get_algod,
    get_native_signer,
    print_balances,
)


def already_opted_in(account_info: dict, asset_id: int) -> bool:
    for asset in account_info.get("assets", []):
        if asset.get("asset-id") == asset_id:
            return True
    return False


def main() -> None:
    client = get_algod()
    signer = get_native_signer()

    info = client.account_info(NEW_SPONSOR_ADDRESS)
    pending = [(name, aid) for name, aid in ASSETS.items() if not already_opted_in(info, aid)]
    if not pending:
        print("New sponsor already opted into all assets — nothing to do.")
        return

    print("Phase B2: opt new sponsor into ASAs")
    for name, aid in pending:
        print(f"  - {name} (asset id {aid})")
    print(f"  Sender: {NEW_SPONSOR_ADDRESS}")
    print_balances(client, {"legacy": LEGACY_SPONSOR_ADDRESS, "new": NEW_SPONSOR_ADDRESS})

    confirm(
        f"About to opt {len(pending)} asset(s) into the NEW sponsor on MAINNET.",
        "OPTIN ASSETS",
    )

    for name, aid in pending:
        sp = client.suggested_params()
        txn = transaction.AssetTransferTxn(
            sender=NEW_SPONSOR_ADDRESS,
            sp=sp,
            receiver=NEW_SPONSOR_ADDRESS,
            amt=0,
            index=aid,
            note=f"sponsor-migration:optin-asa:{name}".encode(),
        )
        signed = signer.sign_transaction(txn)
        tx_id = client.send_transaction(signed)
        print(f"  {name}: submitted {tx_id}")
        confirmed = transaction.wait_for_confirmation(client, tx_id, 6)
        print(f"    confirmed round: {confirmed.get('confirmed-round')}")
        print(f"    explorer: https://algoexplorer.io/tx/{tx_id}")

    print_balances(client, {"legacy": LEGACY_SPONSOR_ADDRESS, "new": NEW_SPONSOR_ADDRESS})


if __name__ == "__main__":
    main()
