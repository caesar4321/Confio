#!/usr/bin/env python3
"""Phase E — Close out legacy sponsor's ASA + app opt-ins and drain remaining ALGO.

Runs strictly after Phase D (initial drain) succeeded. The legacy KMS key/account
is intentionally kept around (we are NOT scheduling KMS key deletion). This
script just clears every opt-in slot the legacy sponsor still holds and pushes
the freed MBR + spare ALGO to the new sponsor.

Order:
  1. AssetCloseOutTxn cUSD  (3198259450) → close_assets_to NEW sponsor
  2. AssetCloseOutTxn CONFIO (3351104258) → close_assets_to NEW sponsor
  3. ApplicationClearStateTxn cUSD app (3198259271)
     (cUSD clear program is `pushint 0; return` — opt-out is unconditional,
      avoiding cUSD's CloseOut path which Beaker does not define.)
  4. ApplicationCloseOutTxn legacy presale (3351520941)
  5. ApplicationCloseOutTxn prod presale  (3353218127)
  6. PaymentTxn remaining ALGO → NEW sponsor (leaves min-balance + 0.001 fee
     buffer so the legacy account stays solvent for its 18 created apps).

Run with::

    aws-vault exec Julian -- myvenv/bin/python \
        scripts/contracts/migrate_sponsor_native_kms/closeout_legacy.py
"""
from __future__ import annotations

from algosdk import transaction

from _common import (  # type: ignore  # noqa: E402
    ASSETS,
    LEGACY_SPONSOR_ADDRESS,
    NEW_SPONSOR_ADDRESS,
    confirm,
    get_algod,
    get_legacy_signer,
    print_balances,
)

# Apps the legacy sponsor is currently opted into.
LEGACY_APP_OPTINS = {
    "cusd": 3198259271,             # ClearState (Beaker, no CloseOut handler)
    "presale_legacy": 3351520941,   # CloseOut OK
    "presale_prod": 3353218127,     # CloseOut OK
}
CLEAR_STATE_APPS = {"cusd"}


def main() -> None:
    client = get_algod()
    signer = get_legacy_signer()

    info = client.account_info(LEGACY_SPONSOR_ADDRESS)
    optin_app_ids = {entry["id"] for entry in info.get("apps-local-state", [])}
    held_asset_ids = {a["asset-id"] for a in info.get("assets", [])}

    # The legacy sponsor is the CREATOR of CONFIO (asset 3351104258), so it
    # cannot close out CONFIO without destroying the asset — the 0.1 ALGO MBR
    # for that opt-in stays locked on legacy forever. Only cUSD is closable.
    created_asset_ids = {a["index"] for a in info.get("created-assets", [])}
    pending_assets = [
        (name, aid)
        for name, aid in ASSETS.items()
        if aid in held_asset_ids and aid not in created_asset_ids and name != "USDC"
    ]
    pending_apps = [(name, aid) for name, aid in LEGACY_APP_OPTINS.items() if aid in optin_app_ids]

    print("Phase E: close out legacy sponsor and forward remaining ALGO")
    print("  Pending ASA closeouts:", pending_assets or "(none)")
    print("  Pending app closeouts:", pending_apps or "(none)")
    print_balances(client, {"legacy": LEGACY_SPONSOR_ADDRESS, "new": NEW_SPONSOR_ADDRESS})

    confirm(
        "About to close out all legacy opt-ins and forward remaining ALGO on MAINNET.",
        "CLOSEOUT LEGACY",
    )

    # Step 1+2: ASA closeouts
    for name, aid in pending_assets:
        sp = client.suggested_params()
        txn = transaction.AssetTransferTxn(
            sender=LEGACY_SPONSOR_ADDRESS,
            sp=sp,
            receiver=NEW_SPONSOR_ADDRESS,
            amt=0,
            index=aid,
            close_assets_to=NEW_SPONSOR_ADDRESS,
            note=f"sponsor-migration:asa-closeout:{name}".encode(),
        )
        signed = signer.sign_transaction(txn)
        tx_id = client.send_transaction(signed)
        confirmed = transaction.wait_for_confirmation(client, tx_id, 6)
        print(f"  ASA {name} ({aid}) closed: {tx_id} round={confirmed.get('confirmed-round')}")

    # Step 3+4+5: App closeouts / clear-state
    for name, app_id in pending_apps:
        sp = client.suggested_params()
        if name in CLEAR_STATE_APPS:
            txn = transaction.ApplicationClearStateTxn(
                sender=LEGACY_SPONSOR_ADDRESS,
                sp=sp,
                index=app_id,
                note=f"sponsor-migration:app-clearstate:{name}".encode(),
            )
            label = "ClearState"
        else:
            txn = transaction.ApplicationCloseOutTxn(
                sender=LEGACY_SPONSOR_ADDRESS,
                sp=sp,
                index=app_id,
                note=f"sponsor-migration:app-closeout:{name}".encode(),
            )
            label = "CloseOut"
        signed = signer.sign_transaction(txn)
        tx_id = client.send_transaction(signed)
        confirmed = transaction.wait_for_confirmation(client, tx_id, 6)
        print(f"  App {name} ({app_id}) {label}: {tx_id} round={confirmed.get('confirmed-round')}")

    # Step 6: forward remaining ALGO (regular payment, not close-account)
    info = client.account_info(LEGACY_SPONSOR_ADDRESS)
    fee = 1_000
    drain_amt = info["amount"] - info.get("min-balance", 0) - fee
    if drain_amt <= 0:
        print(f"  No spendable ALGO to forward (amount={info['amount']}, mbr={info.get('min-balance')}, fee={fee})")
    else:
        sp = client.suggested_params()
        sp.fee = fee
        sp.flat_fee = True
        txn = transaction.PaymentTxn(
            sender=LEGACY_SPONSOR_ADDRESS,
            sp=sp,
            receiver=NEW_SPONSOR_ADDRESS,
            amt=drain_amt,
            note=b"sponsor-migration:final-drain",
        )
        signed = signer.sign_transaction(txn)
        tx_id = client.send_transaction(signed)
        confirmed = transaction.wait_for_confirmation(client, tx_id, 6)
        print(f"  Forwarded {drain_amt/1e6:.6f} ALGO: {tx_id} round={confirmed.get('confirmed-round')}")

    print_balances(client, {"legacy": LEGACY_SPONSOR_ADDRESS, "new": NEW_SPONSOR_ADDRESS})


if __name__ == "__main__":
    main()
