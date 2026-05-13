"""
Audit: re-derive each V1 address from OAuth claims + server pepper and compare
with the stored algorand_address. If they match and is_keyless_migrated=True,
the user is still on a V1 address falsely marked as V2.

V1 derivation formula (from secureDeterministicWallet.ts):
  clientSalt  = SHA256(canonicalize(iss) + "_" + sub + "_" + canonicalize(aud)
                       + "_" + accountType + "_" + accountIndex)
  ikm         = SHA256("confio-wallet-v1|" + clientSalt)
  extractSalt = SHA256("confio/extract/v1|" + derivationPepper)
  info        = "confio/algo/v1|" + provider + "|" + accountType + "|"
                + str(accountIndex) + "|"
  seed32      = HKDF-SHA256(ikm, extractSalt, info, 32)
  address     = ed25519_pubkey_to_algorand_address(seed32)
"""
import sys, os, hmac, hashlib, struct

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from users.models import Account
from users.models_wallet import WalletDerivationPepper
from algosdk import encoding
import nacl.signing

GOOGLE_WEB_CLIENT_ID = "730050241347-o14ekr3j4ge45cuvqt9d1oa0ukghdvr9.apps.googleusercontent.com"
APPLE_BUNDLE_ID = "com.confio.app"

DERIV_ROOT    = "confio-wallet-v1"
DERIV_EXTRACT = "confio/extract/v1"
DERIV_ALGO    = "confio/algo/v1"


def canonicalize(s):
    return s.strip().lower().rstrip('/')


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    t = b""
    okm = b""
    i = 0
    while len(okm) < length:
        i += 1
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def hkdf(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    prk = hkdf_extract(salt, ikm)
    return hkdf_expand(prk, info, length)


def derive_v1_address(iss, sub, aud, provider, derivation_pepper,
                      account_type='personal', account_index=0, business_id=None):
    c_iss = canonicalize(iss)
    c_aud = canonicalize(aud)

    if business_id:
        salt_input = f"{c_iss}_{sub}_{c_aud}_{account_type}_{business_id}_{account_index}"
    else:
        salt_input = f"{c_iss}_{sub}_{c_aud}_{account_type}_{account_index}"

    client_salt = sha256_hex(salt_input.encode('utf-8'))

    ikm = sha256(f"{DERIV_ROOT}|{client_salt}".encode('utf-8'))
    extract_salt = sha256(f"{DERIV_EXTRACT}|{derivation_pepper}".encode('utf-8'))
    info = f"{DERIV_ALGO}|{provider}|{account_type}|{account_index}|".encode('utf-8')

    seed32 = hkdf(ikm, extract_salt, info, 32)

    signing_key = nacl.signing.SigningKey(seed32)
    public_key = signing_key.verify_key.encode()
    address = encoding.encode_address(public_key)
    return address


def run_audit():
    from firebase_admin import auth as fb_auth

    migrated_accounts = Account.objects.filter(
        is_keyless_migrated=True,
        account_type='personal',
        account_index=0,
        algorand_address__isnull=False,
    ).exclude(algorand_address='').select_related('user')

    total = migrated_accounts.count()
    print("Accounts with is_keyless_migrated=True and an address: %d" % total)
    print("Re-deriving V1 addresses and comparing...")
    print("=" * 90)

    matches = []
    no_social = 0
    no_pepper = 0
    errors = 0
    checked = 0

    for acc in migrated_accounts.iterator():
        user = acc.user
        checked += 1
        if checked % 500 == 0:
            print("  ...checked %d / %d" % (checked, total))

        # Get OAuth provider info from Firebase
        try:
            fb_user = fb_auth.get_user(user.firebase_uid)
            provider_data = fb_user.provider_data
        except Exception:
            no_social += 1
            continue

        if not provider_data:
            no_social += 1
            continue

        p = provider_data[0]
        provider_id = p.provider_id
        uid = p.uid

        if provider_id == 'google.com':
            iss = "https://accounts.google.com"
            aud = GOOGLE_WEB_CLIENT_ID
            provider = 'google'
        elif provider_id == 'apple.com':
            iss = "https://appleid.apple.com"
            aud = APPLE_BUNDLE_ID
            provider = 'apple'
        else:
            errors += 1
            continue

        # Get derivation pepper
        pepper_key = "user_%d_personal_0" % user.id
        try:
            deriv = WalletDerivationPepper.objects.get(account_key=pepper_key)
            pepper = deriv.encrypted_pepper or deriv.pepper
        except WalletDerivationPepper.DoesNotExist:
            no_pepper += 1
            continue

        # Derive V1 address
        try:
            v1_address = derive_v1_address(iss, uid, aud, provider, pepper)
        except Exception as e:
            errors += 1
            print("  ERROR deriving for user %d: %s" % (user.id, e))
            continue

        # Compare
        if v1_address == acc.algorand_address:
            matches.append({
                'user_id': user.id,
                'account_id': acc.id,
                'email': user.email,
                'address': acc.algorand_address,
                'date_joined': user.date_joined.strftime('%Y-%m-%d'),
                'backup_provider': user.backup_provider,
                'backup_verified': user.backup_verified_at,
            })

    print("\nRESULTS:")
    print("=" * 90)
    print("Total checked:         %d" % total)
    print("No social auth:        %d (skipped)" % no_social)
    print("No derivation pepper:  %d (skipped)" % no_pepper)
    print("Errors:                %d" % errors)
    print()
    print("MATCHES (V1 address == current address, but marked V2): %d" % len(matches))
    print("=" * 90)

    for m in matches:
        print("  user_id=%d acct=%d" % (m['user_id'], m['account_id']))
        print("    email:    %s" % m['email'])
        print("    address:  %s" % m['address'])
        print("    joined:   %s" % m['date_joined'])
        print("    backup:   provider=%s verified=%s" % (m['backup_provider'], m['backup_verified']))
        print()

    if not matches:
        print("  None found. All migrated accounts have rotated to a V2 address.")

if __name__ == "__main__":
    run_audit()
