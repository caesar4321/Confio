"""
Custom transaction executor for pre-signed transactions
"""
import base64
from typing import List, Dict, Any
from pysui import AsyncClient
from pysui.sui.sui_types.scalars import SuiTxBytes
import logging

logger = logging.getLogger(__name__)


async def execute_transaction_with_signatures(
    client: AsyncClient,
    tx_bytes: bytes,
    signatures: List[Any]
) -> Dict[str, Any]:
    """
    Execute a transaction with pre-computed signatures
    
    This is needed because pysui's execute method expects a builder,
    but we have pre-signed transaction bytes.
    
    Args:
        client: The pysui AsyncClient
        tx_bytes: The transaction bytes
        signatures: List of signatures (strings or dicts with scheme/signature)
        
    Returns:
        Transaction result
    """
    try:
        # Make a raw RPC call using direct RPC client
        from blockchain.rpc_client import SuiRpcClient
        from django.conf import settings
        
        rpc_client = SuiRpcClient(settings.SUI_RPC_URL)
        # Sui RPC expects signatures as flat base64 strings, not objects
        # Convert any objects to strings, otherwise pass through
        flat_signatures = []
        for sig in signatures:
            if isinstance(sig, dict) and 'signature' in sig:
                # Extract signature string from dict
                flat_signatures.append(sig['signature'])
            elif isinstance(sig, str):
                # Already a string, use as-is
                flat_signatures.append(sig)
            else:
                raise ValueError(f"Invalid signature format: {type(sig)}")
        
        logger.info(f"Calling RPC with {len(flat_signatures)} signatures:")
        for i, sig in enumerate(flat_signatures):
            logger.info(f"  sig[{i}]: {sig[:24]}... ({len(sig)} chars)")
        
        # Ensure tx_bytes are properly encoded
        if isinstance(tx_bytes, bytes):
            tx_bytes_b64 = base64.b64encode(tx_bytes).decode()
        else:
            tx_bytes_b64 = tx_bytes
            
        result = await rpc_client.execute_rpc(
            "sui_executeTransactionBlock",
            [
                tx_bytes_b64,
                flat_signatures,
                {
                    "showInput": True,
                    "showEffects": True,
                    "showEvents": True,
                    "showObjectChanges": True,
                    "showBalanceChanges": True
                },
                "WaitForLocalExecution"  # Execution request type
            ]
        )
        
        # The result is already a dict from RPC
        return result
            
    except Exception as e:
        logger.error(f"Error executing transaction: {e}")
        return {
            'success': False,
            'error': str(e)
        }