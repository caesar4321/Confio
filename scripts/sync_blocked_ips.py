import os
import sys
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django_redis import get_redis_connection
from security.models import IPAddress

def sync_blocked_ips():
    """
    Syncs all blocked IPs from the database to the Redis 'blocked_ips' set.
    This ensures that even if Redis is restarted, the blocklist is restored.
    """
    print("Starting sync of blocked IPs to Redis...")
    
    # Get all blocked IPs from DB
    blocked_ips = IPAddress.objects.filter(is_blocked=True).values_list('ip_address', flat=True)
    count = blocked_ips.count()
    
    if count == 0:
        print("No blocked IPs found in database.")
        return

    print(f"Found {count} blocked IPs in database.")

    # Get Redis connection
    redis_conn = get_redis_connection("default")
    
    # Ideally, we should maybe clear the set first to ensure consistency, 
    # but strictly adding is safer to avoid a window of openness.
    # If we want to be exact:
    # redis_conn.delete("blocked_ips") 
    
    # Pipeline for performance
    pipe = redis_conn.pipeline()
    for ip in blocked_ips:
        pipe.sadd("blocked_ips", ip)
    
    pipe.execute()
    
    print(f"Successfully synced {count} IPs to Redis key 'blocked_ips'.")

if __name__ == "__main__":
    sync_blocked_ips()
