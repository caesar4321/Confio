"""
Sui Coin Management Strategy

On Sui, tokens are represented as individual Coin objects. This module handles:
1. Merging fragmented coins before sending
2. Splitting coins when exact amounts are needed
3. Optimizing gas usage by selecting appropriate coins
"""

import asyncio
from typing import List, Dict, Optional
from decimal import Decimal
from blockchain.sui_client import sui_client
import logging

logger = logging.getLogger(__name__)


class CoinManager:
    """
    Manages coin objects for efficient transactions.
    
    Philosophy: Lazy merging - only merge when necessary, not preemptively.
    Gas costs scale with coin count, so merging 100 coins is expensive.
    """
    
    @staticmethod
    async def get_coin_objects(address: str, coin_type: str) -> List[Dict]:
        """
        Get all coin objects of a specific type owned by an address
        
        Returns list of coin objects with format:
        {
            'objectId': '0x...',
            'balance': '1000000',  # Raw amount
            'version': '123',
            'digest': '...'
        }
        """
        # Get owned objects of the coin type
        result = await sui_client._make_rpc_call(
            "suix_getOwnedObjects",
            [
                address,
                {
                    "filter": {
                        "StructType": f"0x2::coin::Coin<{coin_type}>"
                    },
                    "options": {
                        "showType": True,
                        "showContent": True
                    }
                }
            ]
        )
        
        coins = []
        for obj in result.get('data', []):
            if obj['data']['content']['dataType'] == 'moveObject':
                coins.append({
                    'objectId': obj['data']['objectId'],
                    'balance': obj['data']['content']['fields']['balance'],
                    'version': obj['data']['version'],
                    'digest': obj['data']['digest']
                })
        
        # Sort by balance descending for optimal selection
        coins.sort(key=lambda x: int(x['balance']), reverse=True)
        return coins
    
    @staticmethod
    async def select_coins_for_amount(
        address: str, 
        coin_type: str, 
        amount: Decimal,
        decimals: int = 9
    ) -> List[Dict]:
        """
        Select optimal coin objects to cover the requested amount
        
        Strategy:
        1. Try to find a single coin that covers the amount
        2. If not, use minimum number of coins
        3. Leave some coins unmerged for gas payments
        """
        amount_raw = int(amount * Decimal(10 ** decimals))
        coins = await CoinManager.get_coin_objects(address, coin_type)
        
        if not coins:
            raise ValueError(f"No {coin_type} coins found for {address}")
        
        # Check if any single coin covers the amount
        for coin in coins:
            if int(coin['balance']) >= amount_raw:
                return [coin]
        
        # Otherwise, select minimum coins to cover amount
        selected = []
        total = 0
        
        for coin in coins:
            selected.append(coin)
            total += int(coin['balance'])
            if total >= amount_raw:
                break
        
        if total < amount_raw:
            raise ValueError(
                f"Insufficient balance. Need {amount_raw}, have {total}"
            )
        
        return selected
    
    @staticmethod
    async def should_merge_for_transaction(
        coins_needed: List[Dict],
        total_coins: int
    ) -> bool:
        """
        Determine if merging is worthwhile for this transaction.
        
        Only merge if:
        - Need more than 10 coins for the transaction
        - Would significantly reduce transaction complexity
        """
        return len(coins_needed) > 10
    
    @staticmethod
    async def merge_coins(
        address: str,
        coin_type: str,
        coins_to_merge: List[Dict],
        private_key: str = None  # In production, use zkLogin
    ) -> Optional[str]:
        """
        Merge specific coin objects. Only called when necessary.
        
        This is NOT called preemptively - only when a transaction
        needs many coins and merging would save gas overall.
        """
        if len(coins_to_merge) < 2:
            return None
        
        # Build merge transaction
        primary_coin = coins_to_merge[0]
        coins_to_merge_into = coins_to_merge[1:]
        
        # Calculate gas cost estimate
        merge_gas_cost = len(coins_to_merge) * 50000  # Rough estimate
        
        logger.info(
            f"Merging {len(coins_to_merge)} coins into 1. "
            f"Estimated gas: {merge_gas_cost / 1e9:.4f} SUI"
        )
        
        tx_data = {
            "packageObjectId": "0x2",
            "module": "pay",
            "function": "join_vec",
            "typeArguments": [coin_type],
            "arguments": [
                primary_coin['objectId'],
                [coin['objectId'] for coin in coins_to_merge_into]
            ],
            "gasBudget": merge_gas_cost + 1000000  # Add buffer
        }
        
        # In production, sign with zkLogin
        return "merge_tx_placeholder"
    
    @staticmethod
    async def prepare_exact_amount(
        address: str,
        coin_type: str,
        amount: Decimal,
        decimals: int = 9,
        private_key: str = None  # In production, use zkLogin
    ) -> str:
        """
        Prepare a coin object with exact amount needed
        
        Returns the coin object ID that has exactly the amount needed
        """
        amount_raw = int(amount * Decimal(10 ** decimals))
        coins = await CoinManager.select_coins_for_amount(
            address, coin_type, amount, decimals
        )
        
        # If we have exactly one coin with the right amount, use it
        if len(coins) == 1 and int(coins[0]['balance']) == amount_raw:
            return coins[0]['objectId']
        
        # Otherwise, we need to split or merge+split
        primary_coin = coins[0]
        
        if len(coins) > 1:
            # First merge the coins
            # In production, implement actual merge
            logger.info(f"Would merge {len(coins)} coins first")
        
        if int(primary_coin['balance']) > amount_raw:
            # Split the coin to get exact amount
            # In production, implement actual split
            logger.info(
                f"Would split coin {primary_coin['objectId']} "
                f"to get {amount_raw} from {primary_coin['balance']}"
            )
        
        return primary_coin['objectId']


