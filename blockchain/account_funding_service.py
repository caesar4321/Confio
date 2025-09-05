"""
Service to handle automatic account funding from sponsor
"""
import logging
from decimal import Decimal
from algosdk.v2client import algod
from algosdk.transaction import PaymentTxn, wait_for_confirmation
from algosdk import account, mnemonic
from django.conf import settings
import os

logger = logging.getLogger(__name__)


class AccountFundingService:
    """Handle automatic funding of user accounts for minimum balance requirements"""
    
    def __init__(self):
        from blockchain.algorand_client import get_algod_client
        self.algod_client = get_algod_client()
        self.sponsor_address = settings.ALGORAND_SPONSOR_ADDRESS
        # Get sponsor mnemonic from Django settings (which loads from .env)
        self.sponsor_mnemonic = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
        if self.sponsor_mnemonic:
            self.sponsor_private_key = mnemonic.to_private_key(self.sponsor_mnemonic)
        else:
            self.sponsor_private_key = None
            logger.warning("Sponsor mnemonic not configured - automatic funding disabled")
    
    def calculate_funding_needed(self, user_address: str, for_app_optin: bool = True) -> int:
        """
        Calculate how much ALGO is needed to fund an account
        
        Args:
            user_address: The user's Algorand address
            for_app_optin: Whether we're calculating for an app opt-in
            
        Returns:
            Amount needed in microAlgos (0 if sufficient balance)
        """
        try:
            account_info = self.algod_client.account_info(user_address)
            
            current_balance = account_info.get('amount', 0)
            current_min_balance = account_info.get('min-balance', 0)
            
            # Log current state for debugging
            num_assets = len(account_info.get('assets', []))
            num_apps = len(account_info.get('apps-local-state', []))
            logger.info(f"Account state: {num_assets} assets, {num_apps} apps")
            logger.info(f"Current min balance from Algorand: {current_min_balance} microAlgos")
            
            # Check if user is already opted into the cUSD app
            if for_app_optin:
                apps_local_state = account_info.get('apps-local-state', [])
                already_opted_in = any(app['id'] == settings.ALGORAND_CUSD_APP_ID for app in apps_local_state)
                
                if already_opted_in:
                    logger.info(f"User already opted into cUSD app {settings.ALGORAND_CUSD_APP_ID}, no additional min balance needed")
                    new_min_balance = current_min_balance
                else:
                    # Each app opt-in increases min balance by at least 100,000 microAlgos (0.1 ALGO)
                    # But apps with local state may require more
                    # The cUSD app has local state for is_frozen and is_vault
                    # Each uint64 in local state adds 28,500 microAlgos
                    # Each bytes in local state adds 50,000 microAlgos
                    # cUSD has 2 uint64 fields: is_frozen and is_vault
                    app_min_increase = 100_000 + (2 * 28_500)  # 157,000 microAlgos total
                    new_min_balance = current_min_balance + app_min_increase
                    logger.info(f"User needs to opt into app, new min balance will be {new_min_balance} microAlgos")
            else:
                new_min_balance = current_min_balance
            
            # We need exactly the new minimum balance, nothing more
            required_balance = new_min_balance
            
            if current_balance >= required_balance:
                return 0  # No funding needed
            
            # Calculate how much to send - exactly what's needed for MRB
            funding_amount = required_balance - current_balance
            
            logger.info(f"Account {user_address[:10]}... needs {funding_amount} microAlgos")
            logger.info(f"  Current balance: {current_balance}")
            logger.info(f"  Current min: {current_min_balance}")
            logger.info(f"  New min after opt-in: {new_min_balance}")
            logger.info(f"  Required: {required_balance}")
            
            return funding_amount
            
        except Exception as e:
            logger.error(f"Error calculating funding needed: {e}")
            # Default to 0.5 ALGO if we can't calculate
            return 500_000
    
    def fund_account_for_optin(self, user_address: str) -> dict:
        """
        Fund a user account from sponsor for app opt-in
        
        Args:
            user_address: The user's Algorand address
            
        Returns:
            Dict with success status and transaction ID or error
        """
        try:
            if not self.sponsor_private_key:
                return {
                    'success': False,
                    'error': 'Sponsor account not configured'
                }
            
            # Calculate how much funding is needed
            funding_amount = self.calculate_funding_needed(user_address, for_app_optin=True)
            
            if funding_amount == 0:
                logger.info(f"Account {user_address[:10]}... has sufficient balance")
                return {
                    'success': True,
                    'already_funded': True
                }
            
            # Check sponsor balance
            sponsor_info = self.algod_client.account_info(self.sponsor_address)
            sponsor_balance = sponsor_info.get('amount', 0)
            sponsor_min = sponsor_info.get('min-balance', 0)
            sponsor_available = sponsor_balance - sponsor_min
            
            if sponsor_available < funding_amount + 1000:  # Keep 1000 microAlgos buffer
                logger.error(f"Sponsor account has insufficient balance: {sponsor_available} < {funding_amount}")
                return {
                    'success': False,
                    'error': 'Sponsor account has insufficient balance'
                }
            
            # Create and send funding transaction
            params = self.algod_client.suggested_params()
            
            funding_txn = PaymentTxn(
                sender=self.sponsor_address,
                sp=params,
                receiver=user_address,
                amt=funding_amount,
                note=b"Auto funding for cUSD app opt-in"
            )
            
            # Sign and send
            signed_txn = funding_txn.sign(self.sponsor_private_key)
            tx_id = self.algod_client.send_transaction(signed_txn)
            
            # Wait for confirmation
            confirmed_txn = wait_for_confirmation(self.algod_client, tx_id, 10)
            
            logger.info(f"Funded account {user_address[:10]}... with {funding_amount} microAlgos")
            logger.info(f"Transaction ID: {tx_id}")
            
            return {
                'success': True,
                'transaction_id': tx_id,
                'amount_funded': funding_amount,
                'amount_funded_algo': funding_amount / 1_000_000
            }
            
        except Exception as e:
            logger.error(f"Error funding account: {e}")
            return {
                'success': False,
                'error': str(e)
            }


# Singleton instance
account_funding_service = AccountFundingService()
