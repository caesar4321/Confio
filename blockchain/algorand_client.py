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
from contracts.presale.state_utils import decode_local_state

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
        
        # Optional fallback (reuse dryrun endpoint if configured, otherwise Algonode public endpoint)
        self.fallback_algod_address = (
            settings.ALGORAND_DRYRUN_ALGOD_ADDRESS
            or 'https://mainnet-api.algonode.cloud'
        )
        self.fallback_algod_token = getattr(settings, 'ALGORAND_DRYRUN_ALGOD_TOKEN', '') or ''

        # Initialize clients
        self._algod_client = None
        self._indexer_client = None
        self._using_fallback_algod = False
        self._using_fallback_indexer = False
        
        # Asset IDs for tokens - single source of truth from settings
        self.USDC_ASSET_ID = settings.ALGORAND_USDC_ASSET_ID
        self.CUSD_ASSET_ID = settings.ALGORAND_CUSD_ASSET_ID
        self.CONFIO_ASSET_ID = settings.ALGORAND_CONFIO_ASSET_ID
    
    def _build_algod_client(self):
        """Instantiate an algod client, falling back if the primary endpoint needs an API key."""
        ua = {'User-Agent': 'confio-backend/algosdk'}
        address = self.algod_address
        token = self.algod_token or ''

        if 'nodely' in (address or '').lower():
            headers = dict(ua)
            if token:
                headers['X-API-Key'] = token
            else:
                logger.info(
                    "ALGORAND_ALGOD_TOKEN not set; continuing to use %s without X-API-Key header",
                    address,
                )
            self._using_fallback_algod = False
            return algod.AlgodClient('', address, headers=headers)

        self._using_fallback_algod = False
        return algod.AlgodClient(token, address, headers=ua)

    def _build_indexer_client(self):
        """Instantiate an indexer client with optional API key support."""
        ua = {'User-Agent': 'confio-backend/algosdk'}
        address = self.indexer_address
        token = self.indexer_token or ''

        if 'nodely' in (address or '').lower():
            headers = dict(ua)
            if token:
                headers['X-API-Key'] = token
            self._using_fallback_indexer = False
            return indexer.IndexerClient('', address, headers=headers)

        self._using_fallback_indexer = False
        return indexer.IndexerClient(token, address, headers=ua)

    async def __aenter__(self):
        """Async context manager entry"""
        self._algod_client = self._build_algod_client()
        self._indexer_client = self._build_indexer_client()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        # Algorand clients don't need explicit closing
        pass
    
    @property
    def algod(self) -> algod.AlgodClient:
        """Get the algod client instance"""
        if not self._algod_client:
            self._algod_client = self._build_algod_client()
        return self._algod_client
    
    @property
    def indexer(self) -> indexer.IndexerClient:
        """Get the indexer client instance"""
        if not self._indexer_client:
            self._indexer_client = self._build_indexer_client()
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
            logger.exception(
                "Error getting balance for %s (asset_id=%s, using_fallback_algod=%s): %s",
                address,
                asset_id,
                self._using_fallback_algod,
                e,
            )
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

    async def get_balances_snapshot(self, address: str, skip_cache: bool = False) -> Dict[str, Decimal]:
        """Fetch cUSD, CONFIO, USDC, and presale-locked in one algod.account_info call.

        Returns a dict with Decimal values in human units (6 decimals for all).
        Keys: 'CUSD', 'CONFIO', 'USDC', 'CONFIO_PRESALE'
        """
        try:
            info = self.algod.account_info(address)
        except Exception as e:
            logger.error("[snapshot] failed to fetch account_info for %s: %s", address, e)
            return {k: Decimal('0') for k in ['CUSD', 'CONFIO', 'USDC', 'CONFIO_PRESALE']}

        def asset_amount(asset_id: Optional[int]) -> Decimal:
            if not asset_id:
                return Decimal('0')
            for a in (info.get('assets') or []):
                if a.get('asset-id') == asset_id:
                    return Decimal(str(a.get('amount', 0))) / Decimal('1000000')
            return Decimal('0')

        cusd = asset_amount(self.CUSD_ASSET_ID)
        confio = asset_amount(self.CONFIO_ASSET_ID)
        usdc = asset_amount(self.USDC_ASSET_ID)

        app_id = getattr(settings, 'ALGORAND_PRESALE_APP_ID', 0)
        presale_locked = Decimal('0')
        if app_id:
            try:
                local = decode_local_state(info, int(app_id))
                user_confio = int(local.get('user_confio', 0) or 0)
                claimed = int(local.get('claimed', 0) or 0)
                locked = max(0, user_confio - claimed)
                presale_locked = Decimal(str(locked)) / Decimal('1000000')
            except Exception as e:
                logger.error("[snapshot] presale decode error for %s: %s", address, e)

        return {
            'CUSD': cusd,
            'CONFIO': confio,
            'USDC': usdc,
            'CONFIO_PRESALE': presale_locked,
        }
    
    async def get_presale_locked_confio(self, address: str, skip_cache: bool = False) -> Decimal:
        """Get presale-locked CONFIO amount for a user address.
        Computed as user_confio - claimed from local state of the presale app.
        """
        from django.conf import settings
        app_id = getattr(settings, 'ALGORAND_PRESALE_APP_ID', 0)
        if not app_id:
            logger.warning("[presale_locked] ALGORAND_PRESALE_APP_ID not configured; returning 0 for %s", address)
            return Decimal('0')
        cache_key = f"presale_locked_confio:{address}:{app_id}"
        if not skip_cache:
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
        try:
            account_info = self.algod.account_info(address)
            local = decode_local_state(account_info, int(app_id))
            user_confio = int(local.get('user_confio', 0) or 0)
            claimed = int(local.get('claimed', 0) or 0)
            locked = max(0, user_confio - claimed)
            locked_dec = Decimal(str(locked)) / Decimal('1000000')
            logger.info("[presale_locked] addr=%s app_id=%s user_confio=%s claimed=%s locked=%s",
                        address, app_id, user_confio, claimed, locked)
        except Exception as e:
            logger.error("[presale_locked] error for %s: %s", address, e)
            locked_dec = Decimal('0')
        if not skip_cache:
            cache.set(cache_key, locked_dec, 30)
        else:
            cache.delete(cache_key)
        return locked_dec
    
    
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

