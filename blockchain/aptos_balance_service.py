"""
Aptos balance service for fetching custom token balances
"""
import asyncio
import logging
from decimal import Decimal
from typing import Dict, Optional
from django.core.cache import cache
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class AptosBalanceService:
    """Service for fetching Aptos blockchain balances"""
    
    # Cache settings
    CACHE_TIMEOUT = 60  # 1 minute cache for balances
    CACHE_PREFIX = "aptos_balance"
    
    # Token addresses on Aptos testnet
    USDC_ADDRESS = "0x69091fbab5f7d635ee7ac5098cf0c1efbe31d68fec0f2cd565e8d168daf52832"
    CUSD_ADDRESS = "0xe0ff8b1b72b21692bc125b2ad3087578aac8aea8803879bdc67adb92eeaa9a08"
    CONFIO_ADDRESS = "0x4ee337bec5c9bafe1d9b65265de67c08b29a0b5ed6f4c2da9f3abb3eab9251be"
    
    @classmethod
    def get_cache_key(cls, address: str) -> str:
        """Generate cache key for an address"""
        return f"{cls.CACHE_PREFIX}:{address}"
    
    @classmethod
    async def get_token_balance_async(cls, address: str, token_address: str, decimals: int = 6) -> Dict[str, any]:
        """
        Get token balance for an address (async) using Python Aptos SDK
        
        Args:
            address: User's Aptos address
            token_address: Token contract address
            decimals: Token decimal places (default 6 for USDC)
        
        Returns:
            {
                'amount': Decimal('100.5'),  # Token amount
                'raw': '100500000',  # Raw amount
                'last_synced': datetime
            }
        """
        try:
            from aptos_sdk.async_client import RestClient
            from aptos_sdk.account_address import AccountAddress
            import httpx
            
            # Use official Aptos Python SDK with proper GraphQL client
            if token_address in [cls.USDC_ADDRESS, cls.CUSD_ADDRESS, cls.CONFIO_ADDRESS]:
                # Query fungible asset balance using indexer GraphQL API
                indexer_url = "https://indexer-testnet.staging.gcp.aptosdev.com/v1/graphql"
                
                # Get fungible asset balance
                account_addr = AccountAddress.from_str(address)
                metadata_addr = AccountAddress.from_str(token_address)
                
                # Query for fungible asset balances
                query = """
                query GetAccountFungibleAssets($owner_address: String!, $asset_type: String!) {
                    current_fungible_asset_balances(
                        where: {
                            owner_address: {_eq: $owner_address},
                            asset_type: {_eq: $asset_type}
                        }
                    ) {
                        amount
                        asset_type
                    }
                }
                """
                
                variables = {
                    "owner_address": str(account_addr),
                    "asset_type": str(metadata_addr)
                }
                
                # Use httpx for GraphQL query (part of aptos-sdk dependencies)
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        indexer_url,
                        json={"query": query, "variables": variables},
                        headers={"Content-Type": "application/json"}
                    )
                    
                    if response.status_code != 200:
                        logger.error(f"Indexer query failed: {response.status_code}")
                        return {
                            'amount': Decimal('0'),
                            'raw': '0',
                            'last_synced': datetime.now(timezone.utc),
                            'error': f"Indexer query failed: {response.status_code}"
                        }
                    
                    result = response.json()
                    
                    if result and 'data' in result:
                        balances = result['data'].get('current_fungible_asset_balances', [])
                        if balances:
                            raw_balance = int(balances[0]['amount'])
                            token_amount = Decimal(raw_balance) / Decimal(10**decimals)
                            
                            logger.info(f"Found {token_address} balance via Aptos SDK: {raw_balance} raw = {token_amount} tokens")
                            
                            return {
                                'amount': token_amount,
                                'raw': str(raw_balance),
                                'last_synced': datetime.now(timezone.utc)
                            }
                
                # No balance found
                logger.info(f"No fungible asset balance found for {token_address} in account {address}")
                return {
                    'amount': Decimal('0'),
                    'raw': '0',
                    'last_synced': datetime.now(timezone.utc)
                }
            else:
                # Unknown token
                return {
                    'amount': Decimal('0'),
                    'raw': '0',
                    'last_synced': datetime.now(timezone.utc)
                }
                
        except Exception as e:
            logger.error(f"Error fetching token balance for {address}: {e}")
            return {
                'amount': Decimal('0'),
                'raw': '0',
                'last_synced': None,
                'error': str(e)
            }
    
    @classmethod
    def get_token_balance(cls, address: str, token_address: str, token_name: str, decimals: int = 6, use_cache: bool = True) -> Dict[str, any]:
        """
        Get token balance for an address (sync wrapper)
        
        Args:
            address: Aptos address
            token_address: Token contract address
            token_name: Token name for cache key
            decimals: Token decimal places
            use_cache: Whether to use cached values
            
        Returns:
            Balance data dictionary
        """
        # Check cache first
        if use_cache:
            cache_key = f"{cls.get_cache_key(address)}:{token_name}"
            cached_data = cache.get(cache_key)
            if cached_data:
                logger.debug(f"Using cached {token_name} balance for {address}")
                return cached_data
        
        # Fetch from blockchain
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            balance_data = loop.run_until_complete(cls.get_token_balance_async(address, token_address, decimals))
            
            # Cache the result
            if use_cache and not balance_data.get('error'):
                cache_key = f"{cls.get_cache_key(address)}:{token_name}"
                cache.set(cache_key, balance_data, cls.CACHE_TIMEOUT)
            
            return balance_data
        finally:
            loop.close()
    
    @classmethod
    def get_all_balances(cls, account: 'Account', use_cache: bool = True) -> Dict[str, Dict]:
        """
        Get all token balances for an account
        
        All custom tokens (CUSD, CONFIO, USDC) are now deployed on Aptos testnet.
        
        Returns:
            {
                # Custom tokens on Aptos
                'cusd': {'amount': Decimal('100.0'), 'available': Decimal('100.0'), 'pending': Decimal('0')},
                'confio': {'amount': Decimal('1000.0'), 'available': Decimal('1000.0'), 'pending': Decimal('0')},
                'usdc': {'amount': Decimal('100.5'), 'available': Decimal('100.5'), 'pending': Decimal('0')},
                # Legacy - no longer used
                'sui': {'amount': Decimal('0'), 'available': Decimal('0'), 'pending': Decimal('0')}
            }
        """
        # Log the address we're querying
        logger.info(f"[AptosBalanceService] Querying balances for address: {account.aptos_address}")
        
        # Validate Aptos address format (should start with 0x and be 64 chars + 2 for 0x)
        if not account.aptos_address or not account.aptos_address.startswith('0x') or len(account.aptos_address) != 66:
            logger.warning(f"[AptosBalanceService] Invalid Aptos address format: {account.aptos_address}")
            # This might be a Aptos address, return 0 balances
            return {
                'cusd': {'amount': Decimal('0'), 'available': Decimal('0'), 'pending': Decimal('0'), 'last_synced': datetime.now(timezone.utc)},
                'confio': {'amount': Decimal('0'), 'available': Decimal('0'), 'pending': Decimal('0'), 'last_synced': datetime.now(timezone.utc)},
                'usdc': {'amount': Decimal('0'), 'available': Decimal('0'), 'pending': Decimal('0'), 'last_synced': datetime.now(timezone.utc)},
                'sui': {'amount': Decimal('0'), 'available': Decimal('0'), 'pending': Decimal('0'), 'last_synced': datetime.now(timezone.utc)}
            }
        
        # Get token balances from Aptos
        usdc_balance = cls.get_token_balance(
            account.aptos_address,  # This will be the Aptos address
            cls.USDC_ADDRESS,
            'usdc',
            decimals=6,
            use_cache=use_cache
        )
        
        cusd_balance = cls.get_token_balance(
            account.aptos_address,
            cls.CUSD_ADDRESS,
            'cusd',
            decimals=6,
            use_cache=use_cache
        )
        
        confio_balance = cls.get_token_balance(
            account.aptos_address,
            cls.CONFIO_ADDRESS,
            'confio',
            decimals=6,
            use_cache=use_cache
        )
        
        # Return balances in expected format
        return {
            # cUSD on Aptos testnet
            'cusd': {
                'amount': cusd_balance['amount'],
                'available': cusd_balance['amount'],
                'pending': Decimal('0'),
                'last_synced': cusd_balance.get('last_synced', datetime.now(timezone.utc))
            },
            # CONFIO on Aptos testnet
            'confio': {
                'amount': confio_balance['amount'],
                'available': confio_balance['amount'],
                'pending': Decimal('0'),
                'last_synced': confio_balance.get('last_synced', datetime.now(timezone.utc))
            },
            # USDC on Aptos testnet
            'usdc': {
                'amount': usdc_balance['amount'],
                'available': usdc_balance['amount'],
                'pending': Decimal('0'),
                'last_synced': usdc_balance.get('last_synced', datetime.now(timezone.utc))
            },
            # Legacy Sui - no longer used
            'sui': {
                'amount': Decimal('0'),
                'available': Decimal('0'),
                'pending': Decimal('0'),
                'last_synced': datetime.now(timezone.utc)
            }
        }
    
    @classmethod
    def invalidate_cache(cls, address: str):
        """Invalidate cached balance for an address"""
        cache_key = cls.get_cache_key(address)
        cache.delete(cache_key)
        logger.info(f"Invalidated balance cache for {address}")