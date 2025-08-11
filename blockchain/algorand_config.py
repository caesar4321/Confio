"""
Centralized Algorand blockchain configuration.
Retrieves all settings from Django settings.py which reads from environment variables.
"""

from django.conf import settings
from algosdk.v2client import algod, indexer

def get_algod_client():
    """Get Algorand Algod client using Django settings"""
    return algod.AlgodClient(
        settings.ALGORAND_ALGOD_TOKEN,
        settings.ALGORAND_ALGOD_ADDRESS
    )

def get_indexer_client():
    """Get Algorand Indexer client using Django settings"""
    return indexer.IndexerClient(
        settings.ALGORAND_INDEXER_TOKEN,
        settings.ALGORAND_INDEXER_ADDRESS
    )

def get_network():
    """Get current network (testnet/mainnet/localnet)"""
    return settings.BLOCKCHAIN_CONFIG.get('NETWORK', 'testnet')

def get_asset_ids():
    """Get all configured asset IDs"""
    return {
        'CONFIO': settings.ALGORAND_CONFIO_ASSET_ID,
        'USDC': settings.ALGORAND_USDC_ASSET_ID,  # Mock USDC on LocalNet, real USDC on testnet
        'CUSD': settings.ALGORAND_CUSD_ASSET_ID,
    }

def get_sponsor_config():
    """Get sponsor account configuration"""
    return {
        'address': settings.ALGORAND_SPONSOR_ADDRESS,
        'mnemonic': settings.ALGORAND_SPONSOR_MNEMONIC,
    }

# For LocalNet testing, we need to get the creator keys from environment
def get_localnet_creators():
    """
    Get LocalNet creator accounts from environment variables.
    These should be set when running LocalNet tests.
    """
    import os
    from decouple import config as decouple_config
    
    return {
        'CONFIO': {
            'address': decouple_config('LOCALNET_CONFIO_CREATOR_ADDRESS', default=''),
            'private_key': decouple_config('LOCALNET_CONFIO_CREATOR_KEY', default=''),
        },
        'USDC': {
            'address': decouple_config('LOCALNET_USDC_CREATOR_ADDRESS', default=''),
            'private_key': decouple_config('LOCALNET_USDC_CREATOR_KEY', default=''),
        },
        'CUSD': {
            'address': decouple_config('LOCALNET_CUSD_CREATOR_ADDRESS', default=''),
            'private_key': decouple_config('LOCALNET_CUSD_CREATOR_KEY', default=''),
            'app_id': decouple_config('LOCALNET_CUSD_APP_ID', default=None, cast=int),
        }
    }

def get_distribution_amounts():
    """Get default token distribution amounts"""
    return {
        'CONFIO': decouple_config('DISTRIBUTION_CONFIO', default=1000, cast=int),
        'USDC': decouple_config('DISTRIBUTION_USDC', default=5000, cast=int),
        'CUSD': decouple_config('DISTRIBUTION_CUSD', default=100, cast=int),
    }