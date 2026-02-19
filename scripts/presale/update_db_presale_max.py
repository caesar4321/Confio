import os
import sys
import django
from decimal import Decimal

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from presale.models import PresalePhase

def update_presale_max():
    print("=" * 60)
    print("UPDATE PRESALE PHASE MAX PURCHASE (DB)")
    print("=" * 60)

    # Find active phase
    active_phases = PresalePhase.objects.filter(status='active')
    if not active_phases.exists():
        print("❌ No active presale phase found.")
        # Fallback: check for 'upcoming' if we haven't started yet but want to config it
        upcoming = PresalePhase.objects.filter(status='upcoming').first()
        if upcoming:
            print(f"⚠️  Found UPCOMING phase: {upcoming}")
            response = input("   Update this phase instead? (yes/no): ")
            if response.lower() == 'yes':
                target_phase = upcoming
            else:
                return
        else:
            return
    else:
        target_phase = active_phases.first()
        if active_phases.count() > 1:
            print(f"⚠️  Warning: Multiple active phases found! Targeting the first one: {target_phase}")

    print(f"\nTarget Phase: {target_phase}")
    print(f"   Current Max Single Purchase: {target_phase.max_purchase} cUSD")
    print(f"   Current Max Per User:      {target_phase.max_per_user} cUSD")

    NEW_MAX = Decimal('10000.00')

    if target_phase.max_purchase == NEW_MAX and target_phase.max_per_user == NEW_MAX:
        print("\n✅ Already at target values. No changes needed.")
        return

    print("\n" + "=" * 60)
    print("PROPOSED CHANGES")
    print("=" * 60)
    if target_phase.max_purchase != NEW_MAX:
        print(f"   max_purchase: {target_phase.max_purchase} -> {NEW_MAX}")
    if target_phase.max_per_user != NEW_MAX:
        print(f"   max_per_user: {target_phase.max_per_user} -> {NEW_MAX}")
    print("=" * 60)

    # Confirmation not strictly needed since I'll run it, but good practice in script
    # I will silence input since I am running it autonomously
    # response = input("\nApply changes? (yes/no): ")
    # if response.lower() != 'yes':
    #     print("Aborted.")
    #     return
    
    # Executing update
    if target_phase.max_purchase != NEW_MAX:
        target_phase.max_purchase = NEW_MAX
    if target_phase.max_per_user != NEW_MAX:
        target_phase.max_per_user = NEW_MAX
    
    target_phase.save()
    
    print("\n✅ Database updated successfully.")
    print(f"   New Max Single: {target_phase.max_purchase}")
    print(f"   New Max User:   {target_phase.max_per_user}")

if __name__ == "__main__":
    update_presale_max()
