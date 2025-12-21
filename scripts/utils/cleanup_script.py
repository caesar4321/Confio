from django.utils import timezone
from datetime import timedelta
from security.models import SuspiciousActivity, DeviceFingerprint, IPDeviceUser
from users.models import User
import logging

logger = logging.getLogger(__name__)

def run_cleanup():
    print("Starting cleanup of false positive suspicious activities...")
    
    # 1. Define the time window (e.g., last 7 days since the bug might have started)
    # The bug was likely introduced recently with the new referral system
    cutoff_date = timezone.now() - timedelta(days=7)
    
    # 2. Identify Suspicious Activities related to "duplicate_device"
    # These were triggered by the shared model-based fingerprint
    activities = SuspiciousActivity.objects.filter(
        activity_type__in=['duplicate_device', 'device_fingerprint', 'multiple_accounts_per_device'],
        created_at__gte=cutoff_date
    )
    
    count = activities.count()
    print(f"Found {count} suspicious activities to clear.")
    
    if count > 0:
        activities.delete()
        print(f"Successfully deleted {count} activities.")
        
    # 3. Fix Device Fingerprint Counts
    # We need to find fingerprints with abnormally high user counts (e.g. > 10)
    # These are likely the "iPhone 13" generic fingerprints.
    
    # Find high-traffic fingerprints
    high_traffic_prints = DeviceFingerprint.objects.filter(
        total_users__gt=5  # Threshold for "suspicious" was 3
    )
    
    print(f"Found {high_traffic_prints.count()} device fingerprints with > 5 users.")
    
    for device in high_traffic_prints:
        print(f"Processing fingerprint {device.fingerprint[:10]}... Users: {device.total_users}")
        device.delete()
        
    print("Cleanup complete.")

if __name__ == '__main__':
    run_cleanup()