class CoinOptimizer:
    """
    Background coin optimization - runs only during low activity.
    
    Philosophy: Don't optimize prematurely. Only merge when:
    1. User has excessive fragmentation (>20 coins)
    2. During low-activity periods
    3. Gas prices are favorable
    """
    
    @staticmethod
    async def should_optimize(account: 'Account', coin_count: int) -> bool:
        """Only optimize if really fragmented"""
        return coin_count > 20  # Much higher threshold
    
    @staticmethod
    async def optimize_account_coins(account: 'Account'):
        """
        Light-touch optimization during low activity periods.
        
        Only merges excessive fragmentation, keeping 5-10 coins
        for optimal parallel operations.
        """
        from blockchain.blockchain_settings import CUSD_PACKAGE_ID, CONFIO_PACKAGE_ID
        
        coin_types = [
            (f"{CUSD_PACKAGE_ID}::cusd::CUSD", "CUSD", 6),
            (f"{CONFIO_PACKAGE_ID}::confio::CONFIO", "CONFIO", 9),
        ]
        
        for coin_type, name, decimals in coin_types:
            try:
                coins = await CoinManager.get_coin_objects(
                    account.sui_address, 
                    coin_type
                )
                
                if len(coins) > 5:  # Threshold for optimization
                    logger.info(
                        f"Account {account.id} has {len(coins)} {name} coins. "
                        f"Consider merging for efficiency."
                    )
                    
                    # In production, could auto-merge here
                    # await CoinManager.merge_coins(...)
                
            except Exception as e:
                logger.error(
                    f"Error checking {name} coins for account {account.id}: {e}"
                )


# Usage examples:
"""
# Get coin objects for an address
coins = await CoinManager.get_coin_objects(
    address="0x...",
    coin_type="0x...::cusd::CUSD"
)

# Select coins to send 5 CUSD
selected_coins = await CoinManager.select_coins_for_amount(
    address="0x...",
    coin_type="0x...::cusd::CUSD",
    amount=Decimal('5'),
    decimals=6
)

# Prepare exact amount for payment
coin_id = await CoinManager.prepare_exact_amount(
    address="0x...",
    coin_type="0x...::cusd::CUSD",
    amount=Decimal('5'),
    decimals=6
)
"""