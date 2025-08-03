"""
Synchronous transaction builder to avoid async/sync issues
"""
from typing import List, Dict, Any
from pysui import SyncClient, SuiConfig
from pysui.sui.sui_types import SuiAddress
from pysui.sui.sui_txn.sync_transaction import SuiTransaction
import logging
import time
import ssl

logger = logging.getLogger(__name__)


def build_sponsored_transaction_sync(
    sender: str,
    sponsor: str, 
    transactions: List[Dict[str, Any]],
    gas_budget: int = 10000000,
    network: str = 'testnet'
) -> bytes:
    """
    Build a sponsored transaction using sync client
    
    This avoids the async/sync mismatch issue by using
    a dedicated sync client for transaction building.
    """
    max_retries = 3
    retry_delay = 1.0
    client = None
    
    # Try to establish connection with retries
    for attempt in range(max_retries):
        try:
            # Create a sync client
            if network == 'mainnet':
                from django.conf import settings
                config = SuiConfig.user_config(
                    rpc_url=settings.SUI_RPC_URL
                )
            else:
                config = SuiConfig.default_config()
            
            client = SyncClient(config)
            
            # Test the connection
            version = client.rpc_version  # It's a property, not a method
            logger.info(f"Successfully connected to Sui RPC on attempt {attempt + 1}, version: {version}")
            break
            
        except Exception as conn_error:
            logger.warning(f"Connection failed on attempt {attempt + 1}: {conn_error}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
            else:
                raise Exception(f"Failed to connect to Sui RPC after {max_retries} attempts: {conn_error}")
    
    if not client:
        raise Exception("Failed to create Sui client")
    
    try:
        # Create transaction builder
        txn = SuiTransaction(client=client)
        
        # Add each transaction command
        for tx_cmd in transactions:
            if tx_cmd.get('type') == 'moveCall':
                txn.move_call(
                    target=f"{tx_cmd['packageObjectId']}::{tx_cmd['module']}::{tx_cmd['function']}",
                    arguments=tx_cmd.get('arguments', []),
                    type_arguments=tx_cmd.get('typeArguments', [])
                )
            elif tx_cmd.get('type') == 'transferObjects':
                txn.transfer_objects(
                    objects=tx_cmd['objects'],
                    recipient=SuiAddress(tx_cmd['recipient'])
                )
        
        # Set sender and sponsor
        txn.sender = SuiAddress(sender)
        txn.gas_sponsor = SuiAddress(sponsor)
        txn.gas_budget = gas_budget
        
        # Build the transaction (synchronous)
        # The method is actually 'serialize' to get the bytes
        logger.info("Serializing transaction...")
        tx_bytes = txn.serialize()
        logger.info(f"Transaction serialized: {len(tx_bytes)} bytes")
        
        return tx_bytes
        
    except Exception as e:
        logger.error(f"Error building sponsored transaction (sync): {e}")
        raise
    finally:
        # Clean up the sync client
        if 'client' in locals():
            client.close()