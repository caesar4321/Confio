"""
Blockchain settings - Easy switch between testnet and mainnet

Algorand Network Configuration (replacing Sui):
- Using Algorand for better stablecoin support and lower fees
- Native USDC support on Algorand
- Atomic transfers for better P2P exchange support
"""
import os
from django.conf import settings

# Network selection
NETWORK = os.environ.get('ALGORAND_NETWORK', 'testnet')  # 'testnet' or 'mainnet'

# RPC Endpoints
if NETWORK == 'testnet':
    # Algorand Testnet - Using Algonode free service
    ALGORAND_ALGOD_ADDRESS = os.environ.get('ALGORAND_ALGOD_ADDRESS', 'https://testnet-api.algonode.cloud')
    ALGORAND_ALGOD_TOKEN = os.environ.get('ALGORAND_ALGOD_TOKEN', '')  # Algonode doesn't require tokens
    ALGORAND_INDEXER_ADDRESS = os.environ.get('ALGORAND_INDEXER_ADDRESS', 'https://testnet-idx.algonode.cloud')
    ALGORAND_INDEXER_TOKEN = os.environ.get('ALGORAND_INDEXER_TOKEN', '')
    
    # Testnet Asset IDs
    # USDC on Algorand Testnet (official Circle USDC)
    ALGORAND_USDC_ASSET_ID = 10458941  # Official testnet USDC
    
    # Custom assets
    ALGORAND_CUSD_ASSET_ID = os.environ.get('ALGORAND_CUSD_ASSET_ID', None)  # Will deploy custom cUSD
    ALGORAND_CONFIO_ASSET_ID = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', '743890784'))  # CONFIO token on testnet
    
    # Sponsor account for fee sponsorship (to be created)
    ALGORAND_SPONSOR_ADDRESS = os.environ.get('ALGORAND_SPONSOR_ADDRESS', None)
    ALGORAND_SPONSOR_MNEMONIC = os.environ.get('ALGORAND_SPONSOR_MNEMONIC', None)
    
    # KMD configuration for secure key management
    ALGORAND_KMD_ADDRESS = os.environ.get('ALGORAND_KMD_ADDRESS', 'http://localhost:4002')
    ALGORAND_KMD_TOKEN = os.environ.get('ALGORAND_KMD_TOKEN', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')
    ALGORAND_KMD_WALLET_NAME = os.environ.get('ALGORAND_KMD_WALLET_NAME', 'sponsor_wallet')
    ALGORAND_KMD_WALLET_PASSWORD = os.environ.get('ALGORAND_KMD_WALLET_PASSWORD', 'sponsor_password')
    
    # Fee collector account
    FEE_COLLECTOR_ADDRESS = os.environ.get('ALGORAND_FEE_COLLECTOR_ADDRESS', None)
    
    # Keep Sui addresses for compatibility during migration
    SUI_RPC_URL = "https://fullnode.testnet.sui.io:443"
    CUSD_PACKAGE_ID = "0x551a39bd96679261aaf731e880b88fa528b66ee2ef6f0da677bdf0762b907bcf"
    SPONSOR_PRIVATE_KEY = os.environ.get('SUI_SPONSOR_PRIVATE_KEY', None)
    
else:  # mainnet
    # Algorand Mainnet - Using Algonode or QuickNode
    ALGORAND_ALGOD_ADDRESS = os.environ.get('ALGORAND_ALGOD_ADDRESS', 'https://mainnet-api.algonode.cloud')
    ALGORAND_ALGOD_TOKEN = os.environ.get('ALGORAND_ALGOD_TOKEN', '')
    ALGORAND_INDEXER_ADDRESS = os.environ.get('ALGORAND_INDEXER_ADDRESS', 'https://mainnet-idx.algonode.cloud')
    ALGORAND_INDEXER_TOKEN = os.environ.get('ALGORAND_INDEXER_TOKEN', '')
    
    # Mainnet Asset IDs
    # USDC on Algorand Mainnet (official Circle USDC)
    ALGORAND_USDC_ASSET_ID = 31566704  # Official mainnet USDC
    
    # Custom assets (to be deployed on mainnet)
    ALGORAND_CUSD_ASSET_ID = os.environ.get('ALGORAND_CUSD_ASSET_ID', None)
    ALGORAND_CONFIO_ASSET_ID = os.environ.get('ALGORAND_CONFIO_ASSET_ID', None)
    
    # Keep Sui for compatibility
    SUI_RPC_URL = f"https://{os.environ.get('QUICKNODE_ENDPOINT', 'fullnode.mainnet.sui.io:443')}"
    CUSD_PACKAGE_ID = "0xYOUR_MAINNET_CUSD_PACKAGE"

# Common settings
POLL_INTERVAL_SECONDS = 2
BALANCE_CACHE_TTL = 30  # seconds
TRANSACTION_CACHE_TTL = 60  # seconds

# Gas settings
DEFAULT_GAS_BUDGET = 10000000  # 0.01 SUI
MAX_GAS_BUDGET = 50000000      # 0.05 SUI

# Monitoring settings (disabled during migration)
MONITOR_ADDRESSES = []

# Add to Django settings
local_vars = dict(locals())
for key, value in local_vars.items():
    if key.isupper() and not key.startswith('_'):
        setattr(settings, key, value)