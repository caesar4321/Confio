
import os
import django
import algosdk
from algosdk import encoding
from hashlib import sha256
import hmac
import warnings

# Suppress pyteal warning
warnings.filterwarnings("ignore", category=UserWarning)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, WalletDerivationPepper

# Constants from derivationSpec.ts
CONFIO_DERIVATION_SPEC = {
  'root': 'confio-wallet-v1',
  'extract': 'confio/extract/v1',
  'algoInfoPrefix': 'confio/algo/v1',
}

# The address we WANT to find inputs for
TARGET_ADDR = "PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY"

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

def derive_deterministic_algo_key(client_salt, derivation_pepper, provider, account_type, account_index, business_id=None):
    ikm_string = f"{CONFIO_DERIVATION_SPEC['root']}|{client_salt}"
    ikm = sha256(ikm_string.encode('utf-8')).digest()

    extract_salt_input = f"{CONFIO_DERIVATION_SPEC['extract']}|{derivation_pepper}"
    extract_salt = sha256(extract_salt_input.encode('utf-8')).digest()

    bid_str = business_id if business_id else ''
    info_str = f"{CONFIO_DERIVATION_SPEC['algoInfoPrefix']}|{provider}|{account_type}|{account_index}|{bid_str}"
    info = info_str.encode('utf-8')

    seed32 = hkdf_extract_and_expand(extract_salt, ikm, info, 32)
    
    try:
        from nacl.signing import SigningKey
        signing_key = SigningKey(seed32)
        verify_key = signing_key.verify_key
        pub_key_bytes = verify_key.encode()
        address = algosdk.encoding.encode_address(pub_key_bytes)
        return address
    except ImportError:
        return None

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
            print(f"Using server pepper: {pepper}")
        except WalletDerivationPepper.DoesNotExist:
            print("No derivation pepper found!")
            return

        # Prepare candidates
        subs = [
            user.email,
            user.username,
            user.email.split('@')[0], # Handle 'julian' vs 'julian@confio.lat'
            user.firebase_uid,
            'k8g82btw6t@privaterelay.appleid.com', # Explicit from user logs potentially?
            'k8g82btw6t.000305', # Apple hidden email structure
            user.email.lower(),
            user.email.upper(),
        ]
        
        providers = ['google', 'apple', 'facebook', 'email', 'password']
        
        auds = [
            'com.confio.app', 
            'host.exp.exponent', 
            '730050241347-o14ekr3j4ge45cuvqt9d1oa0ukghdvr9.apps.googleusercontent.com',
            'client_id_placeholder',
            'confio-prod',
            'confio-testnet'
        ]
        
        account_indices = range(0, 5) # Check indices 0-4

        print(f"Testing combinations...")
        
        count = 0
        for sub in subs:
            for prov in providers:
                for aud in auds:
                    for idx in account_indices:
                        iss = 'https://appleid.apple.com' if prov == 'apple' else 'https://accounts.google.com'
                        
                        # Test with standard ISS
                        candidates = [(iss, aud)]
                        # Test with swapped ISS/AUD just in case
                        candidates.append((aud, iss))
                        
                        for (c_iss_raw, c_aud_raw) in candidates:
                            c_iss = canonicalize(c_iss_raw)
                            c_aud = canonicalize(c_aud_raw)
                            
                            salt_input = f"{c_iss}_{sub}_{c_aud}_{account_type}_{idx}"
                            client_salt = sha256(salt_input.encode('utf-8')).hexdigest()
                            
                            addr = derive_deterministic_algo_key(client_salt, pepper, prov, account_type, idx)
                            
                            print(f"[{prov}] [{idx}] {sub} -> {addr}")

                            count += 1
                            if addr == TARGET_ADDR:
                                print(f"\n!!!!!! FOUND MATCH FOR TARGET (PFFGG) !!!!!!")
                                return
                            if addr == "P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU":
                                print(f"\n!!!!!! FOUND MATCH FOR CURRENT (P7WYM) !!!!!!")
                                print(f"Provider: {prov}")
                                print(f"Index: {idx}")
                                print(f"ISS: {c_iss_raw}")
                                print(f"SUB: {sub}")
                                print(f"AUD: {c_aud_raw}")
                                print(f"Salt Input: {salt_input}")
        
        print(f"Checked {count} combinations. No match found.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_user_derivation(8)
