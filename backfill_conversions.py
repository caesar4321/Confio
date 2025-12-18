import os
import django
import sys

# Setup Django environment
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'confio.settings')
django.setup()

from conversion.models import Conversion
from users.models_unified import UnifiedTransactionTable
from usdc_transactions.models_unified import UnifiedUSDCTransactionTable
from django.db.models.signals import post_save

print("Starting backfill for recent conversions...")

# Get recent conversions (e.g. last 50)
recent_conversions = Conversion.objects.all().order_by('-created_at')[:50]
print(f"Found {recent_conversions.count()} conversions to process.")

count = 0
for conversion in recent_conversions:
    try:
        # Trigger explicit save to run signals
        # We don't change anything, just save.
        conversion.save()
        count += 1
        print(f"Processed conversion {conversion.internal_id} (ID: {conversion.id})")
    except Exception as e:
        print(f"Failed to process conversion {conversion.id}: {e}")

print(f"Backfill complete. Processed {count} conversions.")
