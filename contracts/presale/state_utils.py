#!/usr/bin/env python3
"""
State decoding utilities for CONFIO presale contract

Provides consistent parsing of Algorand global and local state.
"""

import base64
from typing import Dict, Any, List, Union
from algosdk import encoding
from decimal import Decimal, ROUND_DOWN


def decode_state(state_array: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Decode Algorand state array into a dictionary
    
    Args:
        state_array: Raw state from algod (global-state or local key-value)
    
    Returns:
        Dictionary with decoded keys and properly typed values
    """
    result = {}
    
    for item in state_array:
        # Decode the key from base64
        key = base64.b64decode(item['key']).decode('utf-8', errors='ignore')
        
        # Get the value based on type
        value_obj = item['value']
        
        if value_obj['type'] == 1:  # bytes
            # Return raw bytes (addresses and other binary data)
            raw_bytes = base64.b64decode(value_obj.get('bytes', ''))
            result[key] = raw_bytes
        
        elif value_obj['type'] == 2:  # uint
            result[key] = value_obj.get('uint', 0)
        
        else:
            # Unknown type, store raw
            result[key] = value_obj
    
    return result


def decode_global_state(app_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decode global state from application info
    
    Args:
        app_info: Application info from algod
    
    Returns:
        Decoded global state dictionary
    """
    global_state = app_info.get('params', {}).get('global-state', [])
    return decode_state(global_state)


def decode_local_state(account_info: Dict[str, Any], app_id: int) -> Dict[str, Any]:
    """
    Decode local state for a specific app from account info
    
    Args:
        account_info: Account info from algod
        app_id: Application ID to get state for
    
    Returns:
        Decoded local state dictionary, or empty dict if not opted in
    """
    for app in account_info.get('apps-local-state', []):
        if app['id'] == app_id:
            return decode_state(app.get('key-value', []))
    
    return {}


def format_confio_amount(micro_units: int) -> str:
    """Format CONFIO amount from micro units"""
    return f"{micro_units / 10**6:,.2f}"


def format_cusd_amount(micro_units: int) -> str:
    """Format cUSD amount from micro units (6 decimals)"""
    return f"{micro_units / 10**6:,.2f}"


def parse_confio_amount(amount_str: str) -> int:
    """Parse CONFIO amount string to micro units"""
    # Remove commas and use Decimal to avoid float rounding
    clean_str = amount_str.replace(',', '')
    return int((Decimal(clean_str) * (10**6)).to_integral_value(ROUND_DOWN))


def parse_cusd_amount(amount_str: str) -> int:
    """Parse cUSD amount string to micro units (6 decimals)"""
    # Remove commas and use Decimal to avoid float rounding
    clean_str = amount_str.replace(',', '')
    return int((Decimal(clean_str) * (10**6)).to_integral_value(ROUND_DOWN))


def to_algorand_address(maybe_bytes: Union[bytes, bytearray, str]) -> str:
    """
    Convert bytes to Algorand address if applicable
    
    Args:
        maybe_bytes: Raw bytes, bytearray, or already encoded address
    
    Returns:
        Base32-encoded Algorand address or original value
    """
    if isinstance(maybe_bytes, (bytes, bytearray)) and len(maybe_bytes) == 32:
        return encoding.encode_address(maybe_bytes)
    return maybe_bytes


def format_address(addr: Union[bytes, str]) -> str:
    """Format an address for display (shortened)"""
    full_addr = to_algorand_address(addr)
    if isinstance(full_addr, str) and len(full_addr) > 20:
        return f"{full_addr[:8]}...{full_addr[-6:]}"
    return str(full_addr)