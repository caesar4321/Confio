#!/usr/bin/env python3
"""
Deploy Confío Payroll Contract

This script deploys and initializes the payroll escrow contract.
"""

import os
import sys
from typing import Dict, Any

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    # Load .env from project root
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dotenv(os.path.join(repo_root, '.env'))
except Exception:
    pass

from algosdk import account, mnemonic, encoding
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCreateTxn,
    PaymentTxn,
    StateSchema,
    OnComplete,
    wait_for_confirmation
)
from algosdk.logic import get_application_address
from algosdk.abi import Contract as ABIContract
from algosdk.atomic_transaction_composer import AccountTransactionSigner
from beaker.client import ApplicationClient

# Import the payroll contract
from payroll import app as payroll_app

# Network configuration
ALGOD_ADDRESS = os.getenv("ALGORAND_ALGOD_ADDRESS", "http://localhost:4001")
ALGOD_TOKEN = os.getenv("ALGORAND_ALGOD_TOKEN", "a" * 64)


class PayrollDeployer:
    """Deploy and manage Confío payroll contract"""

    def __init__(self):
        self.algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
        self.app_id = None
        self.app_addr = None

    def deploy_contract(self, creator_address: str, creator_sk: str) -> int:
        """Deploy the payroll contract"""

        print("Deploying Confío Payroll Escrow Contract...")

        # Build the Beaker app
        app_spec = payroll_app.build(self.algod_client)

        # Create signer
        signer = AccountTransactionSigner(creator_sk)

        # Create ApplicationClient
        app_client = ApplicationClient(
            client=self.algod_client,
            app=payroll_app,
            signer=signer
        )

        # Deploy the app
        app_id, app_addr, txid = app_client.create()

        self.app_id = app_id
        self.app_addr = app_addr

        print(f"✅ Payroll contract deployed!")
        print(f"   App ID: {self.app_id}")
        print(f"   App Address: {self.app_addr}")

        return self.app_id

    def setup_asset(self, admin_address: str, admin_sk: str, asset_id: int):
        """Setup the payroll asset and opt the contract into it"""

        print(f"\nSetting up payroll asset {asset_id}...")

        # Create signer
        signer = AccountTransactionSigner(admin_sk)

        # Create ApplicationClient for admin operations
        app_client = ApplicationClient(
            client=self.algod_client,
            app=payroll_app,
            app_id=self.app_id,
            signer=signer
        )

        # Get suggested params and increase fee for inner transaction
        params = self.algod_client.suggested_params()
        params.flat_fee = True
        params.fee = params.min_fee * 2  # Base + inner opt-in

        # Call setup_asset with foreign_assets
        result = app_client.call(
            "setup_asset",
            asset_id=asset_id,
            foreign_assets=[asset_id],
            suggested_params=params
        )

        print(f"✅ Contract opted into asset {asset_id}")

        return result

    def set_fee_recipient(self, admin_address: str, admin_sk: str, fee_recipient: str):
        """Set the fee recipient address"""

        print(f"\nSetting fee recipient to {fee_recipient}...")

        signer = AccountTransactionSigner(admin_sk)

        app_client = ApplicationClient(
            client=self.algod_client,
            app=payroll_app,
            app_id=self.app_id,
            signer=signer
        )

        result = app_client.call(
            "set_fee_recipient",
            addr=fee_recipient
        )

        print(f"✅ Fee recipient set")

        return result

    def set_sponsor(self, admin_address: str, admin_sk: str, sponsor_address: str):
        """Set the sponsor address"""

        print(f"\nSetting sponsor to {sponsor_address}...")

        signer = AccountTransactionSigner(admin_sk)

        app_client = ApplicationClient(
            client=self.algod_client,
            app=payroll_app,
            app_id=self.app_id,
            signer=signer
        )

        result = app_client.call(
            "set_sponsor",
            addr=sponsor_address
        )

        print(f"✅ Sponsor set")

        return result

    def fund_mbr(self, funder_address: str, funder_sk: str, amount: int = 500000):
        """Fund the contract with ALGO for MBR"""

        print(f"\nFunding contract MBR with {amount / 10**6:.2f} ALGO...")

        params = self.algod_client.suggested_params()

        txn = PaymentTxn(
            sender=funder_address,
            sp=params,
            receiver=self.app_addr,
            amt=amount
        )

        signed_txn = txn.sign(funder_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)

        print(f"✅ Contract funded with MBR")

    def get_contract_info(self) -> Dict[str, Any]:
        """Get current contract state"""

        app_info = self.algod_client.application_info(self.app_id)

        # Decode global state
        global_state = {}
        for item in app_info['params']['global-state']:
            import base64
            key = base64.b64decode(item['key']).decode('utf-8', errors='ignore')
            value_obj = item['value']

            if value_obj['type'] == 1:  # bytes
                raw_bytes = base64.b64decode(value_obj.get('bytes', ''))
                if len(raw_bytes) == 32:  # Address
                    global_state[key] = encoding.encode_address(raw_bytes)
                else:
                    global_state[key] = raw_bytes
            elif value_obj['type'] == 2:  # uint
                global_state[key] = value_obj.get('uint', 0)

        return global_state

    def display_contract_info(self):
        """Display contract information"""

        state = self.get_contract_info()

        print("\n" + "=" * 60)
        print("PAYROLL CONTRACT STATUS")
        print("=" * 60)

        print(f"App ID: {self.app_id}")
        print(f"App Address: {self.app_addr}")

        print("\nConfiguration:")
        print(f"   Admin: {state.get('admin', 'Not set')}")
        print(f"   Fee Recipient: {state.get('fee_recipient', 'Not set')}")
        print(f"   Sponsor: {state.get('sponsor_address', 'Not set')}")
        print(f"   Payroll Asset: {state.get('payroll_asset', 0)}")
        print(f"   Paused: {'Yes' if state.get('is_paused', 0) == 1 else 'No'}")

        print("\nCap Settings:")
        print(f"   Period (seconds): {state.get('period_seconds', 0)}")
        print(f"   Period Cap Amount: {state.get('period_cap_amount', 0) / 10**6:.2f}")
        print(f"   Current Period Start: {state.get('current_period_start', 0)}")
        print(f"   Current Period Spent: {state.get('current_period_spent', 0) / 10**6:.2f}")

        print("=" * 60)


