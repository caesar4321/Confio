import os
import django
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from achievements.models import ReferralRewardEvent
from django.db import transaction

def populate_ids():
    # Fetch all events to ensure uniqueness
    events = ReferralRewardEvent.objects.all()
    count = events.count()
    print(f"Found {count} total events. Regenerating IDs for all...")
    
    updated = 0
    for event in events:
        event.internal_id = uuid.uuid4().hex
        event.save(update_fields=['internal_id'])
        updated += 1
        if updated % 100 == 0:
            print(f"Updated {updated} events...")
            
    print(f"Finished updating {updated} events.")

if __name__ == "__main__":
    populate_ids()
