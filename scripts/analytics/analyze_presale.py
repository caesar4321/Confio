import os
import django
from collections import Counter

# Initialize Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

def analyze_presale():
    print("Analyzing Presale List...", flush=True)
    
    from presale.models import PresaleWaitlist
    from notifications.models import FCMDeviceToken
    from users.models import COUNTRY_CODES
    
    # Map country codes to names
    country_map = {code[2]: code[0] for code in COUNTRY_CODES}
    
    entries = PresaleWaitlist.objects.all().select_related('user')
    total = entries.count()
    print(f"Total entries: {total}", flush=True)
    
    nationalities = []
    platforms = []
    
    for entry in entries:
        user = entry.user
        if not user:
            continue
            
        # Nationality
        country_code = user.phone_country
        country_name = country_map.get(country_code, f"Unknown ({country_code})") if country_code else "Unknown"
        nationalities.append(country_name)
        
        # Platform - check active tokens first, then inactive
        tokens = FCMDeviceToken.objects.filter(user=user).order_by('-is_active', '-last_used')
        if tokens.exists():
            platform = tokens.first().device_type
        else:
            platform = "Unknown"
        platforms.append(platform)
        
    # Aggregate
    nat_counts = Counter(nationalities)
    plat_counts = Counter(platforms)
    
    print("\nNationality Profile:", flush=True)
    print("-" * 20, flush=True)
    for nat, count in nat_counts.most_common():
        percentage = (count / total) * 100
        print(f"{nat}: {count} ({percentage:.1f}%)", flush=True)
        
    print("\nPlatform Profile:", flush=True)
    print("-" * 20, flush=True)
    for plat, count in plat_counts.most_common():
        percentage = (count / total) * 100
        print(f"{plat}: {count} ({percentage:.1f}%)", flush=True)

if __name__ == '__main__':
    analyze_presale()
