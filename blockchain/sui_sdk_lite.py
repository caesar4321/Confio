"""
Lightweight Sui SDK for Python 3.9
Implements core functionality needed for production
"""

import aiohttp
import asyncio
import json
import base64
from typing import Dict, List, Optional, Any
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class SuiClient:
    """Lightweight Sui client using JSON-RPC directly"""
    
    def __init__(self, rpc_url: str = "https://fullnode.testnet.sui.io:443"):
        self.rpc_url = rpc_url
        self._id_counter = 0
    
    def _get_id(self) -> int:
        """Get next request ID"""
        self._id_counter += 1
        return self._id_counter
    
    async def _request(self, method: str, params: List[Any]) -> Dict[str, Any]:
        """Make RPC request"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._get_id(),
            "method": method,
            "params": params
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.rpc_url, json=payload) as response:
                result = await response.json()
                
                if "error" in result:
                    raise Exception(f"RPC error: {result['error']}")
                
                return result.get("result", {})
    
    async def get_balance(self, address: str, coin_type: Optional[str] = None) -> Dict[str, Any]:
        """Get balance for an address"""
        params = {"owner": address}
        if coin_type:
            params["coinType"] = coin_type
        
        return await self._request("suix_getBalance", [params])
    
    async def get_coins(self, address: str, coin_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get coin objects for an address"""
        params = {"owner": address, "limit": limit}
        if coin_type:
            params["coinType"] = coin_type
        
        result = await self._request("suix_getCoins", [params])
        return result.get("data", [])
    
    async def get_object(self, object_id: str) -> Dict[str, Any]:
        """Get object details"""
        options = {
            "showType": True,
            "showOwner": True,
            "showContent": True,
            "showDisplay": True
        }
        
        return await self._request("sui_getObject", [object_id, options])
    
    async def dry_run_transaction(self, tx_bytes: str) -> Dict[str, Any]:
        """Dry run a transaction to check if it would succeed"""
        return await self._request("sui_dryRunTransactionBlock", [tx_bytes])
    
    async def execute_transaction(
        self, 
        tx_bytes: str, 
        signatures: List[str],
        options: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        """Execute a signed transaction"""
        if options is None:
            options = {
                "showInput": True,
                "showEffects": True,
                "showEvents": True,
                "showObjectChanges": True,
                "showBalanceChanges": True
            }
        
        return await self._request("sui_executeTransactionBlock", [tx_bytes, signatures, options])
    
    async def get_transaction(self, digest: str) -> Dict[str, Any]:
        """Get transaction details by digest"""
        options = {
            "showInput": True,
            "showEffects": True,
            "showEvents": True,
            "showObjectChanges": True,
            "showBalanceChanges": True
        }
        
        return await self._request("sui_getTransactionBlock", [digest, options])


class TransactionBuilder:
    """Build Sui transactions"""
    
    @staticmethod
    def transfer_objects(
        objects: List[str],
        recipient: str,
        sender: str,
        gas_budget: int = 100000000,
        gas_price: int = 1000
    ) -> Dict[str, Any]:
        """Build a transfer objects transaction"""
        return {
            "version": 1,
            "sender": sender,
            "expiration": None,
            "gasData": {
                "budget": str(gas_budget),
                "price": str(gas_price),
                "owner": sender,
                "payment": []
            },
            "inputs": [
                {
                    "kind": "Input",
                    "value": {"Object": {"ImmOrOwnedObject": {
                        "objectId": obj_id,
                        "version": "SequenceNumber",
                        "digest": obj_id  # Placeholder
                    }}} 
                } for obj_id in objects
            ] + [
                {
                    "kind": "Input", 
                    "value": {"Pure": bytes([0x00] + list(bytes.fromhex(recipient[2:]))).hex()}
                }
            ],
            "transactions": [
                {
                    "TransferObjects": {
                        "objects": [{"Input": i} for i in range(len(objects))],
                        "address": {"Input": len(objects)}
                    }
                }
            ]
        }
    
    @staticmethod
    def split_and_transfer(
        coin_object_id: str,
        amount: int,
        recipient: str,
        sender: str,
        coin_type: str,
        gas_budget: int = 100000000,
        gas_price: int = 1000
    ) -> Dict[str, Any]:
        """Build a split and transfer transaction"""
        return {
            "version": 1,
            "sender": sender,
            "expiration": None,
            "gasData": {
                "budget": str(gas_budget),
                "price": str(gas_price),
                "owner": sender,
                "payment": []
            },
            "inputs": [
                {
                    "kind": "Input",
                    "value": {"Object": {"ImmOrOwnedObject": {
                        "objectId": coin_object_id,
                        "version": "SequenceNumber",
                        "digest": coin_object_id  # Placeholder
                    }}}
                },
                {
                    "kind": "Input",
                    "value": {"Pure": amount.to_bytes(8, byteorder='little').hex()}
                },
                {
                    "kind": "Input", 
                    "value": {"Pure": bytes([0x00] + list(bytes.fromhex(recipient[2:]))).hex()}
                }
            ],
            "transactions": [
                {
                    "MoveCall": {
                        "package": "0x2",
                        "module": "pay",
                        "function": "split_and_transfer",
                        "type_arguments": [coin_type],
                        "arguments": [
                            {"Input": 0},  # coin
                            {"Input": 1},  # amount  
                            {"Input": 2}   # recipient
                        ]
                    }
                }
            ]
        }


# Example usage
async def example_usage():
    client = SuiClient()
    
    # Get balance
    balance = await client.get_balance("0xed36f82d851c5b54ebc8b58a71ea6473823e073a01ce8b6a5c04a4bcebaf6aef")
    print(f"Balance: {balance}")
    
    # Get coins
    coins = await client.get_coins(
        "0xed36f82d851c5b54ebc8b58a71ea6473823e073a01ce8b6a5c04a4bcebaf6aef",
        "0x2::sui::SUI"
    )
    print(f"Found {len(coins)} SUI coins")


if __name__ == "__main__":
    asyncio.run(example_usage())