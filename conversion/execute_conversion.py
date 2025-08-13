"""
Execute pending conversions with user signatures
This handles the actual blockchain transactions for minting/burning cUSD
"""
import logging
import asyncio
from decimal import Decimal
from typing import Optional, Dict
from django.db import transaction
from .models import Conversion
from blockchain.cusd_service import CUSDService
from blockchain.algorand_client import AlgorandClient

logger = logging.getLogger(__name__)


class ConversionExecutor:
    """Execute pending cUSD conversions on the blockchain"""
    
    def __init__(self):
        self.cusd_service = CUSDService()
        self.algorand_client = AlgorandClient()
    
    async def execute_conversion(
        self,
        conversion_id: str,
        user_private_key: str
    ) -> Dict:
        """
        Execute a pending conversion with user's signature
        
        Args:
            conversion_id: ID of the pending conversion
            user_private_key: User's private key for signing transactions
            
        Returns:
            Dict with execution result
        """
        try:
            # Get the conversion
            conversion = Conversion.objects.get(
                id=conversion_id,
                status='PENDING'
            )
            
            # Get the user's Algorand address
            if conversion.actor_user:
                account = conversion.actor_user.accounts.filter(
                    algorand_address__isnull=False
                ).first()
            elif conversion.actor_business:
                account = conversion.actor_business.accounts.filter(
                    algorand_address__isnull=False
                ).first()
            else:
                return {
                    'success': False,
                    'error': 'No account found for conversion'
                }
            
            if not account or not account.algorand_address:
                return {
                    'success': False,
                    'error': 'Account does not have Algorand address'
                }
            
            user_address = account.algorand_address
            
            # Execute based on conversion type
            if conversion.conversion_type == 'usdc_to_cusd':
                result = await self._execute_mint(
                    conversion,
                    user_address,
                    user_private_key
                )
            elif conversion.conversion_type == 'cusd_to_usdc':
                result = await self._execute_burn(
                    conversion,
                    user_address,
                    user_private_key
                )
            else:
                return {
                    'success': False,
                    'error': f'Unknown conversion type: {conversion.conversion_type}'
                }
            
            if result and result.get('success'):
                # Update conversion with transaction details
                with transaction.atomic():
                    conversion.from_transaction_hash = result.get('transaction_id', '')
                    conversion.to_transaction_hash = result.get('transaction_id', '')
                    conversion.mark_completed()
                
                # Update balances (force refresh from blockchain)
                await self.algorand_client.get_usdc_balance(user_address, skip_cache=True)
                await self.algorand_client.get_cusd_balance(user_address, skip_cache=True)
                
                return {
                    'success': True,
                    'conversion_id': str(conversion.id),
                    'transaction_id': result.get('transaction_id'),
                    'block': result.get('block')
                }
            else:
                # Mark conversion as failed
                conversion.status = 'FAILED'
                conversion.save()
                
                return {
                    'success': False,
                    'error': 'Transaction failed on blockchain'
                }
                
        except Conversion.DoesNotExist:
            return {
                'success': False,
                'error': 'Conversion not found or not pending'
            }
        except Exception as e:
            logger.error(f"Error executing conversion: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def _execute_mint(
        self,
        conversion: Conversion,
        user_address: str,
        user_private_key: str
    ) -> Optional[Dict]:
        """Execute minting of cUSD with USDC collateral"""
        try:
            # Check USDC balance
            usdc_balance = await self.algorand_client.get_usdc_balance(user_address)
            
            if usdc_balance < conversion.from_amount:
                logger.error(f"Insufficient USDC balance: {usdc_balance} < {conversion.from_amount}")
                return None
            
            # Execute mint
            result = await self.cusd_service.mint_with_collateral(
                user_address=user_address,
                user_private_key=user_private_key,
                usdc_amount=conversion.from_amount
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing mint: {e}")
            return None
    
    async def _execute_burn(
        self,
        conversion: Conversion,
        user_address: str,
        user_private_key: str
    ) -> Optional[Dict]:
        """Execute burning of cUSD to redeem USDC"""
        try:
            # Check cUSD balance
            cusd_balance = await self.algorand_client.get_cusd_balance(user_address)
            
            if cusd_balance < conversion.from_amount:
                logger.error(f"Insufficient cUSD balance: {cusd_balance} < {conversion.from_amount}")
                return None
            
            # Execute burn
            result = await self.cusd_service.burn_for_collateral(
                user_address=user_address,
                user_private_key=user_private_key,
                cusd_amount=conversion.from_amount
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing burn: {e}")
            return None


# Helper function for GraphQL mutations
def execute_pending_conversion(conversion_id: str, user_private_key: str) -> Dict:
    """
    Synchronous wrapper for executing conversions
    Used by GraphQL mutations
    """
    executor = ConversionExecutor()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            executor.execute_conversion(conversion_id, user_private_key)
        )
        return result
    finally:
        loop.close()