#!/usr/bin/env python3
"""Deploy Confio Ayuda Humanitaria app and opt it into cUSD."""

import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from algosdk import account, encoding, mnemonic
from algosdk.abi import AddressType, Method, UintType
from algosdk.logic import get_application_address
from algosdk.transaction import (
    ApplicationCreateTxn,
    ApplicationNoOpTxn,
    OnComplete,
    PaymentTxn,
    StateSchema,
    wait_for_confirmation,
)
from algosdk.v2client import algod

from blockchain.kms_manager import KMSSigner, NativeKMSSigner


ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
APPROVAL_TEAL = ARTIFACTS / "ConfioAyudaHumanitaria.approval.teal"
CLEAR_TEAL = ARTIFACTS / "ConfioAyudaHumanitaria.clear.teal"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def get_algod_client() -> algod.AlgodClient:
    network = env("ALGORAND_NETWORK", "mainnet").lower()
    address = env("ALGORAND_ALGOD_ADDRESS")
    token = env("ALGORAND_ALGOD_TOKEN")
    if not address:
        address = "https://mainnet-api.algonode.cloud" if network == "mainnet" else "https://testnet-api.algonode.cloud"
    return algod.AlgodClient(token, address)


def get_admin_signer():
    use_kms = env("USE_KMS_SIGNING").lower() == "true" or bool(env("KMS_ADMIN_KEY_ALIAS") or env("KMS_KEY_ALIAS"))
    if use_kms:
        alias = env("KMS_ADMIN_KEY_ALIAS") or env("KMS_KEY_ALIAS")
        if not alias:
            raise SystemExit("KMS_ADMIN_KEY_ALIAS or KMS_KEY_ALIAS is required for KMS signing")
        signer_cls = NativeKMSSigner if env("KMS_NATIVE_SIGNING").lower() == "true" else KMSSigner
        signer = signer_cls(alias, region_name=env("KMS_REGION", "eu-central-2"))
        return signer.address, signer.sign_transaction

    admin_mnemonic = env("ALGORAND_ADMIN_MNEMONIC")
    if not admin_mnemonic:
        raise SystemExit("ALGORAND_ADMIN_MNEMONIC is required when KMS signing is disabled")
    private_key = mnemonic.to_private_key(" ".join(admin_mnemonic.split()))
    return account.address_from_private_key(private_key), lambda txn: txn.sign(private_key)


def compile_teal(client: algod.AlgodClient, teal_path: Path) -> bytes:
    result = client.compile(teal_path.read_text())
    return base64.b64decode(result["result"])


def decode_global_state(client: algod.AlgodClient, app_id: int) -> dict:
    app = client.application_info(app_id)
    state = {}
    for item in app.get("params", {}).get("global-state", []) or []:
        key = base64.b64decode(item["key"]).decode("utf-8", "ignore")
        value = item["value"]
        if value.get("type") == 2:
            state[key] = int(value.get("uint") or 0)
        elif value.get("type") == 1:
            raw = base64.b64decode(value.get("bytes") or "")
            state[key] = encoding.encode_address(raw) if len(raw) == 32 else raw
    return state


def main() -> int:
    client = get_algod_client()
    admin_address, admin_sign = get_admin_signer()
    sponsor_address = env("ALGORAND_SPONSOR_ADDRESS")
    release_operator = env("ALGORAND_HUMANITARIAN_RELEASE_OPERATOR")
    cusd_asset_id = int(env("ALGORAND_CUSD_ASSET_ID", "0") or "0")
    if not release_operator:
        raise SystemExit("ALGORAND_HUMANITARIAN_RELEASE_OPERATOR is required")
    if sponsor_address and release_operator == sponsor_address:
        raise SystemExit("ALGORAND_HUMANITARIAN_RELEASE_OPERATOR must not be the hot sponsor address")
    if not cusd_asset_id:
        raise SystemExit("ALGORAND_CUSD_ASSET_ID is required")

    print("Deploying Confio Ayuda Humanitaria")
    print(f"Admin: {admin_address}")
    print(f"Release operator: {release_operator}")
    print(f"cUSD asset id: {cusd_asset_id}")

    approval_program = compile_teal(client, APPROVAL_TEAL)
    clear_program = compile_teal(client, CLEAR_TEAL)
    approval_size = len(approval_program)
    extra_pages = max(0, (approval_size - 2048 + 2047) // 2048)
    print(f"Approval bytecode: {approval_size} bytes, extra_pages={extra_pages}")
    print(f"Clear bytecode: {len(clear_program)} bytes")

    params = client.suggested_params()
    create_method = Method.from_signature("create(uint64,address,address)void")
    create_txn = ApplicationCreateTxn(
        sender=admin_address,
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=StateSchema(num_uints=6, num_byte_slices=2),
        local_schema=StateSchema(num_uints=0, num_byte_slices=0),
        app_args=[
            create_method.get_selector(),
            UintType(64).encode(cusd_asset_id),
            AddressType().encode(admin_address),
            AddressType().encode(release_operator),
        ],
        extra_pages=extra_pages,
    )
    signed_create = admin_sign(create_txn)
    txid = client.send_transaction(signed_create)
    print(f"Create tx: {txid}")
    confirmed = wait_for_confirmation(client, txid, 10)
    app_id = int(confirmed["application-index"])
    app_address = get_application_address(app_id)
    print(f"App ID: {app_id}")
    print(f"Vault address: {app_address}")

    # Fund app MBR before inner cUSD opt-in.
    params = client.suggested_params()
    fund_txn = PaymentTxn(sender=admin_address, sp=params, receiver=app_address, amt=300_000)
    fund_txid = client.send_transaction(admin_sign(fund_txn))
    wait_for_confirmation(client, fund_txid, 6)
    print(f"Funded app MBR: {fund_txid}")

    params = client.suggested_params()
    params.flat_fee = True
    params.fee = (getattr(params, "min_fee", 1000) or 1000) * 2
    opt_in_method = Method.from_signature("opt_in_cusd()void")
    optin_txn = ApplicationNoOpTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        app_args=[opt_in_method.get_selector()],
        foreign_assets=[cusd_asset_id],
    )
    optin_txid = client.send_transaction(admin_sign(optin_txn))
    wait_for_confirmation(client, optin_txid, 6)
    print(f"cUSD opt-in tx: {optin_txid}")

    state = decode_global_state(client, app_id)
    assets = client.account_info(app_address).get("assets") or []
    opted_cusd = any(int(asset.get("asset-id") or 0) == cusd_asset_id for asset in assets)
    if state.get("cusd_asset_id") != cusd_asset_id:
        raise SystemExit(f"Verification failed: cusd_asset_id={state.get('cusd_asset_id')}")
    if state.get("admin") != admin_address:
        raise SystemExit(f"Verification failed: admin={state.get('admin')}")
    if state.get("release_operator") != release_operator:
        raise SystemExit(f"Verification failed: release_operator={state.get('release_operator')}")
    if not opted_cusd:
        raise SystemExit("Verification failed: app is not opted into cUSD")

    print("Verification passed")
    print(f"ALGORAND_HUMANITARIAN_APP_ID={app_id}")
    print(f"ALGORAND_HUMANITARIAN_VAULT_ADDRESS={app_address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
