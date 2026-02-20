
import hashlib
import base64
import os
import sys
import django
import re

# Setup Django
sys.path.append('/opt/confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
# Try to import WalletDerivationPepper if it exists
try:
    from users.models import WalletDerivationPepper
except ImportError:
    try:
        from users.models_wallet import WalletDerivationPepper
    except ImportError:
        WalletDerivationPepper = None

from algosdk import account, mnemonic
from algosdk.v2client import algod
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from django.conf import settings

# CONSTANTS for V1 Derivation
ROOT_SPEC = 'confio-wallet-v1'
EXTRACT_SPEC = 'confio/extract/v1'
ALGO_INFO_PREFIX = 'confio/algo/v1'

# V1 CREDENTIALS (USER 6090 - sandro_mica)
ISSUER = "https://accounts.google.com"
SUB = "112851974537141109007"
AUD = "730050241347-o14ekr3j4ge45cuvqt9d1oa0ukghdvr9.apps.googleusercontent.com"

def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

def sha256_hash(data: str) -> bytes:
    return hashlib.sha256(data.encode('utf-8')).digest()

def canonicalize(s: str) -> str:
    return s.strip().lower().rstrip('/')

def derive_private_key(issuer, sub, aud, pepper, provider, account_type, account_index):
    can_iss = canonicalize(issuer)
    can_aud = canonicalize(aud)
    
    salt_input = f"{can_iss}_{sub}_{can_aud}_{account_type}_{account_index}"
    client_salt = sha256_hex(salt_input)
    
    ikm_string = f"{ROOT_SPEC}|{client_salt}"
    ikm = sha256_hash(ikm_string)
    
    extract_input = f"{EXTRACT_SPEC}|{pepper}"
    extract_salt = sha256_hash(extract_input)
    
    info_string = f"{ALGO_INFO_PREFIX}|{provider}|{account_type}|{account_index}|"
    info = info_string.encode('utf-8')
    
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=extract_salt, info=info, backend=default_backend())
    seed = hkdf.derive(ikm)
    
    mn = mnemonic.from_private_key(base64.b64encode(seed).decode('utf-8'))
    pk = mnemonic.to_private_key(mn)
    return pk, mn

def check_orphaned():
    if not WalletDerivationPepper:
        print("WalletDerivationPepper model not found.")
        return

    print("Fetching all peppers...")
    all_peppers = WalletDerivationPepper.objects.all()
    print(f"Total Peppers: {all_peppers.count()}")
    
    orphaned_peppers = []
    
    # Cache user IDs for performance
    existing_user_ids = set(User.objects.values_list('id', flat=True))
    
    for p in all_peppers:
        # account_key format: user_{id}_{type}_{index} e.g. user_123_personal_0
        match = re.match(r'user_(\d+)_', p.account_key)
        if match:
            uid = int(match.group(1))
            if uid not in existing_user_ids:
                orphaned_peppers.append((uid, p.pepper))
    
    print(f"Found {len(orphaned_peppers)} orphaned peppers (from deleted users).")
    
    if not orphaned_peppers:
        return

    client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
    
    print("\nChecking for funded wallets using Orphaned Peppers + sandro_mica credentials...")
    
    found_funded = False
    
    for uid, pepper in orphaned_peppers:
        # Derive
        try:
            pk, mn = derive_private_key(ISSUER, SUB, AUD, pepper, "google", "personal", 0)
            addr = account.address_from_private_key(pk)
            
            # Check Balance
            info = client.account_info(addr)
            amount = info.get('amount', 0)
            assets = info.get('assets', [])
            
            # Filter for non-dust
            has_funds = amount > 1000000 or (len(assets) > 0 and any(a['amount'] > 0 for a in assets))
            
            if has_funds:
                print(f"!!! FOUND FUNDED WALLET !!!")
                print(f"Original User ID: {uid}")
                print(f"Address: {addr}")
                print(f"ALGO: {amount/1e6}")
                print(f"Assets: {assets}")
                found_funded = True
                
        except Exception as e:
            # print(f"Error checking pepper for uid {uid}: {e}")
            pass
            
    if not found_funded:
        print("No funded wallets found among orphaned peppers.")

if __name__ == "__main__":
    check_orphaned()
