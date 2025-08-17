#!/usr/bin/env python3
"""
Deploy the Invite & Send Algorand application.

This script:
- Rebuilds the TEAL artifacts via contracts/invite_send/build_contracts.py
- Compiles approval/clear TEAL with Algod
- Creates the application with proper global schema
- Optionally calls set_sponsor and setup_assets in a single grouped flow
- Saves deployment info to invite_send_deployment.json

Environment variables used (with sensible defaults where possible):
- ALGORAND_ALGOD_ADDRESS (required)
- ALGORAND_ALGOD_TOKEN (optional)
- ALGORAND_NETWORK (optional, for metadata only)
- ALGORAND_DEPLOYER_MNEMONIC (required): mnemonic to sign deploy/config calls
- ALGORAND_SPONSOR_ADDRESS (optional): address to set as sponsor
- ALGORAND_CUSD_ASSET_ID (optional, default from repo settings)
- ALGORAND_CONFIO_ASSET_ID (optional, default from repo settings)

Notes:
- setup_assets() requires a grouped Payment to the app that covers 2 ASA opt-in MBRs.
  The contract uses 100_000 microAlgos per opt-in, so 200_000 total is sufficient.
"""

import base64
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from typing import Optional

try:
    from decouple import config as env
except Exception:
    # Minimal fallback if python-decouple is not available
    def env(key, default=None, cast=None):
        val = os.environ.get(key, default)
        if cast and val is not None:
            return cast(val)
        return val

from algosdk import mnemonic, logic, account
from algosdk.v2client import algod
from algosdk import transaction
from algosdk.atomic_transaction_composer import (
    AccountTransactionSigner,
    AtomicTransactionComposer,
    TransactionWithSigner,
)
from algosdk.abi import Contract, Method, Argument, Returns


# When located under contracts/invite_send/, repo root is two levels up
ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIR = ROOT / "contracts" / "invite_send"
ARTIFACTS_DIR = CONTRACT_DIR / "artifacts"