def main():
    """Env-driven deployment runner."""
    print("Confío Payroll Contract Deployment")
    print("=" * 40)

    # Read env vars
    from algosdk import mnemonic as _mn
    cusd_id = int(os.getenv('ALGORAND_CUSD_ASSET_ID', '0') or '0')
    admin_address = os.getenv('ALGORAND_SPONSOR_ADDRESS')
    admin_mn = os.getenv('ALGORAND_ADMIN_MNEMONIC') or os.getenv('ALGORAND_SPONSOR_MNEMONIC')

    # Normalize mnemonic
    def _norm(m):
        if not m:
            return m
        return " ".join(m.strip().split()).lower()

    admin_mn = _norm(admin_mn)

    if not (cusd_id and admin_address and admin_mn):
        print('Missing env. Set ALGORAND_CUSD_ASSET_ID, ALGORAND_SPONSOR_ADDRESS, ALGORAND_ADMIN_MNEMONIC.')
        return

    admin_sk = _mn.to_private_key(admin_mn)

    deployer = PayrollDeployer()

    # Deploy contract
    app_id = deployer.deploy_contract(
        creator_address=admin_address,
        creator_sk=admin_sk
    )

    # Fund MBR
    deployer.fund_mbr(
        funder_address=admin_address,
        funder_sk=admin_sk,
        amount=500000  # 0.5 ALGO for MBR + boxes
    )

    # Setup asset
    deployer.setup_asset(
        admin_address=admin_address,
        admin_sk=admin_sk,
        asset_id=cusd_id
    )

    # Set fee recipient (same as admin for now)
    deployer.set_fee_recipient(
        admin_address=admin_address,
        admin_sk=admin_sk,
        fee_recipient=admin_address
    )

    deployer.display_contract_info()
    print(f"\nSet in .env: ALGORAND_PAYROLL_APP_ID={app_id}")
    print(f"Set in .env: ALGORAND_PAYROLL_ASSET_ID={cusd_id}")


if __name__ == "__main__":
    main()
