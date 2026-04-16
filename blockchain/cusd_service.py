"""
Service for handling cUSD minting and burning operations on Algorand blockchain
"""
import logging
import base64
from typing import Dict, Optional, Tuple
from decimal import Decimal
from algosdk import transaction, encoding
from algosdk.transaction import AssetTransferTxn, ApplicationCallTxn, PaymentTxn, wait_for_confirmation
from algosdk.abi import Method, Returns
from django.conf import settings
from .algorand_client import AlgorandClient
from .algorand_sponsor_service import AlgorandSponsorService

logger = logging.getLogger(__name__)


class CUSDService:
    """Service for minting and burning cUSD with USDC collateral"""
    
    def __init__(self):
        self.client = AlgorandClient()
        self.sponsor_service = AlgorandSponsorService()
        self.app_id = settings.ALGORAND_CUSD_APP_ID
        self.cusd_asset_id = settings.ALGORAND_CUSD_ASSET_ID
        self.usdc_asset_id = settings.ALGORAND_USDC_ASSET_ID
        self.app_address = None
        
    async def mint_with_collateral(
        self, 
        user_address: str,
        user_private_key: str,
        usdc_amount: Decimal
    ) -> Optional[Dict]:
        """
        Mint cUSD by providing USDC collateral (1:1 ratio)
        
        Args:
            user_address: User's Algorand address
            user_private_key: User's private key for signing
            usdc_amount: Amount of USDC to use as collateral
            
        Returns:
            Dict with transaction details or None if failed
        """
        try:
            logger.info(f"Starting mint_with_collateral: {usdc_amount} USDC from {user_address}")
            
            # Convert amount to microunits (6 decimals for both USDC and cUSD)
            usdc_microunits = int(usdc_amount * 1_000_000)
            
            # Get suggested params
            params = self.client.algod.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            
            # Get app address
            from algosdk.logic import get_application_address
            if not self.app_address:
                self.app_address = get_application_address(self.app_id)
            
            # --- Transaction 0: Sponsor payment (Mandatory per contract) ---
            # Contract requires Gtxn[0].type == pay and Gtxn[0].sender == sponsor
            sponsor_address = self.sponsor_service.sponsor_address
            
            # Calculate funding needed for MBR if user is low on ALGO
            account_info = self.client.algod.account_info(user_address)
            current_balance = account_info.get('amount', 0)
            min_balance_required = account_info.get('min-balance', 0)
            
            funding_amount = min_fee # Minimum to satisfy contract assert Gtxn[0].amount >= min_fee
            if current_balance < min_balance_required:
                funding_amount = max(funding_amount, min_balance_required - current_balance + min_fee)

            sponsor_payment = PaymentTxn(
                sender=sponsor_address,
                sp=params,
                receiver=user_address,
                amt=funding_amount,
                note=b"Sponsorship for cUSD mint"
            )
            
            # --- Transaction 1: USDC transfer from user to app ---
            usdc_params = transaction.SuggestedParams(
                fee=0, # Sponsored
                first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True
            )
            usdc_transfer = AssetTransferTxn(
                sender=user_address,
                sp=usdc_params,
                receiver=self.app_address,
                amt=usdc_microunits,
                index=self.usdc_asset_id
            )
            
            # --- Transaction 2: App call to mint_with_collateral (Sent by Sponsor) ---
            # 3*min_fee budget for 2 inner transactions
            app_params = transaction.SuggestedParams(
                fee=3 * min_fee,
                first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True
            )
            
            mint_selector = Method(name="mint_with_collateral", args=[], returns=Returns("void")).get_selector()
            app_call = ApplicationCallTxn(
                sender=sponsor_address, # Sponsor sends the app call
                sp=app_params,
                index=self.app_id,
                app_args=[mint_selector],
                foreign_assets=[self.usdc_asset_id, self.cusd_asset_id],
                accounts=[user_address] # User address as account reference
            )
            
            # Group transactions: [Payment, AssetTransfer, AppCall]
            group_id = transaction.calculate_group_id([sponsor_payment, usdc_transfer, app_call])
            sponsor_payment.group = group_id
            usdc_transfer.group = group_id
            app_call.group = group_id
            
            # Sign transactions
            signed_sponsor_pay = await self.sponsor_service._sign_transaction(sponsor_payment)
            signed_usdc = usdc_transfer.sign(user_private_key)
            signed_app_call = await self.sponsor_service._sign_transaction(app_call)
            
            if not signed_sponsor_pay or not signed_app_call:
                return {'success': False, 'error': 'Failed to sign sponsor transactions'}

            # Wait, signed_sponsor_pay is base64 string from KMS signer
            raw_signed_txns = [
                base64.b64decode(signed_sponsor_pay),
                encoding.msgpack_encode(signed_usdc),
                base64.b64decode(signed_app_call)
            ]
            
            tx_id = self.client.algod.send_raw_transaction(b''.join(raw_signed_txns))
            
            # Wait for confirmation
            confirmed_txn = wait_for_confirmation(self.client.algod, tx_id, 10)
            
            logger.info(f"Mint successful: {usdc_amount} cUSD minted, tx: {tx_id}")
            
            return {
                'success': True,
                'transaction_id': tx_id,
                'usdc_amount': str(usdc_amount),
                'cusd_amount': str(usdc_amount),
                'block': confirmed_txn.get('confirmed-round', 0)
            }
            
        except Exception as e:
            logger.error(f"Error in mint_with_collateral: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def burn_for_collateral(
        self,
        user_address: str,
        user_private_key: str,
        cusd_amount: Decimal
    ) -> Optional[Dict]:
        """
        Burn cUSD to redeem USDC collateral (1:1 ratio)
        
        Args:
            user_address: User's Algorand address
            user_private_key: User's private key for signing
            cusd_amount: Amount of cUSD to burn
            
        Returns:
            Dict with transaction details or None if failed
        """
        try:
            logger.info(f"Starting burn_for_collateral: {cusd_amount} cUSD from {user_address}")
            
            # Convert amount to microunits (6 decimals for both USDC and cUSD)
            cusd_microunits = int(cusd_amount * 1_000_000)
            
            # Get suggested params
            params = self.client.algod.suggested_params()
            min_fee = getattr(params, 'min_fee', 1000) or 1000
            
            # Get app address
            from algosdk.logic import get_application_address
            if not self.app_address:
                self.app_address = get_application_address(self.app_id)
            
            # --- Transaction 0: Sponsor payment (Mandatory per contract) ---
            sponsor_address = self.sponsor_service.sponsor_address
            
            # Calculate funding needed for MBR
            account_info = self.client.algod.account_info(user_address)
            current_balance = account_info.get('amount', 0)
            min_balance_required = account_info.get('min-balance', 0)
            
            funding_amount = min_fee
            if current_balance < min_balance_required:
                funding_amount = max(funding_amount, min_balance_required - current_balance + min_fee)

            sponsor_payment = PaymentTxn(
                sender=sponsor_address,
                sp=params,
                receiver=user_address,
                amt=funding_amount,
                note=b"Sponsorship for cUSD burn"
            )
            
            # --- Transaction 1: cUSD transfer from user to app ---
            cusd_params = transaction.SuggestedParams(
                fee=0, # Sponsored
                first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True
            )
            cusd_transfer = AssetTransferTxn(
                sender=user_address,
                sp=cusd_params,
                receiver=self.app_address,
                amt=cusd_microunits,
                index=self.cusd_asset_id
            )
            
            # --- Transaction 2: App call to burn_for_collateral ---
            # 4*min_fee budget for 3 inner transactions
            app_params = transaction.SuggestedParams(
                fee=4 * min_fee,
                first=params.first, last=params.last, gh=params.gh, gen=params.gen, flat_fee=True
            )
            
            burn_selector = Method(name="burn_for_collateral", args=[], returns=Returns("void")).get_selector()
            app_call = ApplicationCallTxn(
                sender=sponsor_address, # Sponsor sends the app call
                sp=app_params,
                index=self.app_id,
                app_args=[burn_selector],
                foreign_assets=[self.usdc_asset_id, self.cusd_asset_id],
                accounts=[user_address]
            )
            
            # Group transactions: [Payment, AssetTransfer, AppCall]
            group_id = transaction.calculate_group_id([sponsor_payment, cusd_transfer, app_call])
            sponsor_payment.group = group_id
            cusd_transfer.group = group_id
            app_call.group = group_id
            
            # Sign transactions
            signed_sponsor_pay = await self.sponsor_service._sign_transaction(sponsor_payment)
            signed_cusd = cusd_transfer.sign(user_private_key)
            signed_app_call = await self.sponsor_service._sign_transaction(app_call)
            
            if not signed_sponsor_pay or not signed_app_call:
                return {'success': False, 'error': 'Failed to sign sponsor transactions'}

            # Send transaction group
            raw_signed_txns = [
                base64.b64decode(signed_sponsor_pay),
                encoding.msgpack_encode(signed_cusd),
                base64.b64decode(signed_app_call)
            ]
            
            tx_id = self.client.algod.send_raw_transaction(b''.join(raw_signed_txns))
            
            # Wait for confirmation
            confirmed_txn = wait_for_confirmation(self.client.algod, tx_id, 10)
            
            logger.info(f"Burn successful: {cusd_amount} cUSD burned, tx: {tx_id}")
            
            return {
                'success': True,
                'transaction_id': tx_id,
                'cusd_amount': str(cusd_amount),
                'usdc_amount': str(cusd_amount),
                'block': confirmed_txn.get('confirmed-round', 0)
            }
            
        except Exception as e:
            logger.error(f"Error in burn_for_collateral: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def check_opt_in_status(self, user_address: str) -> Dict[str, bool]:
        """
        Check if user has opted into cUSD and USDC assets
        
        Args:
            user_address: User's Algorand address
            
        Returns:
            Dict with opt-in status for each asset
        """
        try:
            account_info = self.client.algod.account_info(user_address)
            assets = account_info.get('assets', [])
            asset_ids = [asset['asset-id'] for asset in assets]
            
            return {
                'usdc_opted_in': self.usdc_asset_id in asset_ids,
                'cusd_opted_in': self.cusd_asset_id in asset_ids
            }
        except Exception as e:
            logger.error(f"Error checking opt-in status: {e}")
            return {
                'usdc_opted_in': False,
                'cusd_opted_in': False
            }
    
