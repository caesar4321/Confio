"""
Transaction builder for cUSD conversions with sponsored fees
"""
import logging
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
import base64
import base64

from algosdk import encoding, transaction
from algosdk import encoding as algo_encoding
from algosdk.logic import get_application_address
from algosdk.transaction import ApplicationCallTxn, AssetTransferTxn, PaymentTxn
from django.conf import settings

from blockchain.kms_manager import get_kms_signer_from_settings

logger = logging.getLogger(__name__)


class CUSDTransactionBuilder:
    """Build unsigned transactions for cUSD conversions with fee sponsorship"""
    
    def __init__(self):
        self.app_id = settings.ALGORAND_CUSD_APP_ID
        self.cusd_asset_id = settings.ALGORAND_CUSD_ASSET_ID
        self.usdc_asset_id = settings.ALGORAND_USDC_ASSET_ID
        self.sponsor_address = settings.ALGORAND_SPONSOR_ADDRESS
        self.signer = get_kms_signer_from_settings()
        self.signer.assert_matches_address(self.sponsor_address)
    
    def build_app_optin_transaction(
        self,
        user_address: str,
        algod_client
    ) -> Dict:
        """
        Build SPONSORED transaction group for opting into the cUSD application
        
        Transaction structure:
        1. Payment from sponsor to cover fees and min balance
        2. App opt-in from user (0 fee - sponsored)
        
        Returns:
            Dict with transactions for app opt-in
        """
        try:
            logger.info(f"Building sponsored app opt-in transaction for {user_address}")
            
            # Check user's current balance and min balance
            account_info = algod_client.account_info(user_address)
            current_balance = account_info.get('amount', 0)
            min_balance_required = account_info.get('min-balance', 0)
            
            # After app opt-in, min balance will increase based on the app's local state schema
            # cUSD app has 2 uint64 fields (is_frozen, is_vault) in local state
            # Base opt-in: 100,000 microAlgos + (2 * 28,500) for the uint64 fields = 157,000 total
            app_mbr_increase = 100_000 + (2 * 28_500)  # 157,000 microAlgos
            min_balance_after_optin = min_balance_required + app_mbr_increase
            
            # Get suggested params
            params = algod_client.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            
            # Calculate funding needed
            funding_needed = 0
            if current_balance < min_balance_after_optin + min_fee:
                funding_needed = min_balance_after_optin + min_fee - current_balance
                logger.info(f"User needs {funding_needed} microAlgos for opt-in")
            
            # Transaction 0: Sponsor payment
            from algosdk.transaction import SuggestedParams, PaymentTxn
            
            sponsor_params = transaction.SuggestedParams(
                fee=min_fee,  # Sponsor pays for both transactions
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            sponsor_payment = PaymentTxn(
                sender=self.sponsor_address,
                sp=sponsor_params,
                receiver=user_address,
                amt=funding_needed,
                note=b"Sponsored cUSD app opt-in"
            )
            
            # Transaction 1: App opt-in (0 fee - sponsored)
            optin_params = transaction.SuggestedParams(
                fee=0,  # Sponsored
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            # The opt_in method selector for Beaker apps
            opt_in_selector = bytes.fromhex("30c6d58a")  # "opt_in()void"
            
            # Create app opt-in transaction with method selector
            opt_in_txn = transaction.ApplicationOptInTxn(
                sender=user_address,
                sp=optin_params,
                index=self.app_id,
                app_args=[opt_in_selector]  # Required for Beaker router
            )
            
            # Group transactions
            group_id = transaction.calculate_group_id([sponsor_payment, opt_in_txn])
            sponsor_payment.group = group_id
            opt_in_txn.group = group_id
            
            # Sign sponsor payment via KMS
            sponsor_payment_signed = self.signer.sign_transaction_msgpack(sponsor_payment)
            
            # Return transactions
            import base64
            return {
                'success': True,
                'transactions_to_sign': [
                    {
                        'txn': algo_encoding.msgpack_encode(opt_in_txn),
                        'signers': [user_address],
                        'message': 'Opt-in to cUSD application'
                    }
                ],
                'sponsor_transactions': [
                    {
                        'txn': algo_encoding.msgpack_encode(sponsor_payment),
                        'signed': sponsor_payment_signed,
                        'index': 0
                    }
                ],
                'group_id': base64.b64encode(group_id).decode('utf-8'),
                'total_fee': str(min_fee),
                'funding_amount': str(funding_needed)
            }
            
        except Exception as e:
            logger.error(f"Error building app opt-in transaction: {e}")
            return {
                'success': False,
                'error': str(e)
            }
        
    def build_mint_transactions(
        self,
        user_address: str,
        usdc_amount: Decimal,
        algod_client
    ) -> Dict:
        """
        Build transaction group for minting cUSD with USDC collateral
        WITH fee sponsorship - 3 transaction group
        
        Transaction structure:
        1. Payment from sponsor to user for fees (index 0)
        2. USDC transfer from user to app (index 1)
        3. App call to mint_with_collateral (index 2)
        
        Returns:
            Dict with unsigned transactions and metadata
        """
        try:
            logger.info(f"Building mint transactions for {user_address}, amount: {usdc_amount}")
            
            # Check if user is opted into the application
            account_info = algod_client.account_info(user_address)
            apps_local_state = account_info.get('apps-local-state', [])
            app_opted_in = any(app['id'] == self.app_id for app in apps_local_state)
            
            if not app_opted_in:
                logger.warning(f"User {user_address} not opted into app {self.app_id}")
                return {
                    'success': False,
                    'error': 'USER_NOT_OPTED_INTO_APP',
                    'app_id': self.app_id,
                    'requires_app_optin': True,
                    'message': 'User needs to opt into the cUSD application first. Call generateAppOptInTransaction mutation to get sponsored opt-in transactions.'
                }
            
            # Convert amount to microunits
            usdc_microunits = int(usdc_amount * 1_000_000)
            
            # Get suggested params
            params = algod_client.suggested_params()
            if isinstance(params, dict):
                params = transaction.SuggestedParams(**params)

            # Ensure we have the minimum fee (1000 microAlgos)
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            logger.info(f"Min fee: {min_fee}")
            
            # Get app address
            app_address = get_application_address(self.app_id)

            logger.info(f"App address: {app_address}")

            try:
                asset_params = algod_client.asset_info(self.cusd_asset_id)["params"]
                logger.info(
                    "cUSD asset %s params manager=%s reserve=%s clawback=%s freeze=%s (expect clawback == app)",
                    self.cusd_asset_id,
                    asset_params.get("manager"),
                    asset_params.get("reserve"),
                    asset_params.get("clawback"),
                    asset_params.get("freeze"),
                )
            except Exception as asset_exc:
                logger.warning("Unable to fetch cUSD asset params for %s: %s", self.cusd_asset_id, asset_exc)
            
            # Check user's balance and minimum balance requirement
            account_info = algod_client.account_info(user_address)
            current_balance = account_info.get('amount', 0)
            min_balance_required = account_info.get('min-balance', 0)
            
            logger.info(f"User {user_address}: balance={current_balance}, min_balance={min_balance_required}")
            
            # Calculate how much the user needs
            # Even with fee pooling, the app call fee is deducted from user's account
            # So user needs: min_balance + app_call_fee (which we'll calculate below)
            # We'll fund them with exactly what they need so they pay net 0
            
            # Transaction 0: Sponsor payment (MUST be first per contract requirements)
            
            # TRUE SPONSORSHIP: Sponsor sends app call and pays all fees
            # Mint does 2 inner transactions, so needs (1 + 2) * min_fee = 3 * min_fee
            app_call_fee = 3 * min_fee  # Budget for app call itself + 2 inner txns
            sponsor_payment_fee = min_fee   # Sponsor payment pays its own fee
            
            # Calculate funding needed for minimum balance only (NOT fees)
            # With true sponsorship, user doesn't pay any fees
            funding_needed = 0
            if current_balance < min_balance_required:
                funding_needed = min_balance_required - current_balance
                logger.info(f"User needs {funding_needed} microAlgos for min balance")
            else:
                logger.info(f"User has sufficient balance")

            # Contract requires Gtxn[0].amount() >= Global.min_txn_fee()
            if funding_needed < min_fee:
                funding_needed = min_fee
                logger.info(f"Adjusting funding to min_fee ({min_fee}) to satisfy contract assertion")

            # Sponsor payment parameters
            sponsor_params = transaction.SuggestedParams(
                fee=sponsor_payment_fee,  # Sponsor payment pays its own fee
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            # Sponsor only funds minimum balance shortfall (if any)
            logger.info(f"Creating sponsor payment with amount: {funding_needed} microAlgos (MBR only)")
            sponsor_payment = PaymentTxn(
                sender=self.sponsor_address,
                sp=sponsor_params,
                receiver=user_address,
                amt=funding_needed,  # Only MBR shortfall, NO fee reimbursement
                note=b"Min balance top-up for cUSD"
            )
            
            # Transaction 1: USDC transfer from user to app (0 fee - sponsored)
            usdc_params = transaction.SuggestedParams(
                fee=0,  # Sponsored by payment transaction
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            usdc_transfer = AssetTransferTxn(
                sender=user_address,
                sp=usdc_params,
                receiver=app_address,
                amt=usdc_microunits,
                index=self.usdc_asset_id
            )
            
            # Transaction 2: App call to mint_with_collateral (SENT BY SPONSOR)
            # TRUE SPONSORSHIP: Sponsor is the sender, pays the fees
            from algosdk.abi import Method, Returns
            
            app_params = transaction.SuggestedParams(
                fee=app_call_fee,  # App call MUST fund its inner transaction budget
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            # Get the ABI method selector for mint_with_collateral
            selector = Method(
                name="mint_with_collateral",
                args=[],  # no ABI args
                returns=Returns("void")
            ).get_selector()
            
            logger.debug(f"Using ABI selector for mint_with_collateral: {selector.hex()} (length: {len(selector)})")
            
            # SPONSOR sends the app call (true sponsorship)
            app_call = ApplicationCallTxn(
                sender=self.sponsor_address,  # SPONSOR is sender!
                sp=app_params,
                index=self.app_id,
                on_complete=transaction.OnComplete.NoOpOC,
                app_args=[selector],  # IMPORTANT: selector, not b"mint_with_collateral"
                foreign_assets=[self.usdc_asset_id, self.cusd_asset_id],
                accounts=[user_address]  # Pass user address as account reference for contract
            )
            
            # Group transactions: [sponsor_payment, usdc_transfer, app_call]
            # Order MUST match contract expectations!
            # Contract expects: Gtxn[0]=Payment, Gtxn[1]=AssetTransfer, Gtxn[2]=ApplicationCall
            group_id = transaction.calculate_group_id([sponsor_payment, usdc_transfer, app_call])
            sponsor_payment.group = group_id
            usdc_transfer.group = group_id
            app_call.group = group_id
            
            # Sign sponsor transactions via KMS
            sponsor_payment_signed = self.signer.sign_transaction_msgpack(sponsor_payment)
            app_call_signed = self.signer.sign_transaction_msgpack(app_call)
            
            # Encode transactions for client - user ONLY signs the USDC transfer (index 1)
            transactions_to_sign = [
                {
                    'txn': algo_encoding.msgpack_encode(usdc_transfer),
                    'signers': [user_address],
                    'message': 'USDC transfer for minting'
                }
            ]
            
            return {
                'success': True,
                'transactions_to_sign': transactions_to_sign,
                'sponsor_transactions': [
                    {
                        'txn': algo_encoding.msgpack_encode(sponsor_payment),
                        'signed': sponsor_payment_signed,
                        'index': 0  # Sponsor payment at index 0
                    },
                    {
                        'txn': algo_encoding.msgpack_encode(app_call),
                        'signed': app_call_signed,
                        'index': 2  # Sponsor app call at index 2
                    }
                ],
                'group_id': base64.b64encode(group_id).decode('utf-8'),
                'total_fee': str(sponsor_payment_fee + app_call_fee),  # Total fees (1 + 3 = 4 * min_fee)
                'usdc_amount': str(usdc_amount),
                'expected_cusd': str(usdc_amount)  # 1:1 ratio
            }
            
        except Exception as e:
            import traceback
            logger.error(f"Error building mint transactions: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def build_burn_transactions(
        self,
        user_address: str,
        cusd_amount: Decimal,
        algod_client
    ) -> Dict:
        """
        Build transaction group for burning cUSD to redeem USDC
        WITH fee sponsorship - 3 transaction group
        
        Transaction structure:
        1. Payment from sponsor to user for fees (index 0)
        2. cUSD transfer from user to app (index 1)
        3. App call to burn_for_collateral (index 2)
        
        Returns:
            Dict with unsigned transactions and metadata
        """
        try:
            # Check if user is opted into the application
            account_info = algod_client.account_info(user_address)
            apps_local_state = account_info.get('apps-local-state', [])
            app_opted_in = any(app['id'] == self.app_id for app in apps_local_state)
            
            if not app_opted_in:
                logger.warning(f"User {user_address} not opted into app {self.app_id}")
                return {
                    'success': False,
                    'error': 'USER_NOT_OPTED_INTO_APP',
                    'app_id': self.app_id,
                    'requires_app_optin': True,
                    'message': 'User needs to opt into the cUSD application first. Call generateAppOptInTransaction mutation to get sponsored opt-in transactions.'
                }
            
            # Convert amount to microunits
            cusd_microunits = int(cusd_amount * 1_000_000)
            
            # Get suggested params
            params = algod_client.suggested_params()
            
            # Ensure we have the minimum fee (1000 microAlgos)
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            logger.info(f"Min fee for burn: {min_fee}")
            
            # Get app address
            app_address = get_application_address(self.app_id)
            
            # Check user's balance and minimum balance requirement
            account_info = algod_client.account_info(user_address)
            current_balance = account_info.get('amount', 0)
            min_balance_required = account_info.get('min-balance', 0)
            
            logger.info(f"User {user_address}: balance={current_balance}, min_balance={min_balance_required}")
            
            # Transaction 0: Sponsor payment (MUST be first per contract requirements)
            from algosdk.transaction import SuggestedParams
            
            # TRUE SPONSORSHIP: Sponsor sends the app call and pays all fees
            # Burn does 2-3 inner transactions, so use 4 * min_fee for safety
            app_call_fee = 4 * min_fee  # Budget for app call itself + up to 3 inner txns
            sponsor_payment_fee = min_fee   # Sponsor payment pays its own fee
            
            # Calculate funding needed for minimum balance only (NOT fees)
            funding_needed = 0
            if current_balance < min_balance_required:
                funding_needed = min_balance_required - current_balance
                logger.info(f"User needs {funding_needed} microAlgos for min balance")
            else:
                logger.info(f"User has sufficient balance")

            # Contract requires Gtxn[0].amount() >= Global.min_txn_fee()
            if funding_needed < min_fee:
                funding_needed = min_fee
                logger.info(f"Adjusting funding to min_fee ({min_fee}) to satisfy contract assertion")

            # Sponsor payment parameters
            sponsor_params = SuggestedParams(
                fee=sponsor_payment_fee,  # Sponsor payment pays its own fee
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            # Sponsor only funds minimum balance shortfall (if any)
            logger.info(f"Creating sponsor payment with amount: {funding_needed} microAlgos (MBR only)")
            sponsor_payment = PaymentTxn(
                sender=self.sponsor_address,
                sp=sponsor_params,
                receiver=user_address,
                amt=funding_needed,  # Only MBR shortfall, NO fee reimbursement
                note=b"Min balance top-up for cUSD"
            )
            
            # Transaction 1: cUSD transfer from user to app (0 fee - sponsored)
            cusd_params = SuggestedParams(
                fee=0,  # Sponsored by payment transaction
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            cusd_transfer = AssetTransferTxn(
                sender=user_address,
                sp=cusd_params,
                receiver=app_address,
                amt=cusd_microunits,
                index=self.cusd_asset_id
            )
            
            # Transaction 2: App call to burn_for_collateral (SENT BY SPONSOR)
            # TRUE SPONSORSHIP: Sponsor is the sender, pays the fees
            from algosdk.abi import Method, Returns
            
            app_params = SuggestedParams(
                fee=app_call_fee,  # App call MUST fund its inner transaction budget
                first=params.first,
                last=params.last,
                gh=params.gh,
                gen=params.gen,
                flat_fee=True
            )
            
            # Get the ABI method selector for burn_for_collateral
            selector = Method(
                name="burn_for_collateral",
                args=[],  # no ABI args
                returns=Returns("void")
            ).get_selector()
            
            logger.debug(f"Using ABI selector for burn_for_collateral: {selector.hex()} (length: {len(selector)})")
            
            # SPONSOR sends the app call (true sponsorship)
            app_call = ApplicationCallTxn(
                sender=self.sponsor_address,  # SPONSOR is sender!
                sp=app_params,
                index=self.app_id,
                on_complete=transaction.OnComplete.NoOpOC,
                app_args=[selector],  # IMPORTANT: selector, not b"burn_for_collateral"
                foreign_assets=[self.usdc_asset_id, self.cusd_asset_id],
                accounts=[user_address]  # Pass user address as account reference for contract
            )
            
            # Group transactions: [sponsor_payment, cusd_transfer, app_call]
            # Order MUST match contract expectations!
            # Contract expects: Gtxn[0]=Payment, Gtxn[1]=AssetTransfer, Gtxn[2]=ApplicationCall
            group_id = transaction.calculate_group_id([sponsor_payment, cusd_transfer, app_call])
            sponsor_payment.group = group_id
            cusd_transfer.group = group_id
            app_call.group = group_id
            
            # Sign sponsor transactions via KMS
            sponsor_payment_signed = self.signer.sign_transaction_msgpack(sponsor_payment)
            app_call_signed = self.signer.sign_transaction_msgpack(app_call)
            
            # Encode transactions for client - user ONLY signs the cUSD transfer (index 1)
            transactions_to_sign = [
                {
                    'txn': algo_encoding.msgpack_encode(cusd_transfer),
                    'signers': [user_address],
                    'message': 'cUSD transfer for burning'
                }
            ]
            
            return {
                'success': True,
                'transactions_to_sign': transactions_to_sign,
                'sponsor_transactions': [
                    {
                        'txn': algo_encoding.msgpack_encode(sponsor_payment),
                        'signed': sponsor_payment_signed,
                        'index': 0  # Sponsor payment at index 0
                    },
                    {
                        'txn': algo_encoding.msgpack_encode(app_call),
                        'signed': app_call_signed,
                        'index': 2  # Sponsor app call at index 2
                    }
                ],
                'group_id': base64.b64encode(group_id).decode('utf-8'),
                'total_fee': str(sponsor_payment_fee + app_call_fee),  # Total fees (1 + 4 = 5 * min_fee)
                'cusd_amount': str(cusd_amount),
                'expected_usdc': str(cusd_amount)  # 1:1 ratio
            }
            
        except Exception as e:
            logger.error(f"Error building burn transactions: {e}")
            return {
                'success': False,
                'error': str(e)
            }
