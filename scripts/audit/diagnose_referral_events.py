
def diagnose():
    from achievements.models import ReferralRewardEvent
    
    print("Checking for Referee events with wrong actor_role...")
    # Events where user is the referee
    referee_events = ReferralRewardEvent.objects.filter(
        referral__isnull=False
    ).select_related('referral', 'user')
    
    mismatches = 0
    correct = 0
    
    for event in referee_events:
        is_referee = (event.user_id == event.referral.referred_user_id)
        is_referrer = (event.user_id == event.referral.referrer_user_id) if event.referral.referrer_user_id else False
        
        role = event.actor_role
        
        if is_referee:
            if role != 'referee':
                print(f"MISMATCH: Event {event.id} User {event.user.username} is REFEREE but role is '{role}'")
                mismatches += 1
            else:
                correct += 1
        elif is_referrer:
            if role != 'referrer':
                print(f"MISMATCH: Event {event.id} User {event.user.username} is REFERRER but role is '{role}'")
                mismatches += 1
            else:
                correct += 1
                
    print(f"Checked events. Correct: {correct}, Mismatches: {mismatches}")

if __name__ == "__main__":
    import os
    import django

    
    # sys.path.append('/Users/julian/Confio')
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    
    diagnose()
