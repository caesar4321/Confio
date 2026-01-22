
from django.contrib.auth import get_user_model
from security.models import UserBan, IPAddress
from django.utils import timezone

User = get_user_model()

def ban_attacker():
    user_id = 5501
    ips_to_block = ['91.217.249.196', '91.217.249.192', '193.37.32.142']
    
    print(f"--- Banning Attacker (User ID: {user_id}) ---")
    
    try:
        user = User.objects.get(id=user_id)
        
        # Check if already banned
        existing_ban = UserBan.objects.filter(user=user, expires_at__isnull=True).first()
        if existing_ban:
            print(f"User {user.username} is already permanently banned.")
        else:
            UserBan.objects.create(
                user=user,
                ban_type='permanent',
                reason='suspicious_activity',
                reason_details='SMS Flooding Attacker - Banned via script',
                banned_at=timezone.now()
            )
            print(f"Banned user {user.username} ({user.email}) successfully.")
            
    except User.DoesNotExist:
        print(f"User ID {user_id} not found.")

    print("\n--- Blocking Attacker IPs ---")
    for ip in ips_to_block:
        obj, created = IPAddress.objects.get_or_create(ip_address=ip)
        if not obj.is_blocked:
            obj.is_blocked = True
            obj.blocked_reason = 'SMS Flooding Attacker IP'
            obj.blocked_at = timezone.now()
            obj.save()
            print(f"Blocked IP: {ip}")
        else:
            print(f"IP {ip} is already blocked.")

try:
    ban_attacker()
except Exception as e:
    import traceback
    traceback.print_exc()
