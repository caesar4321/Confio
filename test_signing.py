#!/usr/bin/env python3
"""
Test how to sign with SuiKeyPair
"""
from pysui.sui.sui_crypto import SuiKeyPair
import base64

def test_signing():
    """Test signing methods"""
    
    # Create a test keypair
    private_key = "suiprivkey1qqa5v7y8n6r24h2kzehm5kqa85f9nl03td56ctxflc3d8zr2x9enxzruhz6"
    keypair = SuiKeyPair.from_bech32(private_key)
    
    print(f"Keypair type: {type(keypair)}")
    print(f"Keypair methods: {[m for m in dir(keypair) if not m.startswith('_') and 'sign' in m]}")
    
    # Check what the keypair has
    if hasattr(keypair, 'signing_key'):
        print(f"Has signing_key: {type(keypair.signing_key)}")
        print(f"Signing key methods: {[m for m in dir(keypair.signing_key) if not m.startswith('_') and 'sign' in m]}")
    
    # Test signing
    test_bytes = b"test message"
    
    # Try different signing methods
    if hasattr(keypair, 'sign_secure'):
        try:
            # sign_secure expects base64 string
            result = keypair.sign_secure(base64.b64encode(test_bytes).decode())
            print(f"\nsign_secure result: {result}")
        except Exception as e:
            print(f"sign_secure error: {e}")
    
    if hasattr(keypair, 'signing_key') and hasattr(keypair.signing_key, 'sign_secure'):
        try:
            result = keypair.signing_key.sign_secure(base64.b64encode(test_bytes).decode())
            print(f"\nsigning_key.sign_secure result: {result}")
        except Exception as e:
            print(f"signing_key.sign_secure error: {e}")
    
    # Check for direct sign method
    if hasattr(keypair, 'signing_key'):
        sk = keypair.signing_key
        print(f"\nSigning key type: {type(sk)}")
        print(f"Signing key class: {sk.__class__.__name__}")


if __name__ == "__main__":
    test_signing()