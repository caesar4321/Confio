"""
Algorand Sponsored Transaction Service backed by AWS KMS

Handles gas sponsorship for Algorand transactions using pooled/atomic transactions.
Uses AWS KMS-backed signing for sponsor keys.
"""

import base64
import logging
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import asyncio
from algosdk import account, encoding, transaction
from algosdk.atomic_transaction_composer import (
    AccountTransactionSigner,
    AtomicTransactionComposer,
    TransactionWithSigner,
)
from algosdk.transaction import (
    AssetTransferTxn,
    PaymentTxn,
    Transaction,
    calculate_group_id,
    wait_for_confirmation,
)
from algosdk.v2client import algod
from django.conf import settings
from django.core.cache import cache

from blockchain.kms_manager import get_kms_signer_from_settings

logger = logging.getLogger(__name__)


class AlgorandSponsorService:
    """
    Manages sponsored transactions for gas-free user experience on Algorand.
    
    Architecture:
    1. User creates and signs their transaction (0 fee)
    2. Server creates fee payment transaction from sponsor
    3. Both transactions grouped atomically
    4. Sponsor transactions are signed via AWS KMS
    5. Atomic group submitted to blockchain
    """
    
    # Cache keys
    SPONSOR_BALANCE_KEY = "algorand:sponsor:balance"
    SPONSOR_STATS_KEY = "algorand:sponsor:stats"
    
    # Thresholds
    MIN_SPONSOR_BALANCE = Decimal('0.5')  # Minimum 0.5 ALGO to operate
    WARNING_THRESHOLD = Decimal('2.0')    # Warn when below 2.0 ALGO
    MAX_FEE_PER_TX = 10000                # Max 0.01 ALGO per transaction
    
    def __init__(self):
        # Algorand node configuration - single source of truth
        self.algod_address = settings.ALGORAND_ALGOD_ADDRESS
        self.algod_token = getattr(settings, 'ALGORAND_ALGOD_TOKEN', '')

        self.signer = get_kms_signer_from_settings()
        self.sponsor_address = getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None) or self.signer.address

        # Client instances
        self._algod_client = None
    
    @property
    def algod(self) -> algod.AlgodClient:
        """Get algod client instance"""
        if not self._algod_client:
            from blockchain.algorand_client import get_algod_client
            self._algod_client = get_algod_client()
        return self._algod_client
    
    async def fund_account(self, address: str, amount_micro_algos: int) -> Dict[str, Any]:
        """
        Fund an account with the specified amount of ALGO.
        
        Args:
            address: The account address to fund
            amount_micro_algos: Amount to send in microAlgos
            
        Returns:
            Dict with success status and transaction details
        """
        try:
            # Check sponsor balance first
            health = await self.check_sponsor_health()
            if not health['can_sponsor']:
                return {
                    'success': False,
                    'error': 'Sponsor account has insufficient balance'
                }
            
            # Create payment transaction
            params = self.algod.suggested_params()
            funding_txn = PaymentTxn(
                sender=self.sponsor_address,
                sp=params,
                receiver=address,
                amt=amount_micro_algos,
                note=b"MBR funding for asset opt-in"
            )
            
            # Sign the transaction
            signed_txn = await self._sign_transaction(funding_txn)
            if not signed_txn:
                return {
                    'success': False,
                    'error': 'Failed to sign funding transaction'
                }
            
            # Submit the transaction
            try:
                tx_id = self.algod.send_raw_transaction(signed_txn)
                logger.info(f"Funding transaction submitted: {tx_id}")
                
                # Wait for confirmation (just a few rounds)
                try:
                    confirmed_txn = wait_for_confirmation(self.algod, tx_id, 4)
                    logger.info(f"Funding confirmed in round {confirmed_txn.get('confirmed-round')}")
                except Exception as e:
                    logger.warning(f"Confirmation wait failed: {e}, but transaction may still be confirmed")
                
                return {
                    'success': True,
                    'tx_id': tx_id,
                    'amount_algo': amount_micro_algos / 1_000_000
                }
            except Exception as e:
                logger.error(f"Failed to submit funding transaction: {e}")
                return {
                    'success': False,
                    'error': str(e)
                }
                
        except Exception as e:
            logger.error(f"Error funding account: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
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
            # IMPORTANT: Sponsor transaction must be first for proper fee payment
            if user_signed_txn:
                # User already signed, we need to reconstruct the unsigned version for grouping
                txn_group = [fee_payment_txn, user_txn]
            else:
                txn_group = [fee_payment_txn, user_txn]
            
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
            # Both need to be base64 encoded for consistency
            import base64
            user_txn_b64 = base64.b64encode(encoding.msgpack_encode(user_txn)).decode('utf-8')
            sponsor_txn_b64 = base64.b64encode(signed_fee_txn).decode('utf-8')
            
            return {
                'success': True,
                'user_transaction': user_txn_b64,
                'sponsor_transaction': sponsor_txn_b64,
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

    async def create_sponsored_execution(
        self,
        user_txn: Transaction
    ) -> Dict[str, Any]:
        """
        Create a sponsored execution for an arbitrary transaction (e.g. App Call).
        The user_txn fee will be set to 0.
        The sponsor will pay user_txn.fee + min_fee.
        
        Args:
            user_txn: The transaction object to sponsor
            
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
            
            # Calculate required fee
            # user_txn.fee should already be set to cover inner txns if needed (e.g. 3x min_fee)
            # We need to cover that PLUS the sponsor's own txn fee (1x min_fee)
            required_fee = user_txn.fee + params.min_fee
            
            # Set user fee to 0
            user_txn.fee = 0
            
            # Create fee payment transaction from sponsor
            fee_payment_txn = PaymentTxn(
                sender=self.sponsor_address,
                sp=params,
                receiver=user_txn.sender, # Send 0 to user (or anyone)
                amt=0,  # Just paying fees
                note=b"Fee sponsorship"
            )
            fee_payment_txn.fee = required_fee
            
            # Create atomic group
            # IMPORTANT: Sponsor transaction must be first for proper fee payment
            txn_group = [fee_payment_txn, user_txn]
            
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
            # Use encoding.msgpack_encode to properly encode the transaction with group ID
            user_txn_b64 = encoding.msgpack_encode(user_txn)
            sponsor_txn_b64 = signed_fee_txn
            
            return {
                'success': True,
                'user_transaction': user_txn_b64,
                'sponsor_transaction': sponsor_txn_b64,
                'group_id': gid.hex(),
                'total_fee': required_fee,
                'sponsored': True
            }
            
        except Exception as e:
            logger.error(f"Error creating sponsored execution: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def submit_solo_transaction(
        self,
        signed_txn: str
    ) -> Dict[str, Any]:
        """
        Submit a single signed transaction (not sponsored).
        
        Args:
            signed_txn: Base64 encoded signed transaction
            
        Returns:
            Dict with transaction result
        """
        try:
            logger.info(f"Submitting solo transaction, length: {len(signed_txn)}")
            
            # Decode transaction from base64
            try:
                stxn = base64.b64decode(signed_txn)
            except Exception as e:
                logger.error(f"Failed to decode transaction: {e}")
                return {
                    'success': False,
                    'error': f'Failed to decode transaction: {e}'
                }
            
            logger.info(f"Transaction bytes length: {len(stxn)}")
            
            # Submit single transaction
            try:
                # Send raw transaction bytes
                tx_id = self.algod.send_raw_transaction(stxn)
                logger.info(f"Solo transaction submitted: {tx_id}")
                
                # Wait for confirmation
                result = wait_for_confirmation(self.algod, tx_id, 4)
                
                return {
                    'success': True,
                    'tx_id': tx_id,
                    'confirmed_round': result.get('confirmed-round', 0),
                    'sponsored': False,
                    'fees_saved': 0  # No fees saved since user pays
                }
                
            except Exception as e:
                logger.error(f"Failed to submit solo transaction: {e}")
                return {
                    'success': False,
                    'error': f'Failed to submit transaction: {str(e)}'
                }
                
        except Exception as e:
            logger.error(f"Error submitting solo transaction: {e}")
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
        Sponsor transaction is always placed first to ensure proper fee payment and MBR funding.
        
        Args:
            signed_user_txn: Base64 encoded signed user transaction(s)
            signed_sponsor_txn: Base64 encoded signed sponsor transaction
            
        Returns:
            Dict with transaction result
        """
        try:
            # Enhanced debugging for transaction inputs
            logger.info(f"submit_sponsored_group called with:")
            logger.info(f"  signed_user_txn type: {type(signed_user_txn)} len={len(signed_user_txn) if signed_user_txn else 0}")
            logger.info(f"  signed_sponsor_txn type: {type(signed_sponsor_txn)} len={len(signed_sponsor_txn) if signed_sponsor_txn else 0}")

            # Decode user transaction(s)
            try:
                if isinstance(signed_user_txn, bytes):
                    user_stxn = signed_user_txn
                else:
                    # Strip potential whitespace
                    clean_user_txn = signed_user_txn.strip()
                    user_stxn = base64.b64decode(clean_user_txn)
            except Exception as e:
                logger.error(f"Failed to decode user transaction: {e}")
                logger.error(f"User txn content preview: {signed_user_txn[:50] if signed_user_txn else 'None'}")
                return {
                    'success': False,
                    'error': f'Failed to decode user transaction: {e}'
                }
            
            # Decode sponsor transaction
            try:
                # Check if it's already raw bytes or base64
                if isinstance(signed_sponsor_txn, bytes):
                    sponsor_stxn = signed_sponsor_txn
                else:
                     # Strip potential whitespace
                    clean_sponsor_txn = signed_sponsor_txn.strip()
                    sponsor_stxn = base64.b64decode(clean_sponsor_txn)
            except Exception as e:
                logger.error(f"Failed to decode sponsor transaction: {e}")
                logger.error(f"Sponsor txn content preview: {signed_sponsor_txn[:50] if signed_sponsor_txn else 'None'}")
                return {
                    'success': False,
                    'error': f'Failed to decode sponsor transaction: {e}'
                }
            
            logger.info(f"Decoded bytes length - User: {len(user_stxn)}, Sponsor: {len(sponsor_stxn)}")
            
            # Submit atomic group as base64-concatenated signed bytes
            try:
                logger.info(f"Concatenating raw bytes: Sponsor ({len(sponsor_stxn)}) + User ({len(user_stxn)})")
                
                # IMPORTANT: Sponsor first!
                combined_group = sponsor_stxn + user_stxn
                combined_b64 = base64.b64encode(combined_group).decode('utf-8')
                
                logger.info(f"Submitting {len(combined_group)} bytes to Algorand network via send_raw_transaction...")
                
                import time
                start_time = time.time()
                tx_id = self.algod.send_raw_transaction(combined_b64)
                elapsed_time = time.time() - start_time
                
                logger.info(f"Successfully submitted atomic group, tx_id: {tx_id}, took {elapsed_time:.2f} seconds")
            except Exception as e:
                logger.error(f"Failed to submit atomic group: {e}")
                
                # Aggressive debug logging on failure
                try:
                    logger.error(f"FAIL_DEBUG: User Txn B64: {base64.b64encode(user_stxn).decode('utf-8')}")
                    logger.error(f"FAIL_DEBUG: Sponsor Txn B64: {base64.b64encode(sponsor_stxn).decode('utf-8')}")
                except:
                    pass
                raise
            
            # Don't wait for confirmation - just return the tx_id immediately
            logger.info(f"Transaction submitted, not waiting for confirmation")
            
            # Update stats asynchronously (don't await)
            asyncio.create_task(self._update_sponsor_stats(2000))  # Approximate fee
            
            return {
                'success': True,
                'tx_id': tx_id,
                'confirmed_round': None,
                'sponsored': True,
                'fees_saved': 2000 / 1_000_000,
                'pending': True
            }
            
        except Exception as e:
            msg = str(e)
            logger.error(f"Error submitting sponsored group: {msg}")
            
            # Idempotency checks
            if 'transaction already in ledger' in msg:
                logger.warning(f"Transaction already in ledger (idempotent success): {msg}")
                parts = msg.split(':')
                tx_id = parts[-1].strip() if len(parts) > 1 else None
                return {
                    'success': True,
                    'tx_id': tx_id,
                    'confirmed_round': None,
                    'sponsored': True,
                    'fees_saved': 0.0,
                    'already_in_ledger': True,
                    'pending': False,
                }

            if 'has already opted in to app' in msg or 'already opted in' in msg.lower():
                logger.info("Treating 'already opted in' submission error as success (idempotent app opt-in)")
                return {
                    'success': True,
                    'tx_id': None,
                    'confirmed_round': None,
                    'sponsored': True,
                    'fees_saved': 0.0,
                    'already_opted_in': True,
                    'pending': False,
                }
                
            return {
                'success': False,
                'error': msg
            }
    
    async def _sign_transaction(self, txn: Transaction) -> Optional[str]:
        """
        Sign a transaction using the configured KMS signer.
        
        Args:
            txn: Transaction to sign
            
        Returns:
            Base64 encoded signed transaction or None if failed
        """
        try:
            return self.signer.sign_transaction_msgpack(txn)
            
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
        asset_id: int,
        funding_amount: int = 0
    ) -> Dict[str, Any]:
        """
        Create a sponsored opt-in transaction for an asset.
        
        Args:
            user_address: Address of the user opting in
            asset_id: Asset ID to opt into
            funding_amount: Optional amount (microAlgos) to fund the account with (for MBR)
            
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
                amt=funding_amount,  # MBR funding if needed
                note=b"Sponsored opt-in with MBR funding" if funding_amount > 0 else b"Opt-in fee sponsorship"
            )
            fee_payment_txn.fee = total_fee  # Sponsor pays all fees
            
            # Create atomic group
            # IMPORTANT: Sponsor transaction must be first for proper fee payment
            txn_group = [fee_payment_txn, opt_in_txn]
            
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
            user_txn_bytes = msgpack.packb(opt_in_txn.dictify(), use_bin_type=True)
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
        asset_id: int,
        funding_amount: int = 0
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
            opt_in_result = await self.create_sponsored_opt_in(user_address, asset_id, funding_amount=funding_amount)
            
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
            # IMPORTANT: Sponsor transaction must be first for proper fee payment
            txn_group = [fee_payment_txn, user_txn]
            
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
            user_txn_bytes = msgpack.packb(user_txn.dictify(), use_bin_type=True)
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
            # IMPORTANT: Sponsor transaction must be first for proper fee payment
            txn_group = [fee_payment_txn, user_txn]
            
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
    
    async def sign_sponsor_transaction(
        self,
        conversion_type: str,
        amount: Decimal
    ) -> Optional[bytes]:
        """
        Sign a sponsor transaction for cUSD conversion.
        This is called when executing a conversion with client-signed transactions.
        
        Args:
            conversion_type: Type of conversion ('usdc_to_cusd' or 'cusd_to_usdc')
            amount: Amount being converted
            
        Returns:
            Signed sponsor transaction bytes or None if failed
        """
        try:
            # For now, return a mock signed transaction
            # In production, this would:
            # 1. Build the fee payment transaction
            # 2. Sign with sponsor private key from KMS
            # 3. Return the signed transaction bytes
            
            logger.info(f"Signing sponsor transaction for {conversion_type} of {amount}")
            
            # TODO: Implement actual sponsor transaction signing
            # This requires the pre-built transaction from the client
            # For now, return None to indicate not implemented
            
            return None
            
        except Exception as e:
            logger.error(f"Error signing sponsor transaction: {e}")
            return None
    
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


async def create_sponsored_vault_funding(
    business_address: str,
    amount_base: int,
    payroll_app_id: int,
    payroll_asset_id: int
) -> Dict[str, Any]:
    """
    Create a sponsored vault funding transaction group.

    Contract expects exactly 2 transactions:
    [0] AXFER(business→app, amount, fee=0) - signed by business
    [1] AppCall(sponsor→app, fund_business, fee=2000) - signed by sponsor (pays all fees)

    Args:
        business_address: Business account address
        amount_base: Amount to fund in base units (e.g., cUSD with 6 decimals)
        payroll_app_id: Payroll application ID
        payroll_asset_id: Payroll asset ID

    Returns:
        Dict with unsigned business AXFER and signed sponsor AppCall
    """
    try:
        from algosdk.abi import Method, AddressType, UintType
        from algosdk import transaction, encoding, logic

        # Check sponsor health
        health = await algorand_sponsor_service.check_sponsor_health()
        if not health['can_sponsor']:
            return {
                'success': False,
                'error': 'Sponsor service unavailable',
                'details': health
            }

        app_addr = logic.get_application_address(payroll_app_id)

        # Ensure app has sufficient ALGO for vault MBR (separate transaction, not in group)
        try:
            app_info = algorand_sponsor_service.algod.account_info(app_addr)
            current_balance = app_info.get('amount', 0)
            min_balance = app_info.get('min-balance', 0)

            if current_balance < min_balance + 500_000:  # Need buffer for vault box
                logger.info(f"Auto-funding vault app {app_addr} for MBR (current: {current_balance}, min: {min_balance})")
                fund_result = await algorand_sponsor_service.fund_account(app_addr, 1_000_000)  # 1 ALGO
                if not fund_result.get('success'):
                    logger.warning(f"Vault MBR funding failed: {fund_result.get('error')}")
        except Exception as e:
            logger.warning(f"Could not check/fund vault MBR: {e}")

        # Transaction 0: cUSD asset transfer from business to app (user signs, 0 fee)
        params_user = algorand_sponsor_service.algod.suggested_params()
        params_user.flat_fee = True
        params_user.fee = 0  # User pays NO fee

        axfer = transaction.AssetTransferTxn(
            sender=business_address,
            sp=params_user,
            receiver=app_addr,
            amt=amount_base,
            index=payroll_asset_id,
        )

        # Transaction 1: App call from sponsor (pays all fees including AXFER)
        params_app = algorand_sponsor_service.algod.suggested_params()
        params_app.flat_fee = True
        params_app.fee = params_app.min_fee * 2  # Cover both transactions

        method = Method.from_signature("fund_business(address,uint64)void")
        addr_type = AddressType()
        u64_type = UintType(64)

        app_args = [
            method.get_selector(),
            addr_type.encode(business_address),
            u64_type.encode(amount_base),
        ]
        vault_key = b"VAULT" + encoding.decode_address(business_address)

        app_call = transaction.ApplicationNoOpTxn(
            sender=algorand_sponsor_service.sponsor_address,
            sp=params_app,
            index=payroll_app_id,
            app_args=app_args,
            boxes=[(payroll_app_id, vault_key)],
        )

        # Assign group ID - exactly 2 transactions as contract expects
        gid = transaction.calculate_group_id([axfer, app_call])
        axfer.group = gid
        app_call.group = gid

        # Sign sponsor app call
        signed_app_call = await algorand_sponsor_service._sign_transaction(app_call)

        if not signed_app_call:
            return {
                'success': False,
                'error': 'Failed to sign sponsor transaction'
            }

        # Return unsigned business AXFER and signed sponsor AppCall
        user_txn_b64 = encoding.msgpack_encode(axfer)

        return {
            'success': True,
            'user_transaction': user_txn_b64,  # Business signs this
            'sponsor_app_call': signed_app_call,  # Already signed
            'group_id': gid.hex(),
            'amount': float(amount_base) / 1_000_000,
        }

    except Exception as e:
        logger.error(f"Error creating sponsored vault funding: {e}")
        return {
            'success': False,
            'error': str(e)
        }


async def submit_sponsored_vault_funding(
    signed_user_txn: str,
    signed_sponsor_app_call: str
) -> Dict[str, Any]:
    """
    Submit a sponsored vault funding transaction group (2 transactions).

    Args:
        signed_user_txn: Base64 encoded signed business AXFER transaction
        signed_sponsor_app_call: Base64 encoded signed sponsor app call transaction

    Returns:
        Dict with transaction result
    """
    try:
        # Decode both transactions
        try:
            user_stxn = base64.b64decode(signed_user_txn)
        except Exception as e:
            logger.error(f"Failed to decode user transaction: {e}")
            return {
                'success': False,
                'error': f'Failed to decode user transaction: {e}'
            }

        try:
            app_call_stxn = signed_sponsor_app_call if isinstance(signed_sponsor_app_call, bytes) else base64.b64decode(signed_sponsor_app_call)
        except Exception as e:
            logger.error(f"Failed to decode sponsor app call: {e}")
            return {
                'success': False,
                'error': f'Failed to decode sponsor app call: {e}'
            }

        # Submit atomic group in correct order: [axfer, app_call]
        try:
            logger.info("Submitting sponsored vault funding group (2 txns)...")
            start_time = time.time()
            combined_b64 = base64.b64encode(user_stxn + app_call_stxn).decode('utf-8')
            tx_id = algorand_sponsor_service.algod.send_raw_transaction(combined_b64)
            elapsed_time = time.time() - start_time
            logger.info(f"Successfully submitted vault funding group, tx_id: {tx_id}, took {elapsed_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Failed to submit vault funding group: {e}")
            raise

        return {
            'success': True,
            'tx_id': tx_id,
            'confirmed_round': None,
            'sponsored': True,
            'pending': True
        }

    except Exception as e:
        msg = str(e)
        logger.error(f"Error submitting sponsored vault funding: {msg}")
        return {
            'success': False,
            'error': msg
        }
