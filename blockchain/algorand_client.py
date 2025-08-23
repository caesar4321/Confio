"""
Production Algorand blockchain client using py-algorand-sdk
"""
import json
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal
from algosdk.v2client import algod, indexer
from algosdk import account, mnemonic, transaction
from algosdk.transaction import PaymentTxn, AssetTransferTxn, wait_for_confirmation
from django.conf import settings
from django.core.cache import cache
import logging
import base64

logger = logging.getLogger(__name__)


class AlgorandClient:
    """
    Production-ready Algorand client using official py-algorand-sdk
    """
    
    def __init__(self):
        # Get Algorand configuration from settings - single source of truth
        self.algod_address = settings.ALGORAND_ALGOD_ADDRESS
        self.algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '')
        self.indexer_address = settings.ALGORAND_INDEXER_ADDRESS
        self.indexer_token = getattr(settings, 'ALGORAND_INDEXER_TOKEN', '')
        
        # Initialize clients
        self._algod_client = None
        self._indexer_client = None
        
        # Asset IDs for tokens - single source of truth from settings
        self.USDC_ASSET_ID = settings.ALGORAND_USDC_ASSET_ID
        self.CUSD_ASSET_ID = settings.ALGORAND_CUSD_ASSET_ID
        self.CONFIO_ASSET_ID = settings.ALGORAND_CONFIO_ASSET_ID
    
    async def __aenter__(self):
        """Async context manager entry"""
        # Add a friendly User-Agent; pass token separately per SDK signature
        ua = {'User-Agent': 'confio-backend/algosdk'}
        # Nodely uses X-API-Key instead of X-Algo-API-Token
        if 'nodely' in (self.algod_address or '').lower() and (self.algod_token or ''):
            algod_headers = {**ua, 'X-API-Key': self.algod_token}
            self._algod_client = algod.AlgodClient('', self.algod_address, headers=algod_headers)
        else:
            self._algod_client = algod.AlgodClient(self.algod_token or '', self.algod_address, headers=ua)
        if 'nodely' in (self.indexer_address or '').lower() and (self.indexer_token or ''):
            indexer_headers = {**ua, 'X-API-Key': self.indexer_token}
            self._indexer_client = indexer.IndexerClient('', self.indexer_address, headers=indexer_headers)
        else:
            self._indexer_client = indexer.IndexerClient(self.indexer_token or '', self.indexer_address, headers=ua)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        # Algorand clients don't need explicit closing
        pass
    
    @property
    def algod(self) -> algod.AlgodClient:
        """Get the algod client instance"""
        if not self._algod_client:
            ua = {'User-Agent': 'confio-backend/algosdk'}
            if 'nodely' in (self.algod_address or '').lower() and (self.algod_token or ''):
                headers = {**ua, 'X-API-Key': self.algod_token}
                self._algod_client = algod.AlgodClient('', self.algod_address, headers=headers)
            else:
                self._algod_client = algod.AlgodClient(self.algod_token or '', self.algod_address, headers=ua)
        return self._algod_client
    
    @property
    def indexer(self) -> indexer.IndexerClient:
        """Get the indexer client instance"""
        if not self._indexer_client:
            ua = {'User-Agent': 'confio-backend/algosdk'}
            if 'nodely' in (self.indexer_address or '').lower() and (self.indexer_token or ''):
                headers = {**ua, 'X-API-Key': self.indexer_token}
                self._indexer_client = indexer.IndexerClient('', self.indexer_address, headers=headers)
            else:
                self._indexer_client = indexer.IndexerClient(self.indexer_token or '', self.indexer_address, headers=ua)
        return self._indexer_client
    
    # ===== Balance Operations =====
    
    async def get_balance(self, address: str, asset_id: Optional[int] = None, skip_cache: bool = False) -> Dict[str, Decimal]:
        """
        Get token balances for an address
        
        Args:
            address: Algorand address
            asset_id: Specific asset ID or None for ALGO balance
            skip_cache: Skip cache and fetch directly from blockchain
        
        Returns:
            Dict of asset_id -> balance
        """
        # Check cache first (unless skip_cache is True)
        cache_key = f"algo_balance:{address}:{asset_id or 'algo'}"
        if not skip_cache:
            cached = cache.get(cache_key)
            if cached:
                logger.info(f"Returning cached balance for {address}, asset_id={asset_id}: {cached}")
                return cached
        
        balances = {}
        
        try:
            # Get account information
            account_info = self.algod.account_info(address)
            
            if asset_id is None:
                # Get ALGO balance (in microAlgos)
                algo_balance = account_info.get('amount', 0) / 1_000_000  # Convert to ALGOs
                balances['ALGO'] = Decimal(str(algo_balance))
            else:
                # Get specific ASA balance
                assets = account_info.get('assets', [])
                for asset in assets:
                    if asset['asset-id'] == asset_id:
                        # Get asset info to determine decimals
                        asset_info = self.algod.asset_info(asset_id)
                        decimals = asset_info['params'].get('decimals', 0)
                        balance = asset['amount'] / (10 ** decimals)
                        balances[str(asset_id)] = Decimal(str(balance))
                        break
                else:
                    # Asset not found or not opted in
                    balances[str(asset_id)] = Decimal('0')
        
        except Exception as e:
            logger.error(f"Error getting balance for {address}: {e}")
            if asset_id:
                balances[str(asset_id)] = Decimal('0')
            else:
                balances['ALGO'] = Decimal('0')
        
        # Only cache if we're not skipping cache (for normal queries)
        # Don't cache force-refresh results to avoid polluting cache with potentially stale data
        if not skip_cache:
            # Cache for 30 seconds
            cache.set(cache_key, balances, 30)
        else:
            # When force refreshing, also clear the existing cache to ensure fresh data
            cache.delete(cache_key)
            logger.info(f"Force refresh: cleared cache for {address}, asset_id={asset_id}")
        
        return balances
    
    async def get_usdc_balance(self, address: str, skip_cache: bool = False) -> Decimal:
        """Get USDC balance for address"""
        if not self.USDC_ASSET_ID:
            logger.warning("USDC_ASSET_ID not configured")
            return Decimal('0')
        balances = await self.get_balance(address, self.USDC_ASSET_ID, skip_cache=skip_cache)
        return balances.get(str(self.USDC_ASSET_ID), Decimal('0'))
    
    async def get_cusd_balance(self, address: str, skip_cache: bool = False) -> Decimal:
        """Get cUSD balance for address"""
        if not self.CUSD_ASSET_ID:
            logger.warning("CUSD_ASSET_ID not configured")
            return Decimal('0')
        balances = await self.get_balance(address, self.CUSD_ASSET_ID, skip_cache=skip_cache)
        return balances.get(str(self.CUSD_ASSET_ID), Decimal('0'))
    
    async def get_confio_balance(self, address: str, skip_cache: bool = False) -> Decimal:
        """Get CONFIO balance for address"""
        if not self.CONFIO_ASSET_ID:
            logger.warning("CONFIO_ASSET_ID not configured")
            return Decimal('0')
        balances = await self.get_balance(address, self.CONFIO_ASSET_ID, skip_cache=skip_cache)
        return balances.get(str(self.CONFIO_ASSET_ID), Decimal('0'))
    
    
    # ===== Transaction Building =====
    
    async def build_transfer_transaction(
        self,
        sender: str,
        recipient: str,
        amount: Decimal,
        asset_id: Optional[int] = None,
        note: Optional[str] = None
    ) -> Tuple[bytes, str]:
        """
        Build a transfer transaction
        
        Args:
            sender: Sender's Algorand address
            recipient: Recipient's Algorand address
            amount: Amount to send
            asset_id: Asset ID for ASA transfer, None for ALGO transfer
            note: Optional transaction note
        
        Returns:
            Tuple of (transaction_bytes, transaction_id)
        """
        try:
            # Get suggested params
            params = self.algod.suggested_params()
            
            if asset_id is None:
                # ALGO transfer
                amount_microalgos = int(amount * 1_000_000)
                txn = PaymentTxn(
                    sender=sender,
                    sp=params,
                    receiver=recipient,
                    amt=amount_microalgos,
                    note=note.encode() if note else None
                )
            else:
                # ASA transfer
                # Get asset info to determine decimals
                asset_info = self.algod.asset_info(asset_id)
                decimals = asset_info['params'].get('decimals', 0)
                amount_units = int(amount * (10 ** decimals))
                
                txn = AssetTransferTxn(
                    sender=sender,
                    sp=params,
                    receiver=recipient,
                    amt=amount_units,
                    index=asset_id,
                    note=note.encode() if note else None
                )
            
            # Get transaction bytes and ID
            import msgpack
            tx_bytes = msgpack.packb(txn.dictify(), use_bin_type=True)  # Serialize transaction
            tx_id = txn.get_txid()
            
            return tx_bytes, tx_id
            
        except Exception as e:
            logger.error(f"Error building transfer transaction: {e}")
            raise
    
    async def build_sponsored_transaction(
        self,
        sender: str,
        sponsor: str,
        transactions: List[Dict[str, Any]],
        fee: int = 1000
    ) -> bytes:
        """
        Build a sponsored transaction where sponsor pays fees
        In Algorand, this would be an atomic group transaction
        
        Args:
            sender: The user making the transaction
            sponsor: The address paying for fees
            transactions: List of transaction commands
            fee: Fee per transaction in microAlgos
            
        Returns:
            Transaction group bytes ready for signing
        """
        try:
            # Get suggested params
            params = self.algod.suggested_params()
            
            txn_list = []
            
            # Build each transaction
            for tx_cmd in transactions:
                if tx_cmd['type'] == 'transfer':
                    if tx_cmd.get('asset_id'):
                        # ASA transfer
                        txn = AssetTransferTxn(
                            sender=sender,
                            sp=params,
                            receiver=tx_cmd['recipient'],
                            amt=tx_cmd['amount'],
                            index=tx_cmd['asset_id']
                        )
                    else:
                        # ALGO transfer
                        txn = PaymentTxn(
                            sender=sender,
                            sp=params,
                            receiver=tx_cmd['recipient'],
                            amt=tx_cmd['amount']
                        )
                    txn_list.append(txn)
            
            # Add fee payment from sponsor to sender to cover fees
            if sponsor != sender:
                total_fee = fee * len(txn_list)
                fee_txn = PaymentTxn(
                    sender=sponsor,
                    sp=params,
                    receiver=sender,
                    amt=total_fee,
                    note=b"Fee sponsorship"
                )
                txn_list.append(fee_txn)
            
            # Create atomic group
            if len(txn_list) > 1:
                transaction.assign_group_id(txn_list)
            
            # Return serialized group
            import msgpack
            return b''.join([msgpack.packb(txn.dictify(), use_bin_type=True) for txn in txn_list])
            
        except Exception as e:
            logger.error(f"Error building sponsored transaction: {e}")
            raise
    
    # ===== Transaction Execution =====
    
    async def execute_transaction(
        self,
        signed_txn: bytes,
        wait_for_confirmation: bool = True
    ) -> Dict[str, Any]:
        """
        Execute a signed transaction
        
        Args:
            signed_txn: Signed transaction bytes
            wait_for_confirmation: Whether to wait for confirmation
            
        Returns:
            Transaction result
        """
        try:
            # Send transaction
            tx_id = self.algod.send_raw_transaction(signed_txn)
            
            if wait_for_confirmation:
                # Wait for confirmation
                confirmed_txn = wait_for_confirmation(
                    self.algod, tx_id, 4
                )
                return {
                    'txId': tx_id,
                    'confirmedRound': confirmed_txn.get('confirmed-round'),
                    'status': 'success'
                }
            else:
                return {'txId': tx_id, 'status': 'pending'}
            
        except Exception as e:
            logger.error(f"Error executing transaction: {e}")
            raise
    
    async def dry_run_transaction(self, signed_txn: bytes) -> Dict[str, Any]:
        """
        Dry run a transaction to check for errors
        
        Args:
            signed_txn: Signed transaction bytes
            
        Returns:
            Dry run result
        """
        try:
            # Create dry run request
            drr = transaction.create_dryrun(self.algod, [signed_txn])
            
            # Execute dry run
            result = self.algod.dryrun(drr)
            
            return result
            
        except Exception as e:
            logger.error(f"Error in dry run: {e}")
            raise
    
    # ===== Transaction Monitoring =====
    
    async def get_transaction(self, tx_id: str) -> Dict[str, Any]:
        """Get transaction details by ID"""
        try:
            # Get pending transaction info
            try:
                pending_tx = self.algod.pending_transaction_info(tx_id)
                if pending_tx:
                    return pending_tx
            except:
                pass
            
            # If not pending, search in indexer
            result = self.indexer.search_transactions(txid=tx_id)
            if result and result.get('transactions'):
                return result['transactions'][0]
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting transaction {tx_id}: {e}")
            raise
    
    async def wait_for_transaction(self, tx_id: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Wait for a transaction to be confirmed
        
        Args:
            tx_id: Transaction ID
            timeout: Maximum seconds to wait
            
        Returns:
            Transaction result
        """
        try:
            confirmed_txn = wait_for_confirmation(
                self.algod, tx_id, timeout
            )
            return {
                'txId': tx_id,
                'confirmedRound': confirmed_txn.get('confirmed-round'),
                'status': 'success',
                'details': confirmed_txn
            }
        except Exception as e:
            logger.error(f"Error waiting for transaction: {e}")
            raise
    
    # ===== Account Management =====
    
    async def create_account(self) -> Dict[str, str]:
        """
        Create a new Algorand account
        
        Returns:
            Dict with 'address' and 'mnemonic'
        """
        try:
            private_key, address = account.generate_account()
            mnemonic_phrase = mnemonic.from_private_key(private_key)
            
            return {
                'address': address,
                'mnemonic': mnemonic_phrase,
                'privateKey': private_key
            }
        except Exception as e:
            logger.error(f"Error creating account: {e}")
            raise
    
    async def opt_in_to_asset(self, address: str, asset_id: int, private_key: str) -> str:
        """
        Opt-in to an ASA (required before receiving it)
        
        Args:
            address: Account address
            asset_id: Asset ID to opt into
            private_key: Private key for signing
            
        Returns:
            Transaction ID
        """
        try:
            params = self.algod.suggested_params()
            
            # Create opt-in transaction (0 amount transfer to self)
            txn = AssetTransferTxn(
                sender=address,
                sp=params,
                receiver=address,
                amt=0,
                index=asset_id
            )
            
            # Sign transaction
            signed_txn = txn.sign(private_key)
            
            # Send transaction
            tx_id = self.algod.send_raw_transaction(signed_txn)
            
            # Wait for confirmation
            wait_for_confirmation(self.algod, tx_id, 4)
            
            return tx_id
            
        except Exception as e:
            logger.error(f"Error opting in to asset: {e}")
            raise
    
    # ===== Helper Methods =====
    
    async def health_check(self) -> bool:
        """Check if Algorand node is accessible"""
        try:
            status = self.algod.status()
            return bool(status)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    async def get_asset_info(self, asset_id: int) -> Dict[str, Any]:
        """Get information about an asset"""
        try:
            return self.algod.asset_info(asset_id)
        except Exception as e:
            logger.error(f"Error getting asset info: {e}")
            return None


# ===== Convenience Functions =====

async def get_algorand_client() -> AlgorandClient:
    """
    Get an AlgorandClient instance for use in async with blocks
    
    Usage:
        async with await get_algorand_client() as client:
            balance = await client.get_usdc_balance(address)
    """
    return AlgorandClient()
