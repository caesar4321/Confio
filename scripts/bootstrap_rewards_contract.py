#!/usr/bin/env python3
"""
Bootstrap a newly deployed CONFIO rewards contract with:
- CONFIO asset ID configuration
- Reward amounts (20 CONFIO for both referee and referrer)
- Box pricing
- Asset opt-in

Usage:
    ALGORAND_REWARD_APP_ID=123456 \
    ALGORAND_CONFIO_ASSET_ID=749148838 \
    ALGORAND_ADMIN_MNEMONIC="your 25-word mnemonic" \
    python scripts/bootstrap_rewards_contract.py
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

from algosdk import account, mnemonic, transaction
from algosdk.v2client import algod


def env(key: str, default: str | None = None) -> str:
    """Get environment variable or raise error if not found."""
    value = os.environ.get(key, default)
    if value is None:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


def main() -> None:
    # Get configuration
    app_id = int(env("ALGORAND_REWARD_APP_ID"))
    confio_asset_id = int(env("ALGORAND_CONFIO_ASSET_ID"))
    admin_mnemonic = env("ALGORAND_ADMIN_MNEMONIC")
    algod_url = env("ALGORAND_ALGOD_ADDRESS", "https://testnet-api.4160.nodely.dev")
    algod_token = env("ALGORAND_ALGOD_TOKEN", "")

    # Reward amounts (20 CONFIO with 6 decimals = 20_000_000)
    referee_reward = 20_000_000
    referrer_reward = 20_000_000

    # Box price in microAlgos (0.0025 ALGO per byte, 72 bytes = 180,000 microAlgos)
    box_price = 180_000

    # Initialize client
    client = algod.AlgodClient(algod_token, algod_url)

    # Get admin account
    admin_private_key = mnemonic.to_private_key(admin_mnemonic)
    admin_address = account.address_from_private_key(admin_private_key)

    print(f"Bootstrapping rewards contract:")
    print(f"  App ID:          {app_id}")
    print(f"  Admin:           {admin_address}")
    print(f"  CONFIO asset:    {confio_asset_id}")
    print(f"  Referee reward:  {referee_reward / 1_000_000} CONFIO")
    print(f"  Referrer reward: {referrer_reward / 1_000_000} CONFIO")
    print(f"  Box price:       {box_price / 1_000_000} ALGO")
    print()

    params = client.suggested_params()

    # Step 1: Opt the contract into the CONFIO asset
    print("Step 1: Opting contract into CONFIO asset...")
    opt_in_txn = transaction.ApplicationCallTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"bootstrap"],
        foreign_assets=[confio_asset_id],
    )

    signed_opt_in = opt_in_txn.sign(admin_private_key)
    tx_id = client.send_transaction(signed_opt_in)
    print(f"  Submitted transaction {tx_id}")

    result = transaction.wait_for_confirmation(client, tx_id, 6)
    print(f"  ✅ Confirmed in round {result.get('confirmed-round')}")
    print()

    # Step 2: Set reward amounts
    print("Step 2: Setting reward amounts...")
    set_rewards_txn = transaction.ApplicationCallTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[
            b"set_rewards",
            referee_reward.to_bytes(8, "big"),
            referrer_reward.to_bytes(8, "big"),
        ],
    )

    signed_rewards = set_rewards_txn.sign(admin_private_key)
    tx_id = client.send_transaction(signed_rewards)
    print(f"  Submitted transaction {tx_id}")

    result = transaction.wait_for_confirmation(client, tx_id, 6)
    print(f"  ✅ Confirmed in round {result.get('confirmed-round')}")
    print()

    # Step 3: Set box price
    print("Step 3: Setting box price...")
    set_price_txn = transaction.ApplicationCallTxn(
        sender=admin_address,
        sp=params,
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"set_box_price", box_price.to_bytes(8, "big")],
    )

    signed_price = set_price_txn.sign(admin_private_key)
    tx_id = client.send_transaction(signed_price)
    print(f"  Submitted transaction {tx_id}")

    result = transaction.wait_for_confirmation(client, tx_id, 6)
    print(f"  ✅ Confirmed in round {result.get('confirmed-round')}")
    print()

    # Verify the configuration
    print("="*80)
    print("Verifying contract configuration...")
    app_info = client.application_info(app_id)
    global_state = app_info.get("params", {}).get("global-state", [])

    state_dict = {}
    for item in global_state:
        key = item.get("key", "")
        value_obj = item.get("value", {})
        value_type = value_obj.get("type")

        # Decode the key
        import base64
        try:
            decoded_key = base64.b64decode(key).decode("utf-8")
        except:
            decoded_key = key

        # Get the value
        if value_type == 1:  # bytes
            value = value_obj.get("bytes", "")
        elif value_type == 2:  # uint
            value = value_obj.get("uint", 0)
        else:
            value = None

        state_dict[decoded_key] = value

    print(f"\nGlobal State:")
    print(f"  Admin:                  {state_dict.get('admin', 'NOT SET')}")
    print(f"  CONFIO Asset ID:        {state_dict.get('confio_asset_id', 'NOT SET')}")
    print(f"  Box Price:              {state_dict.get('box_price', 0) / 1_000_000} ALGO")
    print(f"  Referee Reward:         {state_dict.get('referee_reward_amount', 0) / 1_000_000} CONFIO")
    print(f"  Referrer Reward:        {state_dict.get('referrer_reward_amount', 0) / 1_000_000} CONFIO")
    print(f"  Paused:                 {state_dict.get('paused', 0)}")

    print(f"\n{'='*80}")
    print(f"✅ BOOTSTRAP COMPLETE!")
    print(f"{'='*80}")
    print(f"\nContract {app_id} is ready to use.")
    print(f"\nNext step: Update .env.testnet with:")
    print(f"  ALGORAND_REWARD_APP_ID={app_id}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
