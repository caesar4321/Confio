#!/usr/bin/env python3
"""Phase B1 — Send seed ALGO from the legacy sponsor to the new native sponsor.

The new sponsor needs enough ALGO to cover its own min-balance after opting
into 3 ASAs (3 * 0.1 ALGO MBR) and 3 apps (3 * 0.1 ALGO MBR plus any state
contribution), and ~10 fees for the opt-in transactions themselves. 5 ALGO is
comfortably above that.

Run with::

    aws-vault exec Julian -- myvenv/bin/python \
        scripts/contracts/migrate_sponsor_native_kms/seed_algo.py
"""
from __future__ import annotations

from algosdk import transaction

from _common import (  # type: ignore  # noqa: E402
    LEGACY_SPONSOR_ADDRESS,
    NEW_SPONSOR_ADDRESS,
    confirm,
    get_algod,
    get_legacy_signer,
    print_balances,
)

SEED_AMOUNT_ALGO = 5  # micro = 5_000_000


def main() -> None:
    client = get_algod()
    signer = get_legacy_signer()
    amt_microalgo = SEED_AMOUNT_ALGO * 1_000_000

    print(f"Phase B1: seed {SEED_AMOUNT_ALGO} ALGO from legacy sponsor to new sponsor.")
    print(f"  From: {LEGACY_SPONSOR_ADDRESS}")
    print(f"  To:   {NEW_SPONSOR_ADDRESS}")
    print(f"  Amt:  {amt_microalgo} microalgo ({SEED_AMOUNT_ALGO} ALGO)")
    print_balances(client, {"legacy": LEGACY_SPONSOR_ADDRESS, "new": NEW_SPONSOR_ADDRESS})

    confirm(
        "Seeding new sponsor on MAINNET. This is a real on-chain payment.",
        "SEED NEW SPONSOR",
    )

    sp = client.suggested_params()
    txn = transaction.PaymentTxn(
        sender=LEGACY_SPONSOR_ADDRESS,
        sp=sp,
        receiver=NEW_SPONSOR_ADDRESS,
        amt=amt_microalgo,
        note=b"sponsor-migration:seed",
    )

    signed = signer.sign_transaction(txn)
    tx_id = client.send_transaction(signed)
    print(f"  submitted: {tx_id}")
    confirmed = transaction.wait_for_confirmation(client, tx_id, 6)
    print(f"  confirmed round: {confirmed.get('confirmed-round')}")
    print(f"  explorer: https://algoexplorer.io/tx/{tx_id}")

    print_balances(client, {"legacy": LEGACY_SPONSOR_ADDRESS, "new": NEW_SPONSOR_ADDRESS})


if __name__ == "__main__":
    main()
