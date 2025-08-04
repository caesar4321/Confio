#!/usr/bin/env python3
"""
Generate zkLogin circuit inputs from JWT and other parameters.
Based on the kzero-circuit input format.
"""

import json
import base64
import hashlib
from typing import Dict, List, Tuple

def base64url_decode(data: str) -> bytes:
    """Decode base64url string"""
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data)

def parse_jwt(jwt_str: str) -> Tuple[str, str, str, dict, dict]:
    """Parse JWT into components"""
    parts = jwt_str.split('.')
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    
    header_b64 = parts[0]
    payload_b64 = parts[1]
    signature_b64 = parts[2]
    
    header = json.loads(base64url_decode(header_b64))
    payload = json.loads(base64url_decode(payload_b64))
    
    return header_b64, payload_b64, signature_b64, header, payload

def find_field_in_jwt(payload_b64: str, field_name: str, field_value: str) -> Dict:
    """Find field position in base64 JWT payload"""
    payload_str = base64url_decode(payload_b64).decode('utf-8')
    
    # Find the field in JSON
    search_str = f'"{field_name}":'
    field_index = payload_str.find(search_str)
    
    if field_index == -1:
        return {
            'index': 0,
            'length': 0,
            'value_index': 0,
            'value_length': 0,
            'colon_index': 0
        }
    
    # Find colon position
    colon_index = field_index + len(search_str) - 1
    
    # Find value start (after colon and spaces/quotes)
    value_start = colon_index + 1
    while value_start < len(payload_str) and payload_str[value_start] in ' "':
        value_start += 1
    
    # Find value end
    value_end = value_start
    in_quotes = payload_str[value_start - 1] == '"'
    while value_end < len(payload_str):
        if in_quotes and payload_str[value_end] == '"':
            break
        elif not in_quotes and payload_str[value_end] in ',}':
            break
        value_end += 1
    
    return {
        'index': field_index,
        'length': len(search_str) + (value_end - value_start),
        'value_index': value_start - field_index,
        'value_length': value_end - value_start,
        'colon_index': len(search_str) - 1
    }

def string_to_ascii_array(s: str, max_length: int = 1024) -> List[str]:
    """Convert string to padded ASCII array"""
    arr = [str(ord(c)) for c in s]
    while len(arr) < max_length:
        arr.append("0")
    return arr[:max_length]

def generate_zklogin_inputs(
    jwt: str,
    ephemeral_public_key: str,
    max_epoch: str,
    jwt_randomness: str,
    salt: str,
    key_claim_name: str = "sub"
) -> Dict:
    """Generate zkLogin circuit inputs"""
    
    # Parse JWT
    header_b64, payload_b64, signature_b64, header, payload = parse_jwt(jwt)
    
    # Create unsigned JWT (header.payload)
    unsigned_jwt = f"{header_b64}.{payload_b64}"
    
    # Find field positions
    aud_info = find_field_in_jwt(payload_b64, "aud", payload.get("aud", ""))
    nonce_info = find_field_in_jwt(payload_b64, "nonce", payload.get("nonce", ""))
    kc_info = find_field_in_jwt(payload_b64, key_claim_name, payload.get(key_claim_name, ""))
    
    # Convert ephemeral key (assuming it's base64)
    eph_key_bytes = base64.b64decode(ephemeral_public_key)
    # Split into two 128-bit numbers for circuit
    eph_key_1 = int.from_bytes(eph_key_bytes[:16], 'big')
    eph_key_2 = int.from_bytes(eph_key_bytes[16:32], 'big')
    
    # Prepare inputs
    inputs = {
        "padded_unsigned_jwt": string_to_ascii_array(unsigned_jwt, 1024),
        "signature": list(signature_b64),  # Keep as base64 string chars
        "modulus": ["0"] * 256,  # RSA modulus (needs actual value)
        "payload_len": str(len(payload_b64)),
        "payload_start_index": str(len(header_b64) + 1),  # After header and dot
        "eph_public_key": [str(eph_key_1), str(eph_key_2)],
        "max_epoch": max_epoch,
        "jwt_randomness": jwt_randomness,
        "salt": salt,
        
        # Audience field
        "aud_index_b64": str(aud_info['index']),
        "aud_length_b64": str(aud_info['length']),
        "aud_value_index": str(aud_info['value_index']),
        "aud_value_length": str(aud_info['value_length']),
        "aud_colon_index": str(aud_info['colon_index']),
        
        # Nonce field
        "nonce_index_b64": str(nonce_info['index']),
        "nonce_length_b64": str(nonce_info['length']),
        "nonce_value_index": str(nonce_info['value_index']),
        "nonce_colon_index": str(nonce_info['colon_index']),
        
        # Key claim field
        "kc_index_b64": str(kc_info['index']),
        "kc_length_b64": str(kc_info['length']),
        "kc_value_index": str(kc_info['value_index']),
        "kc_value_length": str(kc_info['value_length']),
        "kc_colon_index": str(kc_info['colon_index']),
        "kc_name_length": str(len(key_claim_name)),
        
        # Extended fields (actual values as ASCII arrays)
        "ext_aud": string_to_ascii_array(json.dumps(payload.get("aud", "")), 256),
        "ext_aud_length": str(len(json.dumps(payload.get("aud", "")))),
        "ext_nonce": string_to_ascii_array(payload.get("nonce", ""), 256),
        "ext_nonce_length": str(len(payload.get("nonce", ""))),
        "ext_kc": string_to_ascii_array(payload.get(key_claim_name, ""), 256),
        "ext_kc_length": str(len(payload.get(key_claim_name, ""))),
        
        # Email verified field (if exists)
        "ev_index_b64": "0",
        "ev_length_b64": "0",
        "ev_value_index": "0",
        "ev_value_length": "0",
        "ev_colon_index": "0",
        "ev_name_length": "0",
        "ext_ev": ["0"] * 256,
        "ext_ev_length": "0",
        
        # Other required fields
        "iss_index_b64": "0",
        "iss_length_b64": "0",
        "num_sha2_blocks": "4",  # Depends on JWT size
        "all_inputs_hash": "0"  # Will be computed by circuit
    }
    
    return inputs

if __name__ == "__main__":
    # Test with sample data
    test_jwt = "eyJhbGciOiJSUzI1NiIsImtpZCI6InRlc3QifQ.eyJpc3MiOiJodHRwczovL2FwcGxlaWQuYXBwbGUuY29tIiwic3ViIjoidGVzdC11c2VyIiwiYXVkIjoiYXBwbGUiLCJub25jZSI6InRlc3Qtbm9uY2UifQ.signature"
    
    inputs = generate_zklogin_inputs(
        jwt=test_jwt,
        ephemeral_public_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        max_epoch="100",
        jwt_randomness="12345",
        salt="67890",
        key_claim_name="sub"
    )
    
    print(json.dumps(inputs, indent=2))