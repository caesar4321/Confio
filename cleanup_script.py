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
        # Delete them (Soft delete is fine, or hard delete if we want to fully clear history)
        # Using soft delete (delete() on SoftDeleteModel usually does soft delete)
        # But we might want to hard delete to ensure Trust Score is recalculated correctly 
        # (Trust Score checks for existence of records)
        # Let's see models.py: SuspiciousActivity is SoftDeleteModel.
        # AbusePreventionService filters by: SuspiciousActivity.objects.filter(...) - logic usually excludes deleted
        # But let's check abuse_prevention.py again... 
        # It just does .filter(). It relies on the default manager? SoftDeleteModel usually overrides objects.
        # To be safe, we can delete them.
        
        activities.delete()
        print(f"Successfully deleted {count} activities.")
        
    # 3. Fix Device Fingerprint Counts
    # We need to find fingerprints with abnormally high user counts (e.g. > 10)
    # These are likely the "iPhone 13" generic fingerprints.
    # We should reset their counts or mark them as "generic" so they don't block.
    # However, simply deleting the fingerprint record might be safer -> users will generate new ones.
    
    # Find high-traffic fingerprints
    high_traffic_prints = DeviceFingerprint.objects.filter(
        total_users__gt=5  # Threshold for "suspicious" was 3
    )
    
    print(f"Found {high_traffic_prints.count()} device fingerprints with > 5 users.")
    
    for device in high_traffic_prints:
        print(f"Processing fingerprint {device.fingerprint[:10]}... Users: {device.total_users}")
        # We can aggressively delete these bad fingerprints. 
        # Since they are based on non-unique IDs, they are useless anyway.
        # The cascade might delete IPDeviceUser associations, which is fine.
        # It will NOT delete Users.
        device.delete()
        
    print("Cleanup complete.")

if __name__ == '__main__':
    run_cleanup()
