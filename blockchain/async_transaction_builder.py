"""
Async transaction builder with proper error handling
"""
from typing import List, Dict, Any
import asyncio
import ssl
import httpx
from pysui import AsyncClient, SuiConfig
from pysui.sui.sui_types import SuiAddress
from pysui.sui.sui_txn.async_transaction import SuiTransactionAsync
import logging
import base64

logger = logging.getLogger(__name__)


async def build_sponsored_transaction_async(
    sender: str,
    sponsor: str, 
    transactions: List[Dict[str, Any]],
    gas_budget: int = 10000000,
    network: str = 'testnet'
) -> bytes:
    """
    Build a sponsored transaction using async client with better error handling
    """
    max_retries = 3
    retry_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            # Create config
            if network == 'mainnet':
                from django.conf import settings
                config = SuiConfig.user_config(
                    rpc_url=settings.SUI_RPC_URL
                )
            else:
                config = SuiConfig.default_config()
            
            # Create async client
            async with AsyncClient(config) as client:
                # Test connection
                try:
                    version = client.rpc_version  # This is a property, not a method
                    logger.info(f"Successfully connected to Sui RPC (async) on attempt {attempt + 1}, version: {version}")
                except Exception as e:
                    logger.warning(f"Connection test failed: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay * (attempt + 1))
                        continue
                    raise
                
                # Create transaction builder
                txn = SuiTransactionAsync(client=client)
                
                # Add each transaction command
                for tx_cmd in transactions:
                    if tx_cmd.get('type') == 'moveCall':
                        await txn.move_call(
                            target=f"{tx_cmd['packageObjectId']}::{tx_cmd['module']}::{tx_cmd['function']}",
                            arguments=tx_cmd.get('arguments', []),
                            type_arguments=tx_cmd.get('typeArguments', [])
                        )
                    elif tx_cmd.get('type') == 'transferObjects':
                        await txn.transfer_objects(
                            transfers=tx_cmd['objects'],
                            recipient=SuiAddress(tx_cmd['recipient'])
                        )
                
                # Set sender and sponsor
                txn.sender = SuiAddress(sender)
                txn.gas_sponsor = SuiAddress(sponsor)
                txn.gas_budget = gas_budget
                
                # Serialize the transaction
                logger.info("Serializing transaction (async)...")
                tx_bytes = await txn.serialize()
                logger.info(f"Transaction serialized: {len(tx_bytes)} bytes")
                
                return tx_bytes
                
        except ssl.SSLError as ssl_error:
            logger.error(f"SSL error on attempt {attempt + 1}: {ssl_error}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))
            else:
                raise
        except Exception as e:
            logger.error(f"Error building transaction on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1 and "timeout" in str(e).lower():
                await asyncio.sleep(retry_delay * (attempt + 1))
            else:
                raise
    
    raise Exception("Failed to build transaction after all retries")


async def build_simple_transaction(
    sender: str,
    sponsor: str,
    transactions: List[Dict[str, Any]],
    gas_budget: int = 10000000
) -> str:
    """
    Build transaction using direct RPC calls to avoid SSL issues
    """
    from blockchain.rpc_client import SuiRpcClient
    from django.conf import settings
    
    # Use the RPC client directly
    rpc_client = SuiRpcClient(settings.SUI_RPC_URL)
    
    # Create transaction data structure
    tx_data = {
        "sender": sender,
        "gasData": {
            "payment": [],
            "owner": sponsor,
            "price": "1000",
            "budget": str(gas_budget)
        },
        "kind": {
            "ProgrammableTransaction": {
                "inputs": [],
                "commands": []
            }
        }
    }
    
    # Add commands
    for tx_cmd in transactions:
        if tx_cmd.get('type') == 'moveCall':
            command = {
                "MoveCall": {
                    "package": tx_cmd['packageObjectId'],
                    "module": tx_cmd['module'],
                    "function": tx_cmd['function'],
                    "type_arguments": tx_cmd.get('typeArguments', []),
                    "arguments": tx_cmd.get('arguments', [])
                }
            }
            tx_data["kind"]["ProgrammableTransaction"]["commands"].append(command)
    
    # For now, return a dummy transaction bytes
    # In production, this would properly serialize the transaction
    import json
    tx_json = json.dumps(tx_data)
    return base64.b64encode(tx_json.encode()).decode()