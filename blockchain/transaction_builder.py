"""
Simple Sui transaction builder for sponsored transactions
"""
import json
import base64
import hashlib
from typing import Dict, List, Any, Optional
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class SuiTransactionBuilder:
    """
    Build Sui transactions for sponsored execution
    
    Note: This is a simplified builder for our specific use cases.
    For production, consider using the official Sui SDK.
    """
    
    @staticmethod
    def build_transfer_transaction(
        sender: str,
        recipient: str,
        amount: int,
        coin_object_ids: List[str],
        coin_type: str,
        gas_budget: int = 10000000,
        sponsor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build a transfer transaction
        
        Args:
            sender: Sender's Sui address
            recipient: Recipient's Sui address
            amount: Amount in smallest units
            coin_object_ids: List of coin object IDs to use
            coin_type: Full coin type (e.g., "0x2::sui::SUI")
            gas_budget: Gas budget in MIST
            sponsor: Optional sponsor address for gas payment
            
        Returns:
            Transaction data ready for RPC
        """
        if len(coin_object_ids) == 1:
            # Single coin - use TransferObjects
            return {
                "sender": sender,
                "gasPayment": None if sponsor else coin_object_ids,
                "gasBudget": str(gas_budget),
                "gasPrice": "1000",
                "sponsor": sponsor,
                "inputs": [
                    {
                        "type": "object",
                        "objectType": "immOrOwnedObject",
                        "objectId": coin_object_ids[0],
                        "version": None,
                        "digest": None
                    },
                    {
                        "type": "pure",
                        "valueType": "address", 
                        "value": recipient
                    }
                ],
                "transactions": [
                    {
                        "TransferObjects": {
                            "objects": [{"Input": 0}],
                            "address": {"Input": 1}
                        }
                    }
                ]
            }
        else:
            # Multiple coins - need to merge first
            # For now, we'll use the first coin only
            # TODO: Implement coin merging
            logger.warning(f"Multiple coins provided ({len(coin_object_ids)}), using first coin only")
            return SuiTransactionBuilder.build_transfer_transaction(
                sender, recipient, amount, [coin_object_ids[0]], 
                coin_type, gas_budget, sponsor
            )
    
    @staticmethod
    def build_split_and_transfer_transaction(
        sender: str,
        recipient: str,
        amount: int,
        coin_object_id: str,
        coin_type: str,
        gas_budget: int = 10000000,
        sponsor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build a transaction that splits a coin and transfers the split amount
        
        This is useful when the coin has more value than needed
        """
        return {
            "sender": sender,
            "gasPayment": None if sponsor else [coin_object_id],
            "gasBudget": str(gas_budget),
            "gasPrice": "1000",
            "sponsor": sponsor,
            "inputs": [
                {
                    "type": "object",
                    "objectType": "immOrOwnedObject",
                    "objectId": coin_object_id,
                    "version": None,
                    "digest": None
                },
                {
                    "type": "pure",
                    "valueType": "u64",
                    "value": str(amount)
                },
                {
                    "type": "pure",
                    "valueType": "address",
                    "value": recipient
                }
            ],
            "transactions": [
                {
                    "SplitCoins": {
                        "coin": {"Input": 0},
                        "amounts": [{"Input": 1}]
                    }
                },
                {
                    "TransferObjects": {
                        "objects": [{"NestedResult": [0, 0]}],
                        "address": {"Input": 2}
                    }
                }
            ]
        }
    
    @staticmethod
    def build_pay_transaction(
        payer: str,
        recipients: List[str],
        amounts: List[int],
        coin_object_ids: List[str],
        coin_type: str,
        gas_budget: int = 10000000,
        sponsor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build a pay transaction (multiple recipients)
        
        Uses the Sui framework's pay module
        """
        # Build inputs
        inputs = []
        
        # Add coin objects
        for coin_id in coin_object_ids:
            inputs.append({
                "type": "object",
                "objectType": "immOrOwnedObject",
                "objectId": coin_id,
                "version": None,
                "digest": None
            })
        
        # Add recipients array
        inputs.append({
            "type": "pure",
            "valueType": "vector<address>",
            "value": recipients
        })
        
        # Add amounts array
        inputs.append({
            "type": "pure",
            "valueType": "vector<u64>",
            "value": [str(amt) for amt in amounts]
        })
        
        return {
            "sender": payer,
            "gasPayment": None if sponsor else coin_object_ids[:1],
            "gasBudget": str(gas_budget),
            "gasPrice": "1000", 
            "sponsor": sponsor,
            "inputs": inputs,
            "transactions": [
                {
                    "MoveCall": {
                        "package": "0x2",
                        "module": "pay",
                        "function": "split_vec",
                        "type_arguments": [coin_type],
                        "arguments": [
                            {"Input": 0},  # First coin
                            {"Input": len(coin_object_ids)},  # Recipients vector
                            {"Input": len(coin_object_ids) + 1}  # Amounts vector
                        ]
                    }
                }
            ]
        }
    
    @staticmethod
    def serialize_transaction(tx_data: Dict[str, Any]) -> str:
        """
        Serialize transaction data to base64 for signing
        
        Note: This is a simplified version. Real serialization requires
        BCS encoding according to Sui's transaction format.
        """
        # For now, return a mock serialization
        # In production, this would use proper BCS encoding
        tx_json = json.dumps(tx_data, sort_keys=True)
        tx_bytes = tx_json.encode('utf-8')
        return base64.b64encode(tx_bytes).decode('utf-8')