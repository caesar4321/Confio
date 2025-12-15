
import os
import django
import algosdk
from algosdk import encoding, account, mnemonic, transaction
from hashlib import sha256, pbkdf2_hmac
import hmac
import struct
import warnings
import sys

# Suppress pyteal warning
warnings.filterwarnings("ignore", category=UserWarning)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, WalletDerivationPepper
from blockchain.algorand_client import get_algod_client

# Constants from derivationSpec.ts
CONFIO_DERIVATION_SPEC = {
  'root': 'confio-wallet-v1',
  'extract': 'confio/extract/v1',
  'algoInfoPrefix': 'confio/algo/v1',
}

TARGET_ADDR = "PRDLU7ZJRFB2ZMFJHQW3J5G3NEGN6HHV47CVKNHDAGF5P7MJAMHR37R72E"
NEW_ADDRESS = "MDNNU3AXYICHOVIVHUAKITQEGUKSYRWJUQDATLJUQZMTFCVFRT34UO3J7Y"

def hkdf_extract_and_expand(salt, ikm, info, length=32):
    prk = hmac.new(salt, ikm, sha256).digest()
    t = b""
    okm = b""
    i = 0
    while len(okm) < length:
        i += 1
        t = hmac.new(prk, t + info + bytes([i]), sha256).digest()
        okm += t
    return okm[:length]

def derive_key_pair(client_salt, derivation_pepper, provider, account_type, account_index, business_id=None):
    ikm_string = f"{CONFIO_DERIVATION_SPEC['root']}|{client_salt}"
    ikm = sha256(ikm_string.encode('utf-8')).digest()

    extract_salt_input = f"{CONFIO_DERIVATION_SPEC['extract']}|{derivation_pepper}"
    extract_salt = sha256(extract_salt_input.encode('utf-8')).digest()

    bid_str = business_id if business_id else ''
    info_str = f"{CONFIO_DERIVATION_SPEC['algoInfoPrefix']}|{provider}|{account_type}|{account_index}|{bid_str}"
    info = info_str.encode('utf-8')

    seed32 = hkdf_extract_and_expand(extract_salt, ikm, info, 32)
    
    try:
        # Replicate Private Key Derivation
        
        # Algorand private key is usually the 32-byte seed + 32-byte public key.
        # But we need to use a library that takes the seed directly.
        from nacl.signing import SigningKey
        signing_key = SigningKey(seed32)
        verify_key = signing_key.verify_key
        pub_key_bytes = verify_key.encode()
        address = algosdk.encoding.encode_address(pub_key_bytes)
        
        # Construct private key for Algorand SDK (seed + public)
        private_key_bytes = seed32 + pub_key_bytes
        private_key_b64 = algosdk.encoding.msgpack.packb(private_key_bytes) # No, msgpack is for transaction
        # Standard encoding.msgpack.packb(private_key_bytes)? No.
        # algosdk.account.address_from_private_key takes a base64 string.
        # Actually in Python SDK `private_key` usually refers to the base64 encoded string of the 64 bytes.
        import base64
        private_key_b64 = base64.b64encode(private_key_bytes).decode('utf-8')
        
        return address, private_key_b64
        
    except ImportError:
        print("ERROR: PyNaCl not installed.")
        return None, None

def canonicalize(s):
    return s.strip().lower().rstrip('/')

def check_user_derivation(user_id):
    try:
        user = User.objects.get(id=user_id)
        print(f"Brute-forcing User {user.id} ({user.email}) for target: {TARGET_ADDR}")
        
        # Get Pepper
        account_type = 'personal'
        account_index = 0
        pepper_key = f"user_{user.id}_{account_type}_{account_index}"
        
        try:
            deriv = WalletDerivationPepper.objects.get(account_key=pepper_key)
            pepper = deriv.encrypted_pepper or deriv.pepper
            print(f"Using server pepper prefix: {pepper[:10]}...")
        except WalletDerivationPepper.DoesNotExist:
            print("No derivation pepper found!")
            return

        print(f"User Firebase UID: {user.firebase_uid}")
        
        # Prepare candidates
        subs = [
            user.email,
            user.username,
            user.email.split('@')[0], 
            user.firebase_uid,
            'k8g82btw6t@privaterelay.appleid.com',
            'k8g82btw6t.000305',
        ]
        
        if user.last_name and user.first_name:
             subs.append(f"{user.first_name} {user.last_name}")

        print(f"Candidate Subjects (subs): {subs}")

        providers = ['google', 'apple', 'email', 'password', 'facebook']
        
        auds = [
            'com.confio.app', 
            'host.exp.exponent', 
            '730050241347-o14ekr3j4ge45cuvqt9d1oa0ukghdvr9.apps.googleusercontent.com',
            'client_id_placeholder',
            'confio-prod',
            'confio'
        ]
        
        account_indices = range(0, 10) # Check indices 0-9

        print(f"Testing combinations...")
        
        count = 0
        match_found = False
        
        for sub in subs:
            for prov in providers:
                for aud in auds:
                    for idx in account_indices:
                        iss = 'https://appleid.apple.com' if prov == 'apple' else 'https://accounts.google.com'
                        
                        candidates = [(iss, aud), (aud, iss)]
                        
                        for (c_iss_raw, c_aud_raw) in candidates:
                            c_iss = canonicalize(c_iss_raw)
                            c_aud = canonicalize(c_aud_raw)
                            
                            salt_input = f"{c_iss}_{sub}_{c_aud}_{account_type}_{idx}"
                            client_salt = sha256(salt_input.encode('utf-8')).hexdigest()
                            
                            addr, pk = derive_key_pair(client_salt, pepper, prov, account_type, idx)
                            
                            count += 1
                            if addr == TARGET_ADDR:
                                print(f"\n!!!!!! FOUND MATCH !!!!!!")
                                print(f"Address: {addr}")
                                print(f"Provider: {prov}")
                                print(f"Index: {idx}")
                                print(f"ISS: {c_iss_raw}")
                                print(f"SUB: {sub}")
                                print(f"AUD: {c_aud_raw}")
                                print(f"Salt Input: {salt_input}")
                                print(f"Private Key (B64): {pk[:10]}...[HIDDEN]")
                                
                                # Try to drain funds?
                                # transfer_funds(pk, NEW_ADDRESS)
                                return

        print(f"Checked {count} combinations. No match found.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_user_derivation(2696)
