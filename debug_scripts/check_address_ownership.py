
import os
import django
import algosdk
from algosdk import encoding, account
from hashlib import sha256, pbkdf2_hmac
import base64
import hmac
import struct

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, Account

# Addresses to check
TARGET_ADDR_V1 = "PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY"
TARGET_ADDR_DERIVED = "P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU"
TARGET_ADDR_V2 = "D4LMXEAOL6IRA25ZWMIU4XQZMYQ6NY2USH742QZWM23ZUGTVWJFCFPBB2I"

def check_db_for_address(addr):
    try:
        acc = Account.objects.get(algorand_address=addr)
        print(f"[DB] Address {addr} belongs to User {acc.user.id} ({acc.user.email}), AccountType: {acc.account_type}, Index: {acc.account_index}")
        return acc
    except Account.DoesNotExist:
        print(f"[DB] Address {addr} NOT found in database.")
        return None

def hkdf_extract_and_expand(salt, ikm, info, length=32):
    # Minimal HKDF implementation using hashlib
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

def derive_v1_address(user_id, account_type='personal', account_index=0):
    try:
        user = User.objects.get(id=user_id)
        
        # Determine OAuth claims (approximated from DB)
        # Note: In production, these come from the JWT.
        # We need to guess what they were when the user signed up/logged in.
        
        # Common providers: google, apple
        # The logs show issuer: https://accounts.google.com
        # sub: This is the critical part. We don't store raw 'sub' in DB usually, unless in social_auth or username?
        # User 8 username is 'julianmoonluna' (from logs) or an email?
        # Logs: "sub": "1098..."? No, logs didn't show full sub.
        # Wait, the logs DID show "sub" in token payload?
        # No, decoded token payload has `user_id`, not `sub`.
        # However, `AccountManager` usually stores the `sub` in Keychain.
        # But we can try to guess or use the 'username' if it Was the sub.
        # For Google, sub is numeric string.
        # If the user logged in via Google, we might have the social auth record.
        
        from social_django.models import UserSocialAuth
        try:
            social = UserSocialAuth.objects.filter(user=user).first()
            if social:
                provider = social.provider
                uid = social.uid
                print(f"[Derivation] Found Social Auth: {provider} - {uid}")
                
                if provider == 'google-oauth2':
                    iss = "https://accounts.google.com"
                    sub = uid
                    aud = "730050241347-o14ekr3j4ge45cuvqt9d1oa0ukghdvr9.apps.googleusercontent.com" # From logs
                elif provider == 'apple-id':
                    iss = "https://appleid.apple.com"
                    sub = uid
                    aud = "com.confio.app" # Guessed
                else:
                    print(f"[Derivation] Unknown provider {provider}")
                    return

                # Get Pepper
                from users.utils import get_derivation_pepper
                pepper = get_derivation_pepper(user, account_type, account_index)
                print(f"[Derivation] Pepper: {pepper}")
                
                # --- Reproduce secureDeterministicWallet.ts logic ---
                
                # canonicalize
                def canonicalize(s):
                    return s.strip().lower().rstrip('/')

                c_iss = canonicalize(iss)
                c_aud = canonicalize(aud)
                
                # generateClientSalt
                # saltInput = `${canonicalIssuer}_${subject}_${canonicalAudience}_${accountType}_${accountIndex}`
                salt_input = f"{c_iss}_{sub}_{c_aud}_{account_type}_{account_index}"
                client_salt = sha256(salt_input.encode('utf-8')).hexdigest()
                # print(f"Client Salt: {client_salt}")

                # deriveDeterministicAlgorandKey
                # ikmString = `${CONFIO_DERIVATION_SPEC.root}|${clientSalt}`
                # root = "confio-stack-root" (from derivationSpec.ts usually, let's assume standard)
                # ERROR: I don't have derivationSpec.ts content. I need to read it or guess.
                # Found it in view_file of wallet service: imports { CONFIO_DERIVATION_SPEC } from './derivationSpec';
                # I'll need to read that file to get the constants.
                
                return # Can't proceed without constants.

        except Exception as e:
            print(f"[Derivation] Error finding social auth: {e}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Checking DB for addresses...")
    check_db_for_address(TARGET_ADDR_V1)
    check_db_for_address(TARGET_ADDR_DERIVED)
    check_db_for_address(TARGET_ADDR_V2)
    
    print("\nAttempting derivation check (Partial)...")
    # I need to read derivationSpec.ts first