def get_algod_client():
    """
    Get a properly configured algod client for Nodely/Algonode
    This function handles authentication headers correctly for different providers.
    
    Usage:
        algod_client = get_algod_client()
        status = algod_client.status()
    """
    from django.conf import settings
    
    algod_address = settings.ALGORAND_ALGOD_ADDRESS
    algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '')
    
    ua = {'User-Agent': 'confio-backend/algosdk'}
    if 'nodely' in (algod_address or '').lower():
        headers = dict(ua)
        if algod_token:
            headers['X-API-Key'] = algod_token
        return algod.AlgodClient('', algod_address, headers=headers)
    else:
        return algod.AlgodClient(algod_token or '', algod_address, headers=ua)

def get_indexer_client():
    """
    Get a properly configured indexer client for Nodely/Algonode
    This function handles authentication headers correctly for different providers.
    
    Usage:
        indexer_client = get_indexer_client()
        health = indexer_client.health()
    """
    from django.conf import settings
    
    indexer_address = settings.ALGORAND_INDEXER_ADDRESS
    indexer_token = getattr(settings, 'ALGORAND_INDEXER_TOKEN', '')
    
    ua = {'User-Agent': 'confio-backend/algosdk'}
    if 'nodely' in (indexer_address or '').lower():
        headers = dict(ua)
        if indexer_token:
            headers['X-API-Key'] = indexer_token
        return indexer.IndexerClient('', indexer_address, headers=headers)
    else:
        return indexer.IndexerClient(indexer_token or '', indexer_address, headers=ua)

async def get_algorand_client() -> AlgorandClient:
    """
    Get an AlgorandClient instance for use in async with blocks
    
    Usage:
        async with await get_algorand_client() as client:
            balance = await client.get_usdc_balance(address)
    """
    return AlgorandClient()
