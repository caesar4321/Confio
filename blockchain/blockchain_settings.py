"""
Blockchain settings - Easy switch between testnet and mainnet
"""
import os
from django.conf import settings

# Network selection
NETWORK = os.environ.get('SUI_NETWORK', 'testnet')  # 'testnet' or 'mainnet'

# RPC Endpoints
if NETWORK == 'testnet':
    # Free Sui testnet
    SUI_RPC_URL = "https://fullnode.testnet.sui.io:443"
    SUI_WS_URL = "wss://fullnode.testnet.sui.io:443"
    
    # Testnet contract addresses (from your deployments)
    CUSD_PACKAGE_ID = "0xYOUR_TESTNET_CUSD_PACKAGE"
    CONFIO_PACKAGE_ID = "0xYOUR_TESTNET_CONFIO_PACKAGE"
    PAY_PACKAGE_ID = "0xYOUR_TESTNET_PAY_PACKAGE"
    P2P_TRADE_PACKAGE_ID = "0xYOUR_TESTNET_P2P_TRADE_PACKAGE"
    INVITE_SEND_PACKAGE_ID = "0xYOUR_TESTNET_INVITE_SEND_PACKAGE"
    
    # Testnet object IDs
    FEE_COLLECTOR_OBJECT_ID = "0xYOUR_TESTNET_FEE_COLLECTOR"
    TRADE_REGISTRY_OBJECT_ID = "0xYOUR_TESTNET_TRADE_REGISTRY"
    ESCROW_VAULT_OBJECT_ID = "0xYOUR_TESTNET_ESCROW_VAULT"
    
else:  # mainnet
    # QuickNode mainnet (future)
    SUI_RPC_URL = f"https://{os.environ.get('QUICKNODE_ENDPOINT')}"
    SUI_WS_URL = None  # QuickNode uses gRPC, not WebSocket
    QUICKNODE_API_KEY = os.environ.get('QUICKNODE_API_KEY')
    
    # Mainnet contract addresses (deploy later)
    CUSD_PACKAGE_ID = "0xYOUR_MAINNET_CUSD_PACKAGE"
    CONFIO_PACKAGE_ID = "0xYOUR_MAINNET_CONFIO_PACKAGE"
    # ... etc

# Common settings
POLL_INTERVAL_SECONDS = 2
BALANCE_CACHE_TTL = 30  # seconds
TRANSACTION_CACHE_TTL = 60  # seconds

# Gas settings
DEFAULT_GAS_BUDGET = 10000000  # 0.01 SUI
MAX_GAS_BUDGET = 50000000      # 0.05 SUI

# Monitoring settings
MONITOR_ADDRESSES = [
    FEE_COLLECTOR_OBJECT_ID,
    ESCROW_VAULT_OBJECT_ID,
]

# Add to Django settings
local_vars = dict(locals())
for key, value in local_vars.items():
    if key.isupper() and not key.startswith('_'):
        setattr(settings, key, value)