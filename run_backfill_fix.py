import os
import django
import sys

# KMS default
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

sys.path.append(os.getcwd())
django.setup()

from usdc_transactions.models import GuardarianTransaction

print("--- Running Targeted Backfill for Unlinked Finished Transactions ---")

# Find all transactions that are 'finished' but have no deposit linked
unlinked_txs = GuardarianTransaction.objects.filter(
    status='finished', 
    onchain_deposit__isnull=True
)

# Since transaction_type is a property, we can't filter by it directly in DB unless it maps to fields.
# But 'onchain_deposit' is only relevant for buys anyway (related_name='guardarian_source').
# So if onchain_deposit is null, and it's a finished buy, we should check.

count = 0
linked = 0
print(f"Found {unlinked_txs.count()} candidates (may include sells). Checking...")

for tx in unlinked_txs:
    if tx.transaction_type != 'buy':
        continue
        
    print(f"Checking Tx {tx.guardarian_id} ({tx.to_amount_actual} USDC)...")
    matched = tx.attempt_match_deposit()
    if matched:
        print(f" -> SUCCESS! Linked to Deposit {matched.internal_id}")
        linked += 1
    else:
        # print(" -> No match found.")
        pass
    count += 1

print(f"--- Finished. Checked {count} BUY txs. Successfully Linked {linked}. ---")
