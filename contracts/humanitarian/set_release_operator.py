#!/usr/bin/env python3
"""Rotate the Confio Ayuda Humanitaria release operator."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from algosdk.abi import AddressType, Method
from algosdk.transaction import ApplicationNoOpTxn, wait_for_confirmation

from contracts.humanitarian.deploy_humanitarian import decode_global_state, env, get_admin_signer, get_algod_client


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate humanitarian release operator")
    parser.add_argument("--app-id", type=int, default=int(env("ALGORAND_HUMANITARIAN_APP_ID", "0") or "0"))
    parser.add_argument("--operator", default=env("ALGORAND_HUMANITARIAN_RELEASE_OPERATOR"))
    parser.add_argument("--to-admin", action="store_true", help="Set release operator to the admin address")
    parser.add_argument("--allow-sponsor", action="store_true", help="Allow setting the hot sponsor as operator")
    args = parser.parse_args()

    if args.app_id <= 0:
        raise SystemExit("ALGORAND_HUMANITARIAN_APP_ID or --app-id is required")

    client = get_algod_client()
    state = decode_global_state(client, args.app_id)
    admin_address, admin_sign = get_admin_signer()
    current_admin = state.get("admin")
    if current_admin != admin_address:
        raise SystemExit(f"Admin signer mismatch: signer={admin_address}, onchain={current_admin}")

    new_operator = current_admin if args.to_admin else args.operator
    if not new_operator:
        raise SystemExit("ALGORAND_HUMANITARIAN_RELEASE_OPERATOR, --operator, or --to-admin is required")

    sponsor_address = env("ALGORAND_SPONSOR_ADDRESS")
    if sponsor_address and new_operator == sponsor_address and not args.allow_sponsor:
        raise SystemExit("Refusing to set release operator to the hot sponsor address")

    current_operator = state.get("release_operator")
    if current_operator == new_operator:
        print(f"Release operator already set: {new_operator}")
        return 0

    params = client.suggested_params()
    params.flat_fee = True
    params.fee = getattr(params, "min_fee", 1000) or 1000
    method = Method.from_signature("set_release_operator(address)void")
    txn = ApplicationNoOpTxn(
        sender=admin_address,
        sp=params,
        index=args.app_id,
        app_args=[method.get_selector(), AddressType().encode(new_operator)],
    )
    txid = client.send_transaction(admin_sign(txn))
    wait_for_confirmation(client, txid, 6)

    verified = decode_global_state(client, args.app_id).get("release_operator")
    if verified != new_operator:
        raise SystemExit(f"Verification failed: release_operator={verified}")

    print(f"Release operator rotated: {current_operator} -> {new_operator}")
    print(f"TxID: {txid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
