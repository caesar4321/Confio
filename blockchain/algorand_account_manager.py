"""
Algorand Account Manager - Handles account creation and asset opt-ins
"""
import logging
import os
from typing import Dict, Optional, Tuple
from decimal import Decimal
from algosdk import account, mnemonic
from algosdk.v2client import algod
from algosdk.transaction import PaymentTxn, AssetTransferTxn, wait_for_confirmation, assign_group_id
from django.conf import settings
from django.db import transaction as db_transaction
from users.models import Account

logger = logging.getLogger(__name__)


class AlgorandAccountManager:
    """
    Manages Algorand account creation and asset opt-ins for users
    """
    
    # Determine network from environment or settings
    NETWORK = os.environ.get('ALGORAND_NETWORK', getattr(settings, 'ALGORAND_NETWORK', 'testnet')).lower()
    
    # Network-specific configurations
    NETWORK_CONFIGS = {
        'localnet': {
            'algod_address': 'http://localhost:4001',
            'algod_token': 'a' * 64,
            'confio_asset_id': 1057,  # CONFIO with 1 billion supply
            'usdc_asset_id': 1020,    # Mock USDC (old CONFIO)
            'cusd_asset_id': 1036,     # cUSD stablecoin
            # Localnet sponsor account (you may need to update this)
            'sponsor_address': 'KNKFUBM3GHOLF6S7L2O7JU6YDB7PCRV3PKBOBRCABLYHBHXRFXKNDWGAWE',
            'sponsor_mnemonic': 'toss vacuum table old mobile sound bid net evidence fee ticket skin twice invest over machine young dad travel custom offer target duck able air'
        },
        'testnet': {
            'algod_address': 'https://testnet-api.algonode.cloud',
            'algod_token': '',
            'confio_asset_id': 743890784,
            'usdc_asset_id': 10458941,
            'cusd_asset_id': None,  # Not deployed on testnet yet
            'sponsor_address': 'KNKFUBM3GHOLF6S7L2O7JU6YDB7PCRV3PKBOBRCABLYHBHXRFXKNDWGAWE',
            'sponsor_mnemonic': 'toss vacuum table old mobile sound bid net evidence fee ticket skin twice invest over machine young dad travel custom offer target duck able air'
        },
        'mainnet': {
            'algod_address': 'https://mainnet-api.algonode.cloud',
            'algod_token': '',
            'confio_asset_id': None,  # Will be set when deployed to mainnet
            'usdc_asset_id': 31566704,  # Real USDC on mainnet
            'cusd_asset_id': None,  # Will be set when deployed to mainnet
            'sponsor_address': None,  # Will be set for mainnet
            'sponsor_mnemonic': None  # Will be set for mainnet
        }
    }
    
    # Get configuration for current network
    _config = NETWORK_CONFIGS.get(NETWORK, NETWORK_CONFIGS['testnet'])
    
    # Asset configurations from network config or settings override
    CONFIO_ASSET_ID = getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', _config['confio_asset_id'])
    USDC_ASSET_ID = getattr(settings, 'ALGORAND_USDC_ASSET_ID', _config['usdc_asset_id'])
    CUSD_ASSET_ID = getattr(settings, 'ALGORAND_CUSD_ASSET_ID', _config.get('cusd_asset_id'))
    
    # Sponsor account for funding new users
    SPONSOR_ADDRESS = getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', _config['sponsor_address'])
    SPONSOR_MNEMONIC = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', _config['sponsor_mnemonic'])
    
    # Algorand node configuration
    ALGOD_ADDRESS = getattr(settings, 'ALGORAND_ALGOD_ADDRESS', _config['algod_address'])
    ALGOD_TOKEN = getattr(settings, 'ALGORAND_ALGOD_TOKEN', _config['algod_token'])
    
    # Funding amounts
    INITIAL_ALGO_FUNDING = 300000  # 0.3 ALGO in microAlgos (exactly the MBR for 2 assets)
    INITIAL_CONFIO_GRANT = 100_000_000  # 100 CONFIO tokens (6 decimals)
    
    @classmethod
    def get_or_create_algorand_account(cls, user, existing_address: Optional[str] = None) -> Dict:
        """
        Django-style get_or_create for Algorand accounts with automatic opt-ins.
        
        Args:
            user: Django User instance
            existing_address: Optional existing Algorand address to use
            
        Returns:
            Dict with:
                - account: Account model instance
                - created: Boolean indicating if new account was created
                - algorand_address: The Algorand address
                - opted_in_assets: List of asset IDs opted into
                - errors: List of any errors encountered
        """
        
        errors = []
        opted_in_assets = []
        
        # Log the network configuration being used
        logger.info(f"AlgorandAccountManager using network: {cls.NETWORK}")
        logger.info(f"  Algod: {cls.ALGOD_ADDRESS}")
        logger.info(f"  CONFIO Asset ID: {cls.CONFIO_ASSET_ID}")
        logger.info(f"  cUSD Asset ID: {cls.CUSD_ASSET_ID}")
        logger.info(f"  USDC Asset ID: {cls.USDC_ASSET_ID}")
        
        try:
            # Get or create the user's personal account
            account, created = Account.objects.get_or_create(
                user=user,
                account_type='personal',
                defaults={}
            )
            
            # Check if account already has an Algorand address
            if account.algorand_address and len(account.algorand_address) == 58:
                # Account already exists with Algorand address
                logger.info(f"Existing Algorand account found for user {user.email}: {account.algorand_address}")
                
                # Check opt-in status
                opted_in_assets = cls._check_opt_ins(account.algorand_address)
                
                return {
                    'account': account,
                    'created': False,
                    'algorand_address': account.algorand_address,
                    'opted_in_assets': opted_in_assets,
                    'errors': errors
                }
            
            # If existing_address provided, use it
            if existing_address and len(existing_address) == 58:
                algorand_address = existing_address
                logger.info(f"Using provided Algorand address for user {user.email}: {algorand_address}")
            else:
                # Generate new Algorand account
                private_key, algorand_address = account.generate_account()
                mnemonic_phrase = mnemonic.from_private_key(private_key)
                
                # Store mnemonic securely (in production, use encryption)
                # For now, we'll log it for development
                logger.info(f"Generated new Algorand account for user {user.email}: {algorand_address}")
                logger.debug(f"Mnemonic (SECURE THIS): {mnemonic_phrase}")
            
            # Update account with Algorand address
            account.algorand_address = algorand_address  # Using algorand_address field temporarily
            account.save()
            
            # Initialize Algod client
            algod_client = algod.AlgodClient(cls.ALGOD_TOKEN, cls.ALGOD_ADDRESS)
            
            # Fund the account
            funded = cls._fund_account(algod_client, algorand_address)
            if not funded:
                errors.append("Failed to fund account with ALGO")
            
            # Auto opt-in to CONFIO
            if cls.CONFIO_ASSET_ID:
                opt_in_success = cls._opt_in_to_asset(algod_client, algorand_address, cls.CONFIO_ASSET_ID)
                if opt_in_success:
                    opted_in_assets.append(cls.CONFIO_ASSET_ID)
                    
                    # Send initial CONFIO grant
                    cls._send_initial_confio(algod_client, algorand_address)
                else:
                    errors.append(f"Failed to opt-in to CONFIO (Asset ID: {cls.CONFIO_ASSET_ID})")
            
            # Auto opt-in to cUSD (available on localnet)
            if cls.CUSD_ASSET_ID:
                opt_in_success = cls._opt_in_to_asset(algod_client, algorand_address, cls.CUSD_ASSET_ID)
                if opt_in_success:
                    opted_in_assets.append(cls.CUSD_ASSET_ID)
                    logger.info(f"Successfully opted in to cUSD (Asset ID: {cls.CUSD_ASSET_ID})")
                else:
                    errors.append(f"Failed to opt-in to cUSD (Asset ID: {cls.CUSD_ASSET_ID})")
            
            # Note: NOT auto-opting in to USDC - traders will opt-in when they deposit
            
            logger.info(f"Account setup complete for {user.email}. Opted into assets: {opted_in_assets}")
            
            return {
                'account': account,
                'created': True,
                'algorand_address': algorand_address,
                'opted_in_assets': opted_in_assets,
                'errors': errors
            }
            
        except Exception as e:
            logger.error(f"Error setting up Algorand account for user {user.email}: {e}")
            errors.append(str(e))
            
            return {
                'account': None,
                'created': False,
                'algorand_address': None,
                'opted_in_assets': [],
                'errors': errors
            }
    
    @classmethod
    def _fund_account(cls, algod_client, address: str) -> bool:
        """Fund a new account with initial ALGO from sponsor"""
        try:
            # Check if account needs funding
            account_info = algod_client.account_info(address)
            balance = account_info.get('amount', 0)
            
            if balance >= cls.INITIAL_ALGO_FUNDING:
                logger.info(f"Account {address} already funded with {balance} microAlgos")
                return True
            
            # Get sponsor private key
            sponsor_private_key = mnemonic.to_private_key(cls.SPONSOR_MNEMONIC)
            
            # Get suggested parameters
            params = algod_client.suggested_params()
            
            # Create funding transaction
            fund_txn = PaymentTxn(
                sender=cls.SPONSOR_ADDRESS,
                sp=params,
                receiver=address,
                amt=cls.INITIAL_ALGO_FUNDING
            )
            
            # Sign and send
            signed_txn = fund_txn.sign(sponsor_private_key)
            tx_id = algod_client.send_transaction(signed_txn)
            
            # Wait for confirmation
            wait_for_confirmation(algod_client, tx_id, 4)
            
            logger.info(f"Funded account {address} with {cls.INITIAL_ALGO_FUNDING} microAlgos. TX: {tx_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to fund account {address}: {e}")
            return False
    
    @classmethod
    def _opt_in_to_asset(cls, algod_client, address: str, asset_id: int) -> bool:
        """
        Opt-in an account to an asset.
        For Web3Auth wallets, we generate unsigned transactions for the frontend to sign.
        """
        try:
            # Check if already opted in
            account_info = algod_client.account_info(address)
            assets = account_info.get('assets', [])
            
            if any(asset['asset-id'] == asset_id for asset in assets):
                logger.info(f"Account {address} already opted into asset {asset_id}")
                return True
            
            # Since Web3Auth holds the keys on frontend, we can't auto opt-in
            # Instead, we'll return instructions for the frontend
            logger.info(f"Account {address} needs frontend opt-in for asset {asset_id}")
            
            # The frontend will need to:
            # 1. Call our optInToAsset mutation to get unsigned transaction
            # 2. Sign with Web3Auth
            # 3. Submit to Algorand
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check opt-in for {address} to asset {asset_id}: {e}")
            return False
    
    @classmethod
    def _send_initial_confio(cls, algod_client, address: str) -> bool:
        """Send initial CONFIO tokens to new user"""
        try:
            # Get sponsor private key
            sponsor_private_key = mnemonic.to_private_key(cls.SPONSOR_MNEMONIC)
            
            # Get suggested parameters
            params = algod_client.suggested_params()
            
            # Create CONFIO transfer transaction
            transfer_txn = AssetTransferTxn(
                sender=cls.SPONSOR_ADDRESS,
                sp=params,
                receiver=address,
                amt=cls.INITIAL_CONFIO_GRANT,
                index=cls.CONFIO_ASSET_ID
            )
            
            # Sign and send
            signed_txn = transfer_txn.sign(sponsor_private_key)
            tx_id = algod_client.send_transaction(signed_txn)
            
            # Wait for confirmation
            wait_for_confirmation(algod_client, tx_id, 4)
            
            logger.info(f"Sent {cls.INITIAL_CONFIO_GRANT / 1_000_000} CONFIO to {address}. TX: {tx_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send CONFIO to {address}: {e}")
            return False
    
    @classmethod
    def _check_opt_ins(cls, address: str) -> list:
        """Check which assets an account is opted into"""
        try:
            algod_client = algod.AlgodClient(cls.ALGOD_TOKEN, cls.ALGOD_ADDRESS)
            account_info = algod_client.account_info(address)
            assets = account_info.get('assets', [])
            
            opted_in = [asset['asset-id'] for asset in assets]
            return opted_in
            
        except Exception as e:
            logger.error(f"Failed to check opt-ins for {address}: {e}")
            return []
    
    @classmethod
    def ensure_user_algorand_ready(cls, user) -> Dict:
        """
        Convenience method to ensure a user is ready for Algorand operations.
        Called during login or when user needs Algorand functionality.
        """
        return cls.get_or_create_algorand_account(user)
    
    @classmethod
    def opt_in_to_usdc(cls, user) -> Dict:
        """
        Opt-in a user's account to USDC for trading.
        This is called when a trader wants to deposit USDC.
        
        Returns:
            Dict with:
                - success: Boolean indicating if opt-in succeeded
                - already_opted_in: Boolean if already opted in
                - error: Error message if failed
                - algorand_address: The user's Algorand address
        """
        try:
            # Get user's account
            account = Account.objects.filter(
                user=user,
                account_type='personal'
            ).first()
            
            if not account or not account.algorand_address:
                return {
                    'success': False,
                    'already_opted_in': False,
                    'error': 'User does not have an Algorand account',
                    'algorand_address': None
                }
            
            algorand_address = account.algorand_address
            
            # Check if already opted in
            opted_in_assets = cls._check_opt_ins(algorand_address)
            if cls.USDC_ASSET_ID in opted_in_assets:
                logger.info(f"User {user.email} already opted into USDC")
                return {
                    'success': True,
                    'already_opted_in': True,
                    'error': None,
                    'algorand_address': algorand_address
                }
            
            # Initialize Algod client
            algod_client = algod.AlgodClient(cls.ALGOD_TOKEN, cls.ALGOD_ADDRESS)
            
            # Opt-in to USDC
            if cls.USDC_ASSET_ID:
                opt_in_success = cls._opt_in_to_asset(algod_client, algorand_address, cls.USDC_ASSET_ID)
                if opt_in_success:
                    logger.info(f"Successfully opted user {user.email} into USDC (Asset ID: {cls.USDC_ASSET_ID})")
                    return {
                        'success': True,
                        'already_opted_in': False,
                        'error': None,
                        'algorand_address': algorand_address
                    }
                else:
                    error_msg = f"Failed to opt-in to USDC (Asset ID: {cls.USDC_ASSET_ID})"
                    logger.error(f"USDC opt-in failed for {user.email}: {error_msg}")
                    return {
                        'success': False,
                        'already_opted_in': False,
                        'error': error_msg,
                        'algorand_address': algorand_address
                    }
            else:
                return {
                    'success': False,
                    'already_opted_in': False,
                    'error': 'USDC asset ID not configured',
                    'algorand_address': algorand_address
                }
                
        except Exception as e:
            logger.error(f"Error opting user {user.email} into USDC: {e}")
            return {
                'success': False,
                'already_opted_in': False,
                'error': str(e),
                'algorand_address': None
            }