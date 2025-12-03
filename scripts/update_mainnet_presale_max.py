#!/usr/bin/env python3
"""
Update Mainnet Presale Max Contribution

Updates only the max contribution per address for the mainnet presale contract.
Price remains unchanged at $0.20.
"""

import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Load mainnet env
    env_path = os.path.join(repo_root, '.env.mainnet')
    load_dotenv(env_path)
    print(f"Loaded environment from: {env_path}")
except Exception as e:
    print(f"Warning: Could not load .env.mainnet: {e}")
    pass

from algosdk.v2client import algod
from algosdk.transaction import ApplicationCallTxn, OnComplete, wait_for_confirmation
from blockchain.kms_manager import get_kms_signer_from_settings

# Network configuration
ALGOD_ADDRESS = os.getenv("ALGORAND_ALGOD_ADDRESS", "https://mainnet-api.4160.nodely.dev")
ALGOD_TOKEN = os.getenv("ALGORAND_ALGOD_TOKEN", "")


def update_presale_parameter(algod_client, app_id, admin_address, signer, param_type, value, confio_asset_id=None):
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

    signed_txn = signer.sign_transaction(txn)
    tx_id = algod_client.send_transaction(signed_txn)

    result = wait_for_confirmation(algod_client, tx_id, 4)
    print(f"✅ Parameter '{param_type}' updated successfully!")
    print(f"   Transaction ID: {tx_id}")

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
    """Update mainnet presale max parameter only"""
    print("=" * 60)
    print("MAINNET PRESALE - UPDATE MAX CONTRIBUTION")
    print("=" * 60)

    app_id = int(os.getenv('ALGORAND_PRESALE_APP_ID', '0') or '0')
    confio_asset_id = int(os.getenv('ALGORAND_CONFIO_ASSET_ID', '0') or '0')
    admin_address = os.getenv('ALGORAND_SPONSOR_ADDRESS')
    try:
        signer = get_kms_signer_from_settings()
        if admin_address:
            signer.assert_matches_address(admin_address)
        admin_address = admin_address or signer.address
    except Exception as e:
        signer = None

    print(f"\nConfiguration:")
    print(f"   Network: MAINNET")
    print(f"   Algod: {ALGOD_ADDRESS}")
    print(f"   Presale App ID: {app_id}")
    print(f"   CONFIO Asset ID: {confio_asset_id}")
    print(f"   Admin Address: {admin_address}")

    if not (app_id and confio_asset_id and admin_address and signer):
        print('\n❌ ERROR: Missing required environment variables.')
        print('   Required: ALGORAND_PRESALE_APP_ID, ALGORAND_CONFIO_ASSET_ID,')
        print('             ALGORAND_SPONSOR_ADDRESS, USE_KMS_SIGNING/KMS_KEY_ALIAS')
        return

    # Verify this is mainnet
    if app_id < 1000000000:  # Testnet app IDs are typically < 1B
        print('\n⚠️  WARNING: App ID suggests this might not be mainnet!')
        response = input('   Continue anyway? (yes/no): ')
        if response.lower() != 'yes':
            print('   Aborted.')
            return

    algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

    # Get current state
    print("\n" + "=" * 60)
    print("CURRENT PRESALE STATE")
    print("=" * 60)
    state = get_presale_state(algod_client, app_id)

    print(f"   Price: ${state.get('price', 0) / 10**6:.2f} cUSD per CONFIO")
    print(f"   Max Per Address: ${state.get('max_addr', 0) / 10**6:.2f} cUSD")
    print(f"   Min Buy: ${state.get('min_buy', 0) / 10**6:.2f} cUSD")
    print(f"   Round Cap: ${state.get('cusd_cap', 0) / 10**6:,.2f} cUSD")
    print(f"   Round Raised: ${state.get('cusd_raised', 0) / 10**6:,.2f} cUSD")
    print(f"   Round Active: {'Yes' if state.get('active', 0) == 1 else 'No'}")

    # Confirm before proceeding
    print("\n" + "=" * 60)
    print("PROPOSED CHANGE")
    print("=" * 60)
    print(f"   Update Max Per Address: ${state.get('max_addr', 0) / 10**6:.2f} → $5,000.00 cUSD")
    print(f"   Keep Price: ${state.get('price', 0) / 10**6:.2f} cUSD per CONFIO (unchanged)")
    print("=" * 60)

    response = input('\n⚠️  This will update the MAINNET contract. Continue? (yes/no): ')
    if response.lower() != 'yes':
        print('Aborted.')
        return

    # Update max per address to $5,000 (5,000,000,000 with 6 decimals)
    new_max = 5_000_000_000  # 5,000 cUSD
    update_presale_parameter(
        algod_client=algod_client,
        app_id=app_id,
        admin_address=admin_address,
        signer=signer,
        param_type="max",
        value=new_max,
        confio_asset_id=confio_asset_id
    )

    # Get updated state
    state = get_presale_state(algod_client, app_id)

    print("\n" + "=" * 60)
    print("✅ MAINNET PRESALE UPDATED SUCCESSFULLY")
    print("=" * 60)
    print(f"   Price: ${state.get('price', 0) / 10**6:.2f} cUSD per CONFIO")
    print(f"   Max Per Address: ${state.get('max_addr', 0) / 10**6:,.2f} cUSD")
    print(f"   Min Buy: ${state.get('min_buy', 0) / 10**6:.2f} cUSD")
    print("=" * 60)


if __name__ == "__main__":
    main()
