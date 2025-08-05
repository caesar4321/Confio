"""
Deterministic pepper generation for Aptos Keyless
Following the same formula as zkLogin salt generation
"""
import hashlib
from typing import Optional

def generate_keyless_pepper(
    iss: str,
    sub: str, 
    aud: str,
    account_type: str = 'personal',
    business_id: str = '',
    account_index: int = 0
) -> str:
    """
    Generates a deterministic pepper for Aptos Keyless according to the formula:
    - Personal accounts: SHA256(issuer_subject_audience_account_type_account_index)
    - Business accounts: SHA256(issuer_subject_audience_account_type_business_id_account_index)
    
    Components are joined with underscore separators. Empty business_id is omitted.
    This ensures the same user with the same account parameters always gets the same address,
    making the system truly non-custodial.
    
    Args:
        iss: The issuer from the JWT (e.g., "https://accounts.google.com")
        sub: The subject from the JWT (user's unique ID)
        aud: The audience from the JWT (OAuth client ID)
        account_type: The account type ('personal' or 'business')
        business_id: The business ID (empty string for personal accounts)
        account_index: The account index (0, 1, 2, etc.)
    
    Returns:
        The pepper as a hex string with 0x prefix (31 bytes for Aptos)
    """
    # Concatenate all components with underscore separator
    # Format: iss_sub_aud_account_type_business_id_account_index
    # For personal accounts (no business_id), format: iss_sub_aud_account_type_account_index
    components = [iss, sub, aud, account_type]
    
    # Only include business_id if it's not empty
    if business_id:
        components.append(business_id)
    
    components.append(str(account_index))
    
    combined_string = '_'.join(components)
    combined = combined_string.encode('utf-8')
    
    # Generate SHA-256 hash
    full_hash = hashlib.sha256(combined).digest()
    
    # Aptos pepper is 31 bytes (248 bits)
    # Take the first 31 bytes of the hash
    pepper = full_hash[:31]
    
    # Return as hex string with 0x prefix
    return '0x' + pepper.hex()