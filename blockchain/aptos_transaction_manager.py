"""
Aptos Transaction Manager

Manages token transfers and transactions on Aptos blockchain.
Integrates with the Aptos sponsored transaction service.
"""

import asyncio
from typing import Dict, Optional, Any
from decimal import Decimal
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class AptosTransactionManager:
    """
    Manages Aptos blockchain transactions with sponsorship support.
    
    This replaces the Sui-based TransactionManagerPySui for Aptos transactions.
    """
    
    @classmethod
    async def send_tokens(
        cls,
        sender_account: 'Account',
        recipient_address: str,
        amount: Decimal,
        token_type: str,
        user_signature: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send tokens using Aptos sponsored transactions.
        
        Args:
            sender_account: Account model instance with Aptos address
            recipient_address: Recipient's Aptos address
            amount: Amount to send (in token units, e.g., 100.50)
            token_type: Token type ('CUSD', 'CONFIO', etc.)
            user_signature: User's keyless signature (optional for mock)
            
        Returns:
            Dict with transaction result
        """
        try:
            from blockchain.aptos_sponsor_service import AptosSponsorService
            
            # Validate sender address
            if not sender_account.sui_address:  # Note: using sui_address field for Aptos addresses
                return {
                    'success': False,
                    'error': 'Sender address not found'
                }
            
            # Prepare keyless info if signature provided
            keyless_info = None
            if user_signature:
                keyless_info = {
                    'available': True,
                    'signature': user_signature,
                    'account_id': str(sender_account.id)
                }
            
            # Send tokens based on token type
            if token_type.upper() == 'CUSD':
                result = await AptosSponsorService.sponsor_cusd_transfer(
                    sender_account.sui_address,  # Note: using sui_address field for Aptos addresses
                    recipient_address,
                    amount,
                    keyless_info
                )
            elif token_type.upper() == 'CONFIO':
                result = await AptosSponsorService.sponsor_confio_transfer(
                    sender_account.sui_address,
                    recipient_address,
                    amount,
                    keyless_info
                )
            else:
                return {
                    'success': False,
                    'error': f'Unsupported token type: {token_type}'
                }
            
            # Log the transaction attempt
            logger.info(
                f"Aptos transaction: {amount} {token_type} "
                f"from {sender_account.sui_address[:16]}... "
                f"to {recipient_address[:16]}... "
                f"Result: {'SUCCESS' if result.get('success') else 'FAILED'}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error in Aptos send_tokens: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @classmethod
    async def prepare_send_transaction(
        cls,
        account: 'Account',
        recipient: str,
        amount: Decimal,
        token_type: str
    ) -> Dict[str, Any]:
        """
        Prepare a send transaction for client signing.
        
        For Aptos, this creates the transaction payload and returns it
        for the client to sign with their keyless credentials.
        
        Args:
            account: Sender's account
            recipient: Recipient's Aptos address
            amount: Amount to send
            token_type: Token type ('CUSD', 'CONFIO')
            
        Returns:
            Dict with transaction preparation result
        """
        try:
            from blockchain.aptos_sponsor_service import AptosSponsorService
            
            # Check sponsor health first
            health = await AptosSponsorService.check_sponsor_health()
            if not health['can_sponsor']:
                return {
                    'success': False,
                    'error': 'Sponsor service unavailable',
                    'requiresUserSignature': False
                }
            
            # For Aptos, we prepare the transaction payload
            if token_type.upper() == 'CUSD':
                function_id = '75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::cusd::transfer_cusd'
            elif token_type.upper() == 'CONFIO':
                function_id = '75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::confio::transfer_confio'
            else:
                return {
                    'success': False,
                    'error': f'Unsupported token type: {token_type}',
                    'requiresUserSignature': False
                }
            
            # Convert amount to units (6 decimals for both CUSD and CONFIO)
            amount_units = int(amount * Decimal(10**6))
            
            # Create transaction payload
            transaction_payload = {
                'function': function_id,
                'type_arguments': [],
                'arguments': [recipient, str(amount_units)]
            }
            
            # For MVP, return a simplified response
            # In production, this would build the actual Aptos transaction
            import json
            import base64
            
            tx_data = {
                'sender': account.sui_address,
                'payload': transaction_payload,
                'amount': str(amount),
                'token_type': token_type,
                'recipient': recipient
            }
            
            # Encode as base64 for consistency with Sui approach
            tx_bytes = base64.b64encode(json.dumps(tx_data).encode()).decode()
            
            return {
                'success': True,
                'requiresUserSignature': True,
                'txBytes': tx_bytes,
                'sponsorSignature': 'sponsor_ready',  # Placeholder
                'estimatedGas': await cls._estimate_gas_cost(token_type)
            }
            
        except Exception as e:
            logger.error(f"Error preparing Aptos transaction: {e}")
            return {
                'success': False,
                'error': str(e),
                'requiresUserSignature': False
            }
    
    @classmethod
    async def execute_transaction_with_signatures(
        cls,
        tx_bytes: str,
        sponsor_signature: str,
        user_signature: str,
        account_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Execute a prepared transaction with signatures.
        
        Args:
            tx_bytes: Base64 encoded transaction data
            sponsor_signature: Sponsor's signature (placeholder for Aptos)
            user_signature: User's keyless signature
            account_id: Account ID for context
            
        Returns:
            Dict with execution result
        """
        try:
            import json
            import base64
            from blockchain.aptos_sponsor_service import AptosSponsorService
            
            # Decode transaction data
            tx_data = json.loads(base64.b64decode(tx_bytes).decode())
            
            sender_address = tx_data['sender']
            recipient_address = tx_data['recipient']
            amount = Decimal(tx_data['amount'])
            token_type = tx_data['token_type']
            
            # Prepare keyless info
            keyless_info = {
                'available': True,
                'signature': user_signature,
                'account_id': str(account_id) if account_id else None
            }
            
            # Execute the sponsored transaction
            if token_type.upper() == 'CUSD':
                result = await AptosSponsorService.sponsor_cusd_transfer(
                    sender_address,
                    recipient_address,
                    amount,
                    keyless_info
                )
            elif token_type.upper() == 'CONFIO':
                result = await AptosSponsorService.sponsor_confio_transfer(
                    sender_address,
                    recipient_address,
                    amount,
                    keyless_info
                )
            else:
                return {
                    'success': False,
                    'error': f'Unsupported token type: {token_type}'
                }
            
            logger.info(
                f"Executed Aptos transaction: {amount} {token_type} "
                f"from {sender_address[:16]}... to {recipient_address[:16]}... "
                f"Success: {result.get('success', False)}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing Aptos transaction: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @classmethod
    async def _estimate_gas_cost(cls, token_type: str) -> Dict[str, Any]:
        """Estimate gas cost for a transaction"""
        from blockchain.aptos_sponsor_service import AptosSponsorService
        
        # Use transfer type for estimation
        return await AptosSponsorService.estimate_sponsorship_cost('transfer', {})
    
    @classmethod
    async def get_token_balance(
        cls,
        account: 'Account',
        token_type: str
    ) -> Decimal:
        """
        Get token balance for an account.
        
        Args:
            account: Account model instance
            token_type: Token type ('CUSD', 'CONFIO', etc.)
            
        Returns:
            Balance as Decimal
        """
        try:
            from blockchain.aptos_balance_service import AptosBalanceService
            
            # Get all balances and extract the requested token
            balances = AptosBalanceService.get_all_balances(account, use_cache=True)
            
            token_key = token_type.lower()
            if token_key in balances:
                return balances[token_key]['amount']
            else:
                logger.warning(f"Token type {token_type} not found in balances")
                return Decimal('0')
                
        except Exception as e:
            logger.error(f"Error getting token balance: {e}")
            return Decimal('0')
    
    @classmethod
    def get_supported_tokens(cls) -> list:
        """Get list of supported token types"""
        return ['CUSD', 'CONFIO']


# Async helper function for Django views
def run_async_transaction(coro):
    """Helper to run async transaction methods in Django views"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Example usage:
"""
from blockchain.aptos_transaction_manager import AptosTransactionManager, run_async_transaction

# In a Django view or GraphQL mutation:
result = run_async_transaction(
    AptosTransactionManager.send_tokens(
        sender_account=account,
        recipient_address="0x...",
        amount=Decimal('100.50'),
        token_type='CUSD',
        user_signature=keyless_signature
    )
)
"""