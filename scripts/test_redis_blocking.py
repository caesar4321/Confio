from security.models import IPAddress
from django_redis import get_redis_connection
from scripts.sync_blocked_ips import sync_blocked_ips
import time

def test_redis_blocking():
    print("--- Starting Redis Blocking Verification ---")
    redis_conn = get_redis_connection("default")
    test_ip = "1.2.3.4"
    
    # helper to clean up
    def cleanup():
        IPAddress.objects.filter(ip_address=test_ip).delete()
        redis_conn.srem("blocked_ips", test_ip)
        
    cleanup()
    
    # 1. Test Signal: Block IP -> Redis Add
    print("\n1. Testing Signal (Block IP)...")
    try:
        ip_obj = IPAddress.objects.create(ip_address=test_ip, is_blocked=True)
    except Exception as e:
        print(f"Error creating IP: {e}")
        return

    if redis_conn.sismember("blocked_ips", test_ip):
        print("PASS: IP added to Redis via signal.")
    else:
        print("FAIL: IP NOT found in Redis after blocking in DB.")
        
    # 2. Test Signal: Unblock IP -> Redis Remove
    print("\n2. Testing Signal (Unblock IP)...")
    ip_obj.is_blocked = False
    ip_obj.save()
    
    if not redis_conn.sismember("blocked_ips", test_ip):
        print("PASS: IP removed from Redis via signal.")
    else:
        print("FAIL: IP still in Redis after unblocking in DB.")

    # 3. Test Signal: Delete IP -> Redis Remove
    print("\n3. Testing Signal (Delete IP)...")
    # First re-block it
    ip_obj.is_blocked = True
    ip_obj.save() 
    if redis_conn.sismember("blocked_ips", test_ip):
        print("   (Re-blocked successfully)")
    
    ip_obj.delete()
    
    if not redis_conn.sismember("blocked_ips", test_ip):
        print("PASS: IP removed from Redis via delete signal.")
    else:
        print("FAIL: IP still in Redis after delete.")

    # 4. Test Sync Script
    print("\n4. Testing Sync Script...")
    
    IPAddress.objects.create(ip_address=test_ip, is_blocked=True)
    # Manually remove from Redis to simulate data loss
    redis_conn.srem("blocked_ips", test_ip)
    
    if not redis_conn.sismember("blocked_ips", test_ip):
        print("   (Simulated Redis data loss: IP is in DB but not Redis)")
    
    # Run Sync
    sync_blocked_ips()
    
    if redis_conn.sismember("blocked_ips", test_ip):
        print("PASS: Sync script restored IP to Redis.")
    else:
        print("FAIL: Sync script failed to restore IP.")
        
    cleanup()
    print("\n--- Verification Complete ---")

if __name__ == "__main__":
    test_redis_blocking()
elif __name__ == "builtins": # When running in shell
    test_redis_blocking()
