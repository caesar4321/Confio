#!/usr/bin/env python3
"""
User interaction script for CONFIO presale

This script provides functions for users to:
- Buy CONFIO tokens during presale
- Check their purchase history
- Claim unlocked tokens
"""

import os
import sys
from typing import Dict, Any, Tuple

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state_utils import decode_state, decode_local_state, format_confio_amount, format_cusd_amount

from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import (
    ApplicationCallTxn,
    ApplicationOptInTxn,
    AssetTransferTxn,
    PaymentTxn,
    OnComplete,
    assign_group_id,
    wait_for_confirmation
)

# Network configuration
ALGOD_ADDRESS = os.getenv("ALGOD_ADDRESS", "http://localhost:4001")
ALGOD_TOKEN = os.getenv("ALGOD_TOKEN", "a" * 64)

class PresaleUser:
    """User interface for CONFIO presale"""
    
    def __init__(self, app_id: int, confio_id: int, cusd_id: int):
        self.algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
        self.app_id = app_id
        self.confio_id = confio_id
        self.cusd_id = cusd_id
    
    def _calculate_sponsor_fee(self, num_outer_txns: int, num_inner_txns: int, padding: int = 0) -> int:
        """Calculate sponsor fee budget for a group transaction
        
        Args:
            num_outer_txns: Number of outer transactions in the group
            num_inner_txns: Number of inner transactions the app call will make
            padding: Optional extra fee padding for safety
        
        Returns:
            Total fee the sponsor should pay
        """
        base = self.algod_client.suggested_params()
        min_fee = getattr(base, "min_fee", 1000)
        return min_fee * (num_outer_txns + num_inner_txns + padding)
        
    def opt_in(self, user_address: str, user_sk: str, 
               sponsor_address: str, sponsor_sk: str):
        """Opt into the presale contract (fully sponsored - ONLY method supported)
        
        In our custom wallet environment, users NEVER hold ALGO.
        The sponsor handles ALL MBR and fees.
        
        Args:
            user_address: User's address
            user_sk: User's secret key
            sponsor_address: Sponsor's address
            sponsor_sk: Sponsor's secret key
        """
        
        print(f"Opting into presale contract...")
        
        # Import PaymentTxn if not already imported
        from algosdk.transaction import PaymentTxn
        
        # Set up fee pooling - sponsor pays all fees
        # Group: 2 outer txns (sponsor payment + opt-in), 0 inner txns
        sponsor_fee = self._calculate_sponsor_fee(num_outer_txns=2, num_inner_txns=0)
        
        sp_fee = self.algod_client.suggested_params()
        sp_fee.flat_fee = True
        sp_fee.fee = sponsor_fee
        
        sp_zero = self.algod_client.suggested_params()
        sp_zero.flat_fee = True
        sp_zero.fee = 0
        
        # Group: [Payment from sponsor, OptIn]
        
        # Sponsor payment (covers all fees)
        sponsor_payment = PaymentTxn(
            sender=sponsor_address,
            sp=sp_fee,
            receiver=sponsor_address,  # 0-ALGO fee bump
            amt=0
        )
        
        # User opt-in (no fees)
        opt_in_txn = ApplicationOptInTxn(
            sender=user_address,
            sp=sp_zero,
            index=self.app_id
        )
        
        # Group transactions
        group = [sponsor_payment, opt_in_txn]
        assign_group_id(group)  # Mutates in place, ignore return value
        
        # Sign transactions
        signed_payment = group[0].sign(sponsor_sk)
        signed_opt_in = group[1].sign(user_sk)
        
        # Send group
        self.algod_client.send_transactions([signed_payment, signed_opt_in])
        
        # Wait for confirmation on the opt-in transaction
        tx_id = signed_opt_in.get_txid()
        wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Opted into presale contract")
    
    def buy_confio(self, user_address: str, user_sk: str, 
                   sponsor_address: str, sponsor_sk: str,
                   cusd_amount: int) -> Dict[str, Any]:
        """
        Buy CONFIO tokens with cUSD (fully sponsored)
        
        Args:
            user_address: Buyer's address
            user_sk: Buyer's secret key
            sponsor_address: Sponsor's address
            sponsor_sk: Sponsor's secret key
            cusd_amount: Amount of cUSD to spend (in base units with 6 decimals)
        
        Returns:
            Transaction details
        """
        
        print(f"\nBuying CONFIO with {cusd_amount / 10**6:.2f} cUSD...")
        
        # Check user opt-ins first for better error messages
        try:
            account_info = self.algod_client.account_info(user_address)
            
            # Check app opt-in
            opted_in_app = False
            for app in account_info.get('apps-local-state', []):
                if app['id'] == self.app_id:
                    opted_in_app = True
                    break
            
            # Check cUSD opt-in
            opted_in_cusd = False
            cusd_balance = 0
            for asset in account_info.get('assets', []):
                if asset['asset-id'] == self.cusd_id:
                    opted_in_cusd = True
                    cusd_balance = asset['amount']
                    break
            
            if not opted_in_app or not opted_in_cusd:
                print("\n⚠️  User is not properly set up!")
                if not opted_in_app:
                    print(f"   ❌ Not opted into presale contract (App ID: {self.app_id})")
                if not opted_in_cusd:
                    print(f"   ❌ Not opted into cUSD asset (ASA ID: {self.cusd_id})")
                print("\n💡 Solution: Run sponsor_bootstrap_user() first")
                raise Exception("User needs opt-ins. Run sponsor_bootstrap_user() first.")
            
            # Check cUSD balance
            if cusd_balance < cusd_amount:
                print(f"\n⚠️  Insufficient cUSD balance!")
                print(f"   Available: {cusd_balance / 10**6:.2f} cUSD")
                print(f"   Needed: {cusd_amount / 10**6:.2f} cUSD")
                raise Exception(f"Insufficient cUSD balance")
                
        except Exception as e:
            if "opt-ins" in str(e) or "Insufficient" in str(e):
                raise
            # Continue if we can't check (might be network issue)
            pass
        
        # Get current price (cUSD per CONFIO)
        contract_info = self.get_contract_state()
        price = contract_info.get('price', 0)  # cUSD per CONFIO (6 decimals)
        
        if price == 0:
            raise Exception("Price not set or round not active")
        
        # Calculate expected CONFIO amount
        # confio_amount = cusd_amount * 10^6 / price
        expected_confio = (cusd_amount * 10**6) // price
        
        print(f"   Price: {price / 10**6:.4f} cUSD per CONFIO")
        print(f"   Expected CONFIO: {expected_confio / 10**6:.2f}")
        
        # Import PaymentTxn if not already imported
        from algosdk.transaction import PaymentTxn
        
        # Set up fee pooling - sponsor pays all fees
        # Group: 3 outer txns (sponsor payment + cUSD transfer + app call), 0 inner txns
        sponsor_fee = self._calculate_sponsor_fee(num_outer_txns=3, num_inner_txns=0)
        
        sp_fee = self.algod_client.suggested_params()
        sp_fee.flat_fee = True
        sp_fee.fee = sponsor_fee
        
        sp_zero = self.algod_client.suggested_params()
        sp_zero.flat_fee = True
        sp_zero.fee = 0
        
        # Group transaction: [Payment(sponsor), cUSD(user->app), AppCall(buy)]
        
        # Sponsor payment (covers all fees)
        sponsor_payment = PaymentTxn(
            sender=sponsor_address,
            sp=sp_fee,
            receiver=sponsor_address,  # 0-ALGO fee bump
            amt=0
        )
        
        # cUSD payment to contract (no fees)
        app_addr = self.get_app_address()
        cusd_txn = AssetTransferTxn(
            sender=user_address,
            sp=sp_zero,
            receiver=app_addr,
            amt=cusd_amount,
            index=self.cusd_id
        )
        
        # App call to buy tokens (no fees)
        app_txn = ApplicationCallTxn(
            sender=user_address,
            sp=sp_zero,
            index=self.app_id,
            app_args=[b"buy"],
            on_complete=OnComplete.NoOpOC
        )
        
        # Group transactions
        group = [sponsor_payment, cusd_txn, app_txn]
        assign_group_id(group)  # Mutates in place, ignore return value
        
        # Sign transactions
        signed_payment = group[0].sign(sponsor_sk)
        signed_cusd = group[1].sign(user_sk)
        signed_app = group[2].sign(user_sk)
        
        # Send group transaction
        self.algod_client.send_transactions([signed_payment, signed_cusd, signed_app])
        tx_id = signed_app.get_txid()  # Wait for the AppCall specifically
        result = wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Successfully bought CONFIO!")
        print(f"   Transaction ID: {tx_id}")
        
        # Get updated user info
        user_info = self.get_user_info(user_address)
        print(f"\nYour presale status:")
        print(f"   Total CONFIO purchased: {user_info['purchased'] / 10**6:.2f}")
        print(f"   Total cUSD spent: {user_info['spent'] / 10**6:.2f}")
        print(f"   Status: {'Locked (waiting for unlock)' if user_info['locked'] else 'Ready to claim'}")
        
        return {
            'tx_id': tx_id,
            'cusd_spent': cusd_amount,
            'confio_received': expected_confio,
            'total_purchased': user_info['purchased'],
            'total_spent': user_info['spent']
        }
    
    
    def claim_tokens(self, sponsor_address: str, sponsor_sk: str,
                    user_address: str, user_sk: str) -> Dict[str, Any]:
        """Claim tokens for user (fully sponsored - PREFERRED method)
        
        In our custom wallet environment, users typically NEVER hold ALGO.
        The sponsor pays ALL fees while the user provides a signature witness.
        
        Note: If sponsor is unavailable, use claim_tokens_emergency_fallback()
        
        Args:
            sponsor_address: Sponsor's address (must match contract sponsor)
            sponsor_sk: Sponsor's secret key
            user_address: User's address (beneficiary)
            user_sk: User's secret key (for signature witness)
        """
        
        print(f"\nClaiming tokens for {user_address} (fully sponsored)...")
        
        # Check if tokens are unlocked
        contract_info = self.get_contract_state()
        if contract_info.get('locked', 1) == 1:
            raise Exception("Tokens are still locked. Wait for admin to unlock.")
        
        # Get user info
        user_info = self.get_user_info(user_address)
        claimable = user_info['purchased'] - user_info['claimed']
        
        if claimable <= 0:
            raise Exception("No tokens to claim")
        
        print(f"   Claimable CONFIO: {claimable / 10**6:.2f}")
        
        # Import PaymentTxn if not already imported
        from algosdk.transaction import PaymentTxn
        
        # Set up transaction parameters
        base = self.algod_client.suggested_params()
        min_fee = getattr(base, "min_fee", 1000)
        
        # User's signature witness (0-ALGO self-payment, 0 fee - truly sponsored)
        sp_user = self.algod_client.suggested_params()
        sp_user.flat_fee = True
        sp_user.fee = 0  # User pays NO fees - sponsor covers everything
        
        user_witness = PaymentTxn(
            sender=user_address,
            sp=sp_user,
            receiver=user_address,
            amt=0  # 0 ALGO payment
        )
        
        # Sponsor's app call (carries all claim fees)
        sp_sponsor = self.algod_client.suggested_params()
        sp_sponsor.flat_fee = True
        sp_sponsor.fee = min_fee * 2  # App + 1 inner transfer
        
        app_txn = ApplicationCallTxn(
            sender=sponsor_address,
            sp=sp_sponsor,
            index=self.app_id,
            app_args=[b"claim"],
            accounts=[user_address],  # Beneficiary in accounts array (becomes accounts[1] in TEAL)
            on_complete=OnComplete.NoOpOC
        )
        
        # Group transactions
        group = [user_witness, app_txn]
        assign_group_id(group)  # Mutates in place, ignore return value
        
        # Sign transactions
        signed_witness = group[0].sign(user_sk)
        signed_app = group[1].sign(sponsor_sk)
        
        # Send group
        self.algod_client.send_transactions([signed_witness, signed_app])
        
        # Wait for confirmation
        tx_id = signed_app.get_txid()
        result = wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Successfully claimed {claimable / 10**6:.2f} CONFIO for {user_address}!")
        print(f"   Transaction ID: {tx_id}")
        print(f"   Sponsor paid all fees")
        
        return {
            'tx_id': tx_id,
            'claimed_amount': claimable,
            'beneficiary': user_address,
            'sponsor': sponsor_address
        }
    
    def claim_tokens_emergency_fallback(self, user_address: str, user_sk: str) -> Dict[str, Any]:
        """Emergency fallback: Claim tokens if sponsor is unavailable
        
        This is a SAFETY VALVE ONLY - users must have ALGO to pay fees.
        Use this if the sponsor wallet is down or unavailable.
        Users will pay ~0.002 ALGO in fees.
        
        Args:
            user_address: User's address
            user_sk: User's secret key
        """
        
        print(f"\n⚠️  EMERGENCY FALLBACK: Claiming tokens (self-funded)...")
        print(f"   User will pay transaction fees (~0.002 ALGO)")
        
        # Check if tokens are unlocked
        contract_info = self.get_contract_state()
        if contract_info.get('locked', 1) == 1:
            raise Exception("Tokens are still locked. Wait for admin to unlock.")
        
        # Get user info
        user_info = self.get_user_info(user_address)
        claimable = user_info['purchased'] - user_info['claimed']
        
        if claimable <= 0:
            raise Exception("No tokens to claim")
        
        print(f"   Claimable CONFIO: {claimable / 10**6:.2f}")
        
        # Set up transaction parameters
        base = self.algod_client.suggested_params()
        min_fee = getattr(base, "min_fee", 1000)
        
        # Single transaction with fees for app + inner transfer
        sp = self.algod_client.suggested_params()
        sp.flat_fee = True
        sp.fee = min_fee * 2  # App + 1 inner transfer
        
        app_txn = ApplicationCallTxn(
            sender=user_address,
            sp=sp,
            index=self.app_id,
            app_args=[b"claim"],
            on_complete=OnComplete.NoOpOC
        )
        
        # Sign and send
        signed_txn = app_txn.sign(user_sk)
        tx_id = self.algod_client.send_transaction(signed_txn)
        result = wait_for_confirmation(self.algod_client, tx_id, 4)
        
        print(f"✅ Successfully claimed {claimable / 10**6:.2f} CONFIO!")
        print(f"   Transaction ID: {tx_id}")
        print(f"   Mode: Emergency fallback (user paid fees)")
        
        return {
            'tx_id': tx_id,
            'claimed_amount': claimable,
            'emergency_mode': True
        }
    
    def get_user_info(self, user_address: str) -> Dict[str, Any]:
        """Get user's presale information"""
        
        try:
            # Get user's local state
            account_info = self.algod_client.account_info(user_address)
            
            # Decode local state using helper
            local_state = decode_local_state(account_info, self.app_id)
            
            if local_state:
                # Extract values using exact keys
                purchased = local_state.get('user_confio', 0)
                spent = local_state.get('user_cusd', 0)
                claimed = local_state.get('claimed', 0)
                
                # Check if tokens are locked
                contract_info = self.get_contract_state()
                locked = contract_info.get('locked', 1) == 1
                
                return {
                    'purchased': purchased,
                    'spent': spent,
                    'claimed': claimed,
                    'claimable': purchased - claimed,
                    'locked': locked
                }
            
            # User hasn't opted in
            return {
                'purchased': 0,
                'spent': 0,
                'claimed': 0,
                'claimable': 0,
                'locked': True
            }
            
        except Exception as e:
            print(f"Error getting user info: {e}")
            return {
                'purchased': 0,
                'spent': 0,
                'claimed': 0,
                'claimable': 0,
                'locked': True
            }
    
    def get_contract_state(self) -> Dict[str, Any]:
        """Get current contract state"""
        
        app_info = self.algod_client.application_info(self.app_id)
        # Use helper to decode state consistently
        return decode_state(app_info['params']['global-state'])
    
    def get_app_address(self) -> str:
        """Get application address"""
        from algosdk.logic import get_application_address
        return get_application_address(self.app_id)
    
    def sponsor_bootstrap_user(self, user_address: str, user_sk: str,
                              sponsor_address: str, sponsor_sk: str,
                              mbr_topup: int = 400_000):
        """Bootstrap new user with MBR for ASAs and app opt-in (fully sponsored)
        
        This enables true "users only need cUSD" experience by sponsoring:
        - 0.1 ALGO for cUSD ASA opt-in
        - 0.1 ALGO for CONFIO ASA opt-in  
        - 0.1 ALGO for app local state
        - 0.1 ALGO buffer for transactions
        
        Args:
            user_address: User's address to bootstrap
            user_sk: User's secret key
            sponsor_address: Sponsor's address
            sponsor_sk: Sponsor's secret key
            mbr_topup: ALGO amount in microALGO (default 0.4 ALGO)
        
        Returns:
            Transaction details
        """
        
        print(f"\nBootstrapping user {user_address[:8]}...")
        
        # Check what the user already has
        account_info = self.algod_client.account_info(user_address)
        algo_balance = account_info['amount']
        
        # Check if already opted into assets
        has_cusd = False
        has_confio = False
        for asset in account_info.get('assets', []):
            if asset['asset-id'] == self.cusd_id:
                has_cusd = True
            elif asset['asset-id'] == self.confio_id:
                has_confio = True
        
        # Check if already opted into app
        has_app = False
        for app in account_info.get('apps-local-state', []):
            if app['id'] == self.app_id:
                has_app = True
        
        if has_cusd and has_confio and has_app:
            print("User already fully bootstrapped!")
            return None
        
        # Calculate fees
        base = self.algod_client.suggested_params()
        min_fee = getattr(base, "min_fee", 1000)
        
        results = []
        
        # -------- Group 1: MBR + ASA opt-ins (if needed) --------
        if not has_cusd or not has_confio:
            txns_g1 = []
            
            # Sponsor covers group 1 fees: 1 payment + (0–2) ASA opt-ins
            g1_count = 1 + (0 if has_cusd else 1) + (0 if has_confio else 1)
            
            sp_g1_fee = self.algod_client.suggested_params()
            sp_g1_fee.flat_fee = True
            sp_g1_fee.fee = min_fee * g1_count
            
            sp_zero = self.algod_client.suggested_params()
            sp_zero.flat_fee = True
            sp_zero.fee = 0
            
            # 1) MBR top-up to user (actual ALGO sent)
            mbr_payment = PaymentTxn(
                sender=sponsor_address,
                sp=sp_g1_fee,
                receiver=user_address,
                amt=mbr_topup
            )
            txns_g1.append(mbr_payment)
            
            # 2) cUSD ASA opt-in if needed
            if not has_cusd:
                txns_g1.append(AssetTransferTxn(
                    sender=user_address,
                    sp=sp_zero,
                    receiver=user_address,
                    amt=0,
                    index=self.cusd_id
                ))
            
            # 3) CONFIO ASA opt-in if needed
            if not has_confio:
                txns_g1.append(AssetTransferTxn(
                    sender=user_address,
                    sp=sp_zero,
                    receiver=user_address,
                    amt=0,
                    index=self.confio_id
                ))
            
            # Sign & send group 1
            assign_group_id(txns_g1)
            signed_g1 = [txns_g1[0].sign(sponsor_sk)]
            for t in txns_g1[1:]:
                signed_g1.append(t.sign(user_sk))
            
            self.algod_client.send_transactions(signed_g1)
            tx_id_g1 = signed_g1[0].get_txid()
            wait_for_confirmation(self.algod_client, tx_id_g1, 4)
            results.append(tx_id_g1)
        
        # -------- Group 2: Sponsored app opt-in (must be exactly 2 txns) --------
        if not has_app:
            sp_bump = self.algod_client.suggested_params()
            sp_bump.flat_fee = True
            sp_bump.fee = min_fee * 2  # contract requires sponsor to cover both outer txns
            
            sp_app = self.algod_client.suggested_params()
            sp_app.flat_fee = True
            sp_app.fee = 0  # contract allows <= min; 0 is fine since sponsor covers group
            
            sponsor_selfpay = PaymentTxn(
                sender=sponsor_address,
                sp=sp_bump,
                receiver=sponsor_address,
                amt=0
            )
            app_optin = ApplicationOptInTxn(
                sender=user_address,
                sp=sp_app,
                index=self.app_id
            )
            
            assign_group_id([sponsor_selfpay, app_optin])
            self.algod_client.send_transactions([
                sponsor_selfpay.sign(sponsor_sk),
                app_optin.sign(user_sk)
            ])
            tx_id_g2 = app_optin.get_txid()
            wait_for_confirmation(self.algod_client, tx_id_g2, 4)
            results.append(tx_id_g2)
        
        print(f"✅ User bootstrapped successfully!")
        print(f"   MBR funded: {mbr_topup / 10**6:.2f} ALGO")
        if not has_cusd:
            print(f"   ✓ Opted into cUSD")
        if not has_confio:
            print(f"   ✓ Opted into CONFIO")
        if not has_app:
            print(f"   ✓ Opted into presale app")
        if results:
            print(f"   Transactions: {', '.join(results)}")
        
        return {
            'tx_ids': results,
            'mbr_funded': mbr_topup,
            'opted_cusd': not has_cusd,
            'opted_confio': not has_confio,
            'opted_app': not has_app
        }
    
    def display_presale_info(self):
        """Display current presale information"""
        
        state = self.get_contract_state()
        
        print("\n" + "=" * 60)
        print("CONFIO PRESALE STATUS")
        print("=" * 60)
        
        print(f"Round #{state.get('round', 0)}")
        
        if state.get('active', 0) == 1:
            print("🟢 PRESALE IS ACTIVE")
            
            # Use new field names
            price = state.get('price', 0)           # 6d
            cap = state.get('cusd_cap', 0)          # 6d
            raised = state.get('cusd_raised', 0)    # 6d
            
            progress = (raised / cap * 100) if cap else 0
            confio_est = (raised * 10**6) // price if price else 0  # 6d
            
            print(f"\nPrice: {price/1e6:.4f} cUSD/CONFIO")
            print(f"Progress: {raised/1e6:,.2f} / {cap/1e6:,.2f} cUSD ({progress:.1f}%)")
            print(f"Est. CONFIO sold this round: {confio_est/1e6:,.0f}")
            
            # Progress bar
            bar_length = 40
            filled = int(bar_length * progress / 100)
            bar = '█' * filled + '░' * (bar_length - filled)
            print(f"[{bar}]")
            
        else:
            print("🔴 PRESALE IS PAUSED")
        
        print(f"\nTotal Statistics:")
        print(f"   Total Sold: {state.get('confio_sold', 0) / 10**6:,.2f} CONFIO")
        print(f"   Total Raised: {state.get('total_raised', 0) / 10**6:,.2f} cUSD")
        print(f"   Participants (cumulative): {state.get('participants', 0)}")
        
        if state.get('locked', 1) == 0:
            print("\n✨ TOKENS ARE UNLOCKED - Users can claim!")
        else:
            print("\n🔒 Tokens are locked until presale ends")
        
        print("=" * 60)

def main():
    """Example usage"""
    
    # Configuration
    APP_ID = 123  # Your presale app ID
    CONFIO_ID = 456  # Your CONFIO asset ID
    CUSD_ID = 789  # Your cUSD asset ID
    
    # Create user interface
    presale = PresaleUser(APP_ID, CONFIO_ID, CUSD_ID)
    
    # Display presale info
    presale.display_presale_info()
    
    # Example: Get user info
    # user_address = "YOUR_ADDRESS"
    # info = presale.get_user_info(user_address)
    # print(f"\nYour balance: {info['purchased'] / 10**6:.2f} CONFIO")
    
    print("\nTo interact with presale:")
    print("1. Update APP_ID, CONFIO_ID, and CUSD_ID")
    print("2. Uncomment and run the example code")

if __name__ == "__main__":
    main()
