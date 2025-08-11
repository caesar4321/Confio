"""
Blockchain settings - Easy switch between testnet and mainnet

Algorand Network Configuration (replacing Sui):
- Using Algorand for better stablecoin support and lower fees
- Native USDC support on Algorand
- Atomic transfers for better P2P exchange support
"""
import os
from django.conf import settings

# Use Django settings if available, otherwise fall back to environment
try:
    # Try to use Django settings first
    NETWORK = settings.BLOCKCHAIN_CONFIG.get('NETWORK', 'testnet')
    ALGORAND_ALGOD_ADDRESS = settings.ALGORAND_ALGOD_ADDRESS
    ALGORAND_ALGOD_TOKEN = settings.ALGORAND_ALGOD_TOKEN
    ALGORAND_INDEXER_ADDRESS = settings.ALGORAND_INDEXER_ADDRESS
    ALGORAND_INDEXER_TOKEN = settings.ALGORAND_INDEXER_TOKEN
    ALGORAND_USDC_ASSET_ID = settings.ALGORAND_USDC_ASSET_ID
    ALGORAND_CUSD_ASSET_ID = settings.ALGORAND_CUSD_ASSET_ID
    ALGORAND_CONFIO_ASSET_ID = settings.ALGORAND_CONFIO_ASSET_ID
    # Keep Sui settings for compatibility
    SUI_RPC_URL = getattr(settings, 'SUI_RPC_URL', '')
    CUSD_PACKAGE_ID = getattr(settings, 'CUSD_PACKAGE_ID', '')
    CONFIO_PACKAGE_ID = getattr(settings, 'CONFIO_PACKAGE_ID', '')
except (ImportError, AttributeError):
    # Fall back to environment-based configuration
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
        # USDC on Algorand Testnet (official testing USDC)
        ALGORAND_USDC_ASSET_ID = int(os.environ.get('ALGORAND_USDC_ASSET_ID', 10458941))
        
        # Custom assets deployed on testnet
        ALGORAND_CUSD_ASSET_ID = int(os.environ.get('ALGORAND_CUSD_ASSET_ID', 0)) if os.environ.get('ALGORAND_CUSD_ASSET_ID') else None
        ALGORAND_CONFIO_ASSET_ID = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', 743890784))  # Created on testnet
        
        # Keep Sui for compatibility
        SUI_RPC_URL = os.environ.get('SUI_RPC_URL', 'https://fullnode.testnet.sui.io:443')
        # Sui testnet package IDs
        CUSD_PACKAGE_ID = "0x551a39bd96679261aaf731e880b88fa528b66ee2ef6f0da677bdf0762b907bcf"
        CONFIO_PACKAGE_ID = "0x2c5f46d4dda1ca49ed4b2c223bd1137b0f8f005a7f6012eb8bc09bf3a858cd56"  # New CONFIO contract with correct 1B supply

    elif NETWORK == 'localnet':
        # Algorand LocalNet - Using local Algorand node
        ALGORAND_ALGOD_ADDRESS = os.environ.get('ALGORAND_ALGOD_ADDRESS', 'http://localhost:4001')
        ALGORAND_ALGOD_TOKEN = os.environ.get('ALGORAND_ALGOD_TOKEN', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')
        ALGORAND_INDEXER_ADDRESS = os.environ.get('ALGORAND_INDEXER_ADDRESS', 'http://localhost:8980')
        ALGORAND_INDEXER_TOKEN = os.environ.get('ALGORAND_INDEXER_TOKEN', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')
        
        # LocalNet Asset IDs (will be set after deployment)
        ALGORAND_USDC_ASSET_ID = int(os.environ.get('ALGORAND_USDC_ASSET_ID', 0)) if os.environ.get('ALGORAND_USDC_ASSET_ID') else None  # Mock USDC on LocalNet
        ALGORAND_CUSD_ASSET_ID = int(os.environ.get('ALGORAND_CUSD_ASSET_ID', 0)) if os.environ.get('ALGORAND_CUSD_ASSET_ID') else None
        ALGORAND_CONFIO_ASSET_ID = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', 0)) if os.environ.get('ALGORAND_CONFIO_ASSET_ID') else None
        
        # Keep Sui for compatibility (LocalNet)
        SUI_RPC_URL = os.environ.get('SUI_RPC_URL', 'http://127.0.0.1:9000')
        CUSD_PACKAGE_ID = os.environ.get('CUSD_PACKAGE_ID', None)
        CONFIO_PACKAGE_ID = os.environ.get('CONFIO_PACKAGE_ID', None)

    else:
        # Algorand Mainnet - Using Algonode or QuickNode
        ALGORAND_ALGOD_ADDRESS = os.environ.get('ALGORAND_ALGOD_ADDRESS', 'https://mainnet-api.algonode.cloud')
        ALGORAND_ALGOD_TOKEN = os.environ.get('ALGORAND_ALGOD_TOKEN', '')
        ALGORAND_INDEXER_ADDRESS = os.environ.get('ALGORAND_INDEXER_ADDRESS', 'https://mainnet-idx.algonode.cloud')
        ALGORAND_INDEXER_TOKEN = os.environ.get('ALGORAND_INDEXER_TOKEN', '')
        
        # Mainnet Asset IDs
        # USDC on Algorand Mainnet (official Circle USDC)
        ALGORAND_USDC_ASSET_ID = int(os.environ.get('ALGORAND_USDC_ASSET_ID', 31566704))  # Official mainnet USDC if not specified
        
        # Custom assets (to be deployed on mainnet)
        ALGORAND_CUSD_ASSET_ID = int(os.environ.get('ALGORAND_CUSD_ASSET_ID', 0)) if os.environ.get('ALGORAND_CUSD_ASSET_ID') else None
        ALGORAND_CONFIO_ASSET_ID = int(os.environ.get('ALGORAND_CONFIO_ASSET_ID', 0)) if os.environ.get('ALGORAND_CONFIO_ASSET_ID') else None
        
        # Keep Sui for compatibility
        SUI_RPC_URL = f"https://{os.environ.get('QUICKNODE_ENDPOINT', 'fullnode.mainnet.sui.io:443')}"
        CUSD_PACKAGE_ID = "0xYOUR_MAINNET_CUSD_PACKAGE"
        CONFIO_PACKAGE_ID = "0xYOUR_MAINNET_CONFIO_PACKAGE"

# Common settings
POLL_INTERVAL_SECONDS = 2

# Export all settings as a dict for easy access
BLOCKCHAIN_SETTINGS = {
    'NETWORK': NETWORK,
    'ALGORAND_ALGOD_ADDRESS': ALGORAND_ALGOD_ADDRESS,
    'ALGORAND_ALGOD_TOKEN': ALGORAND_ALGOD_TOKEN,
    'ALGORAND_INDEXER_ADDRESS': ALGORAND_INDEXER_ADDRESS,
    'ALGORAND_INDEXER_TOKEN': ALGORAND_INDEXER_TOKEN,
    'ALGORAND_USDC_ASSET_ID': ALGORAND_USDC_ASSET_ID,
    'ALGORAND_CUSD_ASSET_ID': ALGORAND_CUSD_ASSET_ID,
    'ALGORAND_CONFIO_ASSET_ID': ALGORAND_CONFIO_ASSET_ID,
    'SUI_RPC_URL': SUI_RPC_URL,
    'CUSD_PACKAGE_ID': CUSD_PACKAGE_ID,
    'CONFIO_PACKAGE_ID': CONFIO_PACKAGE_ID,
}