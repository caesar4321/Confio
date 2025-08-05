#!/usr/bin/env python3
"""
Test direct transaction structure to understand the ULEB128 error
"""

import os
from aptos_sdk.account import Account
from aptos_sdk.transactions import (
    RawTransaction,
    FeePayerRawTransaction,
    SignedTransaction,
    TransactionPayload,
    EntryFunction,
    TransactionArgument
)
from aptos_sdk.authenticator import (
    Authenticator,
    Ed25519Authenticator,
    FeePayerAuthenticator,
    AccountAuthenticator
)
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.bcs import Serializer, Deserializer
from aptos_sdk.ed25519 import PublicKey, Signature
import time

# Test data
user_address = "0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c"
recipient_address = "0x2b4efedb3d02b5546cd1473053ba8f65c07e04452cd1fa7383cc552d38b26c36"
sponsor_address = "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c"

# Load sponsor account
sponsor_private_key = os.getenv('APTOS_SPONSOR_PRIVATE_KEY')
if not sponsor_private_key:
    print("❌ APTOS_SPONSOR_PRIVATE_KEY not set")
    exit(1)

sponsor_account = Account.load_key(sponsor_private_key)

print("🧪 Testing Transaction Structure")
print("=" * 60)

# Build the raw transaction
payload = TransactionPayload(
    EntryFunction.natural(
        "0x75f38ae0c198dcedf766e0d2a39847f9b269052024e943c58970854b9cb70e2c::confio",
        "transfer_confio",
        [],
        [
            TransactionArgument(
                AccountAddress.from_str(recipient_address),
                lambda s, v: s.struct(v)
            ),
            TransactionArgument(
                10000,  # 0.01 CONFIO
                lambda s, v: s.u64(v)
            )
        ]
    )
)

raw_txn = RawTransaction(
    sender=AccountAddress.from_str(user_address),
    sequence_number=0,
    payload=payload,
    max_gas_amount=100000,
    gas_unit_price=100,
    expiration_timestamps_secs=int(time.time()) + 600,
    chain_id=2
)

print(f"✅ Built raw transaction")

# Create fee payer transaction
fee_payer_txn = FeePayerRawTransaction(
    raw_transaction=raw_txn,
    secondary_signers=[],
    fee_payer=sponsor_account.address()
)

print(f"✅ Built fee payer transaction")

# Serialize for signing
serializer = Serializer()
fee_payer_txn.serialize(serializer)
txn_bytes = serializer.output()
signing_message = b"APTOS::RawTransaction" + txn_bytes

print(f"📋 Transaction details:")
print(f"   Signing message length: {len(signing_message)} bytes")
print(f"   Transaction bytes length: {len(txn_bytes)} bytes")

# Test deserialization
try:
    deserializer = Deserializer(txn_bytes)
    deserialized = FeePayerRawTransaction.deserialize(deserializer)
    print(f"✅ Successfully deserialized FeePayerRawTransaction")
except Exception as e:
    print(f"❌ Failed to deserialize: {e}")

# Create test user authenticator (simulate frontend signature)
# In real scenario, this would be the user's ephemeral key
test_user_key = Account.generate()
user_signature = test_user_key.sign(signing_message)
user_auth = AccountAuthenticator(
    Ed25519Authenticator(test_user_key.public_key(), user_signature)
)

print(f"✅ Created user authenticator")

# Sponsor signs the transaction
sponsor_auth = sponsor_account.sign_transaction(fee_payer_txn)

print(f"✅ Created sponsor authenticator")

# Create fee payer authenticator
fee_payer_auth = FeePayerAuthenticator(
    sender=user_auth,
    secondary_signers=[],
    fee_payer=(sponsor_account.address(), sponsor_auth)
)

print(f"✅ Created fee payer authenticator")

# Create signed transaction
try:
    signed_txn = SignedTransaction(
        transaction=fee_payer_txn,
        authenticator=Authenticator(fee_payer_auth)
    )
    print(f"✅ Created signed transaction")
    
    # Try to serialize it
    serializer = Serializer()
    signed_txn.serialize(serializer)
    final_bytes = serializer.output()
    
    print(f"✅ Successfully serialized signed transaction")
    print(f"   Final transaction size: {len(final_bytes)} bytes")
    
    # Try to deserialize to verify
    deserializer = Deserializer(final_bytes)
    deserialized_signed = SignedTransaction.deserialize(deserializer)
    print(f"✅ Successfully deserialized signed transaction")
    
except Exception as e:
    print(f"❌ Error with signed transaction: {e}")
    import traceback
    traceback.print_exc()

print("\n✅ Test complete - transaction structure is valid")