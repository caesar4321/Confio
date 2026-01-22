
from django.contrib.auth import get_user_model
from sms_verification.models import SMSVerification
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count

User = get_user_model()

def identify_attacker():
    # Look for verifications in the last 24 hours
    now = timezone.now()
    since = now - timedelta(days=1)
    
    print(f"Analyzing SMS Verifications since {since}...")
    
    # Group by user and count
    stats = SMSVerification.objects.filter(
        created_at__gte=since
    ).values('user').annotate(
        count=Count('id')
    ).order_by('-count')[:5]
    
    print("\nTop 5 Users by SMS Volume:")
    print("-" * 60)
    print(f"{'Count':<10} | {'User ID':<10} | {'Email':<30} | {'Name':<20}")
    print("-" * 60)
    
    for stat in stats:
        count = stat['count']
        user_id = stat['user']
        try:
            u = User.objects.get(id=user_id)
            print(f"{count:<10} | {user_id:<10} | {u.email:<30} | {u.first_name} {u.last_name}")
        except User.DoesNotExist:
            print(f"{count:<10} | {user_id:<10} | {'<Deleted>':<30} | -")

    print("-" * 60)
    
    # If we have a top attacker (e.g. > 20 requests), grab their recent IP sessions
    if stats and stats[0]['count'] > 10:
        top_user_id = stats[0]['user']
        print(f"\nInvestigating Top Attacker (User ID: {top_user_id})...")
        
        try:
            u = User.objects.get(id=top_user_id)
            from security.models import UserSession
            sessions = UserSession.objects.filter(user=u).order_by('-last_activity')[:5]
            
            print("Recent Sessions / IPs:")
            for s in sessions:
                ip = s.ip_address.ip_address if s.ip_address else "Unknown"
                country = s.ip_address.country_code if (s.ip_address and s.ip_address.country_code) else "??"
                print(f" - {s.last_activity} | IP: {ip} ({country}) | Device: {s.device_type} / {s.os_name}")
                
        except Exception as e:
            print(f"Could not fetch session info: {e}")

try:
    identify_attacker()
except Exception as e:
    import traceback
    traceback.print_exc()
