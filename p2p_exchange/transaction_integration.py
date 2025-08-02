"""
P2P Exchange integration with automatic coin management

This module shows how to integrate the TransactionManager into P2P trading flows.
"""

from decimal import Decimal
from typing import Dict, Optional
from blockchain.transaction_manager import TransactionManager
from blockchain.sui_client import sui_client
import asyncio
import logging

logger = logging.getLogger(__name__)


class P2PTransactionHandler:
    """
    Handles P2P trade transactions with automatic coin management
    """
    
    @TransactionManager.prepare_transaction('CUSD')
    async def create_escrow(
        self,
        seller_account: 'Account',
        trade: 'Trade',
        amount: Decimal
    ) -> str:
        """
        Create escrow for P2P trade with automatic coin preparation.
        
        The @prepare_transaction decorator ensures coins are merged
        if needed before creating the escrow.
        """
        # Access prepared coins
        prepared_coins = seller_account._prepared_coins
        
        logger.info(
            f"Creating escrow for trade {trade.id}: "
            f"{amount} CUSD using {len(prepared_coins['coins'])} coins"
        )
        
        # Build escrow creation transaction
        tx_data = {
            "packageObjectId": "0x2",  # Would be P2P_TRADE_PACKAGE_ID
            "module": "escrow",
            "function": "create_escrow",
            "typeArguments": [f"{settings.CUSD_PACKAGE_ID}::cusd::CUSD"],
            "arguments": [
                prepared_coins['primary_coin']['objectId'],
                int(amount * Decimal(10 ** 6)),  # Convert to smallest unit
                trade.buyer.sui_address,
                trade.id  # Trade reference
            ],
            "gasBudget": "100000000"
        }
        
        # In production: sign with zkLogin and submit
        # For now, return mock escrow ID
        return f"escrow_{trade.id}"
    
    @TransactionManager.prepare_transaction('CONFIO')
    async def pay_with_confio(
        self,
        payer_account: 'Account',
        recipient_address: str,
        amount: Decimal,
        payment_reference: str = None
    ) -> str:
        """
        Pay using CONFIO tokens with 0.9% fee.
        
        Automatically handles coin selection and merging.
        """
        prepared_coins = payer_account._prepared_coins
        
        # Calculate fee (0.9%)
        fee_amount = amount * Decimal('0.009')
        total_amount = amount + fee_amount
        
        logger.info(
            f"Paying {amount} CONFIO (fee: {fee_amount}) "
            f"using {len(prepared_coins['coins'])} coins"
        )
        
        # Use Pay contract for fee collection
        tx_data = {
            "packageObjectId": settings.PAY_PACKAGE_ID,
            "module": "pay",
            "function": "pay_with_confio",
            "typeArguments": [],
            "arguments": [
                prepared_coins['primary_coin']['objectId'],
                int(total_amount * Decimal(10 ** 9)),  # 9 decimals for CONFIO
                recipient_address,
                payment_reference or ""
            ],
            "gasBudget": "50000000"
        }
        
        # Return transaction hash
        return f"tx_pay_{payment_reference}"
    
    async def release_escrow(
        self,
        trade: 'Trade',
        escrow_id: str,
        release_to_seller: bool = True
    ) -> str:
        """
        Release escrow funds after trade completion.
        
        No coin preparation needed as escrow already holds the funds.
        """
        recipient = trade.seller.sui_address if release_to_seller else trade.buyer.sui_address
        
        tx_data = {
            "packageObjectId": "0x2",  # Would be P2P_TRADE_PACKAGE_ID
            "module": "escrow",
            "function": "release_escrow",
            "typeArguments": [],
            "arguments": [
                escrow_id,
                recipient,
                trade.id
            ],
            "gasBudget": "50000000"
        }
        
        logger.info(
            f"Releasing escrow {escrow_id} for trade {trade.id} to "
            f"{'seller' if release_to_seller else 'buyer'}"
        )
        
        return f"tx_release_{trade.id}"
    
    async def estimate_trade_gas_cost(
        self,
        seller_account: 'Account',
        amount: Decimal,
        token_type: str = 'CUSD'
    ) -> Dict:
        """
        Estimate gas costs for a P2P trade including coin management.
        """
        # Get transaction cost estimate
        estimate = await TransactionManager.estimate_transaction_cost(
            seller_account,
            token_type,
            amount
        )
        
        # Add P2P specific costs
        escrow_creation_gas = 100000  # Base escrow creation
        escrow_release_gas = 50000    # Base escrow release
        
        total_gas = (
            estimate['gas_estimates']['direct'] +
            escrow_creation_gas +
            escrow_release_gas
        )
        
        total_with_merge = (
            estimate['gas_estimates']['merge_cost'] +
            estimate['gas_estimates']['after_merge'] +
            escrow_creation_gas +
            escrow_release_gas
        )
        
        return {
            'coin_management': estimate,
            'escrow_costs': {
                'creation': escrow_creation_gas,
                'release': escrow_release_gas
            },
            'total_gas': {
                'without_merge': total_gas,
                'with_merge': total_with_merge,
                'recommended': total_with_merge if estimate['needs_merge'] else total_gas
            },
            'recommendation': (
                f"{'Merge and ' if estimate['needs_merge'] else ''}"
                f"create escrow with {estimate['coins_needed']} coin(s)"
            )
        }


# Usage example in GraphQL mutation
async def create_p2p_trade_mutation(
    seller_account: 'Account',
    buyer_sui_address: str,
    amount: Decimal,
    payment_method_id: int
) -> Dict:
    """
    Example GraphQL mutation for creating a P2P trade.
    """
    from p2p_exchange.models import Trade, PaymentMethod
    
    # Create trade record
    trade = Trade.objects.create(
        seller=seller_account,
        buyer_sui_address=buyer_sui_address,
        amount=amount,
        token_type='CUSD',
        payment_method_id=payment_method_id,
        status='pending_escrow'
    )
    
    # Create escrow with automatic coin management
    handler = P2PTransactionHandler()
    
    try:
        escrow_id = await handler.create_escrow(
            seller_account,
            trade,
            amount
        )
        
        # Update trade with escrow ID
        trade.escrow_id = escrow_id
        trade.status = 'escrow_created'
        trade.save()
        
        return {
            'success': True,
            'trade_id': trade.id,
            'escrow_id': escrow_id,
            'message': 'Trade created with escrow'
        }
        
    except Exception as e:
        trade.status = 'failed'
        trade.save()
        
        return {
            'success': False,
            'error': str(e),
            'trade_id': trade.id
        }


# Integration with existing P2P models
def integrate_with_trade_model():
    """
    Example of adding methods to the Trade model for coin management.
    """
    from p2p_exchange.models import Trade
    
    async def prepare_escrow_coins(self):
        """Prepare coins for escrow creation"""
        return await TransactionManager.prepare_coins(
            self.seller,
            self.token_type,
            self.amount,
            merge_if_needed=True
        )
    
    async def estimate_escrow_gas(self):
        """Estimate gas for this trade"""
        handler = P2PTransactionHandler()
        return await handler.estimate_trade_gas_cost(
            self.seller,
            self.amount,
            self.token_type
        )
    
    # Add methods to Trade model
    Trade.prepare_escrow_coins = prepare_escrow_coins
    Trade.estimate_escrow_gas = estimate_escrow_gas