"""
Transaction Manager using pysui SDK
Handles blockchain transactions with production-ready coin management
"""

import asyncio
from typing import Dict, List, Optional, Any
from decimal import Decimal
from django.conf import settings
from blockchain.pysui_client import get_pysui_client
from blockchain.sponsor_service_pysui import sponsor_transaction_pysui
from blockchain.balance_service import BalanceService
from users.models import Account
import logging

logger = logging.getLogger(__name__)


class TransactionManagerPySui:
    """
    Production transaction manager using pysui SDK
    """
    
    # Token configurations
    TOKEN_CONFIGS = {
        'CUSD': {
            'package_id': settings.CUSD_PACKAGE_ID,
            'type': f"{settings.CUSD_PACKAGE_ID}::cusd::CUSD",
            'decimals': 6,
            'merge_threshold': 10,  # Merge if need >10 coins
        },
        'CONFIO': {
            'package_id': settings.CONFIO_PACKAGE_ID,
            'type': f"{settings.CONFIO_PACKAGE_ID}::confio::CONFIO",
            'decimals': 9,
            'merge_threshold': 10,
        },
        'SUI': {
            'package_id': '0x2',
            'type': '0x2::sui::SUI',
            'decimals': 9,
            'merge_threshold': 10,
        }
    }
    
    @classmethod
    async def send_tokens(
        cls,
        sender_account: Account,
        recipient_address: str,
        amount: Decimal,
        token_type: str,
        user_signature: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send tokens from one account to another using sponsored transactions
        
        Args:
            sender_account: The sending account
            recipient_address: Recipient's Sui address
            amount: Amount to send
            token_type: Token type (CUSD, CONFIO, etc.)
            user_signature: Optional user signature (for zkLogin)
            
        Returns:
            Dict with transaction result
        """
        try:
            # Validate token type
            if token_type not in cls.TOKEN_CONFIGS:
                return {
                    'success': False,
                    'error': f'Unsupported token type: {token_type}'
                }
            
            # Validate amount
            if amount <= 0:
                return {
                    'success': False,
                    'error': 'Amount must be positive'
                }
            
            # Check balance
            current_balance = await cls.get_token_balance(sender_account, token_type)
            if current_balance < amount:
                return {
                    'success': False,
                    'error': f'Insufficient balance. Available: {current_balance} {token_type}'
                }
            
            # Use sponsor service to handle the transaction
            result = await sponsor_transaction_pysui(
                account=sender_account,
                transaction_type='send',
                params={
                    'recipient': recipient_address,
                    'amount': amount,
                    'token_type': token_type,
                    'user_signature': user_signature
                }
            )
            
            # Update cached balance on success
            if result.get('success'):
                await cls.invalidate_balance_cache(sender_account, token_type)
                
                # Log successful transaction
                logger.info(
                    f"Successful send: {amount} {token_type} "
                    f"from {sender_account.algorand_address[:16]}... "
                    f"to {recipient_address[:16]}... "
                    f"Digest: {result.get('digest', 'N/A')}"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error in send_tokens: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @classmethod
    async def get_token_balance(cls, account: Account, token_type: str) -> Decimal:
        """
        Get current token balance for an account
        
        Args:
            account: The Account instance
            token_type: Token type (CUSD, CONFIO, etc.)
            
        Returns:
            Current balance as Decimal
        """
        try:
            if token_type not in cls.TOKEN_CONFIGS:
                return Decimal('0')
            
            async with await get_pysui_client() as client:
                if token_type == 'CUSD':
                    return await client.get_cusd_balance(account.algorand_address)
                elif token_type == 'CONFIO':
                    return await client.get_confio_balance(account.algorand_address)
                elif token_type == 'SUI':
                    return await client.get_sui_balance(account.algorand_address)
                else:
                    # Generic token balance
                    coin_type = cls.TOKEN_CONFIGS[token_type]['type']
                    balances = await client.get_balance(account.algorand_address, coin_type)
                    return balances.get(coin_type, Decimal('0'))
                    
        except Exception as e:
            logger.error(f"Error getting {token_type} balance for {account.algorand_address}: {e}")
            return Decimal('0')
    
    @classmethod
    async def get_all_balances(cls, account: Account) -> Dict[str, Decimal]:
        """
        Get all token balances for an account
        
        Args:
            account: The Account instance
            
        Returns:
            Dict of token_type -> balance
        """
        try:
            balances = {}
            
            async with await get_pysui_client() as client:
                # Get all balances from blockchain
                all_balances = await client.get_balance(account.algorand_address)
                
                # Map to our token types
                for token_type, config in cls.TOKEN_CONFIGS.items():
                    coin_type = config['type']
                    balances[token_type] = all_balances.get(coin_type, Decimal('0'))
            
            return balances
            
        except Exception as e:
            logger.error(f"Error getting all balances for {account.algorand_address}: {e}")
            return {token_type: Decimal('0') for token_type in cls.TOKEN_CONFIGS.keys()}
    
    @classmethod
    async def prepare_coins_for_transaction(
        cls,
        account: Account,
        token_type: str,
        amount: Decimal
    ) -> Dict[str, Any]:
        """
        Prepare coins for a transaction
        
        Args:
            account: The Account instance
            token_type: Token type (CUSD, CONFIO, etc.)
            amount: Amount needed for transaction
            
        Returns:
            Dict with prepared coins information
        """
        try:
            if token_type not in cls.TOKEN_CONFIGS:
                return {
                    'success': False,
                    'error': f'Unsupported token type: {token_type}'
                }
            
            config = cls.TOKEN_CONFIGS[token_type]
            coin_type = config['type']
            
            async with await get_pysui_client() as client:
                # Get available coins
                coins = await client.get_coins(
                    address=account.algorand_address,
                    coin_type=coin_type,
                    limit=20  # Get up to 20 coins
                )
                
                if not coins:
                    return {
                        'success': False,
                        'error': f'No {token_type} coins found'
                    }
                
                # Calculate total available
                total_available = sum(Decimal(coin['balance']) for coin in coins)
                amount_units = int(amount * Decimal(10 ** config['decimals']))
                
                if total_available < amount_units:
                    available_decimal = total_available / Decimal(10 ** config['decimals'])
                    return {
                        'success': False,
                        'error': f'Insufficient balance. Available: {available_decimal} {token_type}'
                    }
                
                # Select coins for transaction
                selected_coins = []
                running_total = 0
                
                # Sort coins by balance (largest first)
                sorted_coins = sorted(coins, key=lambda x: int(x['balance']), reverse=True)
                
                for coin in sorted_coins:
                    selected_coins.append(coin)
                    running_total += int(coin['balance'])
                    
                    if running_total >= amount_units:
                        break
                
                return {
                    'success': True,
                    'coins': selected_coins,
                    'total_value': running_total,
                    'coin_count': len(selected_coins),
                    'needs_merge': len(selected_coins) > 1
                }
                
        except Exception as e:
            logger.error(f"Error preparing coins for {token_type} transaction: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @classmethod
    async def estimate_transaction_cost(
        cls,
        transaction_type: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Estimate the cost of a transaction
        
        Args:
            transaction_type: Type of transaction (send, pay, trade, etc.)
            params: Transaction parameters
            
        Returns:
            Dict with cost estimation
        """
        try:
            # Import sponsor service for estimation
            from blockchain.sponsor_service_pysui import SponsorServicePySui
            
            return await SponsorServicePySui.estimate_gas_cost(
                transaction_type=transaction_type,
                params=params
            )
            
        except Exception as e:
            logger.error(f"Error estimating transaction cost: {e}")
            return {
                'estimated_gas': 50000000,  # Default 0.05 SUI
                'estimated_gas_sui': 0.05,
                'sponsor_available': False,
                'error': str(e)
            }
    
    @classmethod
    async def get_transaction_history(
        cls,
        account: Account,
        limit: int = 50,
        cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get transaction history for an account
        
        Args:
            account: The Account instance
            limit: Maximum number of transactions to return
            cursor: Pagination cursor
            
        Returns:
            Dict with transaction history
        """
        try:
            async with await get_pysui_client() as client:
                # This would use client.get_transactions once we implement it
                # For now, return empty history
                return {
                    'success': True,
                    'transactions': [],
                    'has_next_page': False,
                    'next_cursor': None
                }
                
        except Exception as e:
            logger.error(f"Error getting transaction history: {e}")
            return {
                'success': False,
                'error': str(e),
                'transactions': []
            }
    
    @classmethod
    async def invalidate_balance_cache(cls, account: Account, token_type: str):
        """
        Invalidate cached balance for an account
        
        Args:
            account: The Account instance
            token_type: Token type to invalidate
        """
        from django.core.cache import cache
        
        # Invalidate specific token balance
        cache_key = f"balance:{account.algorand_address}:{cls.TOKEN_CONFIGS[token_type]['type']}"
        cache.delete(cache_key)
        
        # Invalidate all balances cache
        cache_key_all = f"balance:{account.algorand_address}:all"
        cache.delete(cache_key_all)
        
        logger.info(f"Invalidated balance cache for {account.algorand_address} {token_type}")
    
    @classmethod
    async def sync_balance_to_database(cls, account: Account):
        """
        Sync blockchain balances to database
        
        Args:
            account: The Account instance
        """
        try:
            # Get fresh balances from blockchain
            balances = await cls.get_all_balances(account)
            
            # Update Balance records
            from blockchain.models import Balance
            
            for token_type, amount in balances.items():
                Balance.objects.update_or_create(
                    account=account,
                    token=token_type,
                    defaults={'amount': amount}
                )
            
            logger.info(f"Synced balances to database for {account.algorand_address}")
            
        except Exception as e:
            logger.error(f"Error syncing balances to database: {e}")


# ===== Backwards Compatibility =====

# Alias for backwards compatibility
TransactionManager = TransactionManagerPySui

# Export the main methods at module level for convenience
send_tokens = TransactionManagerPySui.send_tokens
get_token_balance = TransactionManagerPySui.get_token_balance
get_all_balances = TransactionManagerPySui.get_all_balances