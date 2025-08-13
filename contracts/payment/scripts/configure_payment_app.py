#!/usr/bin/env python3
"""
Configure an existing Payment app:
- Set up asset IDs (setup_assets) so the app opts into cUSD/CONFIO
- Set sponsor address (set_sponsor)

Reads values from environment by default:
- ALGORAND_NETWORK: testnet | mainnet | localnet (default: testnet)
- ALGORAND_PAYMENT_APP_ID: required
- ALGORAND_ADMIN_MNEMONIC: required (admin must sign calls)
- ALGORAND_CUSD_ASSET_ID: required for setup_assets
- ALGORAND_CONFIO_ASSET_ID: required for setup_assets
- ALGORAND_SPONSOR_ADDRESS: optional (set_sponsor)

Usage:
  python contracts/payment/scripts/configure_payment_app.py
"""

import os
import sys
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCallTxn,
    PaymentTxn,
    OnComplete,
    SuggestedParams,
    wait_for_confirmation,
    assign_group_id,
)
from algosdk.abi import Method, Returns, Argument


def get_algod(network: str) -> algod.AlgodClient:
    if network == 'testnet':
        return algod.AlgodClient("", "https://testnet-api.algonode.cloud")
    if network == 'mainnet':
        return algod.AlgodClient("", "https://mainnet-api.algonode.cloud")
    # localnet
    return algod.AlgodClient("a" * 64, "http://localhost:4001")


def main():
    network = os.environ.get('ALGORAND_NETWORK', 'testnet')
    app_id_s = os.environ.get('ALGORAND_PAYMENT_APP_ID')
    admin_mn = os.environ.get('ALGORAND_ADMIN_MNEMONIC')
    cusd_id_s = os.environ.get('ALGORAND_CUSD_ASSET_ID')
    confio_id_s = os.environ.get('ALGORAND_CONFIO_ASSET_ID')
    sponsor_addr = os.environ.get('ALGORAND_SPONSOR_ADDRESS', '')

    if not app_id_s or not admin_mn:
        print("Error: ALGORAND_PAYMENT_APP_ID and ALGORAND_ADMIN_MNEMONIC must be set")
        sys.exit(1)

    try:
        app_id = int(app_id_s)
    except Exception:
        print("Error: ALGORAND_PAYMENT_APP_ID must be an integer")
        sys.exit(1)

    admin_sk = mnemonic.to_private_key(admin_mn)
    admin_addr = account.address_from_private_key(admin_sk)

    algod_client = get_algod(network)
    print(f"Network: {network}")
    print(f"Admin:   {admin_addr}")
    print(f"App ID:  {app_id}")

    # Fetch app global state
    try:
        app_info = algod_client.application_info(app_id)
    except Exception as e:
        print(f"Failed to fetch app info: {e}")
        sys.exit(1)

    # Decode key-value
    gs_kv = {b64['key']: b64['value'] for b64 in app_info.get('params', {}).get('global-state', [])}

    def get_uint(key_b64: str) -> int:
        v = gs_kv.get(key_b64)
        if not v:
            return 0
        if v.get('type') == 2:  # uint
            return int(v.get('uint', 0))
        return 0

    # Check if assets are already set up
    current_cusd_id = get_uint("Y3VzZF9hc3NldF9pZA==")  # "cusd_asset_id"
    current_confio_id = get_uint("Y29uZmlvX2Fzc2V0X2lk")  # "confio_asset_id"
    
    print(f"Current asset IDs in contract: cUSD={current_cusd_id}, CONFIO={current_confio_id}")
    
    # Get target asset IDs
    cusd_id = None
    confio_id = None
    
    # Use env overrides
    if cusd_id_s:
        cusd_id = int(cusd_id_s)
    if confio_id_s:
        confio_id = int(confio_id_s)
        
    # Check if setup is needed
    if current_cusd_id != 0 or current_confio_id != 0:
        if cusd_id == current_cusd_id and confio_id == current_confio_id:
            print("Assets already set up correctly - skipping setup")
            cusd_id = None  # Skip setup
            confio_id = None

    # Setup assets if provided
    if cusd_id and confio_id:
        print(f"Setting up assets: cUSD={cusd_id}, CONFIO={confio_id}")
        from algosdk import logic
        app_address = logic.get_application_address(app_id)
        
        params = algod_client.suggested_params()
        
        # Transaction 0: Payment for MBR (0.2 ALGO for 2 asset opt-ins)
        mbr_amount = 200_000  # 0.2 ALGO in microAlgos
        payment_txn = PaymentTxn(
            sender=admin_addr,
            sp=params,
            receiver=app_address,
            amt=mbr_amount
        )
        
        # Transaction 1: App call with higher fee for inner transactions
        app_params = SuggestedParams(
            fee=3000,  # Base + 2 inner asset opt-ins
            first=params.first,
            last=params.last,
            gh=params.gh,
            gen=params.gen,
            flat_fee=True
        )
        
        method_setup = Method(
            name="setup_assets",
            args=[
                Argument(arg_type="uint64", name="cusd_id"),
                Argument(arg_type="uint64", name="confio_id"),
            ],
            returns=Returns(arg_type="void"),
        )

        setup_txn = ApplicationCallTxn(
            sender=admin_addr,
            sp=app_params,
            index=app_id,
            on_complete=OnComplete.NoOpOC,
            app_args=[
                method_setup.get_selector(),
                cusd_id.to_bytes(8, 'big'),
                confio_id.to_bytes(8, 'big'),
            ],
            foreign_assets=[cusd_id, confio_id]  # Required for asset opt-ins
        )

        # Group transactions as required by contract
        txns = [payment_txn, setup_txn]
        assign_group_id(txns)
        
        # Sign both transactions
        signed_txns = [txn.sign(admin_sk) for txn in txns]
        
        # Send group
        txid = algod_client.send_transactions(signed_txns)
        print(f"setup_assets group sent: {txid}")
        wait_for_confirmation(algod_client, txid, 10)
        print("✅ setup_assets confirmed")
    else:
        print("Skipping setup_assets (missing ALGORAND_CUSD_ASSET_ID/ALGORAND_CONFIO_ASSET_ID)")

    # Set sponsor if provided
    if sponsor_addr:
        print(f"Setting sponsor: {sponsor_addr}")
        params = algod_client.suggested_params()
        method_sponsor = Method(
            name="set_sponsor",
            args=[Argument(arg_type="address", name="sponsor")],
            returns=Returns(arg_type="void"),
        )
        from algosdk.encoding import decode_address
        sponsor_bytes = decode_address(sponsor_addr)
        set_txn = ApplicationCallTxn(
            sender=admin_addr,
            sp=params,
            index=app_id,
            on_complete=OnComplete.NoOpOC,
            app_args=[method_sponsor.get_selector(), sponsor_bytes],
        )
        signed = set_txn.sign(admin_sk)
        txid = algod_client.send_transaction(signed)
        print(f"set_sponsor sent: {txid}")
        wait_for_confirmation(algod_client, txid, 10)
        print("✅ set_sponsor confirmed")
    else:
        print("Skipping set_sponsor (missing ALGORAND_SPONSOR_ADDRESS)")

    print("All done.")


if __name__ == '__main__':
    main()

