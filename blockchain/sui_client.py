"""
Sui blockchain client with support for both testnet and mainnet (QuickNode)
"""
import json
import asyncio
from typing import Dict, List, Optional, Any
from decimal import Decimal
import aiohttp
from django.conf import settings
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)


class SuiClient:
    """
    Abstracted Sui client that can work with both testnet and QuickNode
    """
    
    def __init__(self):
        # Start with testnet, switch to QuickNode for mainnet
        self.rpc_url = settings.SUI_RPC_URL  # https://fullnode.testnet.sui.io:443
        self.ws_url = settings.SUI_WS_URL    # wss://fullnode.testnet.sui.io:443
        self.headers = {}
        
        # QuickNode requires API key headers
        if 'quicknode' in self.rpc_url:
            self.headers = {
                'x-api-key': settings.QUICKNODE_API_KEY,
                'Content-Type': 'application/json'
            }
    
    async def _make_rpc_call(self, method: str, params: List[Any]) -> Dict:
        """Make JSON-RPC call to Sui node"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.rpc_url,
                json=payload,
                headers=self.headers
            ) as response:
                result = await response.json()
                
                if 'error' in result:
                    logger.error(f"RPC error: {result['error']}")
                    raise Exception(f"RPC error: {result['error']}")
                
                return result.get('result')
    
    # ===== Balance Operations =====
    
    async def get_balance(self, address: str, coin_type: Optional[str] = None) -> Dict[str, Decimal]:
        """
        Get token balances for an address
        
        Args:
            address: Sui address
            coin_type: Specific coin type (e.g., "0x2::sui::SUI") or None for all
        
        Returns:
            Dict of coin_type -> balance
        """
        # Check cache first
        cache_key = f"balance:{address}:{coin_type or 'all'}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        params = [address]
        if coin_type:
            params.append(coin_type)
        
        result = await self._make_rpc_call("suix_getBalance", params)
        
        # Parse balances
        balances = {}
        if coin_type:
            # Single coin balance
            balances[coin_type] = Decimal(result['totalBalance']) / Decimal(10 ** 9)  # Assuming 9 decimals
        else:
            # All balances
            for coin_data in result:
                coin_type = coin_data['coinType']
                balance = Decimal(coin_data['totalBalance'])
                
                # Get decimals for proper conversion
                decimals = self._get_coin_decimals(coin_type)
                balances[coin_type] = balance / Decimal(10 ** decimals)
        
        # Cache for 30 seconds
        cache.set(cache_key, balances, 30)
        
        return balances
    
    async def get_cusd_balance(self, address: str) -> Decimal:
        """Get cUSD balance for address"""
        coin_type = f"{settings.CUSD_PACKAGE_ID}::cusd::CUSD"
        balances = await self.get_balance(address, coin_type)
        return balances.get(coin_type, Decimal('0'))
    
    async def get_confio_balance(self, address: str) -> Decimal:
        """Get CONFIO balance for address"""
        coin_type = f"{settings.CONFIO_PACKAGE_ID}::confio::CONFIO"
        balances = await self.get_balance(address, coin_type)
        return balances.get(coin_type, Decimal('0'))
    
    async def get_sui_balance(self, address: str) -> Decimal:
        """Get SUI balance for address"""
        coin_type = "0x2::sui::SUI"
        balances = await self.get_balance(address, coin_type)
        return balances.get(coin_type, Decimal('0'))
    
    # ===== Epoch Operations =====
    
    async def get_latest_sui_system_state(self):
        """Get the latest SuiSystemState to extract epoch info"""
        return await self._make_rpc_call("suix_getLatestSuiSystemState", [])
    
    async def get_epoch_info(self):
        """Get current epoch information"""
        system_state = await self.get_latest_sui_system_state()
        return {
            'epoch': system_state.get('epoch'),
            'epochStartTimestampMs': system_state.get('epochStartTimestampMs'),
            'epochDurationMs': system_state.get('epochDurationMs'),
            'totalStake': system_state.get('totalStake'),
            'storageRebate': system_state.get('storageRebate'),
            'storageFundTotalObjectStorageRebates': system_state.get('storageFundTotalObjectStorageRebates'),
            'storageFundNonRefundableBalance': system_state.get('storageFundNonRefundableBalance'),
        }
    
    async def get_checkpoints_in_epoch(self, epoch: int):
        """Get checkpoint range for a specific epoch"""
        # Get epoch change events to find checkpoint boundaries
        return await self._make_rpc_call(
            "suix_getCheckpoints",
            {
                "cursor": None,
                "limit": 1,
                "descendingOrder": False
            }
        )
    
    # ===== Transaction Operations =====
    
    async def transfer_cusd(
        self,
        from_address: str,
        to_address: str,
        amount: Decimal,
        gas_budget: int = 10000000
    ) -> str:
        """
        Transfer cUSD tokens
        
        Returns:
            Transaction digest
        """
        # Convert amount to smallest unit (6 decimals for cUSD)
        amount_mist = int(amount * Decimal(10 ** 6))
        
        # Build transaction
        tx_data = await self._make_rpc_call(
            "unsafe_transferObject",
            [
                from_address,
                f"{settings.CUSD_PACKAGE_ID}::cusd::CUSD",
                amount_mist,
                to_address,
                gas_budget
            ]
        )
        
        # Sign and execute (this would integrate with zkLogin)
        # For now, return mock digest
        return tx_data.get('digest', 'mock_digest')
    
    async def execute_pay_transaction(
        self,
        payer_address: str,
        recipient_address: str,
        amount: Decimal,
        token_type: str = "CUSD",
        payment_id: str = None
    ) -> str:
        """
        Execute payment through Pay contract (0.9% fee)
        """
        # Build move call transaction
        if token_type == "CUSD":
            function = "pay_with_cusd"
            coin_type = f"{settings.CUSD_PACKAGE_ID}::cusd::CUSD"
        else:
            function = "pay_with_confio"
            coin_type = f"{settings.CONFIO_PACKAGE_ID}::confio::CONFIO"
        
        decimals = 6 if token_type == "CUSD" else 9
        amount_units = int(amount * Decimal(10 ** decimals))
        
        tx_data = {
            "packageObjectId": settings.PAY_PACKAGE_ID,
            "module": "pay",
            "function": function,
            "typeArguments": [],
            "arguments": [
                settings.FEE_COLLECTOR_OBJECT_ID,
                amount_units,
                recipient_address,
                payment_id or "",
            ],
            "gasBudget": 10000000
        }
        
        # This would be signed by user's zkLogin
        result = await self._make_rpc_call("sui_moveCall", [payer_address, tx_data])
        return result.get('digest')
    
    # ===== Transaction Monitoring =====
    
    async def get_transactions(
        self,
        address: str,
        cursor: Optional[str] = None,
        limit: int = 50
    ) -> Dict:
        """Get transactions for an address"""
        query = {
            "filter": {
                "FromOrToAddress": address
            },
            "options": {
                "showInput": True,
                "showEffects": True,
                "showEvents": True,
                "showBalanceChanges": True
            }
        }
        
        params = [query]
        if cursor:
            params.append(cursor)
        params.append(limit)
        
        return await self._make_rpc_call("suix_queryTransactionBlocks", params)
    
    async def get_transaction_detail(self, digest: str) -> Dict:
        """Get detailed transaction information"""
        options = {
            "showInput": True,
            "showEffects": True,
            "showEvents": True,
            "showObjectChanges": True,
            "showBalanceChanges": True
        }
        
        return await self._make_rpc_call(
            "sui_getTransactionBlock",
            [digest, options]
        )
    
    # ===== Event Subscription (WebSocket) =====
    
    async def subscribe_to_events(self, filter: Dict):
        """
        Subscribe to blockchain events via WebSocket
        
        Note: Testnet supports WebSocket subscriptions.
        For QuickNode mainnet, we'll use their gRPC streaming instead.
        """
        if 'quicknode' in self.ws_url:
            # QuickNode uses gRPC, not WebSocket
            raise NotImplementedError("Use QuickNode gRPC client for mainnet subscriptions")
        
        # Testnet WebSocket subscription
        import websockets
        
        async with websockets.connect(self.ws_url) as websocket:
            # Subscribe to events
            subscribe_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "suix_subscribeEvent",
                "params": [filter]
            }
            
            await websocket.send(json.dumps(subscribe_msg))
            
            # Process events
            while True:
                message = await websocket.recv()
                data = json.loads(message)
                
                if 'params' in data:
                    event = data['params']['result']
                    yield event
    
    # ===== Helper Methods =====
    
    def _get_coin_decimals(self, coin_type: str) -> int:
        """Get decimals for a coin type"""
        if 'cusd' in coin_type.lower():
            return 6
        elif 'confio' in coin_type.lower():
            return 9
        elif 'sui::SUI' in coin_type:
            return 9
        elif 'usdc' in coin_type.lower():
            return 6
        else:
            return 9  # Default
    
    async def health_check(self) -> bool:
        """Check if RPC node is accessible"""
        try:
            result = await self._make_rpc_call("sui_getChainIdentifier", [])
            return bool(result)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False


# Singleton instance
sui_client = SuiClient()


# ===== Django Integration Helpers =====

async def update_user_balance(user_account):
    """Update user's balance from blockchain"""
    from transactions.models import Balance
    
    client = SuiClient()
    
    # Get all balances
    cusd = await client.get_cusd_balance(user_account.sui_address)
    confio = await client.get_confio_balance(user_account.sui_address)
    sui = await client.get_sui_balance(user_account.sui_address)
    
    # Update or create balance records
    Balance.objects.update_or_create(
        account=user_account,
        token='CUSD',
        defaults={'amount': cusd}
    )
    
    Balance.objects.update_or_create(
        account=user_account,
        token='CONFIO',
        defaults={'amount': confio}
    )
    
    Balance.objects.update_or_create(
        account=user_account,
        token='SUI',
        defaults={'amount': sui}
    )
    
    return {
        'CUSD': cusd,
        'CONFIO': confio,
        'SUI': sui
    }