#!/usr/bin/env python3
"""
Deploy production-ready contracts with sponsor support to LocalNet.
This script deploys and initializes all production contracts.
"""

import os
import sys
import time
import hashlib
from typing import Dict, Any

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCreateTxn,
    ApplicationCallTxn,
    AssetTransferTxn,
    PaymentTxn,
    StateSchema,
    OnComplete,
    assign_group_id,
    wait_for_confirmation
)
from algosdk.logic import get_application_address

# Import production contracts
from p2p_vault_production import compile_p2p_vault_production
from inbox_router_production import compile_inbox_router_production
from payment_production import compile_payment_production

# LocalNet configuration
ALGOD_ADDRESS = "http://localhost:4001"
ALGOD_TOKEN = "a" * 64

class ProductionDeployer:
    """Deploy production contracts with sponsor pattern"""
    
    def __init__(self):
        self.algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
        self.contracts = {}
        self.setup_accounts()
        
    def setup_accounts(self):
        """Setup deployment accounts"""
        # Get funded accounts from LocalNet
        kmd_url = "http://localhost:4002"
        kmd_token = "a" * 64
        
        from algosdk.kmd import KMDClient
        kmd_client = KMDClient(kmd_token, kmd_url)
        
        # Get the default wallet
        wallets = kmd_client.list_wallets()
        wallet_id = None
        for wallet in wallets:
            if wallet["name"] == "unencrypted-default-wallet":
                wallet_id = wallet["id"]
                break
        
        if not wallet_id:
            raise Exception("Default wallet not found")
        
        # Get wallet handle
        wallet_handle = kmd_client.init_wallet_handle(wallet_id, "")
        
        # Get accounts
        addresses = kmd_client.list_keys(wallet_handle)
        
        # Setup accounts
        self.creator = addresses[0]
        self.sponsor = addresses[1]  # Sponsor funds all MBR
        self.arbitrator = addresses[2]
        self.fee_collector = addresses[3]
        
        # Export private keys
        self.creator_sk = kmd_client.export_key(wallet_handle, "", self.creator)
        self.sponsor_sk = kmd_client.export_key(wallet_handle, "", self.sponsor)
        
        print("=" * 60)
        print("PRODUCTION CONTRACT DEPLOYMENT")
        print("=" * 60)
        print(f"Creator:        {self.creator}")
        print(f"Sponsor:        {self.sponsor}")
        print(f"Arbitrator:     {self.arbitrator}")
        print(f"Fee Collector:  {self.fee_collector}")
        print("=" * 60)
        
    def get_cusd_asset_id(self) -> int:
        """Get or create cUSD asset ID"""
        # Check if cUSD already exists
        account_info = self.algod_client.account_info(self.creator)
        
        for asset in account_info.get("created-assets", []):
            if asset["params"]["unit-name"] == "cUSD":
                print(f"Found existing cUSD asset: {asset['index']}")
                return asset["index"]
        
        # Create new cUSD if not found
        print("Creating new cUSD asset...")
        params = self.algod_client.suggested_params()
        
        from algosdk.transaction import AssetConfigTxn
        
        txn = AssetConfigTxn(
            sender=self.creator,
            sp=params,
            total=10**15,  # 1 million with 9 decimals
            default_frozen=False,
            unit_name="cUSD",
            asset_name="Confío USD",
            decimals=9,
            url="https://confio.app"
        )
        
        signed_txn = txn.sign(self.creator_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        result = wait_for_confirmation(self.algod_client, tx_id, 4)
        asset_id = result["asset-index"]
        
        print(f"Created cUSD asset: {asset_id}")
        return asset_id
        
    def deploy_contract(self, name: str, approval_program: str, 
                       global_ints: int, global_bytes: int,
                       app_args: list) -> int:
        """Deploy a contract"""
        print(f"\nDeploying {name}...")
        
        params = self.algod_client.suggested_params()
        
        # Simple clear program
        clear_program = "I3ByYWdtYSB2ZXJzaW9uIDgKaW50IDAKcmV0dXJu"
        
        txn = ApplicationCreateTxn(
            sender=self.creator,
            sp=params,
            on_complete=OnComplete.NoOpOC,
            approval_program=approval_program,
            clear_program=clear_program,
            global_schema=StateSchema(global_ints, global_bytes),
            local_schema=StateSchema(0, 0),
            app_args=app_args
        )
        
        signed_txn = txn.sign(self.creator_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        result = wait_for_confirmation(self.algod_client, tx_id, 4)
        app_id = result["application-index"]
        app_addr = get_application_address(app_id)
        
        print(f"✓ {name} deployed:")
        print(f"  App ID:      {app_id}")
        print(f"  App Address: {app_addr}")
        
        self.contracts[name] = {
            "app_id": app_id,
            "app_addr": app_addr
        }
        
        return app_id
        
    def opt_in_contract(self, name: str, app_id: int, app_addr: str, asset_id: int):
        """Opt contract into asset with sponsor funding"""
        print(f"\nOpting {name} into cUSD...")
        
        params = self.algod_client.suggested_params()
        
        # Group: [Payment(sponsor→app), AppCall, AssetOptIn]
        
        # Payment from sponsor for opt-in MBR
        pay_txn = PaymentTxn(
            sender=self.sponsor,
            sp=params,
            receiver=app_addr,
            amt=100000  # 0.1 ALGO for opt-in
        )
        
        # App call
        app_txn = ApplicationCallTxn(
            sender=self.creator,
            sp=params,
            index=app_id,
            app_args=[b"opt_in"],
            on_complete=OnComplete.NoOpOC
        )
        
        # Asset opt-in (would be signed by logic sig in production)
        opt_txn = AssetTransferTxn(
            sender=app_addr,
            sp=params,
            receiver=app_addr,
            amt=0,
            index=asset_id
        )
        
        # Group transactions
        group_txns = [pay_txn, app_txn, opt_txn]
        group_txns = assign_group_id(group_txns)
        
        # Sign transactions
        signed_pay = group_txns[0].sign(self.sponsor_sk)
        signed_app = group_txns[1].sign(self.creator_sk)
        # Note: opt_txn would need logic sig in production
        
        print(f"✓ {name} opt-in prepared (would execute with logic sig)")
        
    def deploy_all(self):
        """Deploy all production contracts"""
        
        # Get cUSD asset
        cusd_id = self.get_cusd_asset_id()
        
        print("\n" + "=" * 60)
        print("DEPLOYING PRODUCTION CONTRACTS")
        print("=" * 60)
        
        # 1. Deploy P2P Vault
        p2p_approval = compile_p2p_vault_production()
        p2p_app_id = self.deploy_contract(
            "P2P Vault",
            p2p_approval,
            global_ints=10,
            global_bytes=3,
            app_args=[
                cusd_id.to_bytes(8, 'big'),
                self.sponsor.encode(),
                self.arbitrator.encode()
            ]
        )
        
        # 2. Deploy Inbox Router
        inbox_approval = compile_inbox_router_production()
        inbox_app_id = self.deploy_contract(
            "Inbox Router",
            inbox_approval,
            global_ints=7,
            global_bytes=2,
            app_args=[
                cusd_id.to_bytes(8, 'big'),
                self.sponsor.encode()
            ]
        )
        
        # 3. Deploy Payment Router
        payment_approval = compile_payment_production()
        payment_app_id = self.deploy_contract(
            "Payment Router",
            payment_approval,
            global_ints=5,
            global_bytes=2,
            app_args=[
                cusd_id.to_bytes(8, 'big'),
                self.sponsor.encode(),
                self.fee_collector.encode()
            ]
        )
        
        print("\n" + "=" * 60)
        print("DEPLOYMENT SUMMARY")
        print("=" * 60)
        
        print(f"""
Production contracts deployed successfully!

Asset:
  cUSD ID: {cusd_id}

Contracts:
  P2P Vault:       App #{p2p_app_id}
  Inbox Router:    App #{inbox_app_id}
  Payment Router:  App #{payment_app_id}

Accounts:
  Sponsor:         {self.sponsor}
  Arbitrator:      {self.arbitrator}
  Fee Collector:   {self.fee_collector}

Next Steps:
1. Fund sponsor account with ALGO for MBR
2. Opt contracts into cUSD (requires logic sig)
3. Test with production transaction patterns

Key Features Implemented:
✓ Sponsor funds all MBR increases
✓ Explicit MBR refunds after box_delete
✓ Correct order of operations (delete → pay)
✓ Recipient opt-in checks before transfers
✓ All terminal paths delete boxes and refund MBR
✓ cUSD-only to save permanent MBR
        """)
        
        # Save deployment info
        self.save_deployment_info(cusd_id)
        
    def save_deployment_info(self, cusd_id: int):
        """Save deployment information to file"""
        import json
        
        deployment = {
            "network": "localnet",
            "timestamp": time.time(),
            "cusd_id": cusd_id,
            "contracts": self.contracts,
            "accounts": {
                "creator": self.creator,
                "sponsor": self.sponsor,
                "arbitrator": self.arbitrator,
                "fee_collector": self.fee_collector
            }
        }
        
        with open("production_deployment.json", "w") as f:
            json.dump(deployment, f, indent=2)
            
        print("\nDeployment info saved to: production_deployment.json")
        
if __name__ == "__main__":
    deployer = ProductionDeployer()
    deployer.deploy_all()