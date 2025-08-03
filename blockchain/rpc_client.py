"""
Raw RPC client for Sui blockchain
"""
import httpx
import json
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class SuiRpcClient:
    """Direct RPC client for Sui blockchain"""
    
    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self._request_id = 0
    
    def _next_id(self) -> int:
        """Get next request ID"""
        self._request_id += 1
        return self._request_id
    
    async def execute_rpc(self, method: str, params: list) -> Dict[str, Any]:
        """
        Execute a raw RPC call
        
        Args:
            method: RPC method name
            params: List of parameters
            
        Returns:
            RPC response
        """
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.rpc_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            result = response.json()
            
            if "error" in result:
                raise Exception(f"RPC error: {result['error']}")
            
            return result.get("result", {})