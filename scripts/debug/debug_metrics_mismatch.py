
import os
import django
from django.conf import settings
from datetime import datetime, date, timedelta
from django.utils import timezone
from django.db.models import Count
from decimal import Decimal

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from users.models_analytics import DailyMetrics

def debug_metrics():
    print("DEBUGGING METRIC MISMATCH")
    print("-------------------------")
    
    # Range: Last 10 days
    days = 10
    start_date = timezone.now() - timedelta(days=days)
    
    # 1. Fetch from DailyMetrics (Snapshot)
    snapshots = DailyMetrics.objects.filter(
        date__gte=start_date.date()
    ).order_by('date')
    
    snapshot_map = {s.date: s.new_users_today for s in snapshots}
    
    # 2. Fetch using User Analytics Logic (Dynamic)
    dynamic_data = User.objects.filter(
        phone_number__isnull=False,
        created_at__gte=start_date
    ).extra(
        select={'day': 'date(users_user.created_at)'}
    ).values('day').annotate(
        count=Count('id')
    ).order_by('day')
    
    dynamic_map = {d['day']: d['count'] for d in dynamic_data}
    
    # 3. Compare
    all_dates = sorted(set(list(snapshot_map.keys()) + list(dynamic_map.keys())))
    
    print(f"{'Date':<15} | {'Snapshot':<10} | {'Updated At':<25} | {'Dynamic':<10} | {'Diff':<5}")
    print("-" * 100)
    
    for d in all_dates:
        snapshot_obj = snapshots.filter(date=d).first()
        s_val = snapshot_obj.new_users_today if snapshot_obj else 0
        updated_at = snapshot_obj.created_at.strftime("%Y-%m-%d %H:%M") if snapshot_obj else "N/A"
        
        d_val = dynamic_map.get(d, 0)
        diff = d_val - s_val
        print(f"{d} | {s_val:<10} | {updated_at:<25} | {d_val:<10} | {diff}")

    print("\n--- DEEP DIVE: 2025-12-01 ---")
    target_date = date(2025, 12, 1)
    
    # Logic from analytics.py
    end_time = timezone.make_aware(datetime.combine(target_date, datetime.max.time()))
    start_time = end_time - timedelta(days=1)
    
    count_analytics_verify = User.objects.filter(
        phone_number__isnull=False,
        created_at__gte=start_time,
        created_at__lte=end_time
    ).count()
    
    print(f"Independent Calc (analytics logic): {count_analytics_verify}")
    print(f"Time Range: {start_time} to {end_time}")
    
    # Logic from Admin Dashboard (Dynamic)
    count_dynamic_verify = User.objects.filter(
        phone_number__isnull=False,
        created_at__gte=start_time, # Using start_time as proxy for day start
        created_at__lte=end_time
    ).count() 
    # Note: Admin Dashboard uses date(created_at) group by. Let's try to mimic that.
    
    count_date_cast = User.objects.filter(
        phone_number__isnull=False,
        created_at__year=2025,
        created_at__month=12,
        created_at__day=1
    ).count()
    
    print(f"Independent Calc (date cast logic): {count_date_cast}")


if __name__ == '__main__':
    debug_metrics()
