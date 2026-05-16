#!/usr/bin/env python3
"""Phase B3 — Opt the new native sponsor into the apps the legacy sponsor was opted into.

The legacy sponsor was opted into:
  - 3198259271 (cUSD)
  - 3351520941 (presale legacy)
  - 3353218127 (presale prod)

These are the only apps the new sponsor needs local state in. Other contracts
that reference sponsor_address (payment, invite_send, reward, payroll) check
sender == sponsor_address at app-call time but do not require the sponsor to
opt-in.

Run with::

    aws-vault exec Julian -- myvenv/bin/python \
        scripts/contracts/migrate_sponsor_native_kms/optin_apps.py
"""
from __future__ import annotations

from algosdk import transaction

from _common import (  # type: ignore  # noqa: E402
    LEGACY_SPONSOR_ADDRESS,
    NEW_SPONSOR_ADDRESS,
    SPONSOR_APP_OPTINS,
    confirm,
    get_algod,
    get_native_signer,
    print_balances,
)

# Some Beaker-generated apps require an ABI method selector on OptIn calls.
# cUSD is one of them ("opt_in()void" = 0x30c6d58a). The presale apps use a raw
# subroutine for OptIn, so they accept a bare opt-in.
APP_OPTIN_ARGS: dict[str, list[bytes]] = {
    "cusd": [bytes.fromhex("30c6d58a")],  # opt_in()void
}


def already_opted_in(account_info: dict, app_id: int) -> bool:
    for entry in account_info.get("apps-local-state", []):
        if entry.get("id") == app_id:
            return True
    return False


def main() -> None:
    client = get_algod()
    signer = get_native_signer()

    info = client.account_info(NEW_SPONSOR_ADDRESS)
    pending = [
        (name, app_id)
        for name, app_id in SPONSOR_APP_OPTINS.items()
        if not already_opted_in(info, app_id)
    ]
    if not pending:
        print("New sponsor already opted into all 3 apps — nothing to do.")
        return

    print("Phase B3: opt new sponsor into apps")
    for name, app_id in pending:
        print(f"  - {name} (app id {app_id})")
    print(f"  Sender: {NEW_SPONSOR_ADDRESS}")
    print_balances(client, {"legacy": LEGACY_SPONSOR_ADDRESS, "new": NEW_SPONSOR_ADDRESS})

    confirm(
        f"About to opt {len(pending)} app(s) into the NEW sponsor on MAINNET.",
        "OPTIN APPS",
    )

    for name, app_id in pending:
        sp = client.suggested_params()
        txn = transaction.ApplicationOptInTxn(
            sender=NEW_SPONSOR_ADDRESS,
            sp=sp,
            index=app_id,
            app_args=APP_OPTIN_ARGS.get(name),
            note=f"sponsor-migration:optin-app:{name}".encode(),
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
