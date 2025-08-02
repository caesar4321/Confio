"""
Blockchain settings - Easy switch between testnet and mainnet

Sui CLI Account Structure (deterministic with one passphrase):
1. Admin (friendly-diamond): 0x0c1589253999177f7ea3eda6aa412cbaa3238c005ba918e724c0a051fe6d1256
2. USDC Vault (friendly-crocidolite): 0x478abc5b847d726e5caad8e9b37d66890f61013b5fe5b5162adc586f99e3833d
3. Sponsor (quizzical-dichroite): 0xed36f82d851c5b54ebc8b58a71ea6473823e073a01ce8b6a5c04a4bcebaf6aef
4. Fee Collector (epic-epidote): 0xd1163e727e7590ade05bba7aaa8af755b21262a07d05fd20da0f1aa9ef6549d2
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
    CUSD_PACKAGE_ID = "0x551a39bd96679261aaf731e880b88fa528b66ee2ef6f0da677bdf0762b907bcf"
    # NOTE: CONFIO was deployed as a dependency within the Pay package deployment
    # For mainnet, consider deploying CONFIO as a standalone package first
    CONFIO_PACKAGE_ID = "0xa603f73f43d4facd9bdcd25815326254f84c741989b64fb88cf464897418a080"
    PAY_PACKAGE_ID = "0xa603f73f43d4facd9bdcd25815326254f84c741989b64fb88cf464897418a080"
    P2P_TRADE_PACKAGE_ID = "0xfa39d9b961930750646148de35923d789561a4d47571bd7ff17eda9d6f9ec17c"
    INVITE_SEND_PACKAGE_ID = "0xc360865f7f30324ade1d283ebfd5bfc385062588af3f389a755887fc5f99e45e"
    
    # Testnet object IDs
    FEE_COLLECTOR_ADDRESS = "0xd1163e727e7590ade05bba7aaa8af755b21262a07d05fd20da0f1aa9ef6549d2"  # Fourth account
    FEE_COLLECTOR_OBJECT_ID = "0xYOUR_TESTNET_FEE_COLLECTOR"  # Will be created by Pay contract
    TRADE_REGISTRY_OBJECT_ID = "0xYOUR_TESTNET_TRADE_REGISTRY"
    ESCROW_VAULT_OBJECT_ID = "0xYOUR_TESTNET_ESCROW_VAULT"
    
    # Sponsor account for gas-free transactions (third account - has 0.5 SUI)
    SPONSOR_ADDRESS = "0xed36f82d851c5b54ebc8b58a71ea6473823e073a01ce8b6a5c04a4bcebaf6aef"
    
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