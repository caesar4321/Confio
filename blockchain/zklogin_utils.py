"""
Utilities for handling zkLogin signatures
"""
import base64
import json
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


def build_zklogin_signature(
    ephemeral_signature: str,
    zkproof: Dict[str, Any],
    issuer: str,
    max_epoch: int,
    user_salt: str,
    subject: str,
    audience: str
) -> str:
    """
    Build a zkLogin signature for Sui transaction execution
    
    The zkLogin signature format for Sui includes:
    - The ephemeral signature
    - The zkProof (a, b, c points)
    - Additional metadata
    
    Args:
        ephemeral_signature: Base64 encoded ephemeral signature
        zkproof: The zkProof object with a, b, c fields
        issuer: JWT issuer (e.g., "https://accounts.google.com")
        max_epoch: Maximum epoch for the signature
        user_salt: User salt used for address generation
        subject: JWT subject
        audience: JWT audience
        
    Returns:
        Base64 encoded zkLogin signature
    """
    try:
        # The zkLogin signature structure for Sui
        # Based on Sui's zkLogin implementation
        zklogin_sig = {
            "zkLogin": {
                "proofPoints": {
                    "a": zkproof.get("a", []),
                    "b": zkproof.get("b", []),
                    "c": zkproof.get("c", [])
                },
                "issBase64Details": {
                    "iss": base64.b64encode(issuer.encode()).decode(),
                    "kid": ""  # Key ID if needed
                },
                "headerBase64": "",  # JWT header if needed
                "userSignature": ephemeral_signature,
                "addressSeed": user_salt  # This affects address derivation
            }
        }
        
        # For Sui, the signature format might be different
        # This is a simplified version - the actual format depends on Sui's implementation
        
        # Convert to JSON and base64 encode
        sig_json = json.dumps(zklogin_sig)
        sig_bytes = sig_json.encode('utf-8')
        sig_base64 = base64.b64encode(sig_bytes).decode()
        
        logger.info(f"Built zkLogin signature structure")
        return sig_base64
        
    except Exception as e:
        logger.error(f"Error building zkLogin signature: {e}")
        raise


def format_zkproof_for_sui(zkproof_data: Any) -> Dict[str, Any]:
    """
    Format the zkProof data from the prover service for Sui
    
    Args:
        zkproof_data: Raw zkProof data from prover or GraphQL
        
    Returns:
        Formatted zkProof dict with a, b, c fields
    """
    # Handle different formats of zkProof
    if isinstance(zkproof_data, dict):
        # Remove GraphQL __typename if present
        if "__typename" in zkproof_data:
            return {
                "a": zkproof_data.get("a", []),
                "b": zkproof_data.get("b", []),
                "c": zkproof_data.get("c", [])
            }
        # Check if it's nested
        if "zkProof" in zkproof_data:
            return format_zkproof_for_sui(zkproof_data["zkProof"])
        # Already in correct format
        return zkproof_data
    else:
        logger.error(f"Invalid zkProof format: {type(zkproof_data)}")
        raise ValueError("Invalid zkProof format")