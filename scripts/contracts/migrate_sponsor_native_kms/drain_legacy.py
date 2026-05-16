#!/usr/bin/env python3
"""Phase D — Drain residual ALGO from the legacy sponsor to the new sponsor.

Leaves ``min-balance + 1 ALGO`` (and 0.001 ALGO for the fee) on the legacy
sponsor so it stays solvent. The legacy sponsor remains creator of 18 apps and
admin/sponsor of presale 3351520941, so we cannot close the account out.

Run AFTER the cutover (steps C1+C2) and after the prod backend is confirmed
healthy on the new sponsor.

Run with::

    aws-vault exec Julian -- myvenv/bin/python \
        scripts/contracts/migrate_sponsor_native_kms/drain_legacy.py
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

BUFFER_ALGO = 1  # microalgo buffer kept on legacy on top of min-balance


def main() -> None:
    client = get_algod()
    signer = get_legacy_signer()

    info = client.account_info(LEGACY_SPONSOR_ADDRESS)
    amount = info["amount"]
    mbr = info.get("min-balance", 0)
    fee = 1_000  # 1 mAlgo flat
    buffer = BUFFER_ALGO * 1_000_000
    drain_amt = amount - mbr - buffer - fee
    if drain_amt <= 0:
        raise SystemExit(
            f"Nothing to drain: amount={amount} mbr={mbr} buffer={buffer} fee={fee} -> drain={drain_amt}"
        )

    print("Phase D: drain legacy sponsor")
    print(f"  Current balance: {amount/1e6:.6f} ALGO  (mbr {mbr/1e6:.6f}, buffer {buffer/1e6:.6f})")
    print(f"  Drain amount:    {drain_amt/1e6:.6f} ALGO  ({drain_amt} microalgo)")
    print(f"  From: {LEGACY_SPONSOR_ADDRESS}")
    print(f"  To:   {NEW_SPONSOR_ADDRESS}")
    print_balances(client, {"legacy": LEGACY_SPONSOR_ADDRESS, "new": NEW_SPONSOR_ADDRESS})

    confirm(
        f"About to send {drain_amt/1e6:.6f} ALGO from legacy → new on MAINNET.",
        "DRAIN LEGACY",
    )

    sp = client.suggested_params()
    sp.fee = fee
    sp.flat_fee = True
    txn = transaction.PaymentTxn(
        sender=LEGACY_SPONSOR_ADDRESS,
        sp=sp,
        receiver=NEW_SPONSOR_ADDRESS,
        amt=drain_amt,
        note=b"sponsor-migration:drain",
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
