#!/usr/bin/env python3
"""
Deploy the CONFIO rewards vault to Algorand testnet and run a basic smoke test.

Steps performed:
    1. Compile the PyTeal approval/clear programs and create the application.
    2. Bootstrap the vault (ASA opt-in) via an atomic group.
    3. Fund the vault with a small CONFIO balance.
    4. Generate a fresh user account, fund it, and opt it into CONFIO.
    5. Set a manual price override, mark the user eligible, and have them claim.

Environment (export before running or pass inline):
    ALGORAND_ALGOD_ADDRESS
    ALGORAND_ALGOD_TOKEN    (empty string for algonode)
    ALGORAND_CONFIO_ASSET_ID
    ALGORAND_SPONSOR_MNEMONIC
    ALGORAND_ADMIN_MNEMONIC (defaults to sponsor mnemonic)

Usage:
    ALGORAND_ALGOD_ADDRESS=https://testnet-api.algonode.cloud \\
    ALGORAND_ALGOD_TOKEN= \\
    ALGORAND_CONFIO_ASSET_ID=3198329568 \\
    ALGORAND_SPONSOR_MNEMONIC="word1 ... word25" \\
    ./myvenv/bin/python contracts/rewards/deploy_rewards.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from algosdk import account, encoding, mnemonic
from algosdk import transaction
from algosdk.transaction import (
    ApplicationCreateTxn,
    ApplicationNoOpTxn,
    AssetTransferTxn,
    BoxReference,
    OnComplete,
    PaymentTxn,
    StateSchema,
    Transaction,
)
from algosdk.logic import get_application_address
from algosdk.v2client import algod
from blockchain.kms_manager import KMSSigner

from contracts.rewards.confio_rewards import compile_confio_rewards


def decode_app_log(log_entry: str) -> str:
    raw = base64.b64decode(log_entry)
    if raw.startswith(b"ELIGIBLE|"):
        offset = len(b"ELIGIBLE|")
        addr_bytes = raw[offset:offset + 32]
        offset += 32
        if raw[offset:offset + 1] != b"|":
            return raw.decode("utf-8", "ignore")
        offset += 1
        amount = int.from_bytes(raw[offset:offset + 8], "big")
        offset += 8
        if raw[offset:offset + 1] != b"|":
            return raw.decode("utf-8", "ignore")
        offset += 1
        round_id = int.from_bytes(raw[offset:offset + 8], "big")
        offset += 8
        if raw[offset:offset + 1] != b"|":
            return raw.decode("utf-8", "ignore")
        offset += 1
        ref_addr_bytes = raw[offset:offset + 32]
        offset += 32
        if raw[offset:offset + 1] != b"|":
            return raw.decode("utf-8", "ignore")
        offset += 1
        ref_amount = int.from_bytes(raw[offset:offset + 8], "big")
        try:
            addr = encoding.encode_address(addr_bytes)
        except Exception:
            addr = base64.b64encode(addr_bytes).decode("utf-8")
        try:
            ref = (
                "None"
                if ref_addr_bytes == bytes(32)
                else encoding.encode_address(ref_addr_bytes)
            )
        except Exception:
            ref = base64.b64encode(ref_addr_bytes).decode("utf-8")
        return f"ELIGIBLE|{addr}|{amount}|round={round_id}|ref={ref}|ref_amt={ref_amount}"
    if raw.startswith(b"CLAIM|"):
        prefix = len(b"CLAIM|")
        addr_bytes = raw[prefix:prefix + 32]
        amount = int.from_bytes(raw[prefix + 32:], "big")
        try:
            addr = encoding.encode_address(addr_bytes)
        except Exception:
            addr = base64.b64encode(addr_bytes).decode("utf-8")
        return f"CLAIM|{addr}|{amount}"
    if raw.startswith(b"REF|"):
        prefix = len(b"REF|")
        ref_addr_bytes = raw[prefix:prefix + 32]
        user_addr_bytes = raw[prefix + 32:prefix + 64]
        amount = int.from_bytes(raw[prefix + 64:], "big")
        try:
            ref_addr = encoding.encode_address(ref_addr_bytes)
        except Exception:
            ref_addr = base64.b64encode(ref_addr_bytes).decode("utf-8")
        try:
            user_addr = encoding.encode_address(user_addr_bytes)
        except Exception:
            user_addr = base64.b64encode(user_addr_bytes).decode("utf-8")
        return f"REF|{ref_addr}|{user_addr}|{amount}"
    try:
        return raw.decode("utf-8", "ignore")
    except Exception:
        return base64.b64encode(raw).decode("utf-8")


@dataclass
class Accounts:
    sponsor_addr: str
    sponsor_signer: Callable[[Transaction], transaction.SignedTransaction]
    admin_addr: str
    admin_signer: Callable[[Transaction], transaction.SignedTransaction]


def read_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def read_env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).lower() in ("1", "true", "yes", "on")


def init_accounts() -> Accounts:
    """Initialize sponsor/admin signers from KMS if enabled, else from mnemonics."""
    kms_enabled = os.getenv("USE_KMS_SIGNING", "").lower() == "true" or bool(os.getenv("KMS_KEY_ALIAS"))
    if kms_enabled:
        region = os.getenv("KMS_REGION", "eu-central-2")
        sponsor_alias = read_env("KMS_KEY_ALIAS")
        admin_alias = os.getenv("KMS_ADMIN_KEY_ALIAS") or sponsor_alias

        sponsor_kms = KMSSigner(sponsor_alias, region_name=region)
        admin_kms = KMSSigner(admin_alias, region_name=region)

        expected_sponsor = os.getenv("ALGORAND_SPONSOR_ADDRESS")
        expected_admin = os.getenv("ALGORAND_ADMIN_ADDRESS") or expected_sponsor
        if expected_sponsor and sponsor_kms.address != expected_sponsor:
            print(f"[warn] KMS sponsor address {sponsor_kms.address} != ALGORAND_SPONSOR_ADDRESS {expected_sponsor}")
        if expected_admin and admin_kms.address != expected_admin:
            print(f"[warn] KMS admin address {admin_kms.address} != ALGORAND_ADMIN_ADDRESS {expected_admin}")

        return Accounts(
            sponsor_addr=sponsor_kms.address,
            sponsor_signer=sponsor_kms.sign_transaction,
            admin_addr=admin_kms.address,
            admin_signer=admin_kms.sign_transaction,
        )

    sponsor_mnemonic = read_env("ALGORAND_SPONSOR_MNEMONIC")
    sponsor_key = mnemonic.to_private_key(sponsor_mnemonic)
    sponsor_addr = account.address_from_private_key(sponsor_key)

    admin_mnemonic = os.getenv("ALGORAND_ADMIN_MNEMONIC") or sponsor_mnemonic
    admin_key = mnemonic.to_private_key(admin_mnemonic)
    admin_addr = account.address_from_private_key(admin_key)

    return Accounts(
        sponsor_addr=sponsor_addr,
        sponsor_signer=lambda txn: txn.sign(sponsor_key),
        admin_addr=admin_addr,
        admin_signer=lambda txn: txn.sign(admin_key),
    )


def update_dotenv_with_app_id(app_id: int, key_name: str = "ALGORAND_REWARD_APP_ID") -> None:
    """Write/replace the reward app id in the project .env."""
    root = Path(__file__).resolve().parents[2]
    env_path = root / ".env"
    line = f"{key_name}={app_id}\n"
    try:
        if not env_path.exists():
            env_path.write_text(line)
            print(f"[i] Created .env with {key_name}={app_id}")
            return
        content = env_path.read_text().splitlines(keepends=True)
        replaced = False
        for i, l in enumerate(content):
            if l.startswith(f"{key_name}="):
                content[i] = line
                replaced = True
                break
        if not replaced:
            content.append(line)
        env_path.write_text("".join(content))
        print(f"[i] Updated .env with {key_name}={app_id}")
    except Exception as e:
        print(f"[warn] Failed to update .env automatically: {e}")


def get_algod_client() -> algod.AlgodClient:
    algod_address = read_env("ALGORAND_ALGOD_ADDRESS")
    algod_token = os.getenv("ALGORAND_ALGOD_TOKEN", "")
    return algod.AlgodClient(algod_token, algod_address)


def decode_global_state(state: list[dict]) -> dict[bytes, object]:
    decoded: dict[bytes, object] = {}
    for entry in state:
        key = base64.b64decode(entry["key"])
        value = entry["value"]
        if value.get("type") == 1:
            decoded[key] = base64.b64decode(value.get("bytes", ""))
        else:
            decoded[key] = value.get("uint", 0)
    return decoded


def wait_for_confirmation(client: algod.AlgodClient, txid: str, timeout: int = 10) -> dict:
    last_round = client.status().get("last-round")
    start_round = last_round
    current_round = start_round
    while current_round < start_round + timeout:
        pending = client.pending_transaction_info(txid)
        if pending.get("confirmed-round", 0) > 0:
            return pending
        if pending.get("pool-error"):
            raise RuntimeError(f"Transaction {txid} rejected: {pending['pool-error']}")
        current_round += 1
        client.status_after_block(current_round)
    raise TimeoutError(f"Transaction {txid} not confirmed after {timeout} rounds")


def compile_program(client: algod.AlgodClient, source: str) -> bytes:
    response = client.compile(source)
    return base64.b64decode(response["result"])


def create_rewards_app(
    client: algod.AlgodClient,
    accounts: Accounts,
    confio_asset_id: int,
) -> int:
    approval_src = compile_confio_rewards()
    clear_src = "#pragma version 8\nint 1\n"
    approval_program = compile_program(client, approval_src)
    clear_program = compile_program(client, clear_src)
    approval_length = len(approval_program)
    extra_pages = max((approval_length + 1023) // 1024 - 1, 0)

    global_schema = StateSchema(num_uints=14, num_byte_slices=2)
    local_schema = StateSchema(num_uints=0, num_byte_slices=0)

    app_args = [
        confio_asset_id.to_bytes(8, "big"),
        encoding.decode_address(accounts.admin_addr),
        encoding.decode_address(accounts.sponsor_addr),
    ]

    params = client.suggested_params()
    total_schema_entries = (
        global_schema.num_uints
        + global_schema.num_byte_slices
        + local_schema.num_uints
        + local_schema.num_byte_slices
    )
    params.flat_fee = True
    params.fee = 1000 * (1 + total_schema_entries)
    txn = ApplicationCreateTxn(
        sender=accounts.admin_addr,
        sp=params,
        on_complete=OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=global_schema,
        local_schema=local_schema,
        app_args=app_args,
        extra_pages=extra_pages,
    )

    signed = accounts.admin_signer(txn)
    txid = client.send_transaction(signed)
    info = wait_for_confirmation(client, txid)
    app_id = info["application-index"]
    print(f"[+] Deployed rewards app: {app_id}")
    return app_id


def grouped_send(client: algod.AlgodClient, txns: Iterable[Transaction], signers: Iterable[Callable[[Transaction], transaction.SignedTransaction]]) -> dict:
    txns = list(txns)
    signers_list = list(signers)
    if len(txns) != len(signers_list):
        raise ValueError("Number of transactions and signing functions must match")
    transaction.assign_group_id(txns)
    signed = [signer(txn) for txn, signer in zip(txns, signers_list)]
    tx_ids = []
    for s in signed:
        if hasattr(s, "transaction"):
            tx_ids.append(s.transaction.get_txid())
        elif hasattr(s, "get_txid"):
            tx_ids.append(s.get_txid())
        else:
            tx_ids.append(None)
    try:
        client.send_transactions(signed)
        info = wait_for_confirmation(client, tx_ids[-1])
        return info
    except Exception as exc:  # capture detailed rejection info
        try:
            status = client.pending_transaction_info(tx_ids[-1])
            pool_error = status.get("pool-error")
            if pool_error:
                print(f"[pool-error] {pool_error}")
            app_messages = status.get("app-call-messages")
            if app_messages:
                decoded = [msg for msg in app_messages]
                print(f"[app-call-messages] {decoded}")
            logs = status.get("logs")
            if logs:
                decoded_logs = []
                for entry in logs:
                    try:
                        decoded_logs.append(base64.b64decode(entry).decode("utf-8", "ignore"))
                    except Exception:
                        decoded_logs.append(entry)
                print(f"[app-logs] {decoded_logs}")
        except Exception as inner:
            print(f"[debug] failed to fetch pending info: {inner}")
        print(f"[debug] send_transactions exception: {exc}")
        if hasattr(exc, "args"):
            print(f"[debug] exception args: {exc.args}")
        raise


def bootstrap_vault(
    client: algod.AlgodClient,
    app_id: int,
    accounts: Accounts,
    confio_asset_id: int,
    payment_amount: int = 350_000,
) -> None:
    app_address = get_application_address(app_id)
    params = client.suggested_params()
    payment_txn = PaymentTxn(
        sender=accounts.sponsor_addr,
        receiver=app_address,
        amt=payment_amount,
        sp=params,
    )
    app_call_params = client.suggested_params()
    app_call_params.flat_fee = True
    app_call_params.fee = max(app_call_params.min_fee, 1000) * 2
    app_call_txn = ApplicationNoOpTxn(
        sender=accounts.admin_addr,
        index=app_id,
        app_args=[b"bootstrap"],
        foreign_assets=[confio_asset_id],
        sp=app_call_params,
    )
    grouped_send(client, [payment_txn, app_call_txn], [accounts.sponsor_signer, accounts.admin_signer])
    print(f"[+] Bootstrapped vault (ASA opt-in)")


def fund_vault_with_confio(client: algod.AlgodClient, app_id: int, accounts: Accounts, asset_id: int, amount: int = 100_000_000) -> None:
    app_address = get_application_address(app_id)
    params = client.suggested_params()
    txn = AssetTransferTxn(
        sender=accounts.sponsor_addr,
        sp=params,
        receiver=app_address,
        amt=amount,
        index=asset_id,
    )
    signed = accounts.sponsor_signer(txn)
    txid = client.send_transaction(signed)
    wait_for_confirmation(client, txid)
    print(f"[+] Funded vault with {amount} CONFIO micro-units")


def create_and_fund_user(client: algod.AlgodClient, sponsor_addr: str, sponsor_signer: Callable[[Transaction], transaction.SignedTransaction], asset_id: int) -> tuple[str, str]:
    user_private_key, user_address = account.generate_account()
    params = client.suggested_params()
    funding_txn = PaymentTxn(
        sender=sponsor_addr,
        receiver=user_address,
        amt=1_000_000,
        sp=params,
    )
    signed_funding = sponsor_signer(funding_txn)
    txid = client.send_transaction(signed_funding)
    wait_for_confirmation(client, txid)
    print(f"[+] Funded new user {user_address}")

    try:
        optin_params = client.suggested_params()
    except Exception:
        optin_params = params
    optin_params.flat_fee = True
    optin_params.fee = max(optin_params.min_fee, 1000)
    optin_txn = AssetTransferTxn(
        sender=user_address,
        sp=optin_params,
        receiver=user_address,
        amt=0,
        index=asset_id,
    )
    signed_optin = optin_txn.sign(user_private_key)
    txid = client.send_transaction(signed_optin)
    wait_for_confirmation(client, txid)
    print(f"[+] User opted into CONFIO ASA")

    return user_private_key, user_address


def set_price_override(client: algod.AlgodClient, app_id: int, accounts: Accounts, price: int, round_id: int = 0) -> None:
    params = client.suggested_params()
    txn = ApplicationNoOpTxn(
        sender=accounts.admin_addr,
        index=app_id,
        sp=params,
        app_args=[
            b"set_price_override",
            price.to_bytes(8, "big"),
            round_id.to_bytes(8, "big"),
        ],
    )
    signed = accounts.admin_signer(txn)
    txid = client.send_transaction(signed)
    wait_for_confirmation(client, txid)
    print(f"[+] Manual price override set to {price} micro-cUSD per CONFIO")


def mark_user_eligible(
    client: algod.AlgodClient,
    app_id: int,
    accounts: Accounts,
    user_addr: str,
    reward_cusd_micro: int,
    confio_asset_id: int,
) -> None:
    app_address = get_application_address(app_id)
    params = client.suggested_params()
    payment_amt = 100_000
    pay_txn = PaymentTxn(
        sender=accounts.sponsor_addr,
        receiver=app_address,
        amt=payment_amt,
        sp=params,
    )

    call_params = client.suggested_params()
    user_key_bytes = encoding.decode_address(user_addr)
    app_args = [
        b"mark_eligible",
        reward_cusd_micro.to_bytes(8, "big"),
        user_key_bytes,
    ]
    app_state = decode_global_state(
        client.application_info(app_id)["params"].get("global-state", [])
    )
    admin_on_chain = app_state.get(b"admin")
    sponsor_on_chain = app_state.get(b"sponsor")
    boot_flag = int(app_state.get(b"boot", 0))
    paused_flag = int(app_state.get(b"paused", 0))

    print(
        "[probe] admin",
        encoding.encode_address(admin_on_chain) if admin_on_chain else "unset",
    )
    print(
        "[probe] sponsor",
        encoding.encode_address(sponsor_on_chain) if sponsor_on_chain else "unset",
    )
    print("[probe] boot", boot_flag)
    print("[probe] paused", paused_flag)

    expected_admin = encoding.decode_address(accounts.admin_addr)
    expected_sponsor = encoding.decode_address(accounts.sponsor_addr)
    if admin_on_chain and admin_on_chain != expected_admin:
        raise RuntimeError("Admin mismatch between chain and local config")
    if sponsor_on_chain and sponsor_on_chain != expected_sponsor:
        raise RuntimeError("Sponsor mismatch between chain and local config")
    if boot_flag != 1:
        raise RuntimeError("Rewards app not bootstrapped before eligibility call")
    if paused_flag != 0:
        raise RuntimeError("Rewards app is paused; cannot mark eligibility")

    app_call = ApplicationNoOpTxn(
        sender=accounts.admin_addr,
        index=app_id,
        sp=call_params,
        app_args=app_args,
        accounts=[user_addr],
        foreign_assets=[confio_asset_id],
        boxes=[BoxReference(0, user_key_bytes)],
    )
    if os.getenv("DEBUG_MARK_ELIGIBLE"):
        print("[debug] accounts", app_call.accounts)
        print("[debug] user arg", encoding.encode_address(user_key_bytes))
    print("[debug] mark_eligible txn", app_call.dictify())

    grouped_send(client, [pay_txn, app_call], [accounts.sponsor_signer, accounts.admin_signer])
    print(f"[+] Marked {user_addr} eligible for {reward_cusd_micro} micro-cUSD reward")


def user_claim_reward(
    client: algod.AlgodClient,
    app_id: int,
    user_addr: str,
    user_key: str,
    confio_asset_id: int,
) -> dict:
    params = client.suggested_params()
    params.flat_fee = True
    params.fee = 2_000  # cover inner transfer
    txn = ApplicationNoOpTxn(
        sender=user_addr,
        index=app_id,
        sp=params,
        app_args=[b"claim"],
        foreign_assets=[confio_asset_id],
        boxes=[BoxReference(0, encoding.decode_address(user_addr))],
    )
    print("[debug] claim txn", txn.dictify())
    signed = txn.sign(user_key)
    txid = client.send_transaction(signed)
    info = wait_for_confirmation(client, txid)
    info.setdefault("txid", txid)
    print(f"[+] User claimed reward (txid: {txid})")
    return info


def main() -> None:
    client = get_algod_client()
    accounts = init_accounts()

    confio_asset_id = int(read_env("ALGORAND_CONFIO_ASSET_ID"))
    skip_smoke = read_env_bool("SKIP_SMOKE_TEST", default=True)
    fund_amount = int(os.getenv("REWARDS_FUND_AMOUNT", "100000000"))
    update_env = read_env_bool("UPDATE_ENV_APP_ID", default=True)

    app_id = create_rewards_app(client, accounts, confio_asset_id)
    app_address = get_application_address(app_id)
    print(f"[i] Application address: {app_address}")
    if update_env:
        update_dotenv_with_app_id(app_id)

    bootstrap_vault(client, app_id, accounts, confio_asset_id)
    if fund_amount > 0:
        fund_vault_with_confio(client, app_id, accounts, confio_asset_id, amount=fund_amount)
    else:
        print("[i] Skipping funding vault (REWARDS_FUND_AMOUNT<=0)")

    if skip_smoke:
        print("[i] SKIP_SMOKE_TEST set; stopping after bootstrap/fund.")
        return

    user_key, user_addr = create_and_fund_user(client, accounts.sponsor_addr, accounts.sponsor_signer, confio_asset_id)

    set_price_override(client, app_id, accounts, price=250_000, round_id=1)
    mark_user_eligible(
        client,
        app_id,
        accounts,
        user_addr=user_addr,
        reward_cusd_micro=5_000_000,  # $5
        confio_asset_id=confio_asset_id,
    )

    if os.getenv("SKIP_CLAIM"):
        print("[debug] SKIP_CLAIM set; skipping user claim")
        return

    claim_info = user_claim_reward(client, app_id, user_addr, user_key, confio_asset_id)
    logs = claim_info.get("logs", [])
    if logs:
        decoded_logs = [decode_app_log(log) for log in logs]
        print("[i] Claim transaction logs:")
        for line in decoded_logs:
            print("    ", line)

    if os.getenv("DEBUG_MARK_ELIGIBLE"):
        print("[debug] claim_info keys", list(claim_info.keys()))

    summary = {
        "app_id": app_id,
        "app_address": app_address,
        "user_address": user_addr,
        "claim_txid": claim_info.get("txid") or claim_info.get("transaction"),
    }
    print("[✓] Deployment + smoke test complete")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