def run_build() -> None:
    """Run the existing build script to refresh TEAL artifacts."""
    build_script = CONTRACT_DIR / "build_contracts.py"
    if not build_script.exists():
        print("Build script not found:", build_script)
        raise SystemExit(1)

    print("Building Invite Send contract (using build_contracts.py)...")
    result = subprocess.run([sys.executable, str(build_script)], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise SystemExit("Build failed. See output above.")
    print("✓ Build complete.")


def get_algod_client() -> algod.AlgodClient:
    addr = env("ALGORAND_ALGOD_ADDRESS")
    token = env("ALGORAND_ALGOD_TOKEN", default="")
    if not addr:
        raise SystemExit("ALGORAND_ALGOD_ADDRESS is required")
    return algod.AlgodClient(token, addr)


def compile_teal(client: algod.AlgodClient, teal_path: Path) -> bytes:
    if not teal_path.exists():
        raise FileNotFoundError(f"TEAL not found: {teal_path}")
    source = teal_path.read_text()
    compiled = client.compile(source)
    return base64.b64decode(compiled["result"])  # type: ignore[index]


def calc_extra_pages(program: bytes) -> int:
    if len(program) <= 1024:
        return 0
    over = len(program) - 1024
    return math.ceil(over / 2048)


def wait_for_confirmation(client: algod.AlgodClient, txid: str, timeout: int = 10):
    return transaction.wait_for_confirmation(client, txid, timeout)


def create_app(client: algod.AlgodClient, sk: bytes) -> int:
    approval_path = ARTIFACTS_DIR / "invite_send_approval.teal"
    clear_path = ARTIFACTS_DIR / "invite_send_clear.teal"

    print("Compiling TEAL with Algod...")
    approval = compile_teal(client, approval_path)
    clear = compile_teal(client, clear_path)
    print(f"✓ Approval size: {len(approval)} bytes, Clear size: {len(clear)} bytes")

    sender = account.address_from_private_key(sk)
    sp = client.suggested_params()
    # Ensure flat min-fee to avoid underpayment on some nodes
    try:
        sp.flat_fee = True
        sp.fee = max(1000, getattr(sp, 'min_fee', 1000))
    except Exception:
        pass

    global_schema = transaction.StateSchema(num_uints=8, num_byte_slices=2)
    local_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

    extra_pages = max(calc_extra_pages(approval), calc_extra_pages(clear))

    # Beaker-style create expects the ABI method selector as first arg
    abi_path = CONTRACT_DIR / "contract.json"
    create_args = []
    if abi_path.exists():
        try:
            c = Contract.from_json(abi_path.read_text())
            m = next((m for m in c.methods if m.name == "create"), None)
            if m is not None:
                create_args = [m.get_selector()]
        except Exception as e:
            print(f"Warning: failed to load ABI for create selector: {e}")

    txn = transaction.ApplicationCreateTxn(
        sender=sender,
        sp=sp,
        on_complete=transaction.OnComplete.NoOpOC.real,
        approval_program=approval,
        clear_program=clear,
        global_schema=global_schema,
        local_schema=local_schema,
        extra_pages=extra_pages,
        app_args=create_args,
    )
    stx = txn.sign(sk)
    txid = client.send_transaction(stx)
    print(f"Sent app create tx: {txid}")
    rcpt = wait_for_confirmation(client, txid, 20)
    app_id = rcpt.get("application-index")
    if not app_id:
        raise RuntimeError("Application ID not found in confirmation")
    print(f"✓ App created with ID: {app_id}")
    return int(app_id)


def try_set_sponsor(
    client: algod.AlgodClient,
    sk: bytes,
    app_id: int,
    abi_contract: Contract,
    sponsor_address: Optional[str],
) -> None:
    if not sponsor_address:
        raise SystemExit("ALGORAND_SPONSOR_ADDRESS is required for strict deploy")

    method = next((m for m in abi_contract.methods if m.name == "set_sponsor"), None)
    if method is None:
        # Construct method inline if not present in contract.json
        method = Method(
            name="set_sponsor",
            args=[Argument(arg_type="address", name="sponsor")],
            returns=Returns(arg_type="void")
        )

    sender = account.address_from_private_key(sk)
    signer = AccountTransactionSigner(sk)
    sp = client.suggested_params()
    try:
        sp.flat_fee = True
        sp.fee = max(1000, getattr(sp, 'min_fee', 1000))
    except Exception:
        pass

    atc = AtomicTransactionComposer()
    atc.add_method_call(
        app_id=app_id,
        method=method,
        sender=sender,
        sp=sp,
        signer=signer,
        method_args=[sponsor_address],
    )
    print("Calling set_sponsor...")
    result = atc.execute(client, 10)
    print(f"✓ set_sponsor confirmed in round {result.confirmed_round}")


def try_setup_assets(
    client: algod.AlgodClient,
    sk: bytes,
    app_id: int,
    abi_contract: Contract,
    cusd_id: Optional[int],
    confio_id: Optional[int],
) -> None:
    if not (cusd_id and confio_id):
        raise SystemExit("ALGORAND_CUSD_ASSET_ID and ALGORAND_CONFIO_ASSET_ID are required for strict deploy")

    method = next((m for m in abi_contract.methods if m.name == "setup_assets"), None)
    if method is None:
        # Construct method inline if not present in contract.json
        method = Method(
            name="setup_assets",
            args=[Argument(arg_type="uint64", name="cusd_id"), Argument(arg_type="uint64", name="confio_id")],
            returns=Returns(arg_type="void")
        )

    sender = account.address_from_private_key(sk)
    signer = AccountTransactionSigner(sk)
    sp = client.suggested_params()
    try:
        sp.flat_fee = True
        sp.fee = max(1000, getattr(sp, 'min_fee', 1000))
    except Exception:
        pass

    # Step 1: Pre-fund base min (100_000) outside the group so the app can hold two assets
    base_fund = 100_000
    fund_txn = transaction.PaymentTxn(
        sender=sender,
        sp=sp,
        receiver=logic.get_application_address(app_id),
        amt=base_fund,
    )
    client.send_transaction(fund_txn.sign(sk))
    wait_for_confirmation(client, fund_txn.get_txid(), 10)

    # Step 2: Grouped MBR funding for 2 ASA opt-ins (per contract constant)
    mbr_amount = 200_000  # microAlgos
    pay_txn = transaction.PaymentTxn(
        sender=sender,
        sp=sp,
        receiver=logic.get_application_address(app_id),
        amt=mbr_amount,
    )

    atc = AtomicTransactionComposer()
    atc.add_transaction(TransactionWithSigner(pay_txn, signer))

    # Use higher fee for the app call to cover two inner opt-in transactions
    sp_call = client.suggested_params()
    try:
        sp_call.flat_fee = True
        sp_call.fee = max(3000, getattr(sp_call, 'min_fee', 1000))
    except Exception:
        pass

    atc.add_method_call(
        app_id=app_id,
        method=method,
        sender=sender,
        sp=sp_call,
        signer=signer,
        method_args=[cusd_id, confio_id],
        foreign_assets=[cusd_id, confio_id],
    )
    print(f"Calling setup_assets with CUSD={cusd_id}, CONFIO={confio_id}...")
    result = atc.execute(client, 10)
    print(f"✓ setup_assets confirmed in round {result.confirmed_round}")
    # Verify app opt-ins
    app_addr = logic.get_application_address(app_id)
    acct = client.account_info(app_addr)
    aset_ids = {a.get('asset-id') for a in acct.get('assets', [])}
    missing = [aid for aid in (cusd_id, confio_id) if aid not in aset_ids]
    if missing:
        raise SystemExit(f"Post-setup verification failed: app missing opt-ins for assets {missing}")


def save_deployment(app_id: int, app_address: str, network: str) -> None:
    out = {
        "network": network,
        "app_id": app_id,
        "app_address": app_address,
    }
    path = ROOT / "invite_send_deployment.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"Saved deployment info to: {path}")


def update_dotenv_with_app_id(app_id: int, key_name: str = "ALGORAND_INVITE_SEND_APP_ID") -> None:
    """Add or replace the app id entry in the project .env file."""
    env_path = ROOT / ".env"
    line = f"{key_name}={app_id}\n"

    try:
        if not env_path.exists():
            env_path.write_text(line)
            print(f"Created .env with {key_name}.")
            return

        content = env_path.read_text().splitlines(keepends=True)
        found = False
        for i, l in enumerate(content):
            if l.startswith(f"{key_name}="):
                content[i] = line
                found = True
                break
        if not found:
            # Append near other APP_ID lines if possible
            insert_at = None
            for idx, l in enumerate(content):
                if "_APP_ID=" in l:
                    insert_at = idx + 1
            if insert_at is None:
                content.append("\n")
                content.append(line)
            else:
                content.insert(insert_at, line)
        env_path.write_text("".join(content))
        print(f"Updated .env with {key_name}={app_id}")
    except Exception as e:
        print(f"Warning: failed to update .env automatically: {e}")


def main():
    run_build()

    client = get_algod_client()
    network = env("ALGORAND_NETWORK", default="testnet")

    deployer_mn = env("ALGORAND_DEPLOYER_MNEMONIC", default=None)
    if not deployer_mn:
        # Fallbacks: try admin, then sponsor
        deployer_mn = env("ALGORAND_ADMIN_MNEMONIC", default=None) or env("ALGORAND_SPONSOR_MNEMONIC", default=None)
    if not deployer_mn:
        raise SystemExit("Provide ALGORAND_DEPLOYER_MNEMONIC or ALGORAND_ADMIN_MNEMONIC in .env")
    sk = mnemonic.to_private_key(deployer_mn)
    sender = account.address_from_private_key(sk)
    print(f"Deployer: {sender}")

    # Create app
    app_id = create_app(client, sk)
    app_address = logic.get_application_address(app_id)
    print(f"Application address: {app_address}")

    # Load ABI contract description for method calls
    abi_path = CONTRACT_DIR / "contract.json"
    if not abi_path.exists():
        print(f"ABI not found at {abi_path}; method calls will be skipped.")
        return

    contract = Contract.from_json(abi_path.read_text())

    # Optional post-deploy configuration
    try_set_sponsor(
        client,
        sk,
        app_id,
        contract,
        sponsor_address=env("ALGORAND_SPONSOR_ADDRESS", default=None),
    )

    try_setup_assets(
        client,
        sk,
        app_id,
        contract,
        cusd_id=env("ALGORAND_CUSD_ASSET_ID", default=None, cast=int),
        confio_id=env("ALGORAND_CONFIO_ASSET_ID", default=None, cast=int),
    )

    save_deployment(app_id, app_address, network)
    update_dotenv_with_app_id(app_id)
    print("\n✅ Invite & Send deployment complete.")


if __name__ == "__main__":
    main()
