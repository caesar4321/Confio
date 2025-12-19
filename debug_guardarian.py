import os
import django
from decimal import Decimal
import sys

# KMS signing enabled by default in settings
# os.environ["USE_KMS_SIGNING"] = "False"
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

# Setup Django
sys.path.append(os.getcwd())
django.setup()

from usdc_transactions.models import GuardarianTransaction, USDCDeposit
from users.models import User

g_id = "6231267291"
print(f"--- Debugging Guardarian Tx {g_id} ---")

try:
    tx = GuardarianTransaction.objects.get(guardarian_id=g_id)
    print(f"Found Tx: {tx}")
    print(f"User: {tx.user} (ID: {tx.user.id}, Username: {tx.user.username})")
    print(f"Status: {tx.status}")
    print(f"Created At: {tx.created_at}")
    print(f"To Amount Estimated: {tx.to_amount_estimated}")
    print(f"To Amount Actual: {tx.to_amount_actual}")
    print(f"Linked Deposit: {tx.onchain_deposit}")

    print("\nSearching for Candidate Deposits:")
    # Look for ALL completed deposits for this user, even if already linked, just to see if they exist
    candidates = USDCDeposit.objects.filter(
        actor_user=tx.user,
        status='COMPLETED'
    ).order_by('-created_at')

    if not candidates.exists():
        print("NO COMPLETED DEPOSITS FOUND FOR THIS USER.")
    
    for dep in candidates:
        print(f" - Deposit ID: {dep.internal_id}, Amount: {dep.amount}, Created: {dep.created_at}")
        
        # Check linkage
        try:
            linked_tx = dep.guardarian_source
            print(f"   -> ALREADY LINKED to Guardarian Tx: {linked_tx.guardarian_id}")
        except Exception:
            print("   -> FREE (Not linked to any Guardarian Tx)")
            
        # Check logic
        match_reasons = []
        if tx.to_amount_actual and dep.amount == tx.to_amount_actual:
            match_reasons.append("EXACT MATCH (Strategy 1)")
        
        if tx.to_amount_estimated:
            tolerance = tx.to_amount_estimated * Decimal('0.05')
            diff = abs(tx.to_amount_estimated - dep.amount)
            if diff <= tolerance:
                match_reasons.append(f"FUZZY MATCH (Strategy 2) Diff={diff}")
        
        if match_reasons:
            for m in match_reasons:
                print(f"   -> MATCH POTENTIAL: {m}")
        else:
            print("   -> NO MATCH criteria met.")

    # Also check if scan_inbound_deposits missed it by looking for ANY deposit around that time?
    # Maybe check address
    print("\nUser Algorand Address:")
    if hasattr(tx.user, 'account_set'):
        for acc in tx.user.account_set.all():
             print(f" - Account {acc.id}: {acc.algorand_address}")

except GuardarianTransaction.DoesNotExist:
    print(f"Tx {g_id} not found in DB.")
except Exception as e:
    print(f"Error: {e}")
