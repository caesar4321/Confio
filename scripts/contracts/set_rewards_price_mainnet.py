#!/usr/bin/env python3
"""
Set the manual price override for the CONFIO rewards vault on MainNet.

This script sets the price to $0.20 USD per CONFIO token, which enables
the rewards vault to accept eligibility entries.

Usage:
    python scripts/set_rewards_price_mainnet.py

Environment variables (from .env.mainnet):
    ALGORAND_REWARD_APP_ID - The deployed rewards app ID
    KMS_KEY_ALIAS - KMS key for signing (confio-mainnet-sponsor)
    KMS_REGION - AWS region (eu-central-2)
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Load Django settings to get mainnet configuration
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from algosdk.v2client import algod
from algosdk import transaction
from django.conf import settings
from blockchain.kms_manager import get_kms_signer_from_settings

def main():
    # Get configuration from Django settings (loaded from .env.mainnet)
    app_id = getattr(settings, 'ALGORAND_REWARD_APP_ID', None)
    if not app_id:
        print("ERROR: ALGORAND_REWARD_APP_ID not configured", file=sys.stderr)
        sys.exit(1)

    algod_address = getattr(settings, 'ALGORAND_ALGOD_ADDRESS', None)
    algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '')

    if not algod_address:
        print("ERROR: ALGORAND_ALGOD_ADDRESS not configured", file=sys.stderr)
        sys.exit(1)

    # Price: $0.20 USD per CONFIO token
    # In micro-cUSD: $0.20 * 1,000,000 = 200,000 micro-cUSD
    price_usd = 0.20
    manual_price_micro_cusd = int(price_usd * 1_000_000)

    print(f"=== Setting CONFIO Price on MainNet ===")
    print(f"App ID: {app_id}")
    print(f"Price: ${price_usd:.2f} USD per CONFIO")
    print(f"Price (micro-cUSD): {manual_price_micro_cusd:,}")
    print()

    # Initialize Algorand client
    client = algod.AlgodClient(algod_token, algod_address)

    # Get KMS signer (admin)
    signer = get_kms_signer_from_settings()
    admin_address = signer.address

    print(f"Admin address: {admin_address}")
    print()

    # Verify current state
    print("Checking current rewards vault state...")
    try:
        app_info = client.application_info(app_id)
        global_state = app_info.get('params', {}).get('global-state', [])

        import base64
        state_dict = {}
        for entry in global_state:
            key = base64.b64decode(entry.get('key', '')).decode('utf-8', errors='ignore')
            value = entry.get('value', {})
            if value.get('type') == 2:  # uint
                state_dict[key] = value.get('uint')

        current_manual_active = state_dict.get('manual_active', 0)
        current_manual_price = state_dict.get('manual_price', 0)

        print(f"  Current MANUAL_ACTIVE: {current_manual_active}")
        print(f"  Current MANUAL_PRICE: {current_manual_price:,} micro-cUSD")

        if current_manual_active == 1 and current_manual_price == manual_price_micro_cusd:
            print()
            print("✅ Price is already correctly set!")
            print("   No action needed.")
            return

        print()
    except Exception as exc:
        print(f"  Warning: Could not read current state: {exc}")
        print()

    # Build set_price_override transaction
    print("Building set_price_override transaction...")
    params = client.suggested_params()

    price_call = transaction.ApplicationNoOpTxn(
        sender=admin_address,
        index=app_id,
        sp=params,
        app_args=[
            b'set_price_override',
            manual_price_micro_cusd.to_bytes(8, 'big')
        ],
    )

    # Sign with KMS
    print("Signing transaction with KMS...")
    signed = signer.sign_transaction(price_call)

    # Send transaction
    print("Sending transaction...")
    tx_id = client.send_transaction(signed)
    print(f"Transaction ID: {tx_id}")
    print()

    # Wait for confirmation
    print("Waiting for confirmation...")
    result = transaction.wait_for_confirmation(client, tx_id, 6)
    confirmed_round = result.get('confirmed-round', 0)

    print()
    print("=" * 50)
    print("✅ SUCCESS!")
    print("=" * 50)
    print(f"Price set to ${price_usd:.2f} USD per CONFIO")
    print(f"Confirmed in round: {confirmed_round}")
    print(f"Transaction ID: {tx_id}")
    print()
    print("The rewards vault is now ready to accept eligibility entries!")
    print()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAborted by user", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
