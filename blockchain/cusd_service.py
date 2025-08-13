"""
Service for handling cUSD minting and burning operations on Algorand blockchain
"""
import logging
from typing import Dict, Optional, Tuple
from decimal import Decimal
from algosdk import transaction, encoding
from algosdk.transaction import AssetTransferTxn, ApplicationCallTxn, wait_for_confirmation
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, TransactionWithSigner
from django.conf import settings
from .algorand_client import AlgorandClient

logger = logging.getLogger(__name__)


class CUSDService:
    """Service for minting and burning cUSD with USDC collateral"""
    
    def __init__(self):
        self.client = AlgorandClient()
        self.app_id = settings.ALGORAND_CUSD_APP_ID
        self.cusd_asset_id = settings.ALGORAND_CUSD_ASSET_ID
        self.usdc_asset_id = settings.ALGORAND_USDC_ASSET_ID
        
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
            
            # Get app address
            from algosdk.logic import get_application_address
            app_address = get_application_address(self.app_id)
            
            # Create atomic transaction group
            # Transaction 0: USDC transfer from user to app
            usdc_transfer = AssetTransferTxn(
                sender=user_address,
                sp=params,
                receiver=app_address,
                amt=usdc_microunits,
                index=self.usdc_asset_id
            )
            
            # Transaction 1: App call to mint_with_collateral
            app_call = ApplicationCallTxn(
                sender=user_address,
                sp=params,
                index=self.app_id,
                app_args=[b"mint_with_collateral"],
                foreign_assets=[self.usdc_asset_id, self.cusd_asset_id]
            )
            
            # Group transactions
            group_id = transaction.calculate_group_id([usdc_transfer, app_call])
            usdc_transfer.group = group_id
            app_call.group = group_id
            
            # Sign transactions
            signed_usdc = usdc_transfer.sign(user_private_key)
            signed_app = app_call.sign(user_private_key)
            
            # Send transaction group
            tx_id = self.client.algod.send_transactions([signed_usdc, signed_app])
            
            # Wait for confirmation
            confirmed_txn = wait_for_confirmation(self.client.algod, tx_id, 10)
            
            # Get the cUSD amount minted (should be 1:1 with USDC)
            cusd_amount = usdc_amount  # 1:1 ratio
            
            logger.info(f"Mint successful: {cusd_amount} cUSD minted, tx: {tx_id}")
            
            return {
                'success': True,
                'transaction_id': tx_id,
                'usdc_amount': str(usdc_amount),
                'cusd_amount': str(cusd_amount),
                'block': confirmed_txn.get('confirmed-round', 0)
            }
            
        except Exception as e:
            logger.error(f"Error minting cUSD: {e}")
            return None
    
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
            
            # Get app address
            from algosdk.logic import get_application_address
            app_address = get_application_address(self.app_id)
            
            # Create atomic transaction group
            # Transaction 0: cUSD transfer from user to app
            cusd_transfer = AssetTransferTxn(
                sender=user_address,
                sp=params,
                receiver=app_address,
                amt=cusd_microunits,
                index=self.cusd_asset_id
            )
            
            # Transaction 1: App call to burn_for_collateral
            app_call = ApplicationCallTxn(
                sender=user_address,
                sp=params,
                index=self.app_id,
                app_args=[b"burn_for_collateral"],
                foreign_assets=[self.usdc_asset_id, self.cusd_asset_id]
            )
            
            # Group transactions
            group_id = transaction.calculate_group_id([cusd_transfer, app_call])
            cusd_transfer.group = group_id
            app_call.group = group_id
            
            # Sign transactions
            signed_cusd = cusd_transfer.sign(user_private_key)
            signed_app = app_call.sign(user_private_key)
            
            # Send transaction group
            tx_id = self.client.algod.send_transactions([signed_cusd, signed_app])
            
            # Wait for confirmation
            confirmed_txn = wait_for_confirmation(self.client.algod, tx_id, 10)
            
            # Get the USDC amount redeemed (should be 1:1 with cUSD)
            usdc_amount = cusd_amount  # 1:1 ratio
            
            logger.info(f"Burn successful: {cusd_amount} cUSD burned, {usdc_amount} USDC redeemed, tx: {tx_id}")
            
            return {
                'success': True,
                'transaction_id': tx_id,
                'cusd_amount': str(cusd_amount),
                'usdc_amount': str(usdc_amount),
                'block': confirmed_txn.get('confirmed-round', 0)
            }
            
        except Exception as e:
            logger.error(f"Error burning cUSD: {e}")
            return None
    
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
    
