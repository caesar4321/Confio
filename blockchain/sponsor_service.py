"""
Sponsored Transaction Service

Handles gas sponsorship for all user transactions so they don't need SUI tokens.
Uses a sponsor account to pay for gas fees on behalf of users.
"""

import asyncio
from typing import Dict, Optional, Any, List
from decimal import Decimal
from django.conf import settings
from django.core.cache import cache
from blockchain.sui_client import sui_client
import logging
import json

logger = logging.getLogger(__name__)


class SponsorService:
    """
    Manages sponsored transactions for gas-free user experience.
    
    Architecture:
    1. User signs transaction with zkLogin
    2. Transaction sent to sponsor service
    3. Sponsor wraps transaction and pays gas
    4. Sponsored transaction submitted to blockchain
    """
    
    # Cache keys
    SPONSOR_BALANCE_KEY = "sponsor:balance"
    SPONSOR_NONCE_KEY = "sponsor:nonce"
    SPONSOR_STATS_KEY = "sponsor:stats"
    
    # Thresholds
    MIN_SPONSOR_BALANCE = Decimal('0.1')  # Minimum 0.1 SUI to operate (lowered for testing)
    WARNING_THRESHOLD = Decimal('0.5')    # Warn when below 0.5 SUI
    MAX_GAS_PER_TX = 100000000           # Max 0.1 SUI per transaction
    
    @classmethod
    async def check_sponsor_health(cls) -> Dict[str, Any]:
        """
        Check sponsor account health and balance.
        
        Returns:
            Dict with health status, balance, and recommendations
        """
        try:
            # Get sponsor address from settings
            sponsor_address = getattr(settings, 'SPONSOR_ADDRESS', None)
            if not sponsor_address:
                return {
                    'healthy': False,
                    'error': 'SPONSOR_ADDRESS not configured',
                    'balance': Decimal('0'),
                    'can_sponsor': False
                }
            
            # Check cached balance first
            cached_balance = cache.get(cls.SPONSOR_BALANCE_KEY)
            if cached_balance is None:
                # Get fresh balance from blockchain
                balance = await sui_client.get_sui_balance(sponsor_address)
                cache.set(cls.SPONSOR_BALANCE_KEY, balance, timeout=60)  # Cache for 1 minute
            else:
                balance = cached_balance
            
            # Get stats
            stats = cache.get(cls.SPONSOR_STATS_KEY, {
                'total_sponsored': 0,
                'total_gas_spent': 0,
                'failed_transactions': 0
            })
            
            # Determine health
            healthy = balance > cls.MIN_SPONSOR_BALANCE
            warning = balance < cls.WARNING_THRESHOLD
            
            return {
                'healthy': healthy,
                'warning': warning,
                'balance': balance,
                'balance_formatted': f"{balance} SUI",
                'can_sponsor': healthy,
                'estimated_transactions': int(balance / Decimal('0.1')) if healthy else 0,
                'stats': stats,
                'recommendations': cls._get_recommendations(balance)
            }
            
        except Exception as e:
            logger.error(f"Error checking sponsor health: {e}")
            return {
                'healthy': False,
                'error': str(e),
                'balance': Decimal('0'),
                'can_sponsor': False
            }
    
    @classmethod
    def _get_recommendations(cls, balance: Decimal) -> List[str]:
        """Get recommendations based on balance"""
        recommendations = []
        
        if balance < cls.MIN_SPONSOR_BALANCE:
            recommendations.append(f"URGENT: Refill sponsor account. Need at least {cls.MIN_SPONSOR_BALANCE} SUI")
        elif balance < cls.WARNING_THRESHOLD:
            recommendations.append(f"WARNING: Low balance. Consider refilling to maintain service")
        
        if balance > Decimal('1000'):
            recommendations.append("Consider implementing multi-sponsor setup for redundancy")
        
        return recommendations
    
    @classmethod
    async def create_sponsored_transaction(
        cls,
        user_address: str,
        transaction_data: Dict[str, Any],
        user_signature: Optional[str] = None,
        zklogin_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a sponsored transaction.
        
        Args:
            user_address: Address of the user making the transaction
            transaction_data: The transaction to sponsor
            user_signature: zkLogin signature from the user (optional for some tx types)
            
        Returns:
            Dict with transaction result or error
        """
        try:
            # Log zkLogin info if available
            if zklogin_info:
                logger.info(
                    f"Creating sponsored transaction with zkLogin. "
                    f"Account: {zklogin_info.get('account_id')}, "
                    f"Proof: {zklogin_info.get('proof_id')}"
                )
            
            # Check sponsor health
            health = await cls.check_sponsor_health()
            if not health['can_sponsor']:
                return {
                    'success': False,
                    'error': 'Sponsor service unavailable',
                    'details': health
                }
            
            # Validate gas budget
            gas_budget = transaction_data.get('gasBudget', cls.MAX_GAS_PER_TX)
            if gas_budget > cls.MAX_GAS_PER_TX:
                return {
                    'success': False,
                    'error': f'Gas budget too high. Max: {cls.MAX_GAS_PER_TX}'
                }
            
            # Build sponsored transaction
            sponsor_address = settings.SPONSOR_ADDRESS
            
            # Create the sponsored transaction structure
            sponsored_tx = {
                "sender": user_address,
                "sponsor": sponsor_address,
                "gasBudget": str(gas_budget),
                "gasPrice": "1000",  # Current testnet price
                "transactionData": transaction_data,
                "sponsorSignature": None  # Will be added after signing
            }
            
            # Log transaction details
            logger.info(
                f"Creating sponsored transaction: "
                f"User: {user_address[:16]}..., "
                f"Type: {transaction_data.get('function', 'unknown')}, "
                f"Gas: {gas_budget}"
            )
            
            # Build the transaction block
            from blockchain.sui_client import SuiClient
            client = SuiClient()
            
            # Create transaction block for sponsored transaction
            tx_block = {
                "sender": user_address,
                "expiration": None,  # No expiration
                "gasData": {
                    "payment": [],  # Sponsor will pay
                    "owner": sponsor_address,
                    "price": "1000",
                    "budget": str(gas_budget)
                },
                "transactions": [transaction_data]
            }
            
            # Implementation for actual blockchain submission
            # NOTE: This requires sponsor private key to be configured
            
            sponsor_private_key = getattr(settings, 'SPONSOR_PRIVATE_KEY', None)
            
            if sponsor_private_key:
                # PRODUCTION PATH: Real blockchain submission
                try:
                    # Use simplified transaction execution
                    from blockchain.simple_transaction import SimpleTransaction
                    
                    logger.info(f"Executing sponsored transaction via simplified method")
                    
                    result = await SimpleTransaction.execute_with_sponsor(
                        user_address,
                        transaction_data,
                        sponsor_address,
                        sponsor_private_key,
                        None,  # prepared_coins - not used in simplified approach
                        zklogin_info  # Pass zkLogin info if available
                    )
                    
                    if result['success']:
                        logger.info(f"Transaction executed: {result.get('digest')}")
                        
                        # Update stats
                        await cls._update_sponsor_stats(gas_budget)
                        
                        return {
                            'success': True,
                            'digest': result.get('digest'),
                            'sponsored': True,
                            'gas_saved': gas_budget / 1e9,
                            'sponsor': sponsor_address,
                            'warning': result.get('warning')
                        }
                    else:
                        raise Exception(result.get('error', 'Unknown error'))
                    
                except Exception as e:
                    logger.error(f"Failed to submit transaction: {e}")
                    logger.exception("Full error trace:")
                    return {
                        'success': False,
                        'error': f'Transaction submission failed: {str(e)}'
                    }
            else:
                # DEVELOPMENT PATH: Mock transaction
                import hashlib
                import time
                tx_content = f"{user_address}_{transaction_data.get('function', 'tx')}_{time.time()}"
                tx_digest = f"mock_{hashlib.sha256(tx_content.encode()).hexdigest()[:32]}"
                
                logger.warning(
                    f"MOCK TRANSACTION: SPONSOR_PRIVATE_KEY not configured. "
                    f"Mock digest: {tx_digest}"
                )
                
                # Update stats
                await cls._update_sponsor_stats(gas_budget)
                
                return {
                    'success': True,
                    'digest': tx_digest,
                    'sponsored': True,
                    'gas_saved': gas_budget / 1e9,  # Convert to SUI
                    'sponsor': sponsor_address,
                    'warning': 'Transaction not submitted to blockchain (SPONSOR_PRIVATE_KEY not configured)'
                }
            
        except Exception as e:
            logger.error(f"Error creating sponsored transaction: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @classmethod
    async def _update_sponsor_stats(cls, gas_used: int):
        """Update sponsor statistics"""
        stats = cache.get(cls.SPONSOR_STATS_KEY, {
            'total_sponsored': 0,
            'total_gas_spent': 0,
            'failed_transactions': 0
        })
        
        stats['total_sponsored'] += 1
        stats['total_gas_spent'] += gas_used
        
        cache.set(cls.SPONSOR_STATS_KEY, stats, timeout=86400)  # 24 hours
        
        # Invalidate balance cache to force refresh
        cache.delete(cls.SPONSOR_BALANCE_KEY)
    
    @classmethod
    async def sponsor_transaction_with_coins(
        cls,
        account: 'Account',
        transaction_type: str,
        prepared_coins: Dict[str, Any],
        transaction_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sponsor a transaction that uses prepared coins.
        
        This integrates with TransactionManager to handle coin-based transactions.
        
        Args:
            account: User's account
            transaction_type: Type of transaction (send, pay, trade, etc.)
            prepared_coins: Coins prepared by TransactionManager
            transaction_params: Additional transaction parameters
            
        Returns:
            Dict with transaction result
        """
        try:
            # Build transaction based on type
            if transaction_type == 'send':
                tx_data = cls._build_send_transaction(
                    account.sui_address,
                    prepared_coins,
                    transaction_params
                )
            elif transaction_type == 'pay':
                tx_data = cls._build_pay_transaction(
                    account.sui_address,
                    prepared_coins,
                    transaction_params
                )
            elif transaction_type == 'trade':
                tx_data = cls._build_trade_transaction(
                    account.sui_address,
                    prepared_coins,
                    transaction_params
                )
            else:
                raise ValueError(f"Unknown transaction type: {transaction_type}")
            
            # Check for zkLogin availability
            zklogin_info = None
            if transaction_params.get('zklogin_available'):
                zklogin_info = {
                    'available': True,
                    'proof_id': transaction_params.get('proof_id'),
                    'account_id': str(account.id)
                }
                logger.info(
                    f"zkLogin available for {transaction_type} transaction. "
                    f"Proof ID: {zklogin_info['proof_id']}"
                )
            
            # Create sponsored transaction
            result = await cls.create_sponsored_transaction(
                account.sui_address,
                tx_data,
                transaction_params.get('user_signature'),
                zklogin_info
            )
            
            if result['success']:
                logger.info(
                    f"Successfully sponsored {transaction_type} transaction "
                    f"for {account.id}. Digest: {result['digest']}"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error sponsoring transaction with coins: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @classmethod
    def _build_send_transaction(
        cls,
        sender: str,
        prepared_coins: Dict[str, Any],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build a send/transfer transaction"""
        recipient = params['recipient']
        amount = params['amount']
        token_type = params['token_type']
        
        # Determine coin type and decimals
        if token_type == 'CUSD':
            coin_type = f"{settings.CUSD_PACKAGE_ID}::cusd::CUSD"
            decimals = 6
        elif token_type == 'CONFIO':
            coin_type = f"{settings.CONFIO_PACKAGE_ID}::confio::CONFIO"
            decimals = 9
        else:
            raise ValueError(f"Unsupported token type: {token_type}")
        
        amount_units = int(amount * Decimal(10 ** decimals))
        
        
        # If single coin, use split_and_transfer
        if len(prepared_coins['coins']) == 1:
            return {
                "packageObjectId": "0x2",
                "module": "pay",
                "function": "split_and_transfer",
                "typeArguments": [coin_type],
                "arguments": [
                    prepared_coins['primary_coin']['objectId'],
                    str(amount_units),
                    recipient
                ]
            }
        else:
            # Multiple coins - use join_vec_and_transfer
            coin_ids = [coin['objectId'] for coin in prepared_coins['coins']]
            return {
                "packageObjectId": "0x2",
                "module": "pay",
                "function": "join_vec_and_transfer",
                "typeArguments": [coin_type],
                "arguments": [
                    coin_ids,
                    recipient
                ]
            }
    
    @classmethod
    def _build_pay_transaction(
        cls,
        payer: str,
        prepared_coins: Dict[str, Any],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build a pay transaction (with 0.9% fee)"""
        recipient = params['recipient']
        amount = params['amount']
        token_type = params['token_type']
        reference = params.get('reference', '')
        
        # Calculate fee
        fee_amount = amount * Decimal('0.009')
        total_amount = amount + fee_amount
        
        if token_type == 'CUSD':
            function = "pay_with_cusd"
            decimals = 6
        else:
            function = "pay_with_confio"
            decimals = 9
        
        amount_units = int(total_amount * Decimal(10 ** decimals))
        
        return {
            "packageObjectId": settings.PAY_PACKAGE_ID,
            "module": "pay",
            "function": function,
            "typeArguments": [],
            "arguments": [
                settings.FEE_COLLECTOR_OBJECT_ID,
                prepared_coins['primary_coin']['objectId'],
                str(amount_units),
                recipient,
                reference
            ]
        }
    
    @classmethod
    def _build_trade_transaction(
        cls,
        seller: str,
        prepared_coins: Dict[str, Any],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build a P2P trade escrow transaction"""
        buyer = params['buyer']
        amount = params['amount']
        token_type = params['token_type']
        trade_id = params['trade_id']
        
        if token_type == 'CUSD':
            coin_type = f"{settings.CUSD_PACKAGE_ID}::cusd::CUSD"
            decimals = 6
        else:
            raise ValueError("Only CUSD supported for P2P trades currently")
        
        amount_units = int(amount * Decimal(10 ** decimals))
        
        return {
            "packageObjectId": settings.P2P_TRADE_PACKAGE_ID,
            "module": "escrow",
            "function": "create_escrow",
            "typeArguments": [coin_type],
            "arguments": [
                prepared_coins['primary_coin']['objectId'],
                str(amount_units),
                buyer,
                trade_id
            ]
        }
    
    @classmethod
    async def estimate_sponsorship_cost(
        cls,
        transaction_type: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Estimate the gas cost for sponsoring a transaction.
        
        Returns estimated gas cost and sponsor availability.
        """
        # Base gas costs by transaction type
        base_costs = {
            'send': 50000000,      # 0.05 SUI
            'pay': 70000000,       # 0.07 SUI (includes fee logic)
            'trade': 100000000,    # 0.10 SUI (escrow creation)
            'merge': 50000000,     # 0.05 SUI per coin
            'custom': 80000000     # 0.08 SUI default
        }
        
        base_cost = base_costs.get(transaction_type, base_costs['custom'])
        
        # Adjust for coin count if provided
        coin_count = params.get('coin_count', 1)
        if coin_count > 1 and transaction_type in ['send', 'pay']:
            # Add cost for handling multiple coins
            base_cost += (coin_count - 1) * 10000000  # 0.01 SUI per extra coin
        
        # Check sponsor availability
        health = await cls.check_sponsor_health()
        
        return {
            'estimated_gas': base_cost,
            'estimated_gas_sui': base_cost / 1e9,
            'sponsor_available': health['can_sponsor'],
            'sponsor_balance': health['balance'],
            'can_afford': health['balance'] > Decimal(base_cost / 1e9),
            'transaction_type': transaction_type
        }


# Management command helper
async def test_sponsor_service():
    """Test sponsor service functionality"""
    # Check health
    health = await SponsorService.check_sponsor_health()
    print(f"Sponsor Health: {json.dumps(health, indent=2, default=str)}")
    
    # Estimate costs
    estimates = {}
    for tx_type in ['send', 'pay', 'trade']:
        estimate = await SponsorService.estimate_sponsorship_cost(
            tx_type,
            {'coin_count': 3}
        )
        estimates[tx_type] = estimate
    
    print(f"\nGas Estimates: {json.dumps(estimates, indent=2, default=str)}")
    
    # Test sponsored transaction
    test_tx = {
        "packageObjectId": "0x2",
        "module": "pay",
        "function": "split",
        "typeArguments": ["0x2::sui::SUI"],
        "arguments": ["0xtest", "1000000", "0xrecipient"]
    }
    
    result = await SponsorService.create_sponsored_transaction(
        "0xuser123",
        test_tx
    )
    
    print(f"\nTest Transaction Result: {json.dumps(result, indent=2, default=str)}")


# Example usage in GraphQL mutation
"""
from blockchain.sponsor_service import SponsorService
from blockchain.transaction_manager import TransactionManager

async def send_payment_mutation(account, recipient, amount, token_type):
    # Prepare coins
    prepared = await TransactionManager.prepare_coins(
        account,
        token_type,
        amount,
        merge_if_needed=True
    )
    
    # Create sponsored transaction
    result = await SponsorService.sponsor_transaction_with_coins(
        account,
        'send',
        prepared,
        {
            'recipient': recipient,
            'amount': amount,
            'token_type': token_type,
            'user_signature': await get_zklogin_signature(account)
        }
    )
    
    return {
        'success': result['success'],
        'transactionDigest': result.get('digest'),
        'error': result.get('error'),
        'gasSaved': result.get('gas_saved', 0)
    }
"""