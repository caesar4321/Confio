#!/usr/bin/env python3
"""
Deploy CONFIO Presale Contract

This script deploys and initializes the CONFIO presale contract.
"""

import os
import sys
import json
from typing import Dict, Any

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    # Load .env from project root so mnemonics with spaces are parsed correctly
    # Repo root is three levels up from this file
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dotenv(os.path.join(repo_root, '.env'))
except Exception:
    pass

from algosdk import account, mnemonic, encoding
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

from confio_presale import compile_presale
from state_utils import decode_state

# Network configuration (prefer ALGORAND_* envs)
ALGOD_ADDRESS = os.getenv("ALGORAND_ALGOD_ADDRESS", os.getenv("ALGOD_ADDRESS", "http://localhost:4001"))
ALGOD_TOKEN = os.getenv("ALGORAND_ALGOD_TOKEN", os.getenv("ALGOD_TOKEN", "a" * 64))

class PresaleDeployer:
    """Deploy and manage CONFIO presale contract"""
    
    def __init__(self):
        self.algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
        self.app_id = None
        self.app_addr = None
        
    def _compile(self, teal_src: str) -> bytes:
        """Compile TEAL source to bytecode"""
        import base64
        resp = self.algod_client.compile(teal_src)
        return base64.b64decode(resp["result"])
        
    def deploy_contract(self, creator_address: str, creator_sk: str,
                       confio_id: int, cusd_id: int, admin_address: str,
                       sponsor_address: str) -> int:
        """Deploy the presale contract"""
        
        print("Deploying CONFIO Presale Contract...")
        
        # Compile contract to bytecode (fallback to prebuilt TEAL if PyTeal fails)
        try:
            approval_src = compile_presale()
            approval_program = self._compile(approval_src)
        except Exception as e:
            print(f"PyTeal compile failed, falling back to approval.teal: {e}")
            repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            fallback_path = os.path.join(repo_root, 'approval.teal')
            if not os.path.exists(fallback_path):
                raise
            with open(fallback_path, 'r', encoding='utf-8') as f:
                approval_teal_text = f.read()
            approval_program = self._compile(approval_teal_text)

        clear_program = self._compile("#pragma version 8\nint 1")
        
        # Get suggested params
        params = self.algod_client.suggested_params()
        
        # Determine extra pages needed for larger programs (page size 1024 bytes)
        appr_len = len(approval_program)
        clr_len = len(clear_program)
        max_len = max(appr_len, clr_len)
        page_size = 1024
        extra_pages = 0
        if max_len > page_size:
            extra_pages = (max_len + page_size - 1) // page_size - 1

        # If extra pages, increase flat fee accordingly
        if extra_pages > 0:
            params = self.algod_client.suggested_params()
            params.flat_fee = True
            # Base fee + 2000 per extra page (Algorand covers min_fee per page). Use a safe multiple
            params.fee = max(getattr(params, 'min_fee', 1000), 1000) * (1 + extra_pages)

        # Create application
        txn = ApplicationCreateTxn(
            sender=creator_address,
            sp=params,
            on_complete=OnComplete.NoOpOC,
            approval_program=approval_program,
            clear_program=clear_program,
            global_schema=StateSchema(17, 2),  # 17 ints, 2 bytes (admin, sponsor addresses)
            local_schema=StateSchema(5, 0),    # 5 ints per user (includes user_round)
            app_args=[
                confio_id.to_bytes(8, 'big'),
                cusd_id.to_bytes(8, 'big'),
                encoding.decode_address(admin_address),
                encoding.decode_address(sponsor_address)  # Proper 32-byte public keys
            ],
            extra_pages=extra_pages
        )
        
        # Sign and send
        signed_txn = txn.sign(creator_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        
        # Wait for confirmation
        result = wait_for_confirmation(self.algod_client, tx_id, 4)
        self.app_id = result["application-index"]
        self.app_addr = get_application_address(self.app_id)
        
        print(f"✅ Presale contract deployed!")
        print(f"   App ID: {self.app_id}")
        print(f"   App Address: {self.app_addr}")
        
        return self.app_id
    
    def opt_in_assets(self, admin_address: str, admin_sk: str,
                      sponsor_address: str, sponsor_sk: str,
                      confio_id: int, cusd_id: int):
        """Opt the contract into CONFIO and cUSD assets"""
        
        print("\nOpting contract into assets...")
        
        # Step 1: Pre-fund MBR (separate transaction)
        print("  1. Funding contract MBR...")
        params = self.algod_client.suggested_params()
        
        mbr_payment = PaymentTxn(
            sender=sponsor_address,
            sp=params,
            receiver=self.app_addr,
            amt=400000  # 0.40 ALGO MBR: 0.1 base + 0.1 per ASA × 2 + 0.1 buffer for future-proofing
        )
        
        signed_mbr = mbr_payment.sign(sponsor_sk)
        tx_id = self.algod_client.send_transaction(signed_mbr)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        print("     ✓ MBR funded")
        
        # Step 2: Opt into assets with strict sponsor bump
        print("  2. Opting into assets...")
        
        # Compute fees
        # IMPORTANT: Inner transaction fees must be paid by the AppCall, not the sponsor payment
        base = self.algod_client.suggested_params()
        min_fee = getattr(base, "min_fee", 1000)
        
        # AppCall: pays for itself + 2 inner opt-ins
        sp_app = self.algod_client.suggested_params()
        sp_app.flat_fee = True
        sp_app.fee = min_fee * 3  # base + 2 inners
        
        # Sponsor: pays for both outer txns (contract expects 2× min fee)
        sp_sponsor = self.algod_client.suggested_params()
        sp_sponsor.flat_fee = True
        sp_sponsor.fee = min_fee * 2
        
        # Group transaction: [0-ALGO sponsor self-payment, AppCall with inner fees]
        sponsor_bump = PaymentTxn(
            sender=sponsor_address,
            sp=sp_sponsor,
            receiver=sponsor_address,  # Self-payment for strict validation
            amt=0                      # 0 ALGO (pure fee bump)
        )
        
        # App call to opt_in_assets (carries inner txn fees)
        app_txn = ApplicationCallTxn(
            sender=admin_address,
            sp=sp_app,
            index=self.app_id,
            app_args=[b"opt_in_assets"],
            on_complete=OnComplete.NoOpOC,
            foreign_assets=[int(confio_id), int(cusd_id)]
        )
        
        # Group transactions
        group = [sponsor_bump, app_txn]
        assign_group_id(group)  # Mutates in place, ignore return value
        
        # Sign transactions
        signed_bump = group[0].sign(sponsor_sk)
        signed_app = group[1].sign(admin_sk)
        
        # Send group
        self.algod_client.send_transactions([signed_bump, signed_app])
        
        # Wait for confirmation
        wait_for_confirmation(self.algod_client, signed_app.get_txid(), 4)
        
        print("✅ Contract opted into CONFIO and cUSD assets")
        
        return True
    
    def fund_with_confio(self, sender_address: str, sender_sk: str,
                        confio_id: int, amount: int):
        """Fund the presale contract with CONFIO tokens"""
        
        print(f"\nFunding contract with {amount / 10**6:.2f} CONFIO...")
        
        params = self.algod_client.suggested_params()
        
        # Transfer CONFIO to contract
        txn = AssetTransferTxn(
            sender=sender_address,
            sp=params,
            receiver=self.app_addr,
            amt=amount,
            index=confio_id
        )
        
        # Sign and send
        signed_txn = txn.sign(sender_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Contract funded with CONFIO")
        
    def start_presale_round(self, admin_address: str, admin_sk: str,
                           price: int, cusd_cap: int, max_per_addr: int):
        """Start a new presale round
        
        Args:
            price: cUSD per CONFIO (6 decimals)
            cusd_cap: Max cUSD to raise this round (6 decimals)
            max_per_addr: Max cUSD per address (6 decimals)
        """
        
        print(f"\nStarting presale round...")
        print(f"   Price: {price / 10**6:.2f} cUSD per CONFIO")
        print(f"   cUSD cap: {cusd_cap / 10**6:.2f} cUSD")
        print(f"   Max per address: {max_per_addr / 10**6:.2f} cUSD")
        
        params = self.algod_client.suggested_params()
        
        # Start round with new parameters
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=[
                b"start_round",
                price.to_bytes(8, 'big'),
                cusd_cap.to_bytes(8, 'big'),
                max_per_addr.to_bytes(8, 'big')
            ],
            on_complete=OnComplete.NoOpOC
        )
        
        # Sign and send
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Presale round started!")
        
    def get_contract_info(self) -> Dict[str, Any]:
        """Get current contract state"""
        
        app_info = self.algod_client.application_info(self.app_id)
        return decode_state(app_info['params']['global-state'])
    
    def display_contract_info(self):
        """Display contract information"""
        
        state = self.get_contract_info()
        
        print("\n" + "=" * 60)
        print("PRESALE CONTRACT STATUS")
        print("=" * 60)
        
        print(f"App ID: {self.app_id}")
        print(f"App Address: {self.app_addr}")
        
        print("\nRound Information:")
        print(f"   Current Round: {state.get('round', 0)}")
        print(f"   Round Active: {'Yes' if state.get('active', 0) == 1 else 'No'}")
        print(f"   Price: {state.get('price', 0) / 10**6:.4f} cUSD per CONFIO")
        print(f"   cUSD Cap: {state.get('cusd_cap', 0) / 10**6:.2f} cUSD")
        print(f"   cUSD Raised This Round: {state.get('cusd_raised', 0) / 10**6:.2f} cUSD")
        print(f"   Min Buy: {state.get('min_buy', 0) / 10**6:.2f} cUSD")
        print(f"   Max Per Address: {state.get('max_addr', 0) / 10**6:.2f} cUSD")
        
        print("\nOverall Statistics:")
        print(f"   Total Rounds: {state.get('total_rounds', 0)}")
        print(f"   Total CONFIO Sold: {state.get('confio_sold', 0) / 10**6:.2f} CONFIO")
        print(f"   Total cUSD Raised: {state.get('total_raised', 0) / 10**6:.2f} cUSD")
        print(f"   Total Participants: {state.get('participants', 0)}")
        
        print("\nLock Status:")
        print(f"   Tokens Locked: {'Yes' if state.get('locked', 1) == 1 else 'No (Permanently Unlocked)'}")
        
        print("=" * 60)

def main():
    """Env-driven deployment runner."""
    print("CONFIO Presale Contract Deployment")
    print("=" * 40)

    # Read env vars
    from algosdk import mnemonic as _mn
    confio_id = int(os.getenv('ALGORAND_CONFIO_ASSET_ID', '0') or '0')
    cusd_id = int(os.getenv('ALGORAND_CUSD_ASSET_ID', '0') or '0')
    sponsor_address = os.getenv('ALGORAND_SPONSOR_ADDRESS')
    sponsor_mn = os.getenv('ALGORAND_SPONSOR_MNEMONIC')
    admin_mn = os.getenv('ALGORAND_ADMIN_MNEMONIC') or sponsor_mn
    # Normalize mnemonics (collapse whitespace, lowercase)
    def _norm(m):
        if not m:
            return m
        return " ".join(m.strip().split()).lower()
    sponsor_mn = _norm(sponsor_mn)
    admin_mn = _norm(admin_mn)
    # Fallback if admin mnemonic malformed -> use sponsor
    if not isinstance(admin_mn, str) or len(admin_mn.split()) != 25:
        admin_mn = sponsor_mn

    if not (confio_id and cusd_id and sponsor_address and sponsor_mn and admin_mn):
        print('Missing env. Set ALGORAND_CONFIO_ASSET_ID, ALGORAND_CUSD_ASSET_ID, ALGORAND_SPONSOR_ADDRESS, ALGORAND_SPONSOR_MNEMONIC, ALGORAND_ADMIN_MNEMONIC(optional).')
        return

    admin_sk = _mn.to_private_key(admin_mn)
    sponsor_sk = _mn.to_private_key(sponsor_mn)
    # Use sponsor address as admin address (admin actions signed by same key as requested)
    admin_address = sponsor_address

    deployer = PresaleDeployer()
    app_id = deployer.deploy_contract(
        creator_address=admin_address,
        creator_sk=admin_sk,
        confio_id=confio_id,
        cusd_id=cusd_id,
        admin_address=admin_address,
        sponsor_address=sponsor_address,
    )

    deployer.opt_in_assets(
        admin_address=admin_address,
        admin_sk=admin_sk,
        sponsor_address=sponsor_address,
        sponsor_sk=sponsor_sk,
        confio_id=confio_id,
        cusd_id=cusd_id,
    )

    deployer.display_contract_info()
    print(f"\nSet in .env: ALGORAND_PRESALE_APP_ID={app_id}")

if __name__ == "__main__":
    main()
