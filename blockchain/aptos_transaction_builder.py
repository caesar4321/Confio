"""
Aptos Transaction Builder for Frontend Signing

This module creates unsigned transactions that can be sent to the frontend
for signing with the user's ephemeral key.
"""

import time
from typing import Dict, Any, Tuple
from decimal import Decimal
import base64

from aptos_sdk.transactions import (
    RawTransaction,
    TransactionPayload,
    EntryFunction,
    TransactionArgument,
    FeePayerRawTransaction
)
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.bcs import Serializer


class AptosTransactionBuilder:
    """Build unsigned transactions for frontend signing"""
    
    # Aptos testnet chain ID
    CHAIN_ID = 2
    
    # Standard transaction parameters
    DEFAULT_GAS_LIMIT = 100000
    DEFAULT_GAS_PRICE = 100
    DEFAULT_EXPIRATION_SECS = 600  # 10 minutes
    
    @classmethod
    def build_transfer_transaction(
        cls,
        sender_address: str,
        function_id: str,
        arguments: list,
        type_arguments: list = None,
        sequence_number: int = 0,
        gas_limit: int = None,
        gas_price: int = None,
        expiration_secs: int = None
    ) -> Tuple[RawTransaction, bytes, str]:
        """
        Build an unsigned transaction for token transfer
        
        Returns:
            - RawTransaction object
            - BCS serialized bytes for signing
            - Base64 encoded transaction bytes
        """
        
        # Parse function ID
        module_address, module_name, function_name = function_id.split('::')
        
        # Convert arguments to TransactionArgument objects with proper serializers
        function_args = []
        for arg in arguments:
            if isinstance(arg, str) and arg.startswith('0x'):
                # Address argument
                address = AccountAddress.from_str(arg)
                function_args.append(TransactionArgument(address, lambda s, v: s.struct(v)))
            elif isinstance(arg, (int, str)) and str(arg).isdigit():
                # Numeric argument (u64)
                value = int(arg)
                function_args.append(TransactionArgument(value, lambda s, v: s.u64(v)))
            else:
                # String arguments
                function_args.append(TransactionArgument(str(arg), lambda s, v: s.str(v)))
        
        # Create entry function
        # EntryFunction.natural expects: module_id, function_name, type_args, args
        module_id = f"{module_address}::{module_name}"
        entry_function = EntryFunction.natural(
            module_id,
            function_name,
            type_arguments or [],
            function_args
        )
        
        # Create transaction payload
        payload = TransactionPayload(entry_function)
        
        # Build raw transaction
        raw_txn = RawTransaction(
            sender=AccountAddress.from_str(sender_address),
            sequence_number=sequence_number,
            payload=payload,
            max_gas_amount=gas_limit or cls.DEFAULT_GAS_LIMIT,
            gas_unit_price=gas_price or cls.DEFAULT_GAS_PRICE,
            expiration_timestamps_secs=int(time.time()) + (expiration_secs or cls.DEFAULT_EXPIRATION_SECS),
            chain_id=cls.CHAIN_ID
        )
        
        # Serialize transaction for signing
        serializer = Serializer()
        raw_txn.serialize(serializer)
        txn_bytes = serializer.output()
        
        # Create signing message (prefix + BCS bytes)
        # Aptos uses a specific prefix for transaction signing
        prefix = b"APTOS::RawTransaction"
        signing_message = prefix + txn_bytes
        
        # Base64 encode for frontend
        txn_base64 = base64.b64encode(txn_bytes).decode('utf-8')
        signing_message_base64 = base64.b64encode(signing_message).decode('utf-8')
        
        return raw_txn, signing_message, signing_message_base64
    
    @classmethod
    def build_sponsored_transaction(
        cls,
        sender_address: str,
        sponsor_address: str,
        function_id: str,
        arguments: list,
        type_arguments: list = None,
        sequence_number: int = 0,
        gas_limit: int = None,
        gas_price: int = None,
        expiration_secs: int = None
    ) -> Tuple[FeePayerRawTransaction, bytes, Dict[str, Any]]:
        """
        Build an unsigned fee-payer transaction for sponsored transfers
        
        Returns:
            - FeePayerRawTransaction object
            - BCS serialized bytes for signing
            - Transaction metadata dict
        """
        
        # First build the base transaction
        raw_txn, _, _ = cls.build_transfer_transaction(
            sender_address=sender_address,
            function_id=function_id,
            arguments=arguments,
            type_arguments=type_arguments,
            sequence_number=sequence_number,
            gas_limit=gas_limit,
            gas_price=gas_price,
            expiration_secs=expiration_secs
        )
        
        # Create fee-payer transaction
        fee_payer_txn = FeePayerRawTransaction(
            raw_transaction=raw_txn,
            secondary_signers=[],  # No secondary signers for simple sponsored txn
            fee_payer=AccountAddress.from_str(sponsor_address)
        )
        
        # Serialize for signing
        serializer = Serializer()
        fee_payer_txn.serialize(serializer)
        txn_bytes = serializer.output()
        
        # Create signing message for FeePayerRawTransaction
        # Use proper domain separation with SHA3-256 hashing
        import hashlib
        hasher = hashlib.sha3_256()
        hasher.update(b"APTOS::RawTransactionWithData")
        prehash = hasher.digest()
        signing_message = prehash + txn_bytes
        
        # Create metadata for frontend
        metadata = {
            'transaction_type': 'fee_payer',
            'sender': sender_address,
            'sponsor': sponsor_address,
            'function': function_id,
            'arguments': arguments,
            'sequence_number': sequence_number,
            'gas_limit': gas_limit or cls.DEFAULT_GAS_LIMIT,
            'gas_price': gas_price or cls.DEFAULT_GAS_PRICE,
            'expiration': int(time.time()) + (expiration_secs or cls.DEFAULT_EXPIRATION_SECS),
            'chain_id': cls.CHAIN_ID,
            'signing_message': base64.b64encode(signing_message).decode('utf-8'),
            'transaction_bytes': base64.b64encode(txn_bytes).decode('utf-8')
        }
        
        return fee_payer_txn, signing_message, metadata
    
    @classmethod
    def prepare_for_frontend(
        cls,
        transaction_type: str,
        sender_address: str,
        recipient_address: str,
        amount: Decimal,
        token_type: str = 'CONFIO',
        sponsor_address: str = None
    ) -> Dict[str, Any]:
        """
        Prepare transaction data for frontend signing
        
        Returns complete transaction data ready for frontend
        """
        
        # Token configuration
        token_configs = {
            'CONFIO': {
                'contract': '0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c',
                'module': 'confio',
                'function': 'transfer_confio',
                'decimals': 6
            },
            'CUSD': {
                'contract': '0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c',
                'module': 'cusd',
                'function': 'transfer_cusd',
                'decimals': 6
            }
        }
        
        config = token_configs.get(token_type.upper())
        if not config:
            raise ValueError(f"Unsupported token type: {token_type}")
        
        # Convert amount to base units
        base_amount = int(amount * (10 ** config['decimals']))
        
        # Build function ID
        function_id = f"{config['contract']}::{config['module']}::{config['function']}"
        
        # Arguments for transfer function
        arguments = [recipient_address, base_amount]
        
        # Build appropriate transaction type
        if transaction_type == 'sponsored' and sponsor_address:
            fee_payer_txn, signing_message, metadata = cls.build_sponsored_transaction(
                sender_address=sender_address,
                sponsor_address=sponsor_address,
                function_id=function_id,
                arguments=arguments,
                sequence_number=0  # Frontend should provide actual sequence
            )
            
            return {
                'type': 'sponsored',
                'metadata': metadata,
                'signing_required': True,
                'signing_message': metadata['signing_message'],
                'instructions': 'Sign the signing_message with your ephemeral private key using Ed25519'
            }
        else:
            raw_txn, signing_message, signing_message_base64 = cls.build_transfer_transaction(
                sender_address=sender_address,
                function_id=function_id,
                arguments=arguments,
                sequence_number=0  # Frontend should provide actual sequence
            )
            
            return {
                'type': 'regular',
                'signing_message': signing_message_base64,
                'transaction_bytes': base64.b64encode(signing_message).decode('utf-8'),
                'metadata': {
                    'sender': sender_address,
                    'recipient': recipient_address,
                    'amount': str(amount),
                    'token': token_type,
                    'function': function_id
                },
                'signing_required': True,
                'instructions': 'Sign the signing_message with your ephemeral private key using Ed25519'
            }