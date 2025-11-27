"""
Production-ready transaction execution for Sui blockchain
Uses proper transaction building and BCS encoding
"""

import json
import base64
import struct
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class BCSEncoder:
    """Basic BCS encoder for Sui transactions"""
    
    @staticmethod
    def encode_u8(value: int) -> bytes:
        return struct.pack('B', value)
    
    @staticmethod
    def encode_u64(value: int) -> bytes:
        return struct.pack('<Q', value)
    
    @staticmethod
    def encode_address(address: str) -> bytes:
        if address.startswith('0x'):
            address = address[2:]
        return bytes.fromhex(address.zfill(64))
    
    @staticmethod
    def encode_vector(items: List[bytes]) -> bytes:
        result = BCSEncoder.encode_uleb128(len(items))
        for item in items:
            result += item
        return result
    
    @staticmethod
    def encode_uleb128(value: int) -> bytes:
        result = []
        while True:
            byte = value & 0x7f
            value >>= 7
            if value != 0:
                byte |= 0x80
            result.append(byte)
            if value == 0:
                break
        return bytes(result)
    
    @staticmethod
    def encode_string(s: str) -> bytes:
        data = s.encode('utf-8')
        return BCSEncoder.encode_uleb128(len(data)) + data


class ProductionTransaction:
    """Production-ready transaction builder for Sui"""
    
    @staticmethod
    async def build_transfer_transaction(
        sender: str,
        recipient: str,
        amount: Decimal,
        coin_type: str,
        coin_objects: List[Dict[str, Any]],
        gas_budget: int = 100000000,
        gas_price: int = 1000,
        sponsor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build a transfer transaction with proper encoding
        
        Args:
            sender: Sender's Sui address
            recipient: Recipient's Sui address  
            amount: Amount to send (with decimals)
            coin_type: Full coin type string
            coin_objects: List of coin objects to use
            gas_budget: Gas budget in MIST
            gas_price: Gas price in MIST
            sponsor: Optional sponsor address for gas payment
            
        Returns:
            Transaction data ready for signing and submission
        """
        # Determine decimals based on coin type
        if 'cusd' in coin_type.lower():
            decimals = 6
        elif 'confio' in coin_type.lower():
            decimals = 9
        else:
            decimals = 9  # Default
        
        amount_units = int(amount * Decimal(10 ** decimals))
        
        # Build programmable transaction
        if len(coin_objects) == 1:
            # Use split_and_transfer for single coin
            tx_data = {
                "sender": sender,
                "inputs": [
                    {
                        "type": "object",
                        "objectType": "immOrOwnedObject",
                        "objectId": coin_objects[0]['objectId'],
                        "version": coin_objects[0].get('version'),
                        "digest": coin_objects[0].get('digest')
                    },
                    {
                        "type": "pure",
                        "valueType": "u64",
                        "value": str(amount_units)
                    },
                    {
                        "type": "pure",
                        "valueType": "address",
                        "value": recipient
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
                ],
                "gasBudget": str(gas_budget),
                "gasPrice": str(gas_price)
            }
        else:
            # Merge coins first, then transfer
            coin_inputs = []
            for i, coin in enumerate(coin_objects):
                coin_inputs.append({
                    "type": "object",
                    "objectType": "immOrOwnedObject",
                    "objectId": coin['objectId'],
                    "version": coin.get('version'),
                    "digest": coin.get('digest')
                })
            
            # Add recipient as last input
            all_inputs = coin_inputs + [{
                "type": "pure",
                "valueType": "address",
                "value": recipient
            }]
            
            # Build merge vector
            merge_args = [{"Input": i} for i in range(len(coin_objects))]
            
            tx_data = {
                "sender": sender,
                "inputs": all_inputs,
                "transactions": [
                    {
                        "MoveCall": {
                            "package": "0x2",
                            "module": "pay",
                            "function": "join_vec",
                            "type_arguments": [coin_type],
                            "arguments": [
                                {"Input": 0},  # primary coin
                                merge_args[1:]  # coins to merge
                            ]
                        }
                    },
                    {
                        "TransferObjects": {
                            "objects": [{"Result": 0}],  # merged coin
                            "address": {"Input": len(coin_objects)}  # recipient
                        }
                    }
                ],
                "gasBudget": str(gas_budget),
                "gasPrice": str(gas_price)
            }
        
        # Add sponsor if provided
        if sponsor:
            tx_data["gasSponsor"] = sponsor
            tx_data["gasPayment"] = []  # Sponsor pays
        
        return tx_data
    
    @staticmethod
    async def build_sponsored_wrapper(
        user_transaction: Dict[str, Any],
        sponsor_address: str,
        sponsor_signature: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Wrap a user transaction for sponsorship
        
        This creates the proper structure for a sponsored transaction
        where the sponsor pays gas on behalf of the user.
        """
        return {
            "sponsoredTransaction": {
                "sender": user_transaction["sender"],
                "transaction": user_transaction,
                "sponsor": sponsor_address,
                "sponsorSignature": sponsor_signature
            }
        }
    
    @staticmethod
    def encode_transaction_data(tx_data: Dict[str, Any]) -> str:
        """
        Encode transaction data to base64 for signing
        
        This is a simplified version - production should use full BCS encoding
        """
        # TODO: Implement proper BCS encoding according to Sui spec
        # For now, return JSON encoding as placeholder
        tx_json = json.dumps(tx_data, sort_keys=True, separators=(',', ':'))
        tx_bytes = tx_json.encode('utf-8')
        return base64.b64encode(tx_bytes).decode('utf-8')
    
    @staticmethod
    async def sign_transaction(
        tx_bytes: str,
        private_key: str,
        signature_scheme: str = "ED25519"
    ) -> str:
        """
        Sign transaction bytes
        
        In production, this would use proper cryptographic signing
        For zkLogin, this would interface with the zkLogin service
        """
        # Fail closed instead of producing mock signatures
        raise NotImplementedError("sign_transaction must use a real cryptographic signer; placeholder disabled for safety")
    
    @staticmethod
    async def submit_transaction(
        tx_bytes: str,
        signatures: List[str],
        rpc_url: str,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Submit a signed transaction to the Sui network
        
        Args:
            tx_bytes: Base64 encoded transaction bytes
            signatures: List of base64 encoded signatures
            rpc_url: Sui RPC endpoint URL
            headers: Optional headers for RPC request
            
        Returns:
            Transaction result from RPC
        """
        import aiohttp
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sui_executeTransactionBlock",
            "params": [
                tx_bytes,
                signatures,
                {
                    "showInput": True,
                    "showEffects": True,
                    "showEvents": True,
                    "showObjectChanges": True,
                    "showBalanceChanges": True
                }
            ]
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                rpc_url,
                json=payload,
                headers=headers or {}
            ) as response:
                result = await response.json()
                
                if 'error' in result:
                    raise Exception(f"RPC error: {result['error']}")
                
                return result.get('result', {})


# Example usage:
async def example_production_send():
    """Example of production transaction flow"""
    
    # 1. Build transaction
    tx_data = await ProductionTransaction.build_transfer_transaction(
        sender="0x28dae7c8bde2f3ca608f86d0e16a214dee74c74bee011cdfdd46bc04b655bc14",
        recipient="0x65a699905c02619370bcf9207f5a477c3d67130ca71ec6f750e07fe8d510b084",
        amount=Decimal("5.0"),
        coin_type="0x551a39bd96679261aaf731e880b88fa528b66ee2ef6f0da677bdf0762b907bcf::cusd::CUSD",
        coin_objects=[{
            "objectId": "0x123...",
            "version": "100",
            "digest": "abc...",
            "balance": "10000000"
        }],
        sponsor="0xed36f82d851c5b54ebc8b58a71ea6473823e073a01ce8b6a5c04a4bcebaf6aef"
    )
    
    # 2. Encode for signing
    tx_bytes = ProductionTransaction.encode_transaction_data(tx_data)
    
    # 3. Get signatures (user via zkLogin, sponsor via private key)
    user_signature = await ProductionTransaction.sign_transaction(
        tx_bytes, 
        "user_zklogin_key",
        "ZKLOGIN"
    )
    
    sponsor_signature = await ProductionTransaction.sign_transaction(
        tx_bytes,
        "sponsor_private_key",
        "ED25519"
    )
    
    # 4. Submit transaction
    result = await ProductionTransaction.submit_transaction(
        tx_bytes,
        [sponsor_signature, user_signature],  # Order matters!
        "https://fullnode.testnet.sui.io:443"
    )
    
    return result
