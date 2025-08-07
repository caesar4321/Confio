#!/usr/bin/env python
"""
Test to understand Algorand key structure
"""

from algosdk import account, mnemonic
import nacl.signing
import base64

# Test mnemonic
test_mnemonic = "quantum there flavor biology family kiss sweet flag pyramid audit under slender small brush sibling world similar bubble enable roof recall include rally above gold"

# Get the private key (returns base64 string)
private_key_b64 = mnemonic.to_private_key(test_mnemonic)
address = account.address_from_private_key(private_key_b64)

print(f"Private key (base64) length: {len(private_key_b64)} chars")
print(f"Address: {address}")

# Decode from base64 to get the actual key bytes
private_key = base64.b64decode(private_key_b64)
print(f"Private key (bytes) length: {len(private_key)} bytes")
print(f"Private key (hex): {private_key.hex()}")

# The Algorand private key is 64 bytes:
# - First 32 bytes: the Ed25519 seed
# - Last 32 bytes: the public key

seed = private_key[:32]
public_key = private_key[32:]

print(f"\nSeed (first 32 bytes): {seed.hex()}")
print(f"Public key (last 32 bytes): {public_key.hex()}")

# Verify the public key derivation
signing_key = nacl.signing.SigningKey(seed)
derived_public = signing_key.verify_key.encode()

print(f"\nDerived public key from seed: {derived_public.hex()}")
print(f"Match: {derived_public == public_key}")

# Now test signing with the correct approach
import nacl.bindings

message = b"Test message"

# Method 1: Using the full 64-byte key with low-level nacl
signature1 = nacl.bindings.crypto_sign(message, private_key)[:64]  # crypto_sign prepends the message
print(f"\nSignature 1 (using full key): {signature1.hex()[:32]}...")

# Method 2: Using SigningKey with 32-byte seed  
signing_key = nacl.signing.SigningKey(seed)
signature2 = signing_key.sign(message).signature
print(f"Signature 2 (using seed): {signature2.hex()[:32]}...")

print(f"\nSignatures match: {signature1 == signature2}")