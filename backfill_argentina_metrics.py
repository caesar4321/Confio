
import os
import django
from django.conf import settings
from datetime import timedelta, date, datetime
from django.utils import timezone
import pytz

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.analytics import snapshot_daily_metrics, snapshot_country_metrics

def backfill_metrics():
    print("STARTING ARGENTINA METRICS BACKFILL")
    print("-----------------------------------")
    
    # Range: Last 45 days to be safe
    days = 45
    tz = pytz.timezone('America/Argentina/Buenos_Aires')
    now_arg = timezone.now().astimezone(tz)
    today_arg = now_arg.date()
    
    for i in range(days, -1, -1):
        target_date = today_arg - timedelta(days=i)
        print(f"Processing {target_date}...", end=" ", flush=True)
        try:
            snapshot_daily_metrics(target_date)
            snapshot_country_metrics(target_date)
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")

    print("\nBACKFILL COMPLETE")

if __name__ == '__main__':
    backfill_metrics()
