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
print(f"--- Debugging Guardarian Tx {g_id} (Verifying Fix Logic) ---")

try:
    tx = GuardarianTransaction.objects.get(guardarian_id=g_id)
    print(f"Found Tx: {tx}")
    print(f"To Amount Actual: {tx.to_amount_actual}")
    print(f"Linked Deposit Before: {tx.onchain_deposit}")

    candidates = USDCDeposit.objects.filter(
        actor_user=tx.user,
        status='COMPLETED',
        guardarian_source__isnull=True
    ).order_by('-created_at')

    # Simulate Strategy 1.5
    matched_dep = None
    if tx.to_amount_actual:
        print("Checking Exact Match...")
        matched_dep = candidates.filter(amount=tx.to_amount_actual).first()
        if matched_dep:
            print(" -> Exact Match Found!")
        else:
            print(" -> No Exact Match.")
            print("Checking Micro-Tolerance Match (Strategy 1.5)...")
            tolerance = Decimal('0.000005')
            min_amt = tx.to_amount_actual - tolerance
            max_amt = tx.to_amount_actual + tolerance
            print(f" -> Range: {min_amt} <= amount <= {max_amt}")
            
            # Using the same filter logic as the fix
            matched_dep = candidates.filter(amount__gte=min_amt, amount__lte=max_amt).first()
            
            if matched_dep:
                print(f" -> MATCH FOUND! Deposit ID: {matched_dep.internal_id}, Amount: {matched_dep.amount}")
                print(f" -> Diff: {abs(matched_dep.amount - tx.to_amount_actual)}")
            else:
                print(" -> Still No Match Found with tolerance.")

except GuardarianTransaction.DoesNotExist:
    print(f"Tx {g_id} not found in DB.")
except Exception as e:
    print(f"Error: {e}")
