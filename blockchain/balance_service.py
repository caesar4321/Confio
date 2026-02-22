"""
Hybrid balance caching service - Fast reads with blockchain truth
"""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Optional
import logging

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import Balance
from .algorand_client import get_algorand_client
from users.models import Account

logger = logging.getLogger(__name__)


class BalanceService:
    """
    Hybrid balance service that provides:
    - Fast cached reads for UI
    - Periodic blockchain reconciliation
    - On-demand verification for critical operations
    """
    
    # Cache configuration
    CACHE_TTL = 300  # 5 minutes
    STALE_THRESHOLD = timedelta(minutes=5)
    RECONCILIATION_THRESHOLD = timedelta(hours=1)
    
    @classmethod
    def get_balance(
        cls,
        account: Account,
        token: str = 'CUSD',
        force_refresh: bool = False,
        verify_critical: bool = False
    ) -> Dict[str, Decimal]:
        """
        Get user balance with smart caching
        
        Args:
            account: User account
            token: Token type (CUSD, CONFIO, USDC)
            force_refresh: Force blockchain query
            verify_critical: Always query blockchain (for critical operations)
            
        Returns:
            Dict with 'amount', 'available', 'pending', 'last_synced'
        """
        # Critical operations or force refresh always hit blockchain
        if verify_critical or force_refresh:
            blockchain_data = cls._fetch_from_blockchain(account, token)
            
            # Clear all caches when force refreshing
            if force_refresh:
                cache_key = f"balance:{account.id}:{token}"
                cache.delete(cache_key)
                logger.info(f"Force refresh: cleared balance cache for {account.id}:{token}")
            
            # Update database with fresh data
            # Always refresh the cache after a force refresh so subsequent calls get the new value
            balance = cls._update_balance_cache(account, token, blockchain_data['amount'], skip_cache=False)
            
            return {
                'amount': balance.amount,
                'available': balance.available_amount,
                'pending': balance.pending_amount,
                'last_synced': balance.last_synced,
                'is_stale': False
            }
        
        # Try to get from cache first (normal flow)
        balance = cls._get_cached_balance(account, token)
        
        # Determine if we need to refresh
        needs_refresh = (
            balance is None or
            balance.is_stale or
            timezone.now() - balance.last_synced > cls.STALE_THRESHOLD
        )
        
        if needs_refresh:
            # Update from blockchain
            try:
                blockchain_data = cls._fetch_from_blockchain(account, token)
                balance = cls._update_balance_cache(account, token, blockchain_data['amount'])
            except Exception as e:
                logger.error(f"Failed to refresh balance: {e}")
                # Fall back to cached data if available
                if balance:
                    logger.warning(f"Using stale balance for {account}")
                else:
                    # No cache and blockchain failed
                    return {
                        'amount': Decimal('0'),
                        'available': Decimal('0'),
                        'pending': Decimal('0'),
                        'last_synced': None,
                        'is_stale': True
                    }
        
        return {
            'amount': balance.amount,
            'available': balance.available_amount,
            'pending': balance.pending_amount,
            'last_synced': balance.last_synced,
            'is_stale': balance.is_stale
        }
    
    @classmethod
    def get_all_balances(cls, account: Account, verify_critical: bool = False, force_refresh: bool = False) -> Dict[str, Dict]:
        """Get all token balances for an account using a single chain snapshot when needed."""
        tokens = ['ALGO', 'CUSD', 'CONFIO', 'USDC', 'CONFIO_PRESALE']
        # Quick path: if not forcing, try cached values and decide if refresh is needed
        if not force_refresh:
            cached = {t: cls._get_cached_balance(account, t) for t in tokens}
            now = timezone.now()
            needs = any(
                (b is None) or b.is_stale or (now - b.last_synced > cls.STALE_THRESHOLD)
                for b in cached.values()
            )
            if not needs:
                return {
                    'algo': cls._format_return(cached['ALGO']),
                    'cusd': cls._format_return(cached['CUSD']),
                    'confio': cls._format_return(cached['CONFIO']),
                    'usdc': cls._format_return(cached['USDC']),
                    'confio_presale': cls._format_return(cached['CONFIO_PRESALE']),
                }
        # Fetch fresh snapshot and update caches for all tokens
        data = cls._fetch_all_from_blockchain(account)
        # Update DB caches
        for t in tokens:
            cls._update_balance_cache(account, t, data.get(t, Decimal('0')))
        now = timezone.now()
        # Return formatted dict
        return {
            'algo': {'amount': data.get('ALGO', Decimal('0')), 'available': data.get('ALGO', Decimal('0')), 'pending': Decimal('0'), 'last_synced': now, 'is_stale': False},
            'cusd': {'amount': data.get('CUSD', Decimal('0')), 'available': data.get('CUSD', Decimal('0')), 'pending': Decimal('0'), 'last_synced': now, 'is_stale': False},
            'confio': {'amount': data.get('CONFIO', Decimal('0')), 'available': data.get('CONFIO', Decimal('0')), 'pending': Decimal('0'), 'last_synced': now, 'is_stale': False},
            'usdc': {'amount': data.get('USDC', Decimal('0')), 'available': data.get('USDC', Decimal('0')), 'pending': Decimal('0'), 'last_synced': now, 'is_stale': False},
            'confio_presale': {'amount': data.get('CONFIO_PRESALE', Decimal('0')), 'available': data.get('CONFIO_PRESALE', Decimal('0')), 'pending': Decimal('0'), 'last_synced': now, 'is_stale': False},
        }

    @classmethod
    def _format_return(cls, balance: Optional[Balance]) -> Dict[str, Decimal]:
        if not balance:
            return {'amount': Decimal('0'), 'available': Decimal('0'), 'pending': Decimal('0'), 'last_synced': None, 'is_stale': True}
        return {
            'amount': balance.amount,
            'available': balance.available_amount,
            'pending': balance.pending_amount,
            'last_synced': balance.last_synced,
            'is_stale': balance.is_stale,
        }

    @classmethod
    def _fetch_all_from_blockchain(cls, account: Account) -> Dict[str, Decimal]:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def fetch():
                async with await get_algorand_client() as client:
                    return await client.get_balances_snapshot(account.algorand_address, skip_cache=True)
            snapshot = loop.run_until_complete(fetch())
            logger.info("[balance_fetch_batch] addr=%s data=%s", account.algorand_address, snapshot)
            return snapshot or {}
        finally:
            loop.close()
    
    @classmethod
    def mark_stale(cls, account: Account, token: Optional[str] = None):
        """Mark balance(s) as stale after transaction"""
        if token:
            Balance.objects.filter(account=account, token=token).update(is_stale=True)
            # Clear Redis cache for this specific token
            cache.delete(f"balance:{account.id}:{token}")
        else:
            # Mark all balances as stale
            Balance.objects.filter(account=account).update(is_stale=True)
            # Clear Redis cache for all known tokens for this account
            for t in ['ALGO', 'CUSD', 'CONFIO', 'USDC', 'CONFIO_PRESALE']:
                cache.delete(f"balance:{account.id}:{t}")
    
    @classmethod
    def update_pending(cls, account: Account, token: str, pending_delta: Decimal):
        """Update pending amount for in-flight transactions"""
        with transaction.atomic():
            balance, _ = Balance.objects.get_or_create(
                account=account,
                token=token,
                defaults={'amount': Decimal('0')}
            )
            balance.pending_amount += pending_delta
            balance.save(update_fields=['pending_amount'])
    
    @classmethod
    def reconcile_user_balances(cls, account: Account) -> Dict[str, bool]:
        """
        Reconcile all balances for a user with blockchain using efficient batch fetching
        Returns dict of token -> success status
        """
        results = {}

        try:
            # Fetch ALL balances in one API call using get_balances_snapshot
            blockchain_balances = cls._fetch_all_from_blockchain(account)

            # Process each token
            for token in ['ALGO', 'CUSD', 'CONFIO', 'USDC', 'CONFIO_PRESALE']:
                try:
                    blockchain_amount = blockchain_balances.get(token, Decimal('0'))

                    # Get cached balance
                    balance = cls._get_cached_balance(account, token)

                    if balance:
                        # Check for discrepancy
                        discrepancy = abs(balance.amount - blockchain_amount)
                        if discrepancy > Decimal('0.000001'):  # Tiny threshold for rounding
                            logger.warning(
                                f"Balance discrepancy for {account} {token}: "
                                f"DB={balance.amount}, Chain={blockchain_amount}"
                            )
                            # Correct the balance
                            balance.amount = blockchain_amount
                            balance.is_stale = False
                            balance.last_blockchain_check = timezone.now()
                            balance.save()
                    else:
                        # Create new balance record
                        cls._update_balance_cache(account, token, blockchain_amount)

                    results[token] = True

                except Exception as e:
                    logger.error(f"Failed to reconcile {token} for {account}: {e}")
                    results[token] = False

        except Exception as e:
            logger.error(f"Failed to fetch blockchain balances for {account}: {e}")
            # Mark all as failed
            for token in ['ALGO', 'CUSD', 'CONFIO', 'USDC', 'CONFIO_PRESALE']:
                results[token] = False

        return results
    
    @classmethod
    def _get_cached_balance(cls, account: Account, token: str) -> Optional[Balance]:
        """Get balance from database cache"""
        # Check Redis first
        cache_key = f"balance:{account.id}:{token}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        # Get from database
        try:
            balance = Balance.objects.get(account=account, token=token)
            # Cache in Redis
            cache.set(cache_key, balance, cls.CACHE_TTL)
            return balance
        except Balance.DoesNotExist:
            return None
    
    @classmethod
    def _fetch_from_blockchain(cls, account: Account, token: str, skip_cache: bool = True) -> Dict[str, Decimal]:
        """Fetch balance directly from blockchain"""
        # Run async code in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def get_balance():
            async with await get_algorand_client() as client:
                if token == 'CUSD':
                    # Get actual cUSD balance from the cUSD asset
                    return await client.get_cusd_balance(account.algorand_address, skip_cache=skip_cache)
                elif token == 'CONFIO':
                    return await client.get_confio_balance(account.algorand_address, skip_cache=skip_cache)
                elif token == 'CONFIO_PRESALE':
                    return await client.get_presale_locked_confio(account.algorand_address, skip_cache=skip_cache)
                elif token == 'USDC':
                    return await client.get_usdc_balance(account.algorand_address, skip_cache=skip_cache)
                else:
                    return Decimal('0')
        
        try:
            amount = loop.run_until_complete(get_balance())
            logger.info("[balance_fetch] addr=%s token=%s amount=%s", account.algorand_address, token, amount)
            
            return {
                'amount': amount,
                'timestamp': timezone.now()
            }
            
        finally:
            loop.close()
    
    @classmethod
    def _update_balance_cache(
        cls,
        account: Account,
        token: str,
        amount: Decimal,
        skip_cache: bool = False
    ) -> Balance:
        """Update balance in database and cache"""
        with transaction.atomic():
            balance, created = Balance.objects.update_or_create(
                account=account,
                token=token,
                defaults={
                    'amount': amount,
                    'is_stale': False,
                    'last_synced': timezone.now(),
                    'last_blockchain_check': timezone.now(),
                    'sync_attempts': 0
                }
            )
        
        # Update Redis cache only if not force refreshing
        if not skip_cache:
            cache_key = f"balance:{account.id}:{token}"
            cache.set(cache_key, balance, cls.CACHE_TTL)
        
        return balance


# Convenience functions for GraphQL/views
def get_user_balance(user, token='CUSD', verify_critical=False):
    """Get balance for a user (handles Account lookup)"""
    try:
        account = user.accounts.filter(is_active=True).first()
        if not account:
            return None
        
        return BalanceService.get_balance(
            account,
            token,
            verify_critical=verify_critical
        )
    except Exception as e:
        logger.error(f"Error getting balance for user {user.id}: {e}")
        return None


def mark_user_balances_stale(user):
    """Mark all user balances as stale"""
    for account in user.accounts.filter(is_active=True):
        BalanceService.mark_stale(account)
