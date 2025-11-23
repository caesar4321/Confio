#!/usr/bin/env python3
"""
Update Presale Contract Parameters

Updates the price and max contribution per address for the presale contract.
"""

import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(repo_root, '.env'))
except Exception:
    pass

from algosdk import mnemonic
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCallTxn,
    OnComplete,
    wait_for_confirmation
)

# Network configuration
ALGOD_ADDRESS = os.getenv("ALGORAND_ALGOD_ADDRESS", "http://localhost:4001")
ALGOD_TOKEN = os.getenv("ALGORAND_ALGOD_TOKEN", "")


def update_presale_parameter(algod_client, app_id, admin_address, admin_sk, param_type, value, confio_asset_id=None):
    """Update a presale contract parameter"""

    print(f"\nUpdating parameter '{param_type}' to {value}...")

    params = algod_client.suggested_params()

    # Price and cap updates need CONFIO asset in foreign_assets for balance checks
    foreign_assets = []
    if param_type in ["price", "cap"] and confio_asset_id:
        foreign_assets = [confio_asset_id]

    txn = ApplicationCallTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        app_args=[
            b"update",
            param_type.encode('utf-8'),
            value.to_bytes(8, 'big')
        ],
        foreign_assets=foreign_assets,
        on_complete=OnComplete.NoOpOC
    )

    signed_txn = txn.sign(admin_sk)
    tx_id = algod_client.send_transaction(signed_txn)

    result = wait_for_confirmation(algod_client, tx_id, 4)
    print(f"✅ Parameter '{param_type}' updated successfully!")

    return result


def get_presale_state(algod_client, app_id):
    """Get current presale state"""
    import base64

    app_info = algod_client.application_info(app_id)
    state = {}

    for item in app_info['params']['global-state']:
        key = base64.b64decode(item['key']).decode('utf-8', errors='ignore')
        value_obj = item['value']

        if value_obj['type'] == 2:  # uint
            state[key] = value_obj.get('uint', 0)

    return state


def main():
    """Update presale parameters"""
    print("Presale Contract Parameter Update")
    print("=" * 40)

    # Read env vars
    from algosdk import mnemonic as _mn

    app_id = int(os.getenv('ALGORAND_PRESALE_APP_ID', '0') or '0')
    confio_asset_id = int(os.getenv('ALGORAND_CONFIO_ASSET_ID', '0') or '0')
    admin_address = os.getenv('ALGORAND_SPONSOR_ADDRESS')
    admin_mn = os.getenv('ALGORAND_ADMIN_MNEMONIC')

    # Normalize mnemonic
    def _norm(m):
        if not m:
            return m
        return " ".join(m.strip().split()).lower()

    admin_mn = _norm(admin_mn)

    if not (app_id and admin_address and admin_mn):
        print('Missing env. Set ALGORAND_PRESALE_APP_ID, ALGORAND_SPONSOR_ADDRESS, ALGORAND_ADMIN_MNEMONIC.')
        return

    admin_sk = _mn.to_private_key(admin_mn)
    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    # Get current state
    print(f"\nPresale App ID: {app_id}")
    state = get_presale_state(algod_client, app_id)

    print("\nCurrent Parameters:")
    print(f"   Price: {state.get('price', 0) / 10**6:.6f} cUSD per CONFIO")
    print(f"   Max Per Address: {state.get('max_addr', 0) / 10**6:.2f} cUSD")
    print(f"   Min Buy: {state.get('min_buy', 0) / 10**6:.2f} cUSD")
    print(f"   Round Cap: {state.get('cusd_cap', 0) / 10**6:.2f} cUSD")

    # Update price to $0.25 (250,000 with 6 decimals)
    new_price = 250_000  # 0.25 cUSD
    update_presale_parameter(
        algod_client=algod_client,
        app_id=app_id,
        admin_address=admin_address,
        admin_sk=admin_sk,
        param_type="price",
        value=new_price,
        confio_asset_id=confio_asset_id
    )

    # Update max per address to $5,000 (5,000,000,000 with 6 decimals)
    new_max = 5_000_000_000  # 5,000 cUSD
    update_presale_parameter(
        algod_client=algod_client,
        app_id=app_id,
        admin_address=admin_address,
        admin_sk=admin_sk,
        param_type="max",
        value=new_max,
        confio_asset_id=confio_asset_id
    )

    # Get updated state
    state = get_presale_state(algod_client, app_id)

    print("\n" + "=" * 40)
    print("UPDATED PARAMETERS")
    print("=" * 40)
    print(f"   Price: {state.get('price', 0) / 10**6:.6f} cUSD per CONFIO")
    print(f"   Max Per Address: {state.get('max_addr', 0) / 10**6:.2f} cUSD")
    print(f"   Min Buy: {state.get('min_buy', 0) / 10**6:.2f} cUSD")
    print("=" * 40)


if __name__ == "__main__":
    main()
