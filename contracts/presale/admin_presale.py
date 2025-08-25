#!/usr/bin/env python3
"""
Admin management script for CONFIO presale

This script provides admin functions for managing the presale:
- Start/stop rounds
- Update parameters
- Monitor statistics
- Unlock tokens
- Withdraw funds
"""

import os
import sys
import json
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .state_utils import decode_state, to_algorand_address, format_address

from algosdk import account, mnemonic, encoding
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCallTxn,
    AssetTransferTxn,
    PaymentTxn,
    OnComplete,
    assign_group_id,
    wait_for_confirmation
)
from algosdk.logic import get_application_address

# Network configuration (prefer ALGORAND_* envs)
ALGOD_ADDRESS = os.getenv("ALGORAND_ALGOD_ADDRESS", os.getenv("ALGOD_ADDRESS", "http://localhost:4001"))
ALGOD_TOKEN = os.getenv("ALGORAND_ALGOD_TOKEN", os.getenv("ALGOD_TOKEN", "a" * 64))

class PresaleAdmin:
    """Admin interface for CONFIO presale management"""
    
    def __init__(self, app_id: int, confio_id: int, cusd_id: int):
        self.algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
        self.app_id = app_id
        self.confio_id = confio_id
        self.cusd_id = cusd_id
        self.app_addr = get_application_address(app_id)
        
    def start_round(self, admin_address: str, admin_sk: str,
                   price_cusd_per_confio: float, cusd_cap: float, max_per_addr: float):
        """
        Start a new presale round
        
        Args:
            price_cusd_per_confio: cUSD per CONFIO (e.g., 0.25 means 0.25 cUSD per 1 CONFIO)
            cusd_cap: Maximum cUSD to raise (e.g., 1000000 means 1M cUSD)
            max_per_addr: Max cUSD per address (e.g., 10000 means 10k cUSD)
        
        Note: All values are in human-readable units, not micro units.
              They will be converted to 6-decimal micro units internally.
        """
        
        # Early validation before conversion
        if price_cusd_per_confio <= 0:
            raise ValueError("Price must be positive")
        if cusd_cap <= 0:
            raise ValueError("cUSD cap must be positive")
        if max_per_addr <= 0:
            raise ValueError("Max per address must be positive")
        if max_per_addr > cusd_cap:
            raise ValueError("Max per address cannot exceed round cap")
        
        # Convert to integers with proper decimals (6 decimals for cUSD) using Decimal for precision
        price_int = int((Decimal(str(price_cusd_per_confio)) * (10**6)).to_integral_value(ROUND_DOWN))
        cusd_cap_int = int((Decimal(str(cusd_cap)) * (10**6)).to_integral_value(ROUND_DOWN))
        max_per_addr_int = int((Decimal(str(max_per_addr)) * (10**6)).to_integral_value(ROUND_DOWN))
        
        print(f"\nStarting new presale round:")
        print(f"   Price: {price_cusd_per_confio:.4f} cUSD per CONFIO")
        print(f"   cUSD cap: {cusd_cap:,.0f} cUSD")
        print(f"   Max per address: {max_per_addr:,.0f} cUSD")
        
        params = self.algod_client.suggested_params()
        
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=[
                b"start_round",
                price_int.to_bytes(8, 'big'),
                cusd_cap_int.to_bytes(8, 'big'),
                max_per_addr_int.to_bytes(8, 'big')
            ],
            foreign_assets=[int(self.confio_id), int(self.cusd_id)],
            on_complete=OnComplete.NoOpOC
        )
        
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Round started successfully!")
        print(f"   Transaction: {tx_id}")
        
    def toggle_round(self, admin_address: str, admin_sk: str):
        """Pause or resume the current round"""
        
        state = self.get_state()
        current_state = "active" if state.get('active', 0) == 1 else "paused"
        new_state = "paused" if current_state == "active" else "active"
        
        print(f"\nToggling round: {current_state} → {new_state}")
        
        params = self.algod_client.suggested_params()
        
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=[b"toggle_round"],
            foreign_assets=[int(self.confio_id), int(self.cusd_id)],
            on_complete=OnComplete.NoOpOC
        )
        
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Round is now {new_state}")
        
    def update_price(self, admin_address: str, admin_sk: str, new_price_cusd_per_confio: float):
        """Update the price for current round"""
        
        if new_price_cusd_per_confio <= 0:
            raise ValueError("Price must be positive")
        
        new_price = int((Decimal(str(new_price_cusd_per_confio)) * (10**6)).to_integral_value(ROUND_DOWN))  # 6 decimals
        
        print(f"\nUpdating price to {new_price_cusd_per_confio:.6f} cUSD per CONFIO")
        
        params = self.algod_client.suggested_params()
        
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=[
                b"update",
                b"price", 
                new_price.to_bytes(8, 'big')
            ],
            foreign_assets=[int(self.confio_id), int(self.cusd_id)],
            on_complete=OnComplete.NoOpOC
        )
        
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Price updated successfully!")
    
    def update_cap(self, admin_address: str, admin_sk: str, new_cap_cusd: float):
        """Update the cUSD cap for current round"""
        
        if new_cap_cusd <= 0:
            raise ValueError("cUSD cap must be positive")
        
        new_cap = int((Decimal(str(new_cap_cusd)) * (10**6)).to_integral_value(ROUND_DOWN))  # 6 decimals
        
        print(f"\nUpdating cUSD cap to {new_cap_cusd:,.2f} cUSD")
        
        params = self.algod_client.suggested_params()
        
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=[
                b"update",
                b"cap", 
                new_cap.to_bytes(8, 'big')
            ],
            foreign_assets=[int(self.confio_id), int(self.cusd_id)],
            on_complete=OnComplete.NoOpOC
        )
        
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Cap updated successfully!")
    
    def update_min_buy(self, admin_address: str, admin_sk: str, new_min_cusd: float):
        """Update the minimum buy amount"""
        
        if new_min_cusd <= 0:
            raise ValueError("Minimum buy must be positive")
        
        new_min = int((Decimal(str(new_min_cusd)) * (10**6)).to_integral_value(ROUND_DOWN))  # 6 decimals
        
        print(f"\nUpdating minimum buy to {new_min_cusd:.2f} cUSD")
        
        params = self.algod_client.suggested_params()
        
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=[
                b"update",
                b"min", 
                new_min.to_bytes(8, 'big')
            ],
            foreign_assets=[int(self.confio_id), int(self.cusd_id)],
            on_complete=OnComplete.NoOpOC
        )
        
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Minimum buy updated successfully!")
    
    def update_max_per_addr(self, admin_address: str, admin_sk: str, new_max_cusd: float):
        """Update the max cUSD per address"""
        
        if new_max_cusd <= 0:
            raise ValueError("Max per address must be positive")
        
        new_max = int((Decimal(str(new_max_cusd)) * (10**6)).to_integral_value(ROUND_DOWN))  # 6 decimals
        
        print(f"\nUpdating max per address to {new_max_cusd:,.2f} cUSD")
        
        params = self.algod_client.suggested_params()
        
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=[
                b"update",
                b"max", 
                new_max.to_bytes(8, 'big')
            ],
            foreign_assets=[int(self.confio_id), int(self.cusd_id)],
            on_complete=OnComplete.NoOpOC
        )
        
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Max per address updated successfully!")
        
    def withdraw_confio(self, admin_address: str, admin_sk: str, 
                        receiver: Optional[str] = None, amount: Optional[int] = None):
        """Withdraw unused CONFIO tokens
        
        Args:
            receiver: Optional address to receive CONFIO (defaults to admin)
            amount: Optional amount to withdraw (defaults to all available)
        """
        
        # Get contract state to check available
        state = self.get_state()
        account_info = self.algod_client.account_info(self.app_addr)
        
        confio_balance = 0
        for asset in account_info.get('assets', []):
            if asset['asset-id'] == self.confio_id:
                confio_balance = asset['amount']
                break
        
        sold = state.get('confio_sold', 0)
        claimed = state.get('claimed_total', 0)
        outstanding = sold - claimed
        available = max(0, confio_balance - outstanding)
        
        if available <= 0:
            print("No unused CONFIO to withdraw")
            return
        
        print(f"\nCONFIO Withdrawal:")
        print(f"   Balance: {confio_balance / 10**6:,.0f}")
        print(f"   Outstanding: {outstanding / 10**6:,.0f}")
        print(f"   Available: {available / 10**6:,.0f}")
        
        receiver_addr = receiver or admin_address
        
        # Check if receiver is opted into CONFIO
        receiver_info = self.algod_client.account_info(receiver_addr)
        opted_in = False
        for asset in receiver_info.get('assets', []):
            if asset['asset-id'] == self.confio_id:
                opted_in = True
                break
        if not opted_in:
            raise Exception(f"Receiver {receiver_addr} is not opted into CONFIO (ASA ID: {self.confio_id}). To opt-in: Send 0 CONFIO to themselves or use AssetOptInTxn.")
        
        withdraw_amount = amount if amount else available
        print(f"\nWithdrawing {withdraw_amount / 10**6:,.0f} CONFIO to {receiver_addr}")
        
        params = self.algod_client.suggested_params()
        params.flat_fee = True
        params.fee = getattr(params, "min_fee", 1000) * 2  # 1 outer + 1 inner
        
        # Build app args
        # Contract expects: arg1=receiver (optional), arg2=amount (optional)
        # If amount is provided, receiver must also be provided
        app_args = [b"withdraw_confio"]
        if receiver or amount is not None:
            app_args.append(encoding.decode_address(receiver or admin_address))
        if amount is not None:
            app_args.append(amount.to_bytes(8, 'big'))
        
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=app_args,
            on_complete=OnComplete.NoOpOC
        )
        
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Withdrew {withdraw_amount / 10**6:,.0f} CONFIO")
        print(f"   Transaction: {tx_id}")
    
    def withdraw_cusd(self, admin_address: str, admin_sk: str, receiver: Optional[str] = None):
        """Withdraw all collected cUSD
        
        Args:
            receiver: Optional address to receive cUSD (defaults to admin)
        """
        
        # Get current cUSD balance
        account_info = self.algod_client.account_info(self.app_addr)
        cusd_balance = 0
        
        for asset in account_info.get('assets', []):
            if asset['asset-id'] == self.cusd_id:
                cusd_balance = asset['amount']
                break
        
        if cusd_balance == 0:
            print("No cUSD to withdraw")
            return
        
        receiver_addr = receiver or admin_address
        
        # Always check if receiver is opted into cUSD (admin or custom)
        receiver_info = self.algod_client.account_info(receiver_addr)
        opted_in = False
        for asset in receiver_info.get('assets', []):
            if asset['asset-id'] == self.cusd_id:
                opted_in = True
                break
        if not opted_in:
            raise Exception(f"Receiver {receiver_addr} is not opted into cUSD (ASA ID: {self.cusd_id}). To opt-in: Send 0 cUSD to themselves or use AssetOptInTxn.")
        
        print(f"\nWithdrawing {cusd_balance / 10**6:.2f} cUSD to {receiver_addr}")
        
        params = self.algod_client.suggested_params()
        params.flat_fee = True
        params.fee = getattr(params, "min_fee", 1000) * 2  # 1 outer + 1 inner
        
        # Build app args
        app_args = [b"withdraw"]
        if receiver:
            app_args.append(encoding.decode_address(receiver))
        
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=app_args,
            on_complete=OnComplete.NoOpOC
        )
        
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Withdrew {cusd_balance / 10**6:.2f} cUSD")
        print(f"   Transaction: {tx_id}")
        
    def permanent_unlock(self, admin_address: str, admin_sk: str, skip_confirmation: bool = False):
        """
        Permanently unlock tokens for claiming
        ⚠️ WARNING: This action is IRREVERSIBLE!
        
        Args:
            skip_confirmation: Skip confirmation prompt (for automation/CI)
        """
        
        if not skip_confirmation:
            print("\n" + "⚠️ " * 10)
            print("WARNING: PERMANENT UNLOCK IS IRREVERSIBLE!")
            print("Once unlocked, tokens can never be locked again.")
            print("⚠️ " * 10)
            
            print(f"\n📍 Contract Details:")
            print(f"   App ID: {self.app_id}")
            print(f"   App Address: {self.app_addr}")
            
            # Show how many tokens will be unlocked
            state = self.get_state()
            total_sold = state.get('confio_sold', 0) / 10**6
            print(f"   Total CONFIO sold: {total_sold:,.0f}")
            print(f"   Participants: {state.get('participants', 0)}")
            
            confirmation = input("\nType 'UNLOCK FOREVER' to confirm: ")
            if confirmation != "UNLOCK FOREVER":
                print("Unlock cancelled")
                return
        
        print("\nUnlocking tokens permanently...")
        
        params = self.algod_client.suggested_params()
        
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=[b"unlock"],
            on_complete=OnComplete.NoOpOC
        )
        
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ TOKENS PERMANENTLY UNLOCKED!")
        print(f"   Users can now claim their CONFIO tokens")
        print(f"   Transaction: {tx_id}")
        
    def update_sponsor(self, admin_address: str, admin_sk: str, new_sponsor_address: str):
        """Update the sponsor address
        
        Args:
            admin_address: Admin's address
            admin_sk: Admin's secret key
            new_sponsor_address: New sponsor's address
        """
        
        print(f"\nUpdating sponsor address...")
        print(f"   New sponsor: {new_sponsor_address}")
        
        params = self.algod_client.suggested_params()
        
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=[
                b"update_sponsor",
                encoding.decode_address(new_sponsor_address)
            ],
            on_complete=OnComplete.NoOpOC
        )
        
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Sponsor updated successfully!")
        print(f"   Transaction: {tx_id}")
        
    def emergency_pause(self, admin_address: str, admin_sk: str):
        """Toggle emergency pause state"""
        
        state = self.get_state()
        current = "paused" if state.get('paused', 0) == 1 else "active"
        
        print(f"\nEmergency pause toggle: Contract is currently {current}")
        
        params = self.algod_client.suggested_params()
        
        txn = ApplicationCallTxn(
            sender=admin_address,
            sp=params,
            index=self.app_id,
            app_args=[b"pause"],
            on_complete=OnComplete.NoOpOC
        )
        
        signed_txn = txn.sign(admin_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        new_state = "active" if current == "paused" else "paused"
        print(f"✅ Contract is now {new_state}")
        
    def fund_contract(self, sender_address: str, sender_sk: str, amount_confio: float):
        """
        Fund the contract with CONFIO tokens
        
        Args:
            amount_confio: Amount of CONFIO tokens in human units (e.g., 100000.0 means 100k CONFIO)
        
        Note: Value will be converted to 6-decimal micro units internally.
        """
        
        amount_int = int((Decimal(str(amount_confio)) * (10**6)).to_integral_value(ROUND_DOWN))
        
        print(f"\nFunding contract with {amount_confio:,.0f} CONFIO")
        
        params = self.algod_client.suggested_params()
        
        txn = AssetTransferTxn(
            sender=sender_address,
            sp=params,
            receiver=self.app_addr,
            amt=amount_int,
            index=self.confio_id
        )
        
        signed_txn = txn.sign(sender_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Contract funded with {amount_confio:,.0f} CONFIO")
        
    def bootstrap_contract(self, admin_address: str, admin_sk: str,
                           sponsor_address: str, sponsor_sk: str,
                           initial_confio_amount: int = 0) -> bool:
        """Bootstrap the contract: fund MBR, opt into assets, and optionally fund with CONFIO
        
        Args:
            admin_address: Admin's address
            admin_sk: Admin's secret key
            sponsor_address: Sponsor's address
            sponsor_sk: Sponsor's secret key
            initial_confio_amount: Optional CONFIO amount to fund (in micro units)
        
        Returns:
            True if successful
        """
        
        print("\n🚀 BOOTSTRAPPING PRESALE CONTRACT")
        print("=" * 50)
        
        # Step 1: Pre-fund MBR
        print("\n1️⃣ Funding contract MBR...")
        params = self.algod_client.suggested_params()
        
        mbr_payment = PaymentTxn(
            sender=sponsor_address,
            sp=params,
            receiver=self.app_addr,
            amt=400000  # 0.40 ALGO MBR: 0.1 base + 0.1 per ASA × 2 + 0.1 buffer
        )
        
        signed_mbr = mbr_payment.sign(sponsor_sk)
        tx_id = self.algod_client.send_transaction(signed_mbr)
        wait_for_confirmation(self.algod_client, tx_id, 4)
        print("   ✅ MBR funded (0.35 ALGO)")
        
        # Step 2: Opt into assets
        print("\n2️⃣ Opting into CONFIO and cUSD assets...")
        
        # Compute fees
        base = self.algod_client.suggested_params()
        min_fee = getattr(base, "min_fee", 1000)
        
        # AppCall: pays for itself + 2 inner opt-ins
        sp_app = self.algod_client.suggested_params()
        sp_app.flat_fee = True
        sp_app.fee = min_fee * 3  # base + 2 inners
        
        # Sponsor: pays for both outer txns
        sp_sponsor = self.algod_client.suggested_params()
        sp_sponsor.flat_fee = True
        sp_sponsor.fee = min_fee * 2
        
        # Group transaction
        sponsor_bump = PaymentTxn(
            sender=sponsor_address,
            sp=sp_sponsor,
            receiver=sponsor_address,
            amt=0
        )
        
        app_txn = ApplicationCallTxn(
            sender=admin_address,
            sp=sp_app,
            index=self.app_id,
            app_args=[b"opt_in_assets"],
            on_complete=OnComplete.NoOpOC
        )
        
        # Group and sign
        group = [sponsor_bump, app_txn]
        assign_group_id(group)  # Mutates in place, ignore return value
        
        signed_bump = group[0].sign(sponsor_sk)
        signed_app = group[1].sign(admin_sk)
        
        # Send group
        self.algod_client.send_transactions([signed_bump, signed_app])
        wait_for_confirmation(self.algod_client, signed_app.get_txid(), 4)
        print("   ✅ Opted into assets")
        
        # Step 3: Optionally fund with CONFIO
        if initial_confio_amount > 0:
            print(f"\n3️⃣ Funding with {initial_confio_amount / 10**6:,.0f} CONFIO...")
            
            # Note: This assumes admin has CONFIO to fund
            # You might want to use a treasury address instead
            txn = AssetTransferTxn(
                sender=admin_address,
                sp=self.algod_client.suggested_params(),
                receiver=self.app_addr,
                amt=initial_confio_amount,
                index=self.confio_id
            )
            
            signed_txn = txn.sign(admin_sk)
            tx_id = self.algod_client.send_transaction(signed_txn)
            wait_for_confirmation(self.algod_client, tx_id, 4)
            print(f"   ✅ Funded with CONFIO")
        
        # Step 4: Verify balances
        print("\n4️⃣ Verifying contract state...")
        account_info = self.algod_client.account_info(self.app_addr)
        
        # Check ALGO balance
        algo_balance = account_info['amount'] / 10**6
        print(f"   ALGO balance: {algo_balance:.4f}")
        
        # Check asset opt-ins
        opted_assets = []
        for asset in account_info.get('assets', []):
            if asset['asset-id'] == self.confio_id:
                opted_assets.append('CONFIO')
                print(f"   CONFIO: ✅ Opted in (balance: {asset['amount'] / 10**6:,.0f})")
            elif asset['asset-id'] == self.cusd_id:
                opted_assets.append('cUSD')
                print(f"   cUSD: ✅ Opted in")
        
        if len(opted_assets) != 2:
            print("   ⚠️ Warning: Not opted into all required assets")
            return False
        
        print("\n✅ CONTRACT BOOTSTRAP COMPLETE!")
        print(f"   App ID: {self.app_id}")
        print(f"   App Address: {self.app_addr}")
        print("\n📝 Next steps:")
        print("   1. Fund with more CONFIO if needed")
        print("   2. Start your first presale round")
        
        return True
    
    def get_state(self) -> Dict[str, Any]:
        """Get current contract state"""
        
        app_info = self.algod_client.application_info(self.app_id)
        return decode_state(app_info['params']['global-state'])
    
    def display_dashboard(self):
        """Display comprehensive admin dashboard"""
        
        state = self.get_state()
        
        # Get contract balances
        account_info = self.algod_client.account_info(self.app_addr)
        confio_balance = 0
        cusd_balance = 0
        
        for asset in account_info.get('assets', []):
            if asset['asset-id'] == self.confio_id:
                confio_balance = asset['amount']
            elif asset['asset-id'] == self.cusd_id:
                cusd_balance = asset['amount']
        
        print("\n" + "=" * 70)
        print("                    PRESALE ADMIN DASHBOARD")
        print("=" * 70)
        
        # Contract Info
        print(f"\n📋 CONTRACT INFO")
        print(f"   App ID: {self.app_id}")
        print(f"   Address: {self.app_addr}")
        
        # Display admin and sponsor addresses if available
        admin_addr = state.get('admin')
        sponsor_addr = state.get('sponsor')
        if admin_addr:
            print(f"   Admin: {format_address(to_algorand_address(admin_addr))}")
        if sponsor_addr:
            print(f"   Sponsor: {format_address(to_algorand_address(sponsor_addr))}")
        
        # Round Status
        round_num = state.get('round', 0)
        is_active = state.get('active', 0) == 1
        is_paused = state.get('paused', 0) == 1
        
        print(f"\n🎯 ROUND #{round_num} STATUS")
        
        if is_paused:
            print("   🔴 CONTRACT EMERGENCY PAUSED")
        elif is_active:
            print("   🟢 ROUND ACTIVE")
        else:
            print("   🟡 ROUND PAUSED")
        
        # Round Parameters
        print(f"\n💱 CURRENT PARAMETERS")
        price = state.get('price', 0) / 10**6
        print(f"   Price: {price:.4f} cUSD per CONFIO")
        print(f"   cUSD Cap: {state.get('cusd_cap', 0) / 10**6:,.2f} cUSD")
        print(f"   Min Buy: {state.get('min_buy', 0) / 10**6:.2f} cUSD")
        print(f"   Max Per Address: {state.get('max_addr', 0) / 10**6:,.2f} cUSD")
        
        # Round Progress
        cusd_raised = state.get('cusd_raised', 0) / 10**6
        cusd_cap = state.get('cusd_cap', 0) / 10**6
        
        if cusd_cap > 0:
            progress = (cusd_raised / cusd_cap) * 100
            # Calculate equivalent CONFIO sold using integers to avoid float drift
            price_u = state.get('price', 0)
            raised_u = state.get('cusd_raised', 0)
            confio_sold = (raised_u * 10**6) // price_u if price_u else 0
            
            print(f"\n📊 ROUND PROGRESS")
            print(f"   cUSD Raised: {cusd_raised:,.2f} / {cusd_cap:,.2f} cUSD ({progress:.1f}%)")
            print(f"   CONFIO Sold: ~{confio_sold / 10**6:,.0f} CONFIO")
            
            # Progress bar
            bar_length = 50
            filled = int(bar_length * progress / 100)
            bar = '█' * filled + '░' * (bar_length - filled)
            print(f"   [{bar}]")
        
        # Overall Statistics
        print(f"\n📈 LIFETIME STATISTICS")
        print(f"   Total Rounds: {state.get('total_rounds', 0)}")
        print(f"   Total CONFIO Sold: {state.get('confio_sold', 0) / 10**6:,.0f} CONFIO")
        print(f"   Total cUSD Raised: {state.get('total_raised', 0) / 10**6:,.2f} cUSD")
        print(f"   Participants (cumulative): {state.get('participants', 0)}")
        
        # Contract Balances
        print(f"\n💰 CONTRACT BALANCES")
        print(f"   CONFIO: {confio_balance / 10**6:,.0f}")
        print(f"   cUSD: {cusd_balance / 10**6:,.2f}")
        
        # Lock Status
        print(f"\n🔒 LOCK STATUS")
        if state.get('locked', 1) == 1:
            print("   Tokens are LOCKED")
        else:
            unlock_time = state.get('unlock_time', 0)
            if unlock_time > 0:
                unlock_date = datetime.fromtimestamp(unlock_time, tz=timezone.utc)
                print(f"   Tokens UNLOCKED on {unlock_date.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            else:
                print("   Tokens are UNLOCKED")
        
        # Available Actions
        print(f"\n⚡ AVAILABLE ACTIONS")
        if not is_active and round_num == 0:
            print("   • Start first presale round")
        elif not is_active:
            print("   • Start new round")
            print("   • Resume current round")
        else:
            print("   • Pause round")
            print("   • Update price")
        
        if cusd_balance > 0:
            print(f"   • Withdraw {cusd_balance / 10**6:.2f} cUSD")
        
        if state.get('locked', 1) == 1:
            print("   • Permanently unlock tokens (⚠️ IRREVERSIBLE)")
        
        print("=" * 70)
    
    def export_statistics(self, filename: str = "presale_stats.json"):
        """Export presale statistics to JSON file"""
        
        state = self.get_state()
        
        # Get unlock time in human-readable format if available
        unlock_time_epoch = state.get('unlock_time', 0)
        unlock_time_human = None
        if unlock_time_epoch > 0:
            unlock_time_human = datetime.fromtimestamp(unlock_time_epoch, tz=timezone.utc).isoformat()
        
        stats = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "app_id": self.app_id,
            "round": {
                "number": state.get('round', 0),
                "active": state.get('active', 0) == 1,
                "price_cusd_per_confio": state.get('price', 0) / 10**6,
                "cusd_cap": state.get('cusd_cap', 0) / 10**6,
                "cusd_raised": state.get('cusd_raised', 0) / 10**6,
                "confio_sold_est": (
                    (state.get('cusd_raised', 0) * 10**6) // max(1, state.get('price', 0))
                ) / 10**6,
            },
            "totals": {
                "rounds": state.get('total_rounds', 0),
                "sold_confio": state.get('confio_sold', 0) / 10**6,
                "raised_cusd": state.get('total_raised', 0) / 10**6,
                "participants": state.get('participants', 0)
            },
            "lock_status": {
                "locked": state.get('locked', 1) == 1,
                "unlock_time": unlock_time_epoch,
                "unlock_time_human": unlock_time_human
            }
        }
        
        with open(filename, 'w') as f:
            json.dump(stats, f, indent=2)
        
        print(f"Statistics exported to {filename}")

def main():
    """Admin CLI interface"""
    
    print("CONFIO PRESALE ADMIN TOOL")
    print("=" * 40)
    
    # Configuration (update these)
    APP_ID = int(os.getenv("PRESALE_APP_ID", "0"))
    CONFIO_ID = int(os.getenv("CONFIO_ASSET_ID", "0"))
    CUSD_ID = int(os.getenv("CUSD_ASSET_ID", "0"))
    
    if APP_ID == 0:
        print("\n⚠️  Please set environment variables:")
        print("   export PRESALE_APP_ID=123")
        print("   export CONFIO_ASSET_ID=456")
        print("   export CUSD_ASSET_ID=789")
        return
    
    admin = PresaleAdmin(APP_ID, CONFIO_ID, CUSD_ID)
    
    # Display dashboard
    admin.display_dashboard()
    
    # Example operations (uncomment to use):
    
    # admin_address = "YOUR_ADMIN_ADDRESS"
    # admin_sk = "YOUR_ADMIN_SK"
    
    # Start a new round
    # admin.start_round(
    #     admin_address, admin_sk,
    #     price_cusd_per_confio=0.25,  # 0.25 cUSD per CONFIO
    #     cusd_cap=1_000_000,           # 1M cUSD to raise
    #     max_per_addr=10_000           # 10k cUSD max per address
    # )
    
    # Withdraw cUSD
    # admin.withdraw_cusd(admin_address, admin_sk)
    
    # Export statistics
    # admin.export_statistics()

if __name__ == "__main__":
    main()
