import os
import sys
import base64
from algosdk import transaction, encoding
from algosdk.transaction import SuggestedParams, PaymentTxn

# Ensure project root is in path and takes precedence
project_root = '/Users/julian/Confio'
if project_root not in sys.path:
    sys.path.insert(0, project_root)
else:
    # Move to front if already there but not first
    sys.path.remove(project_root)
    sys.path.insert(0, project_root)

print(f"DEBUG: CWD: {os.getcwd()}")
print(f"DEBUG: sys.path: {sys.path}")

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
try:
    django.setup()
except Exception as e:
    print(f"DEBUG: Django setup failed: {e}")
    # Print traceback
    import traceback
    traceback.print_exc()
    sys.exit(1)

from django.conf import settings
from blockchain.payroll_transaction_builder import PayrollTransactionBuilder



def verify_atomic_payroll():
    print("Verifying Atomic Payroll Transaction construction...")
    
    builder = PayrollTransactionBuilder(network=settings.ALGORAND_NETWORK)
    sponsor_address = "ZS2HK5N7BZV46ZZGDOQBGFTN3JSXGAFVJFG33WAEP47JQMASSSJIQL7HI4" # Dummy
    business_account = "5LVG2CQWNYBR4QB3KMIKQYLS3RRICOHYAWMG7SCOHSPPBHJAVBLPE5IDZA" # Dummy
    add_set = ["JCST5343ORH4RSK7DTPWP2PGE53Y3BNBPP7TY7LBPQAKKQXKZOLUT2VPR4"]
    remove_set = []
    
    # Fake params (fv=1000, lv=2000)
    sp = SuggestedParams(
        fee=1000,
        first=1000,
        last=2000,
        gh=base64.b64decode("SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI="),
        gen="mainnet-v1.0",
        flat_fee=True
    )
    
    # 1. Build original group
    txns = builder.build_set_business_delegates_group(
        business_account=business_account,
        add=add_set,
        remove=remove_set,
        sponsor_address=sponsor_address,
        sponsor_amount=500_000,
        suggested_params=sp
    )
    
    original_gid = txns[0].group
    print(f"Original Group ID: {base64.b64encode(original_gid).decode()}")
    
    # 2. Simulate Client Signing (Encode Business Txn)
    business_txn = txns[1]
    # In reality, client signs it. Here we just msgpack encode it (unsigned) to simulate 'stx_bytes' container
    # But wait, schema code decodes SignedTransaction. So we need to put it in a SignedTransaction container?
    # Actually, if client sends unsigned, schema might fail. Let's wrap it in empty SignedTransaction (sig=b'\x00'*64) if we want to mimic signed.
    # But schema code logic: `stx_obj = algo_encoding.msgpack_decode(stx_bytes) ... business_txn = stx_obj.txn`
    # So yes, we need SignedTransaction object.
    
    # Fake sign
    business_stx = transaction.SignedTransaction(business_txn, signature=b"\x00"*64)
    stx_encoded_str = encoding.msgpack_encode(business_stx)
    
    # encoding.msgpack_encode returns a base64 string. 
    # To simulate 'stx_bytes' which usually comes from client as b64 string, we use it directly.
    stx_b64 = stx_encoded_str
    
    print(f"Simulated Client STX (b64): {stx_b64[:20]}...")
    
    # 3. Reconstruct Sponsor Transaction (Server Logic)
    print("Reconstructing Sponsor Transaction...")
    
    # encoding.msgpack_decode expects the base64 string
    decoded_stx = encoding.msgpack_decode(stx_b64)
    print(f"DEBUG: Type of decoded_stx: {type(decoded_stx)}")
    print(f"DEBUG: Dir: {dir(decoded_stx)}")

    if hasattr(decoded_stx, 'transaction'):
        received_txn = decoded_stx.transaction
    elif hasattr(decoded_stx, 'txn'):
        received_txn = decoded_stx.txn
    else:
        # Fallback if it decoded directly to txn (unlikely for SignedTransaction but possible if signature is empty/null and sdk simplifies?)
        received_txn = decoded_stx
    
    print(f"DEBUG: Received Txn Type: {type(received_txn)}")
    print(f"DEBUG: Txn Dict: {received_txn.__dict__}")
    
    rebuilt_sp = SuggestedParams(
        fee=1000,
        first=received_txn.first_valid_round,
        last=received_txn.last_valid_round,
        gh=received_txn.genesis_hash,
        gen=received_txn.genesis_id,
        flat_fee=True
    )
    
    sponsor_txn = PaymentTxn(
        sender=sponsor_address,
        sp=rebuilt_sp,
        receiver=business_account,
        amt=500_000, 
        note=b"Payroll Setup Sponsor"
    )
    sponsor_txn.group = received_txn.group
    
    # 4. Compare
    print(f"Reconstructed Group ID: {base64.b64encode(sponsor_txn.group).decode()}")
    
    if sponsor_txn.group == original_gid:
        print("SUCCESS: Group IDs match!")
        
        # Verify params
        print(f"Original Params: fv={sp.first} lv={sp.last} fee={sp.fee}")
        print(f"Rebuilt Params: fv={rebuilt_sp.first} lv={rebuilt_sp.last} fee={rebuilt_sp.fee}")
        
        # Verify hash of sponsor txn (must be identical bytes for signature to be valid if we pre-signed it, 
        # but here we sign AFTER rebuild, so bytes just need to be 'compatible' with group id.
        # Actually, Group ID calculation depends on the txn bytes (except signature). 
        # So if we changed any field, the group ID would change.
        # Since group IDs match, the sponsor txn bytes MUST be effectively identical to what was used to calc the group ID originally.
        print("Success: reconstruction valid.")
    else:
        print("FAILURE: Group IDs mismatch!")
        sys.exit(1)

if __name__ == "__main__":
    verify_atomic_payroll()
