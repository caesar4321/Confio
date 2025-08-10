"""
Algorand LocalNet Configuration for Testing
"""

# LocalNet Configuration
ALGORAND_NODE = "http://localhost:4001"
ALGORAND_INDEXER = "http://localhost:8980"
ALGORAND_TOKEN = "a" * 64  # Default Algokit token

# Network setting for LocalNet
NETWORK = "localnet"

# Test accounts will be generated dynamically
# These will be funded from the LocalNet dispenser account