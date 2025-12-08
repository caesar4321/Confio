import os
import django
import sys

# Add project root to path
sys.path.append(os.getcwd())

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['CONFIO_ENV'] = 'testnet'
os.environ['ALGORAND_NETWORK'] = 'testnet'
django.setup()

from users.tasks import capture_daily_metrics
from users.models_analytics import DailyMetrics

print("Running capture_daily_metrics...")
try:
    result = capture_daily_metrics()
    print("Result:", result)
    
    latest = DailyMetrics.objects.order_by('-date').first()
    print(f"Latest DailyMetrics: {latest.date} (DAU: {latest.dau})")
except Exception as e:
    print(f"Error: {e}")
