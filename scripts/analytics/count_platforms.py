import os
import django
from django.db.models import Count

# Initialize Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

def count_platforms():
    print("Analyzing Global Mobile Platform Usage...", flush=True)
    
    from notifications.models import FCMDeviceToken
    
    # Count by device_type
    stats = FCMDeviceToken.objects.values('device_type').annotate(count=Count('id')).order_by('-count')
    
    total = FCMDeviceToken.objects.count()
    
    print(f"\nTotal Registered Devices: {total}", flush=True)
    print("-" * 30, flush=True)
    
    for stat in stats:
        count = stat['count']
        percentage = (count / total) * 100 if total > 0 else 0
        print(f"{stat['device_type']}: {count} ({percentage:.1f}%)", flush=True)

if __name__ == '__main__':
    count_platforms()
