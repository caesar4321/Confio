#!/usr/bin/env python3
"""
Fund CONFIO Presale Contract

This script helps fund the presale contract with CONFIO tokens
and provides utilities for managing the presale allocation.
"""

import os
import sys
from typing import Dict, Any, Optional
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import (
    AssetTransferTxn,
    ApplicationCallTxn,
    PaymentTxn,
    OnComplete,
    assign_group_id,
    wait_for_confirmation
)
from algosdk.logic import get_application_address

# Network configuration
ALGOD_ADDRESS = os.getenv("ALGOD_ADDRESS", "http://localhost:4001")
ALGOD_TOKEN = os.getenv("ALGOD_TOKEN", "a" * 64)

class PresaleFunder:
    """Manage funding for CONFIO presale contract"""
    
    def __init__(self, app_id: int, confio_id: int, cusd_id: int):
        self.algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
        self.app_id = app_id
        self.confio_id = confio_id
        self.cusd_id = cusd_id
        self.app_addr = get_application_address(app_id)
        
    def check_balances(self) -> Dict[str, Any]:
        """Check current contract balances"""
        
        account_info = self.algod_client.account_info(self.app_addr)
        
        confio_balance = 0
        cusd_balance = 0
        algo_balance = account_info['amount']
        
        for asset in account_info.get('assets', []):
            if asset['asset-id'] == self.confio_id:
                confio_balance = asset['amount']
            elif asset['asset-id'] == self.cusd_id:
                cusd_balance = asset['amount']
        
        # Get presale state using decode_state for consistency
        app_info = self.algod_client.application_info(self.app_id)
        from state_utils import decode_state
        global_state = decode_state(app_info['params']['global-state'])
        
        return {
            'algo_balance': algo_balance / 10**6,
            'confio_balance': confio_balance / 10**6,
            'cusd_balance': cusd_balance / 10**6,
            'total_sold': global_state.get('confio_sold', 0) / 10**6,
            'cusd_raised_round': global_state.get('cusd_raised', 0) / 10**6,  # Current round cUSD raised
            'current_round': global_state.get('round', 0),
            'round_active': global_state.get('active', 0) == 1,
            'tokens_locked': global_state.get('locked', 1) == 1
        }
    
    def fund_with_confio(self, sender_address: str, sender_sk: str, 
                        amount_micro: int) -> str:
        """
        Fund the presale contract with CONFIO tokens
        
        Args:
            sender_address: Address holding CONFIO (treasury)
            sender_sk: Sender's secret key
            amount_micro: Amount of CONFIO in micro units (1_000_000 = 1 CONFIO)
        
        Returns:
            Transaction ID
        """
        
        print(f"\n💰 Funding presale contract with {amount_micro / 10**6:,.2f} CONFIO")
        print(f"   From: {sender_address}")
        print(f"   To: {self.app_addr}")
        
        # Check sender has enough CONFIO
        sender_info = self.algod_client.account_info(sender_address)
        sender_confio = 0
        
        for asset in sender_info.get('assets', []):
            if asset['asset-id'] == self.confio_id:
                sender_confio = asset['amount']
                break
        
        if sender_confio < amount_micro:
            available = sender_confio / 10**6
            raise Exception(f"Insufficient CONFIO. Available: {available:,.0f}, Needed: {amount_micro / 10**6:,.0f}")
        
        # Create transfer transaction
        params = self.algod_client.suggested_params()
        
        txn = AssetTransferTxn(
            sender=sender_address,
            sp=params,
            receiver=self.app_addr,
            amt=amount_micro,
            index=self.confio_id
        )
        
        # Sign and send
        signed_txn = txn.sign(sender_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        
        # Wait for confirmation
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Successfully funded with {amount_micro / 10**6:,.2f} CONFIO")
        print(f"   Transaction: {tx_id}")
        
        # Show new balance
        new_balance = self.check_balances()
        print(f"   New contract balance: {new_balance['confio_balance']:,.0f} CONFIO")
        
        return tx_id
    
    def calculate_funding_needs(self, rounds_plan: list) -> Dict[str, Any]:
        """
        Calculate total CONFIO needed for planned rounds
        
        Args:
            rounds_plan: List of dicts with 'hard_cap' in CONFIO tokens (human units) for each round
                        Example: [{'hard_cap': 10_000_000}, {'hard_cap': 25_000_000}]
        
        Returns:
            Funding analysis with CONFIO amounts needed
        """
        
        total_needed = sum(r['hard_cap'] for r in rounds_plan)
        current_balance = self.check_balances()['confio_balance']
        additional_needed = max(0, total_needed - current_balance)
        
        return {
            'total_needed': total_needed,
            'current_balance': current_balance,
            'additional_needed': additional_needed,
            'rounds': len(rounds_plan),
            'average_per_round': total_needed / len(rounds_plan) if rounds_plan else 0
        }
    
    def stage_funding(self, sender_address: str, sender_sk: str,
                     round_number: int, amount_micro: int) -> str:
        """
        Fund for a specific round (staged approach)
        
        Args:
            round_number: Which round to fund for
            amount_micro: CONFIO amount in micro units
        """
        
        print(f"\n📊 Staged Funding for Round {round_number}")
        print(f"   Amount: {amount_micro / 10**6:,.2f} CONFIO")
        
        # Check current state
        state = self.check_balances()
        
        if state['round_active']:
            print("⚠️  Warning: A round is currently active")
            response = input("Continue anyway? (y/n): ")
            if response.lower() != 'y':
                return None
        
        # Fund the contract
        tx_id = self.fund_with_confio(sender_address, sender_sk, amount_micro)
        
        print(f"\n✅ Round {round_number} funded and ready")
        return tx_id
    
    def withdraw_unused_confio(self, admin_address: str, admin_sk: str,
                              recipient: Optional[str] = None,
                              amount_micro: Optional[int] = None) -> str:
        """
        Withdraw unused CONFIO after presale ends
        
        Args:
            admin_address: Admin address
            admin_sk: Admin secret key
            recipient: Where to send unused CONFIO (defaults to admin)
            amount_micro: Optional amount to withdraw in micro units (defaults to all available)
        """
        
        if recipient is None:
            recipient = admin_address
        
        # Get raw state using decode_state for consistency
        app_info = self.algod_client.application_info(self.app_id)
        from state_utils import decode_state
        g = decode_state(app_info['params']['global-state'])
        
        # Get raw integers (micro units)
        confio_sold_u = g.get('confio_sold', 0)  # microCONFIO (int)
        claimed_total_u = g.get('claimed_total', 0)  # microCONFIO (int)
        
        # Get contract CONFIO balance
        acct = self.algod_client.account_info(self.app_addr)
        confio_balance_u = 0
        for a in acct.get('assets', []):
            if a['asset-id'] == self.confio_id:
                confio_balance_u = a['amount']
                break
        
        # Calculate outstanding and available in microCONFIO (pure integers)
        outstanding_u = confio_sold_u - claimed_total_u
        available_u = max(0, confio_balance_u - outstanding_u)
        
        if available_u <= 0:
            print("No unused CONFIO to withdraw")
            return None
        
        withdraw_amount = amount_micro if amount_micro is not None else available_u
        
        print(f"\n💸 Withdrawing {withdraw_amount / 10**6:,.0f} unused CONFIO")
        print(f"   To: {recipient}")
        print(f"   Available: {available_u / 10**6:,.0f} CONFIO")
        
        # Use the actual withdraw_confio function
        from algosdk import encoding
        from algosdk.transaction import ApplicationCallTxn, wait_for_confirmation
        
        params = self.algod_client.suggested_params()
        params.flat_fee = True
        params.fee = getattr(params, "min_fee", 1000) * 2  # 1 outer + 1 inner
        
        # Build app args
        app_args = [b"withdraw_confio"]
        
        # If specifying amount, you must also include a receiver (even if it's the admin)
        if amount_micro is not None:
            app_args.append(encoding.decode_address(recipient))  # include receiver
            app_args.append(withdraw_amount.to_bytes(8, 'big'))
        else:
            # only include receiver when it's not the admin
            if recipient != admin_address:
                app_args.append(encoding.decode_address(recipient))
        
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
        
        print(f"✅ Successfully withdrew {withdraw_amount / 10**6:,.0f} CONFIO")
        print(f"   Transaction: {tx_id}")
        
        return tx_id
    
    def display_funding_status(self):
        """Display comprehensive funding status"""
        
        state = self.check_balances()
        
        print("\n" + "=" * 70)
        print("                    PRESALE FUNDING STATUS")
        print("=" * 70)
        
        print(f"\n📍 Contract Address: {self.app_addr}")
        
        print(f"\n💰 BALANCES")
        print(f"   CONFIO: {state['confio_balance']:,.0f}")
        print(f"   cUSD: {state['cusd_balance']:,.2f}")
        print(f"   ALGO: {state['algo_balance']:.4f}")
        
        print(f"\n📊 PRESALE PROGRESS")
        print(f"   Current Round: {state['current_round']}")
        print(f"   Round Active: {'Yes 🟢' if state['round_active'] else 'No 🔴'}")
        print(f"   Total Sold: {state['total_sold']:,.0f} CONFIO")
        print(f"   This Round (cUSD): {state['cusd_raised_round']:,.2f}")
        
        # Calculate estimated CONFIO sold this round
        # Use decode_state for consistency
        app_info = self.algod_client.application_info(self.app_id)
        from state_utils import decode_state
        global_state = decode_state(app_info['params']['global-state'])
        
        price = global_state.get('price', 0)
        cusd_raised = global_state.get('cusd_raised', 0)
        confio_round = (cusd_raised * 10**6) // price if price else 0
        print(f"   This Round (CONFIO est): {confio_round/1e6:,.0f}")
        
        # Calculate availability
        available = state['confio_balance'] - state['total_sold']
        print(f"\n🎯 AVAILABILITY")
        print(f"   Available for sale: {available:,.0f} CONFIO")
        
        if available > 0:
            # Estimate rounds possible at different caps
            print(f"\n📈 FUNDING CAPACITY (CONFIO tokens)")
            print(f"   @ 10M CONFIO per round: {int(available / 10_000_000)} rounds")
            print(f"   @ 25M CONFIO per round: {int(available / 25_000_000)} rounds")
            print(f"   @ 50M CONFIO per round: {int(available / 50_000_000)} rounds")
        else:
            print("\n⚠️  WARNING: Insufficient CONFIO for new rounds!")
        
        print(f"\n🔒 LOCK STATUS")
        print(f"   Tokens Locked: {'Yes 🔒' if state['tokens_locked'] else 'No 🔓 (Claimable)'}")
        
        print("=" * 70)
    
    def recommend_funding(self) -> Dict[str, Any]:
        """Provide funding recommendations based on current state"""
        
        state = self.check_balances()
        available = state['confio_balance'] - state['total_sold']
        
        recommendations = {
            'immediate_action_needed': False,
            'recommended_amount': 0,
            'reason': '',
            'strategy': ''
        }
        
        if state['round_active'] and available < 10_000_000:
            recommendations['immediate_action_needed'] = True
            recommendations['recommended_amount'] = 50_000_000
            recommendations['reason'] = "Active round with low inventory"
            recommendations['strategy'] = "Fund immediately to avoid round interruption"
            
        elif available < 5_000_000:
            recommendations['immediate_action_needed'] = True
            recommendations['recommended_amount'] = 100_000_000
            recommendations['reason'] = "Very low CONFIO inventory"
            recommendations['strategy'] = "Fund before starting next round"
            
        elif available < 50_000_000:
            recommendations['recommended_amount'] = 50_000_000
            recommendations['reason'] = "Moderate inventory"
            recommendations['strategy'] = "Consider funding for next 1-2 rounds"
            
        else:
            recommendations['reason'] = "Sufficient inventory"
            recommendations['strategy'] = "No immediate funding needed"
        
        return recommendations

def main():
    """Interactive funding management"""
    
    print("CONFIO PRESALE FUNDING MANAGER")
    print("=" * 40)
    
    # Get configuration from environment or prompt
    APP_ID = int(os.getenv("PRESALE_APP_ID", "0"))
    CONFIO_ID = int(os.getenv("CONFIO_ASSET_ID", "0"))
    CUSD_ID = int(os.getenv("CUSD_ASSET_ID", "0"))
    
    if APP_ID == 0:
        print("\n⚠️  Please set environment variables:")
        print("   export PRESALE_APP_ID=123")
        print("   export CONFIO_ASSET_ID=456")
        print("   export CUSD_ASSET_ID=789")
        return
    
    funder = PresaleFunder(APP_ID, CONFIO_ID, CUSD_ID)
    
    # Display current status
    funder.display_funding_status()
    
    # Get recommendations
    rec = funder.recommend_funding()
    
    print("\n💡 RECOMMENDATIONS")
    if rec['immediate_action_needed']:
        print(f"   ⚠️  URGENT: {rec['reason']}")
        print(f"   Recommended funding: {rec['recommended_amount']:,.0f} CONFIO")
        print(f"   Strategy: {rec['strategy']}")
    else:
        print(f"   ✅ {rec['reason']}")
        print(f"   Strategy: {rec['strategy']}")
    
    # Example funding operations (uncomment to use)
    """
    # Treasury account that holds CONFIO
    TREASURY_ADDRESS = "YOUR_TREASURY_ADDRESS"
    TREASURY_SK = "YOUR_TREASURY_SK"
    
    # Option 1: Fund all at once (200M CONFIO)
    funder.fund_with_confio(
        TREASURY_ADDRESS,
        TREASURY_SK,
        200_000_000 * 10**6  # 200M CONFIO in micro units
    )
    
    # Option 2: Stage funding per round
    funder.stage_funding(
        TREASURY_ADDRESS,
        TREASURY_SK,
        round_number=1,
        amount_micro=20_000_000 * 10**6  # 20M CONFIO in micro units
    )
    """
    
    print("\n📝 To fund the contract:")
    print("   1. Set TREASURY_ADDRESS and TREASURY_SK")
    print("   2. Uncomment funding code above")
    print("   3. Run script again")

if __name__ == "__main__":
    main()