"""
Algorand Sponsored Transaction Service with KMD Integration

Handles gas sponsorship for Algorand transactions using pooled/atomic transactions.
Uses KMD (Key Management Daemon) for secure sponsor key management.
"""

import asyncio
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal
from algosdk.v2client import algod
from algosdk.kmd import KMDClient
from algosdk import account, mnemonic, transaction, encoding
from algosdk.transaction import PaymentTxn, AssetTransferTxn, Transaction, calculate_group_id
from algosdk.atomic_transaction_composer import AtomicTransactionComposer, TransactionWithSigner, AccountTransactionSigner
from django.conf import settings
from django.core.cache import cache
import logging
import base64
import time

logger = logging.getLogger(__name__)


class AlgorandSponsorService:
    """
    Manages sponsored transactions for gas-free user experience on Algorand.
    
    Architecture:
    1. User creates and signs their transaction (0 fee)
    2. Server creates fee payment transaction from sponsor
    3. Both transactions grouped atomically
    4. KMD signs sponsor transaction securely
    5. Atomic group submitted to blockchain
    """
    
    # Cache keys
    SPONSOR_BALANCE_KEY = "algorand:sponsor:balance"
    SPONSOR_STATS_KEY = "algorand:sponsor:stats"
    KMD_HANDLE_KEY = "algorand:kmd:handle"
    
    # Thresholds
    MIN_SPONSOR_BALANCE = Decimal('0.5')  # Minimum 0.5 ALGO to operate
    WARNING_THRESHOLD = Decimal('2.0')    # Warn when below 2.0 ALGO
    MAX_FEE_PER_TX = 10000                # Max 0.01 ALGO per transaction
    
    def __init__(self):
        # Algorand node configuration
        self.algod_address = getattr(settings, 'ALGORAND_ALGOD_ADDRESS', 'https://testnet-api.algonode.cloud')
        self.algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '')
        
        # KMD configuration (for secure key management)
        self.kmd_address = getattr(settings, 'ALGORAND_KMD_ADDRESS', 'http://localhost:4002')
        self.kmd_token = getattr(settings, 'ALGORAND_KMD_TOKEN', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')
        self.kmd_wallet_name = getattr(settings, 'ALGORAND_KMD_WALLET_NAME', 'sponsor_wallet')
        self.kmd_wallet_password = getattr(settings, 'ALGORAND_KMD_WALLET_PASSWORD', 'sponsor_password')
        
        # Sponsor configuration - try direct attribute first, then BLOCKCHAIN_CONFIG
        self.sponsor_address = getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None)
        if not self.sponsor_address and hasattr(settings, 'BLOCKCHAIN_CONFIG'):
            self.sponsor_address = settings.BLOCKCHAIN_CONFIG.get('ALGORAND_SPONSOR_ADDRESS')
        
        self.sponsor_mnemonic = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
        if not self.sponsor_mnemonic and hasattr(settings, 'BLOCKCHAIN_CONFIG'):
            self.sponsor_mnemonic = settings.BLOCKCHAIN_CONFIG.get('ALGORAND_SPONSOR_MNEMONIC')
        
        # Client instances
        self._algod_client = None
        self._kmd_client = None
        self._wallet_handle = None
    
    @property
    def algod(self) -> algod.AlgodClient:
        """Get algod client instance"""
        if not self._algod_client:
            self._algod_client = algod.AlgodClient(self.algod_token, self.algod_address)
        return self._algod_client
    
    @property
    def kmd_client(self) -> KMDClient:
        """Get KMD client instance"""
        if not self._kmd_client:
            self._kmd_client = KMDClient(self.kmd_token, self.kmd_address)
        return self._kmd_client
    
    async def get_wallet_handle(self) -> str:
        """Get or create KMD wallet handle"""
        # Check cache first
        cached_handle = cache.get(self.KMD_HANDLE_KEY)
        if cached_handle:
            try:
                # Verify handle is still valid
                self.kmd_client.list_keys(cached_handle)
                return cached_handle
            except:
                # Handle expired, get new one
                pass
        
        try:
            # List wallets
            wallets = self.kmd_client.list_wallets()
            wallet_id = None
            
            for wallet in wallets:
                if wallet['name'] == self.kmd_wallet_name:
                    wallet_id = wallet['id']
                    break
            
            if not wallet_id:
                # Create wallet if it doesn't exist
                wallet_id = self.kmd_client.create_wallet(
                    self.kmd_wallet_name,
                    self.kmd_wallet_password
                )['id']
                
                # Import sponsor key if we have mnemonic
                if self.sponsor_mnemonic:
                    handle = self.kmd_client.init_wallet_handle(
                        wallet_id,
                        self.kmd_wallet_password
                    )
                    self.kmd_client.import_key(
                        handle,
                        mnemonic.to_private_key(self.sponsor_mnemonic)
                    )
            
            # Get wallet handle
            handle = self.kmd_client.init_wallet_handle(
                wallet_id,
                self.kmd_wallet_password
            )
            
            # Cache for 5 minutes
            cache.set(self.KMD_HANDLE_KEY, handle, 300)
            
            return handle
            
        except Exception as e:
            logger.error(f"Error getting KMD wallet handle: {e}")
            # Fall back to using mnemonic directly if KMD unavailable
            return None
    
    async def check_sponsor_health(self) -> Dict[str, Any]:
        """
        Check sponsor account health and balance.
        
        Returns:
            Dict with health status, balance, and recommendations
        """
        try:
            if not self.sponsor_address:
                return {
                    'healthy': False,
                    'error': 'ALGORAND_SPONSOR_ADDRESS not configured',
                    'balance': Decimal('0'),
                    'can_sponsor': False
                }
            
            # Check cached balance first
            cached_balance = cache.get(self.SPONSOR_BALANCE_KEY)
            if cached_balance is None:
                # Get fresh balance from blockchain
                account_info = self.algod.account_info(self.sponsor_address)
                balance = Decimal(str(account_info['amount'] / 1_000_000))  # Convert to ALGO
                cache.set(self.SPONSOR_BALANCE_KEY, balance, timeout=60)
            else:
                balance = cached_balance
            
            # Get stats
            stats = cache.get(self.SPONSOR_STATS_KEY, {
                'total_sponsored': 0,
                'total_fees_paid': 0,
                'failed_transactions': 0
            })
            
            # Determine health
            healthy = balance > self.MIN_SPONSOR_BALANCE
            warning = balance < self.WARNING_THRESHOLD
            
            return {
                'healthy': healthy,
                'warning': warning,
                'balance': balance,
                'balance_formatted': f"{balance} ALGO",
                'can_sponsor': healthy,
                'estimated_transactions': int(balance / Decimal('0.002')) if healthy else 0,
                'stats': stats,
                'recommendations': self._get_recommendations(balance)
            }
            
        except Exception as e:
            logger.error(f"Error checking sponsor health: {e}")
            return {
                'healthy': False,
                'error': str(e),
                'balance': Decimal('0'),
                'can_sponsor': False
            }
    
    def _get_recommendations(self, balance: Decimal) -> List[str]:
        """Get recommendations based on balance"""
        recommendations = []
        
        if balance < self.MIN_SPONSOR_BALANCE:
            recommendations.append(f"URGENT: Refill sponsor account. Need at least {self.MIN_SPONSOR_BALANCE} ALGO")
        elif balance < self.WARNING_THRESHOLD:
            recommendations.append(f"WARNING: Low balance. Consider refilling to maintain service")
        
        if balance > Decimal('100'):
            recommendations.append("Consider implementing multi-sponsor setup for redundancy")
        
        return recommendations
    
    async def create_sponsored_transaction(
        self,
        user_address: str,
        user_transaction: Dict[str, Any],
        user_signed_txn: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a sponsored transaction using atomic group.
        
        Args:
            user_address: Address of the user making the transaction
            user_transaction: The unsigned transaction from user (as dict)
            user_signed_txn: Base64 encoded signed transaction from user
            
        Returns:
            Dict with transaction result or error
        """
        try:
            # Check sponsor health
            health = await self.check_sponsor_health()
            if not health['can_sponsor']:
                return {
                    'success': False,
                    'error': 'Sponsor service unavailable',
                    'details': health
                }
            
            # Get suggested params
            params = self.algod.suggested_params()
            
            # Decode user's signed transaction if provided
            if user_signed_txn:
                user_stxn = encoding.msgpack_decode(base64.b64decode(user_signed_txn))
            else:
                # Build unsigned transaction from dict
                if user_transaction['type'] == 'pay':
                    user_txn = PaymentTxn(
                        sender=user_address,
                        sp=params,
                        receiver=user_transaction['receiver'],
                        amt=user_transaction['amount'],
                        note=user_transaction.get('note', '').encode()
                    )
                elif user_transaction['type'] == 'axfer':
                    user_txn = AssetTransferTxn(
                        sender=user_address,
                        sp=params,
                        receiver=user_transaction['receiver'],
                        amt=user_transaction['amount'],
                        index=user_transaction['asset_id'],
                        note=user_transaction.get('note', '').encode()
                    )
                else:
                    raise ValueError(f"Unsupported transaction type: {user_transaction['type']}")
                
                # Set fee to 0 for user transaction
                user_txn.fee = 0
            
            # Calculate total fees (user tx + sponsor tx)
            total_fee = params.min_fee * 2  # Fee for both transactions
            
            # Create fee payment transaction from sponsor
            fee_payment_txn = PaymentTxn(
                sender=self.sponsor_address,
                sp=params,
                receiver=user_address,
                amt=0,  # Just paying fees, no ALGO transfer
                note=b"Fee sponsorship"
            )
            fee_payment_txn.fee = total_fee  # Sponsor pays all fees
            
            # Create atomic group
            if user_signed_txn:
                # User already signed, we need to reconstruct the unsigned version for grouping
                txn_group = [user_txn, fee_payment_txn]
            else:
                txn_group = [user_txn, fee_payment_txn]
            
            # Assign group ID
            gid = calculate_group_id(txn_group)
            for txn in txn_group:
                txn.group = gid
            
            # Sign sponsor transaction
            signed_fee_txn = await self._sign_transaction(fee_payment_txn)
            
            if not signed_fee_txn:
                return {
                    'success': False,
                    'error': 'Failed to sign sponsor transaction'
                }
            
            # Return unsigned user transaction and signed sponsor transaction
            # Client will sign user transaction and submit both
            return {
                'success': True,
                'user_transaction': encoding.msgpack_encode(user_txn),
                'sponsor_transaction': signed_fee_txn,
                'group_id': gid.hex(),
                'total_fee': total_fee,
                'sponsored': True
            }
            
        except Exception as e:
            logger.error(f"Error creating sponsored transaction: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def submit_sponsored_group(
        self,
        signed_user_txn: str,
        signed_sponsor_txn: str
    ) -> Dict[str, Any]:
        """
        Submit a complete sponsored transaction group.
        
        Args:
            signed_user_txn: Base64 encoded signed user transaction
            signed_sponsor_txn: Base64 encoded signed sponsor transaction
            
        Returns:
            Dict with transaction result
        """
        try:
            # Decode transactions from base64
            logger.info(f"Received signed_user_txn length: {len(signed_user_txn)}")
            logger.info(f"Received signed_sponsor_txn length: {len(signed_sponsor_txn)}")
            logger.info(f"First 50 chars of user txn: {signed_user_txn[:50]}")
            
            try:
                user_stxn = base64.b64decode(signed_user_txn)
            except Exception as e:
                logger.error(f"Failed to decode user transaction: {e}")
                return {
                    'success': False,
                    'error': f'Failed to decode user transaction: {e}'
                }
            
            try:
                # Check if it's already raw bytes or base64
                if isinstance(signed_sponsor_txn, bytes):
                    sponsor_stxn = signed_sponsor_txn
                else:
                    sponsor_stxn = base64.b64decode(signed_sponsor_txn)
            except Exception as e:
                logger.error(f"Failed to decode sponsor transaction: {e}")
                logger.error(f"Sponsor txn type: {type(signed_sponsor_txn)}, length: {len(signed_sponsor_txn)}")
                return {
                    'success': False,
                    'error': f'Failed to decode sponsor transaction: {e}'
                }
            
            # The transactions are already properly encoded as msgpack
            # For atomic group submission in Algorand, we concatenate the raw transaction bytes
            logger.info(f"User transaction bytes length: {len(user_stxn)}")
            logger.info(f"Sponsor transaction bytes length: {len(sponsor_stxn)}")
            
            # Combine transactions for atomic group submission
            # In Algorand, atomic groups are submitted by concatenating the signed transactions
            combined_txns = user_stxn + sponsor_stxn
            logger.info(f"Combined transaction bytes length: {len(combined_txns)}")
            
            # Submit the atomic group to the network
            # For Algorand atomic groups, the standard is to concatenate the signed transactions
            # The send_raw_transaction expects base64 encoded string, not raw bytes
            try:
                # Encode the combined transactions to base64
                combined_b64 = base64.b64encode(combined_txns).decode('utf-8')
                tx_id = self.algod.send_raw_transaction(combined_b64)
                logger.info(f"Successfully submitted atomic group, tx_id: {tx_id}")
                    
            except Exception as e:
                logger.error(f"Failed to submit atomic group: {e}")
                # Try to provide more detail about the error
                if "msgpack decode error" in str(e):
                    logger.error("Transaction format error - transactions may not be properly encoded")
                    logger.error(f"First 20 bytes of user txn: {user_stxn[:20].hex() if len(user_stxn) >= 20 else user_stxn.hex()}")
                    logger.error(f"First 20 bytes of sponsor txn: {sponsor_stxn[:20].hex() if len(sponsor_stxn) >= 20 else sponsor_stxn.hex()}")
                raise
            
            # Wait for confirmation
            confirmed_txn = transaction.wait_for_confirmation(
                self.algod, tx_id, 4
            )
            
            # Update stats
            await self._update_sponsor_stats(2000)  # Approximate fee
            
            return {
                'success': True,
                'tx_id': tx_id,
                'confirmed_round': confirmed_txn.get('confirmed-round'),
                'sponsored': True,
                'fees_saved': 2000 / 1_000_000  # Convert to ALGO
            }
            
        except Exception as e:
            logger.error(f"Error submitting sponsored group: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def _sign_transaction(self, txn: Transaction) -> Optional[str]:
        """
        Sign a transaction using KMD or fallback to mnemonic.
        
        Args:
            txn: Transaction to sign
            
        Returns:
            Base64 encoded signed transaction or None if failed
        """
        try:
            # Try KMD first
            wallet_handle = await self.get_wallet_handle()
            if wallet_handle:
                try:
                    # Sign with KMD
                    signed = self.kmd_client.sign_transaction(
                        wallet_handle,
                        self.kmd_wallet_password,
                        txn
                    )
                    return base64.b64encode(signed).decode('utf-8')
                except Exception as e:
                    logger.warning(f"KMD signing failed, falling back to mnemonic: {e}")
            
            # Fallback to mnemonic if KMD unavailable
            if self.sponsor_mnemonic:
                private_key = mnemonic.to_private_key(self.sponsor_mnemonic)
                signed_txn = txn.sign(private_key)
                # The sign method returns a SignedTransaction object
                # Use encoding.msgpack_encode to get the properly formatted bytes
                signed_bytes = encoding.msgpack_encode(signed_txn)
                # msgpack_encode returns base64, so just return it
                return signed_bytes
            
            logger.error("No signing method available")
            return None
            
        except Exception as e:
            logger.error(f"Error signing transaction: {e}")
            return None
    
    async def _update_sponsor_stats(self, fee_used: int):
        """Update sponsor statistics"""
        stats = cache.get(self.SPONSOR_STATS_KEY, {
            'total_sponsored': 0,
            'total_fees_paid': 0,
            'failed_transactions': 0
        })
        
        stats['total_sponsored'] += 1
        stats['total_fees_paid'] += fee_used
        
        cache.set(self.SPONSOR_STATS_KEY, stats, timeout=86400)  # 24 hours
        
        # Invalidate balance cache to force refresh
        cache.delete(self.SPONSOR_BALANCE_KEY)
    
    async def create_sponsored_opt_in(
        self,
        user_address: str,
        asset_id: int
    ) -> Dict[str, Any]:
        """
        Create a sponsored opt-in transaction for an asset.
        
        Args:
            user_address: Address of the user opting in
            asset_id: Asset ID to opt into
            
        Returns:
            Dict with transaction result or error
        """
        try:
            # Check sponsor health
            health = await self.check_sponsor_health()
            if not health['can_sponsor']:
                return {
                    'success': False,
                    'error': 'Sponsor service unavailable',
                    'details': health
                }
            
            # Get suggested params
            params = self.algod.suggested_params()
            
            # Create opt-in transaction (0 amount transfer to self) with 0 fee
            opt_in_txn = AssetTransferTxn(
                sender=user_address,
                sp=params,
                receiver=user_address,
                amt=0,
                index=asset_id
            )
            opt_in_txn.fee = 0  # User pays no fee
            
            # Calculate total fees
            total_fee = params.min_fee * 2
            
            # Create fee payment transaction from sponsor
            fee_payment_txn = PaymentTxn(
                sender=self.sponsor_address,
                sp=params,
                receiver=user_address,
                amt=0,  # No ALGO transfer, just paying fees
                note=b"Opt-in fee sponsorship"
            )
            fee_payment_txn.fee = total_fee  # Sponsor pays all fees
            
            # Create atomic group
            txn_group = [opt_in_txn, fee_payment_txn]
            
            # Assign group ID
            gid = calculate_group_id(txn_group)
            for txn in txn_group:
                txn.group = gid
            
            # Sign sponsor transaction
            signed_fee_txn = await self._sign_transaction(fee_payment_txn)
            
            if not signed_fee_txn:
                return {
                    'success': False,
                    'error': 'Failed to sign sponsor transaction'
                }
            
            # Return transaction data for client signing or server execution
            # Encode the user transaction as base64 for client
            import msgpack
            user_txn_bytes = msgpack.packb(opt_in_txn.dictify())
            user_txn_b64 = base64.b64encode(user_txn_bytes).decode('utf-8')
            
            return {
                'success': True,
                'user_transaction': user_txn_b64,
                'sponsor_transaction': signed_fee_txn,
                'group_id': gid.hex(),
                'total_fee': total_fee,
                'asset_id': asset_id
            }
            
        except Exception as e:
            logger.error(f"Error creating sponsored opt-in: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def execute_server_side_opt_in(
        self,
        user_address: str,
        asset_id: int
    ) -> Dict[str, Any]:
        """
        Execute a fully server-side sponsored opt-in without requiring user signature.
        This works only if the server has the user's private key (not for Web3Auth).
        
        For Web3Auth users, we'll return the unsigned transaction for frontend signing.
        """
        try:
            # Check if already opted in
            try:
                account_info = self.algod.account_info(user_address)
                assets = account_info.get('assets', [])
                
                if any(asset['asset-id'] == asset_id for asset in assets):
                    logger.info(f"Account {user_address} already opted into asset {asset_id}")
                    return {
                        'success': True,
                        'already_opted_in': True,
                        'asset_id': asset_id
                    }
            except Exception as e:
                logger.warning(f"Could not check opt-in status: {e}")
            
            # Create sponsored opt-in
            opt_in_result = await self.create_sponsored_opt_in(user_address, asset_id)
            
            if not opt_in_result['success']:
                return opt_in_result
            
            # For Web3Auth, return unsigned transaction for frontend
            return {
                'success': True,
                'requires_user_signature': True,
                'user_transaction': opt_in_result['user_transaction'],
                'sponsor_transaction': opt_in_result['sponsor_transaction'],
                'group_id': opt_in_result['group_id'],
                'asset_id': asset_id,
                'message': 'Please sign the opt-in transaction in your wallet'
            }
            
        except Exception as e:
            logger.error(f"Error executing server-side opt-in: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def create_sponsored_transfer(
        self,
        sender: str,
        recipient: str,
        amount: Decimal,
        asset_id: Optional[int] = None,
        note: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a sponsored transfer transaction for client signing.
        Similar to create_sponsored_opt_in but for transfers.
        
        Args:
            sender: Sender's Algorand address
            recipient: Recipient's Algorand address
            amount: Amount to send
            asset_id: Asset ID for ASA transfer, None for ALGO transfer
            note: Optional transaction note
            
        Returns:
            Dict with unsigned user transaction and signed sponsor transaction
        """
        try:
            # Check sponsor health
            health = await self.check_sponsor_health()
            if not health['can_sponsor']:
                return {
                    'success': False,
                    'error': 'Sponsor service unavailable',
                    'details': health
                }
            
            # Get suggested params
            params = self.algod.suggested_params()
            
            # Create user transaction with 0 fee
            if asset_id is None:
                # ALGO transfer
                amount_microalgos = int(amount * 1_000_000)
                user_txn = PaymentTxn(
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
                
                user_txn = AssetTransferTxn(
                    sender=sender,
                    sp=params,
                    receiver=recipient,
                    amt=amount_units,
                    index=asset_id,
                    note=note.encode() if note else None
                )
            
            user_txn.fee = 0  # User pays no fee
            
            # Calculate total fees
            total_fee = params.min_fee * 2
            
            # Create fee payment transaction from sponsor
            fee_payment_txn = PaymentTxn(
                sender=self.sponsor_address,
                sp=params,
                receiver=sender,
                amt=0,  # Just paying fees, no ALGO transfer
                note=b"Transfer fee sponsorship"
            )
            fee_payment_txn.fee = total_fee  # Sponsor pays all fees
            
            # Create atomic group
            txn_group = [user_txn, fee_payment_txn]
            
            # Assign group ID
            gid = calculate_group_id(txn_group)
            for txn in txn_group:
                txn.group = gid
            
            # Sign sponsor transaction
            signed_fee_txn = await self._sign_transaction(fee_payment_txn)
            
            if not signed_fee_txn:
                return {
                    'success': False,
                    'error': 'Failed to sign sponsor transaction'
                }
            
            # Return transaction data for client signing
            # Encode the user transaction as base64 for client
            import msgpack
            user_txn_bytes = msgpack.packb(user_txn.dictify())
            user_txn_b64 = base64.b64encode(user_txn_bytes).decode('utf-8')
            
            return {
                'success': True,
                'user_transaction': user_txn_b64,
                'sponsor_transaction': signed_fee_txn,
                'group_id': gid.hex(),
                'total_fee': total_fee,
                'amount': str(amount),
                'recipient': recipient,
                'asset_id': asset_id
            }
            
        except Exception as e:
            logger.error(f"Error creating sponsored transfer: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def create_and_submit_sponsored_transfer(
        self,
        sender: str,
        recipient: str,
        amount: Decimal,
        asset_id: Optional[int] = None,
        note: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create and submit a fully sponsored transfer transaction.
        This method handles everything server-side.
        
        Args:
            sender: Sender's Algorand address
            recipient: Recipient's Algorand address
            amount: Amount to send
            asset_id: Asset ID for ASA transfer, None for ALGO transfer
            note: Optional transaction note
            
        Returns:
            Dict with transaction result
        """
        try:
            # Check sponsor health
            health = await self.check_sponsor_health()
            if not health['can_sponsor']:
                return {
                    'success': False,
                    'error': 'Sponsor service unavailable',
                    'details': health
                }
            
            # Get suggested params
            params = self.algod.suggested_params()
            
            # Create user transaction with 0 fee
            if asset_id is None:
                # ALGO transfer
                amount_microalgos = int(amount * 1_000_000)
                user_txn = PaymentTxn(
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
                
                user_txn = AssetTransferTxn(
                    sender=sender,
                    sp=params,
                    receiver=recipient,
                    amt=amount_units,
                    index=asset_id,
                    note=note.encode() if note else None
                )
            
            user_txn.fee = 0  # User pays no fee
            
            # Calculate total fees
            total_fee = params.min_fee * 2
            
            # Create fee payment transaction from sponsor
            fee_payment_txn = PaymentTxn(
                sender=self.sponsor_address,
                sp=params,
                receiver=sender,
                amt=total_fee,  # Transfer the fee amount to user
                note=b"Fee sponsorship"
            )
            fee_payment_txn.fee = total_fee  # Sponsor pays all fees
            
            # Create atomic group
            txn_group = [user_txn, fee_payment_txn]
            
            # Assign group ID
            gid = calculate_group_id(txn_group)
            for txn in txn_group:
                txn.group = gid
            
            # Return transaction data for client signing
            return {
                'success': True,
                'user_transaction': {
                    'txn': encoding.msgpack_encode(user_txn),
                    'type': 'transfer',
                    'amount': str(amount),
                    'recipient': recipient
                },
                'sponsor_transaction': {
                    'txn': encoding.msgpack_encode(fee_payment_txn),
                    'signed': await self._sign_transaction(fee_payment_txn)
                },
                'group_id': gid.hex(),
                'total_fee': total_fee,
                'fee_in_algo': total_fee / 1_000_000
            }
            
        except Exception as e:
            logger.error(f"Error creating sponsored transfer: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def estimate_sponsorship_cost(
        self,
        transaction_type: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Estimate the fee cost for sponsoring a transaction.
        
        Returns estimated fee cost and sponsor availability.
        """
        try:
            # Get current network parameters
            params = self.algod.suggested_params()
            
            # Base fees by transaction type
            tx_count = {
                'transfer': 2,      # User transfer + sponsor fee payment
                'opt_in': 2,       # User opt-in + sponsor fee payment
                'close': 2,        # User close + sponsor fee payment
                'swap': 3,         # Two transfers + sponsor fee payment
                'custom': 2        # Default
            }
            
            num_txns = tx_count.get(transaction_type, tx_count['custom'])
            total_fee = params.min_fee * num_txns
            
            # Check sponsor availability
            health = await self.check_sponsor_health()
            
            return {
                'estimated_fee': total_fee,
                'estimated_fee_algo': total_fee / 1_000_000,
                'sponsor_available': health['can_sponsor'],
                'sponsor_balance': health['balance'],
                'can_afford': health['balance'] > Decimal(total_fee / 1_000_000),
                'transaction_type': transaction_type,
                'transactions_in_group': num_txns
            }
            
        except Exception as e:
            logger.error(f"Error estimating sponsorship cost: {e}")
            return {
                'estimated_fee': 2000,  # Default fallback
                'estimated_fee_algo': 0.002,
                'sponsor_available': False,
                'error': str(e)
            }


# Singleton instance
algorand_sponsor_service = AlgorandSponsorService()


# Helper functions for GraphQL mutations
async def sponsor_algorand_transfer(
    sender: str,
    recipient: str,
    amount: Decimal,
    asset_id: Optional[int] = None,
    note: Optional[str] = None
) -> Dict[str, Any]:
    """
    Helper function to sponsor an Algorand transfer.
    
    This can be called from GraphQL mutations or API endpoints.
    """
    return await algorand_sponsor_service.create_and_submit_sponsored_transfer(
        sender=sender,
        recipient=recipient,
        amount=amount,
        asset_id=asset_id,
        note=note
    )


async def get_sponsor_status() -> Dict[str, Any]:
    """Get current sponsor service status"""
    return await algorand_sponsor_service.check_sponsor_health()