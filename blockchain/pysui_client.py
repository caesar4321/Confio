"""
Production Sui blockchain client using pysui SDK
"""
import json
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal
from pysui import SuiConfig, AsyncClient
from pysui.sui.sui_types import SuiAddress, ObjectID, SuiU64
# Transaction classes will be imported when needed to avoid import errors
from django.conf import settings
from django.core.cache import cache
import logging
import base64

logger = logging.getLogger(__name__)


class PySuiClient:
    """
    Production-ready Sui client using official pysui SDK
    """
    
    def __init__(self):
        # Create config based on network setting
        if settings.BLOCKCHAIN_CONFIG.get('NETWORK') == 'mainnet':
            # For mainnet, we'll need to configure with custom RPC
            self.config = SuiConfig.user_config(
                rpc_url=settings.SUI_RPC_URL,
                ws_url=settings.SUI_WS_URL if hasattr(settings, 'SUI_WS_URL') else None
            )
        else:
            # Default testnet config
            self.config = SuiConfig.default_config()
        
        self._client = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        self._client = AsyncClient(self.config)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self._client:
            await self._client.close()
    
    @property
    def client(self) -> AsyncClient:
        """Get the async client instance"""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with PySuiClient() as client:'")
        return self._client
    
    # ===== Balance Operations =====
    
    async def get_balance(self, address: str, coin_type: Optional[str] = None) -> Dict[str, Decimal]:
        """
        Get token balances for an address using pysui get_coin method
        
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
            logger.info(f"Returning cached balance for {address}, coin_type={coin_type}: {cached}")
            return cached
        
        sui_address = SuiAddress(address)
        balances = {}
        
        try:
            if coin_type:
                # Get coins of specific type and sum their balances
                from pysui.sui.sui_types.scalars import SuiString
                result = await self.client.get_coin(coin_type=SuiString(coin_type), address=sui_address, fetch_all=True)
                total_balance = 0
                if result and hasattr(result, 'result_data') and result.result_data:
                    # result.result_data.data contains the list of SuiCoinObject instances
                    if hasattr(result.result_data, 'data'):
                        for coin in result.result_data.data:
                            if hasattr(coin, 'balance'):
                                total_balance += int(coin.balance)
                    else:
                        # Fallback: try direct iteration (in case structure differs)
                        for coin in result.result_data:
                            if hasattr(coin, 'balance'):
                                total_balance += int(coin.balance)
                
                decimals = self._get_coin_decimals(coin_type)
                balance_value = total_balance / (10 ** decimals)
                balances[coin_type] = Decimal(str(balance_value))
            else:
                # For all balances, we'd need to query each coin type separately
                # For now, just return empty dict - implement if needed
                balances = {}
        
        except Exception as e:
            logger.error(f"Error getting balance for {address}: {e}")
            if coin_type:
                balances[coin_type] = Decimal('0')
        
        # Cache for 30 seconds
        cache.set(cache_key, balances, 30)
        
        return balances
    
    async def get_cusd_balance(self, address: str) -> Decimal:
        """Get cUSD balance for address"""
        coin_type = f"{settings.CUSD_PACKAGE_ID}::cusd::CUSD"
        balances = await self.get_balance(address, coin_type)
        balance = balances.get(coin_type, Decimal('0'))
        logger.info(f"get_cusd_balance for {address}: {balance} cUSD")
        return balance
    
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
    
    # ===== Coin Management =====
    
    async def get_coins(
        self, 
        address: str, 
        coin_type: str,
        cursor: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get coin objects for an address
        
        Returns:
            List of coin objects with objectId, version, digest, balance
        """
        sui_address = SuiAddress(address)
        
        try:
            from pysui.sui.sui_types.scalars import SuiString
            result = await self.client.get_coin(
                coin_type=SuiString(coin_type),
                address=sui_address,
                fetch_all=True  # Get all coins, not just first page
            )
            
            coins = []
            if result and hasattr(result, 'result_data') and result.result_data:
                # result.result_data.data contains the list of SuiCoinObject instances
                if hasattr(result.result_data, 'data'):
                    for coin in result.result_data.data:
                        # Use correct field names based on debug output
                        if hasattr(coin, 'coin_object_id'):
                            coins.append({
                                'objectId': coin.coin_object_id,
                                'version': str(coin.version) if hasattr(coin, 'version') else '0',
                                'digest': coin.digest if hasattr(coin, 'digest') else '',
                                'balance': int(coin.balance) if hasattr(coin, 'balance') else 0,
                                'previousTransaction': coin.previous_transaction if hasattr(coin, 'previous_transaction') else ''
                            })
                else:
                    # Fallback: try direct iteration
                    for coin in result.result_data:
                        if hasattr(coin, 'coin_object_id'):
                            coins.append({
                                'objectId': coin.coin_object_id,
                                'version': str(coin.version) if hasattr(coin, 'version') else '0',
                                'digest': coin.digest if hasattr(coin, 'digest') else '',
                                'balance': int(coin.balance) if hasattr(coin, 'balance') else 0,
                                'previousTransaction': coin.previous_transaction if hasattr(coin, 'previous_transaction') else ''
                            })
            
            return coins
            
        except Exception as e:
            logger.error(f"Error getting coins for {address}: {e}")
            return []
    
    # ===== Transaction Building =====
    
    async def build_transfer_transaction(
        self,
        sender: str,
        recipient: str,
        amount: Decimal,
        coin_type: str,
        gas_budget: int = 10000000
    ) -> Tuple[bytes, str]:
        """
        Build a transfer transaction using pysui
        
        Returns:
            Tuple of (transaction_bytes, transaction_digest)
        """
        try:
            # Import transaction class locally to avoid import errors
            from pysui.sui.sui_txn.sync_transaction import SuiTransaction
            
            # Create transaction builder
            txn = SuiTransaction(client=self.client)
            
            # Convert amount to smallest unit
            decimals = self._get_coin_decimals(coin_type)
            amount_units = int(amount * Decimal(10 ** decimals))
            
            # Get coins for the transfer
            coins = await self.get_coins(sender, coin_type, limit=10)
            if not coins:
                raise ValueError(f"No {coin_type} coins found for {sender}")
            
            # Build transfer
            if len(coins) == 1 and coins[0]['balance'] >= amount_units:
                # Simple transfer with single coin
                coin_obj = ObjectID(coins[0]['objectId'])
                
                # Split and transfer
                txn.move_call(
                    target="0x2::pay::split_and_transfer",
                    arguments=[coin_obj, SuiU64(amount_units), SuiAddress(recipient)],
                    type_arguments=[coin_type]
                )
            else:
                # Need to merge coins first
                coin_objects = [ObjectID(coin['objectId']) for coin in coins]
                
                # Merge and transfer
                txn.move_call(
                    target="0x2::pay::join_vec_and_transfer", 
                    arguments=[coin_objects, SuiAddress(recipient)],
                    type_arguments=[coin_type]
                )
            
            # Set sender and gas budget
            txn.sender = SuiAddress(sender)
            txn.gas_budget = gas_budget
            
            # Build the transaction
            # SuiTransaction.build() is synchronous
            tx_bytes = txn.build()
            
            # Calculate digest for tracking
            import hashlib
            tx_digest = base64.b64encode(
                hashlib.blake2b(tx_bytes, digest_size=32).digest()
            ).decode()
            
            return tx_bytes, tx_digest
            
        except Exception as e:
            logger.error(f"Error building transfer transaction: {e}")
            raise
    
    async def build_sponsored_transaction(
        self,
        sender: str,
        sponsor: str,
        transactions: List[Dict[str, Any]],
        gas_budget: int = 10000000
    ) -> bytes:
        """
        Build a sponsored transaction where sponsor pays gas
        
        Args:
            sender: The user making the transaction
            sponsor: The address paying for gas
            transactions: List of transaction commands
            gas_budget: Gas budget for the transaction
            
        Returns:
            Transaction bytes ready for signing
        """
        try:
            # Use a synchronous transaction builder to avoid async/sync mismatch
            from blockchain.sync_transaction_builder import build_sponsored_transaction_sync
            
            # Get the network from settings
            network = settings.BLOCKCHAIN_CONFIG.get('NETWORK', 'testnet')
            
            # Build transaction synchronously
            tx_bytes = build_sponsored_transaction_sync(
                sender=sender,
                sponsor=sponsor,
                transactions=transactions,
                gas_budget=gas_budget,
                network=network
            )
            
            return tx_bytes
                
        except Exception as e:
            logger.error(f"Error building sponsored transaction (sync): {e}")
            
            # If sync fails due to SSL/timeout, try async
            if "ssl" in str(e).lower() or "timeout" in str(e).lower():
                logger.info("Retrying with async transaction builder...")
                try:
                    from blockchain.async_transaction_builder import build_sponsored_transaction_async
                    import asyncio
                    
                    # Run async builder in sync context
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        tx_bytes = loop.run_until_complete(
                            build_sponsored_transaction_async(
                                sender=sender,
                                sponsor=sponsor,
                                transactions=transactions,
                                gas_budget=gas_budget,
                                network=network
                            )
                        )
                        return tx_bytes
                    finally:
                        loop.close()
                except Exception as async_error:
                    logger.error(f"Async builder also failed: {async_error}")
                    raise e  # Re-raise original error
            else:
                raise
    
    # ===== Transaction Execution =====
    
    async def execute_transaction(
        self,
        tx_bytes: bytes,
        signatures: List[Any],
        options: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        """
        Execute a signed transaction
        
        Args:
            tx_bytes: Transaction bytes
            signatures: List of signature objects (can be strings or dicts with scheme/signature)
            options: Execution options
            
        Returns:
            Transaction result
        """
        try:
            # Use our custom executor for pre-signed transactions
            from blockchain.transaction_executor import execute_transaction_with_signatures
            
            result = await execute_transaction_with_signatures(
                client=self.client,
                tx_bytes=tx_bytes,
                signatures=signatures
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing transaction: {e}")
            raise
    
    async def dry_run_transaction(self, tx_bytes: bytes) -> Dict[str, Any]:
        """
        Dry run a transaction to check for errors
        
        Args:
            tx_bytes: Transaction bytes
            
        Returns:
            Dry run result
        """
        try:
            # Use direct RPC client for dry run
            from blockchain.rpc_client import SuiRpcClient
            
            rpc_client = SuiRpcClient(settings.SUI_RPC_URL)
            result = await rpc_client.execute_rpc(
                "sui_dryRunTransactionBlock",
                [base64.b64encode(tx_bytes).decode() if isinstance(tx_bytes, bytes) else tx_bytes]
            )
            
            return result
                
        except Exception as e:
            logger.error(f"Error in dry run: {e}")
            raise
    
    # ===== zkLogin Support =====
    
    async def get_zklogin_signature_inputs(self) -> Dict[str, Any]:
        """
        Get the current epoch and randomness for zkLogin
        
        Returns:
            Dict with epoch, randomness, and maxEpoch
        """
        try:
            # Get latest system state using direct RPC
            from blockchain.rpc_client import SuiRpcClient
            
            rpc_client = SuiRpcClient(settings.SUI_RPC_URL)
            system_state = await rpc_client.execute_rpc(
                "sui_getLatestSuiSystemState",
                []
            )
            
            current_epoch = int(system_state.get('epoch', 0))
            
            return {
                'epoch': current_epoch,
                'randomness': system_state.get('epochStartTimestampMs', 0),
                'maxEpoch': current_epoch + 2  # zkLogin signatures valid for 2 epochs
            }
            
        except Exception as e:
            logger.error(f"Error getting zkLogin inputs: {e}")
            raise
    
    # ===== Transaction Monitoring =====
    
    async def get_transaction(self, digest: str) -> Dict[str, Any]:
        """Get transaction details by digest"""
        try:
            # Use direct RPC for getting transaction
            from blockchain.rpc_client import SuiRpcClient
            
            rpc_client = SuiRpcClient(settings.SUI_RPC_URL)
            result = await rpc_client.execute_rpc(
                "sui_getTransactionBlock",
                [
                    digest,
                    {
                        "showInput": True,
                        "showEffects": True,
                        "showEvents": True,
                        "showObjectChanges": True,
                        "showBalanceChanges": True
                    }
                ]
            )
            
            return result
        except Exception as e:
            logger.error(f"Error getting transaction {digest}: {e}")
            raise
    
    async def wait_for_transaction(self, digest: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Wait for a transaction to be confirmed
        
        Args:
            digest: Transaction digest
            timeout: Maximum seconds to wait
            
        Returns:
            Transaction result
        """
        start_time = asyncio.get_event_loop().time()
        
        while True:
            try:
                result = await self.get_transaction(digest)
                if result and result.get('effects', {}).get('status', {}).get('status') == 'success':
                    return result
            except:
                pass
            
            if asyncio.get_event_loop().time() - start_time > timeout:
                raise TimeoutError(f"Transaction {digest} not confirmed after {timeout} seconds")
            
            await asyncio.sleep(1)
    
    # ===== Helper Methods =====
    
    def _get_coin_decimals(self, coin_type: str) -> int:
        """Get decimals for a coin type"""
        if 'cusd' in coin_type.lower():
            return 6
        elif 'confio' in coin_type.lower():
            return 6  # CONFIO uses 6 decimals
        elif 'sui::SUI' in coin_type:
            return 9
        elif 'usdc' in coin_type.lower():
            return 6
        else:
            return 9  # Default
    
    async def health_check(self) -> bool:
        """Check if RPC node is accessible"""
        try:
            # Use rpc_version_support as a simple health check
            result = self.client.rpc_version_support()  # Remove await since it's not async
            return bool(result)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False


# ===== Convenience Functions =====

async def get_pysui_client() -> PySuiClient:
    """
    Get a PySuiClient instance for use in async with blocks
    
    Usage:
        async with await get_pysui_client() as client:
            balance = await client.get_cusd_balance(address)
    """
    return PySuiClient()