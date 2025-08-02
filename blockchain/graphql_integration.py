"""
GraphQL integration for blockchain operations
"""
import asyncio
from decimal import Decimal
from typing import Dict, List
from blockchain.sui_client import sui_client
from django.core.cache import cache


class BlockchainService:
    """Service layer for GraphQL to interact with blockchain"""
    
    @staticmethod
    def get_balances(sui_address: str) -> Dict[str, Decimal]:
        """
        Get all token balances for an address
        
        Used in GraphQL query:
        query {
            account(id: "xxx") {
                balances {
                    cusd
                    confio
                    sui
                }
            }
        }
        """
        # Use asyncio in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            balances = loop.run_until_complete(
                BlockchainService._get_balances_async(sui_address)
            )
            return balances
        finally:
            loop.close()
    
    @staticmethod
    async def _get_balances_async(sui_address: str) -> Dict[str, Decimal]:
        """Async helper to get balances"""
        # Check cache first
        cache_key = f"balances:{sui_address}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        # Fetch from blockchain
        balances = {
            'cusd': await sui_client.get_cusd_balance(sui_address),
            'confio': await sui_client.get_confio_balance(sui_address),
            'sui': await sui_client.get_sui_balance(sui_address),
        }
        
        # Cache for 30 seconds
        cache.set(cache_key, balances, 30)
        
        return balances
    
    @staticmethod
    def send_cusd(
        from_address: str,
        to_address: str,
        amount: Decimal,
        user_signature: str  # From zkLogin
    ) -> str:
        """
        Send cUSD tokens
        
        Used in GraphQL mutation:
        mutation {
            sendCusd(
                toAddress: "0x123...",
                amount: "100.50"
            ) {
                transactionId
                status
            }
        }
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # In production, this would:
            # 1. Build the transaction
            # 2. Apply user's zkLogin signature
            # 3. Submit to blockchain
            tx_digest = loop.run_until_complete(
                sui_client.transfer_cusd(
                    from_address,
                    to_address,
                    amount
                )
            )
            
            # Clear balance cache
            cache.delete(f"balances:{from_address}")
            cache.delete(f"balances:{to_address}")
            
            return tx_digest
            
        finally:
            loop.close()
    
    @staticmethod
    def get_transaction_history(
        sui_address: str,
        limit: int = 20
    ) -> List[Dict]:
        """
        Get transaction history
        
        Used in GraphQL query:
        query {
            account(id: "xxx") {
                transactions(limit: 20) {
                    id
                    type
                    amount
                    timestamp
                }
            }
        }
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                sui_client.get_transactions(sui_address, limit=limit)
            )
            
            # Transform to GraphQL-friendly format
            transactions = []
            for tx in result.get('data', []):
                transactions.append({
                    'id': tx['digest'],
                    'type': BlockchainService._determine_tx_type(tx),
                    'amount': BlockchainService._extract_amount(tx),
                    'timestamp': tx.get('timestampMs', 0)
                })
            
            return transactions
            
        finally:
            loop.close()
    
    @staticmethod
    def _determine_tx_type(tx_data: Dict) -> str:
        """Determine transaction type from raw data"""
        # Simplified logic - in production would be more sophisticated
        if 'pay' in str(tx_data).lower():
            return 'payment'
        elif 'transfer' in str(tx_data).lower():
            return 'transfer'
        else:
            return 'other'
    
    @staticmethod
    def _extract_amount(tx_data: Dict) -> Decimal:
        """Extract amount from transaction data"""
        # Look for balance changes
        for change in tx_data.get('balanceChanges', []):
            if change.get('coinType') and 'cusd' in change['coinType'].lower():
                amount = abs(Decimal(change.get('amount', 0)))
                return amount / Decimal(10 ** 6)  # cUSD has 6 decimals
        
        return Decimal('0')


# Example GraphQL resolvers using this service:
"""
# In your GraphQL schema:

type Account {
    id: ID!
    suiAddress: String!
    balances: Balances!
    transactions(limit: Int = 20): [Transaction!]!
}

type Balances {
    cusd: Decimal!
    confio: Decimal!
    sui: Decimal!
}

type Transaction {
    id: ID!
    type: String!
    amount: Decimal!
    timestamp: BigInt!
}

# In your resolvers:

def resolve_balances(account, info):
    return BlockchainService.get_balances(account.sui_address)

def resolve_transactions(account, info, limit=20):
    return BlockchainService.get_transaction_history(
        account.sui_address,
        limit=limit
    )
"""