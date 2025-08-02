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
    def get_balances(account: 'Account', verify_critical: bool = False) -> Dict[str, Decimal]:
        """
        Get all token balances for an account using hybrid caching
        
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
        from .balance_service import BalanceService
        
        # Use the hybrid balance service
        all_balances = BalanceService.get_all_balances(
            account,
            verify_critical=verify_critical
        )
        
        # Return simplified format for GraphQL
        return {
            'cusd': all_balances['cusd']['amount'],
            'confio': all_balances['confio']['amount'],
            'sui': all_balances['sui']['amount'],
            'usdc': all_balances['usdc']['amount'],
            # Additional fields available:
            'cusd_available': all_balances['cusd']['available'],
            'cusd_pending': all_balances['cusd']['pending'],
            'last_synced': max(
                b['last_synced'] for b in all_balances.values() 
                if b['last_synced']
            ) if any(b['last_synced'] for b in all_balances.values()) else None
        }
    
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