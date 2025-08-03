#!/usr/bin/env python3
"""
Test SuiSignature object
"""
from pysui.sui.sui_crypto import SuiKeyPair
import base64

def test_signature():
    """Test what SuiSignature returns"""
    
    # Create a test keypair
    private_key = "suiprivkey1qqa5v7y8n6r24h2kzehm5kqa85f9nl03td56ctxflc3d8zr2x9enxzruhz6"
    keypair = SuiKeyPair.from_bech32(private_key)
    
    # Test signing
    test_bytes = b"test message"
    tx_bytes_b64 = base64.b64encode(test_bytes).decode()
    
    # Sign with new_sign_secure
    signature = keypair.new_sign_secure(tx_bytes_b64)
    
    print(f"Signature type: {type(signature)}")
    print(f"Signature class: {signature.__class__.__name__}")
    print(f"Signature attributes: {[attr for attr in dir(signature) if not attr.startswith('_')]}")
    
    # Check for common methods/attributes
    if hasattr(signature, 'signature'):
        print(f"\nsignature.signature: {signature.signature}")
        print(f"Type: {type(signature.signature)}")
    
    if hasattr(signature, 'to_bytes'):
        print(f"\nsignature.to_bytes(): {signature.to_bytes()}")
    
    if hasattr(signature, 'to_base64'):
        print(f"\nsignature.to_base64(): {signature.to_base64()}")
        
    if hasattr(signature, 'signature_bytes'):
        print(f"\nsignature.signature_bytes: {signature.signature_bytes}")
        
    # Try converting to string
    print(f"\nstr(signature): {str(signature)}")


if __name__ == "__main__":
    test_signature()