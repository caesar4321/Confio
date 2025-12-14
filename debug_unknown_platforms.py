import os
import django

# Initialize Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

def debug_unknowns():
    print("Investigating Unknown Platform Users...", flush=True)
    
    from presale.models import PresaleWaitlist
    from notifications.models import FCMDeviceToken
    from users.models import COUNTRY_CODES
    
    country_map = {code[2]: code[0] for code in COUNTRY_CODES}
    
    entries = PresaleWaitlist.objects.all().select_related('user')
    unknown_users = []
    
    for entry in entries:
        user = entry.user
        if not user:
            continue
            
        # Check for ANY tokens
        has_tokens = FCMDeviceToken.objects.filter(user=user).exists()
        
        if not has_tokens:
            country_name = country_map.get(user.phone_country, user.phone_country)
            unknown_users.append({
                'email': user.email,
                'username': user.username,
                'joined_waitlist': entry.created_at.strftime('%Y-%m-%d'),
                'joined_app': user.date_joined.strftime('%Y-%m-%d'),
                'country': country_name,
                'last_login': user.last_login.strftime('%Y-%m-%d') if user.last_login else 'Never'
            })
            
    print(f"\nFound {len(unknown_users)} users with Unknown platform (No FCM Tokens):", flush=True)
    print("-" * 60, flush=True)
    print(f"{'Email':<30} | {'Joined App':<12} | {'Country':<15} | {'Last Login':<12}", flush=True)
    print("-" * 60, flush=True)
    
    for u in unknown_users:
        # Mask email slightly for privacy in logs
        email = u['email']
        if len(email) > 30:
            email = email[:27] + "..."
        print(f"{email:<30} | {u['joined_app']:<12} | {u['country']:<15} | {u['last_login']:<12}", flush=True)

if __name__ == '__main__':
    debug_unknowns()
