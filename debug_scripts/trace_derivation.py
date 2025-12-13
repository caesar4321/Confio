
import os
import django
import algosdk
from algosdk import encoding, account
from hashlib import sha256, pbkdf2_hmac
import base64
import hmac
import struct
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

# The address we WANT to see (Funded V1)
TARGET_ADDR_V1 = "PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY"
# The address frontend is getting (Empty V1)
TARGET_ADDR_DERIVED = "P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU"
# The V2 address
TARGET_ADDR_V2 = "D4LMXEAOL6IRA25ZWMIU4XQZMYQ6NY2USH742QZWM23ZUGTVWJFCFPBB2I"

def hkdf_extract_and_expand(salt, ikm, info, length=32):
    # HKDF-SHA256
    # Extract
    prk = hmac.new(salt, ikm, sha256).digest()
    # Expand
    t = b""
    okm = b""
    i = 0
    while len(okm) < length:
        i += 1
        t = hmac.new(prk, t + info + bytes([i]), sha256).digest()
        okm += t
    return okm[:length]

def derive_deterministic_algo_key(client_salt, derivation_pepper, provider, account_type, account_index, business_id=None):
    # ikmString = `${CONFIO_DERIVATION_SPEC.root}|${clientSalt}`
    ikm_string = f"{CONFIO_DERIVATION_SPEC['root']}|{client_salt}"
    ikm = sha256(ikm_string.encode('utf-8')).digest()

    # extractSalt = sha256(utf8ToBytes(`${CONFIO_DERIVATION_SPEC.extract}|${derivationPepper}`))
    extract_salt_input = f"{CONFIO_DERIVATION_SPEC['extract']}|{derivation_pepper}"
    extract_salt = sha256(extract_salt_input.encode('utf-8')).digest()

    # info = utf8ToBytes(`${CONFIO_DERIVATION_SPEC.algoInfoPrefix}|${provider}|${accountType}|${accountIndex}|${businessId ?? ''}`)
    bid_str = business_id if business_id else ''
    info_str = f"{CONFIO_DERIVATION_SPEC['algoInfoPrefix']}|{provider}|{account_type}|{account_index}|{bid_str}"
    info = info_str.encode('utf-8')

    seed32 = hkdf_extract_and_expand(extract_salt, ikm, info, 32)
    
    try:
        from nacl.signing import SigningKey
        signing_key = SigningKey(seed32)
        verify_key = signing_key.verify_key
        # VerifyKey bytes are public key
        pub_key_bytes = verify_key.encode()
        # Encode as Algorand address
        address = algosdk.encoding.encode_address(pub_key_bytes)
        return address
    except ImportError:
        print("ERROR: PyNaCl not installed. Cannot derive address accurately.")
        return None

def canonicalize(s):
    return s.strip().lower().rstrip('/')

def check_user_derivation(user_id):
    try:
        user = User.objects.get(id=user_id)
        print(f"Checking User {user.id} ({user.email})...")
        print(f"Firebase UID: {user.firebase_uid}")
        
        # Get Pepper
        account_type = 'personal'
        account_index = 0
        pepper_key = f"user_{user.id}_{account_type}_{account_index}"
        
        try:
            deriv = WalletDerivationPepper.objects.get(account_key=pepper_key)
            pepper = deriv.encrypted_pepper or deriv.pepper
            print(f"Found server pepper: {pepper}")
        except WalletDerivationPepper.DoesNotExist:
            print("No derivation pepper found for this user in DB!")
            return

        # Prepare candidates
        candidates = []
        
        # 1. Try generic Google/Apple with username/email/firebase_uid variations
        sub_variations = [
            user.email, 
            user.username,
            user.email.split('@')[0],
            user.firebase_uid,
            'k8g82btw6t.000305' # Apple style hidden email?
        ]
        
        # Try social_django if available, else skip
        try:
            from social_django.models import UserSocialAuth
            socials = UserSocialAuth.objects.filter(user=user)
            for social in socials:
                print(f"Found Linked Social (via module): {social.provider} / {social.uid}")
                sub_variations.append(social.uid)
                if social.provider == 'google-oauth2':
                    candidates.append({
                        'provider': 'google',
                        'iss': 'https://accounts.google.com',
                        'sub': social.uid,
                        'aud': '730050241347-o14ekr3j4ge45cuvqt9d1oa0ukghdvr9.apps.googleusercontent.com'
                    })
                elif social.provider == 'apple-id':
                     candidates.append({
                        'provider': 'apple',
                        'iss': 'https://appleid.apple.com',
                        'sub': social.uid,
                        'aud': 'com.confio.app'
                    })
        except ImportError:
            print("social_django module not found, relying on manual candidates.")

        # Also generic candidates
        generic_subs = set(sub_variations)
        audience_variations = [
            'com.confio.app', 
            'host.exp.exponent', 
            '730050241347-o14ekr3j4ge45cuvqt9d1oa0ukghdvr9.apps.googleusercontent.com',
            'client_id_placeholder'
        ]
        
        for sub in generic_subs:
            for prov in ['apple', 'google']:
                for aud in audience_variations:
                    iss = 'https://appleid.apple.com' if prov == 'apple' else 'https://accounts.google.com'
                    candidates.append({'provider': prov, 'iss': iss, 'sub': sub, 'aud': aud})

        print(f"Testing {len(candidates)} candidate derivations...")

        found_match = False
        
        for cand in candidates:
            provider = cand['provider']
            iss = cand['iss']
            sub = cand['sub']
            aud = cand['aud']
            
            c_iss = canonicalize(iss)
            c_aud = canonicalize(aud)
            # Personal account salt input
            salt_input = f"{c_iss}_{sub}_{c_aud}_{account_type}_{account_index}"
            client_salt = sha256(salt_input.encode('utf-8')).hexdigest()

            addr = derive_deterministic_algo_key(client_salt, pepper, provider, account_type, account_index)
            
            # Check Match
            if addr == TARGET_ADDR_V1:
                print(f"!!! FOUND MATCH V1 !!!")
                print(f"Input: Provider={provider}, Iss={iss}, Sub={sub}, Aud={aud}")
                found_match = True
                break # Stop if found
                
            if addr == TARGET_ADDR_DERIVED:
                print(f"Matched 'Derived' (Wrong) Address: Provider={provider}, Iss={iss}, Sub={sub}, Aud={aud}")
        
        if not found_match:
            print("No match found for V1 address among candidates.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_user_derivation(8)
