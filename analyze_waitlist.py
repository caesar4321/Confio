from presale.models import PresaleWaitlist
from notifications.models import FCMDeviceToken
from collections import Counter

# Query waitlist
waitlist = PresaleWaitlist.objects.select_related('user').all().order_by('-created_at')

print(f"Total Waitlist Users: {waitlist.count()}")

profiles = []
for entry in waitlist:
    u = entry.user
    
    # Get platform from FCM tokens (most recently used)
    # Check if user has fcm_tokens related manager, otherwise query directly
    last_token = u.fcm_tokens.order_by('-last_used').first()
    
    platform = "Unknown"
    if last_token:
        platform = last_token.device_type
    
    # Safely get country
    country = u.phone_country or "Unknown"
    
    profiles.append({
        'country': country,
        'platform': platform,
        'joined': entry.created_at.strftime('%Y-%m-%d')
    })

# Metrics
platforms = Counter(p['platform'] for p in profiles)
countries = Counter(p['country'] for p in profiles)

print("\nPlatform Distribution:")
for plat, cnt in platforms.most_common():
    print(f"{plat}: {cnt}")

print("\nGeographic Distribution:")
for code, cnt in countries.most_common():
    print(f"{code}: {cnt}")

print("\nDetailed List (Most recent first):")
print(f"{'Country':<8} | {'Platform':<10} | {'Joined':<12}")
print("-" * 35)
for p in profiles:
    # Normalize platform display
    plat_display = p['platform']
    if plat_display == 'ios': plat_display = 'iOS'
    if plat_display == 'android': plat_display = 'Android'
    
    print(f"{p['country']:<8} | {plat_display:<10} | {p['joined']:<12}")
