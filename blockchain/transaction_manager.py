"""
Transaction Manager with automatic coin management

Handles pre-transaction coin optimization for all Sui transactions.
Implements lazy merging strategy - only merges when necessary.
"""

import asyncio
from functools import wraps
from typing import Dict, List, Optional, Callable, Any
from decimal import Decimal
from django.conf import settings
from blockchain.coin_management import CoinManager
from blockchain.sui_client import sui_client
from blockchain.blockchain_settings import CUSD_PACKAGE_ID, CONFIO_PACKAGE_ID
import logging

logger = logging.getLogger(__name__)


class TransactionManager:
    """
    Manages all blockchain transactions with automatic coin optimization.
    
    Usage:
    1. As a decorator: @prepare_transaction('CUSD', amount=Decimal('5'))
    2. As a method: TransactionManager.prepare_coins(account, 'CUSD', amount)
    """
    
    # Token configurations
    TOKEN_CONFIGS = {
        'CUSD': {
            'package_id': CUSD_PACKAGE_ID,
            'module': 'cusd',
            'decimals': 6,
            'merge_threshold': 10,  # Merge if need >10 coins
        },
        'CONFIO': {
            'package_id': CONFIO_PACKAGE_ID,
            'module': 'confio',
            'decimals': 9,
            'merge_threshold': 10,
        },
        'USDC': {
            'package_id': '0xa1ec7fc00a6f40db9693ad1415d0c193ad3906494428cf252621037bd7117e29',
            'module': 'coin',
            'decimals': 6,
            'merge_threshold': 10,
        }
    }
    
    @classmethod
    async def prepare_coins(
        cls,
        account: 'Account',
        token_type: str,
        amount: Decimal,
        merge_if_needed: bool = True
    ) -> Dict[str, Any]:
        """
        Prepare coins for a transaction, merging if necessary.
        
        Args:
            account: Account making the transaction
            token_type: Token type (CUSD, CONFIO, USDC)
            amount: Amount to send
            merge_if_needed: Whether to merge coins if threshold exceeded
            
        Returns:
            Dict with:
            - coins: List of coin objects to use
            - needs_merge: Whether merging is recommended
            - merged: Whether coins were actually merged
            - primary_coin: The main coin object to use
        """
        token_config = cls.TOKEN_CONFIGS.get(token_type.upper())
        if not token_config:
            raise ValueError(f"Unknown token type: {token_type}")
        
        # Build full coin type
        coin_type = f"{token_config['package_id']}::{token_config['module']}::{token_type.upper()}"
        
        try:
            # Get all coin objects
            all_coins = await CoinManager.get_coin_objects(
                account.sui_address,
                coin_type
            )
            
            if not all_coins:
                raise ValueError(f"No {token_type} coins found for account {account.id}")
            
            # Select coins for the amount
            selected_coins = await CoinManager.select_coins_for_amount(
                account.sui_address,
                coin_type,
                amount,
                token_config['decimals']
            )
            
            # Check if we should merge
            needs_merge = len(selected_coins) > token_config['merge_threshold']
            merged = False
            primary_coin = selected_coins[0]
            
            if needs_merge and merge_if_needed:
                logger.info(
                    f"Transaction needs {len(selected_coins)} coins. "
                    f"Merging for efficiency (threshold: {token_config['merge_threshold']})"
                )
                
                # Perform merge
                merge_result = await cls._merge_coins_for_transaction(
                    account,
                    coin_type,
                    selected_coins
                )
                
                if merge_result:
                    merged = True
                    primary_coin = merge_result
                    selected_coins = [merge_result]
            
            return {
                'coins': selected_coins,
                'needs_merge': needs_merge,
                'merged': merged,
                'primary_coin': primary_coin,
                'total_coins': len(all_coins),
                'coin_type': coin_type
            }
            
        except Exception as e:
            logger.error(f"Error preparing coins for {token_type}: {e}")
            raise
    
    @classmethod
    async def _merge_coins_for_transaction(
        cls,
        account: 'Account',
        coin_type: str,
        coins_to_merge: List[Dict]
    ) -> Optional[Dict]:
        """
        Merge coins for a transaction using zkLogin.
        
        Returns the merged coin object or None if merge failed.
        """
        try:
            # Build merge transaction
            primary_coin = coins_to_merge[0]
            coins_to_merge_into = coins_to_merge[1:]
            
            # Use Sui's pay module for merging
            tx_data = {
                "packageObjectId": "0x2",
                "module": "pay",
                "function": "join_vec",
                "typeArguments": [coin_type],
                "arguments": [
                    primary_coin['objectId'],
                    [coin['objectId'] for coin in coins_to_merge_into]
                ],
                "gasBudget": str(100000000)  # 0.1 SUI
            }
            
            # In production, this would use zkLogin to sign
            # For now, log the transaction that would be executed
            logger.info(
                f"Would execute merge transaction: "
                f"Merging {len(coins_to_merge)} coins into {primary_coin['objectId']}"
            )
            
            # Return the primary coin that would contain all merged value
            return primary_coin
            
        except Exception as e:
            logger.error(f"Failed to merge coins: {e}")
            return None
    
    @classmethod
    def prepare_transaction(cls, token_type: str, amount: Decimal = None):
        """
        Decorator for methods that perform blockchain transactions.
        
        Usage:
        @TransactionManager.prepare_transaction('CUSD', amount=Decimal('5'))
        async def send_payment(self, account, recipient, amount):
            # Coins are automatically prepared before this method runs
            # Access prepared coins via: self._prepared_coins
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Extract account from arguments
                account = None
                
                # Check if first arg is self/cls
                if args and hasattr(args[0], '__class__'):
                    # Method call - account might be second argument
                    if len(args) > 1 and hasattr(args[1], 'sui_address'):
                        account = args[1]
                    # Or in kwargs
                    elif 'account' in kwargs:
                        account = kwargs['account']
                else:
                    # Function call - account might be first argument
                    if args and hasattr(args[0], 'sui_address'):
                        account = args[0]
                    elif 'account' in kwargs:
                        account = kwargs['account']
                
                if not account:
                    raise ValueError("Account not found in transaction arguments")
                
                # Determine amount
                tx_amount = amount
                if tx_amount is None:
                    # Try to get amount from kwargs or args
                    if 'amount' in kwargs:
                        tx_amount = kwargs['amount']
                    elif len(args) > 2 and isinstance(args[2], (Decimal, int, float)):
                        tx_amount = Decimal(str(args[2]))
                
                if tx_amount is None:
                    raise ValueError("Transaction amount not specified")
                
                # Prepare coins
                prepared = await cls.prepare_coins(
                    account,
                    token_type,
                    tx_amount,
                    merge_if_needed=True
                )
                
                # Inject prepared coins into the function
                if hasattr(args[0], '__class__'):
                    # For class methods, set attribute on instance
                    args[0]._prepared_coins = prepared
                else:
                    # For functions, add to kwargs
                    kwargs['_prepared_coins'] = prepared
                
                # Log transaction preparation
                logger.info(
                    f"Prepared transaction for {tx_amount} {token_type}: "
                    f"Using {len(prepared['coins'])} coins "
                    f"(merged: {prepared['merged']}, total coins: {prepared['total_coins']})"
                )
                
                # Execute the original function
                return await func(*args, **kwargs)
            
            return wrapper
        return decorator
    
    @classmethod
    async def estimate_transaction_cost(
        cls,
        account: 'Account',
        token_type: str,
        amount: Decimal
    ) -> Dict[str, Any]:
        """
        Estimate the cost and complexity of a transaction.
        
        Returns:
            Dict with gas estimates, coin counts, and recommendations
        """
        token_config = cls.TOKEN_CONFIGS.get(token_type.upper())
        if not token_config:
            raise ValueError(f"Unknown token type: {token_type}")
        
        coin_type = f"{token_config['package_id']}::{token_config['module']}::{token_type.upper()}"
        
        # Get coin information
        all_coins = await CoinManager.get_coin_objects(
            account.sui_address,
            coin_type
        )
        
        selected_coins = await CoinManager.select_coins_for_amount(
            account.sui_address,
            coin_type,
            amount,
            token_config['decimals']
        )
        
        # Calculate estimates
        base_gas = 50000  # Base transaction cost
        per_coin_gas = 10000  # Additional gas per coin
        merge_gas_per_coin = 50000  # Gas to merge each coin
        
        direct_gas = base_gas + (len(selected_coins) * per_coin_gas)
        merge_gas = len(selected_coins) * merge_gas_per_coin if len(selected_coins) > 1 else 0
        total_with_merge = merge_gas + base_gas + per_coin_gas  # After merge, only 1 coin
        
        return {
            'token_type': token_type,
            'amount': str(amount),
            'total_coins': len(all_coins),
            'coins_needed': len(selected_coins),
            'needs_merge': len(selected_coins) > token_config['merge_threshold'],
            'gas_estimates': {
                'direct': direct_gas,
                'merge_cost': merge_gas,
                'after_merge': total_with_merge,
                'savings': direct_gas - total_with_merge if merge_gas > 0 else 0
            },
            'recommendation': (
                'Merge recommended' if len(selected_coins) > token_config['merge_threshold']
                else 'Direct send optimal'
            )
        }


# Example usage functions
async def example_send_payment():
    """Example: Send payment with automatic coin preparation"""
    from users.models import Account
    
    @TransactionManager.prepare_transaction('CUSD')
    async def send_cusd(account: Account, recipient: str, amount: Decimal):
        # Coins are automatically prepared and available in _prepared_coins
        coins = account._prepared_coins
        
        print(f"Sending {amount} CUSD using {len(coins['coins'])} coins")
        print(f"Primary coin: {coins['primary_coin']['objectId']}")
        
        # Actual transaction logic here
        # ...
    
    # Usage
    # account = Account.objects.get(id=1)
    # await send_cusd(account, "0xrecipient...", Decimal('5'))


async def example_manual_preparation():
    """Example: Manual coin preparation"""
    from users.models import Account
    
    # account = Account.objects.get(id=1)
    
    # Prepare coins manually
    # prepared = await TransactionManager.prepare_coins(
    #     account,
    #     'CONFIO',
    #     Decimal('100'),
    #     merge_if_needed=True
    # )
    
    # Use prepared coins in transaction
    # ...