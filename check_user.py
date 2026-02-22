import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from users.models import User, MyBalance
from presale.models import PresalePhase

print("--- User Info ---")
try:
    user = User.objects.get(email="sushicaceres@gmail.com")
    print(f"User: {user.email}")
    balance = MyBalance.objects.get(user=user)
    print(f"Balances: cUSD={balance.cusd}, USDC={balance.usdc}, CONFIO={balance.confio}, CONFIO (PresaleLocked)={balance.confio_presale_locked}")
except Exception as e:
    print(f"Error getting user or balance: {e}")

print("\n--- Presale Phases ---")
active_phase = PresalePhase.objects.filter(status='active').first()
if active_phase:
    print(f"Active Phase: {active_phase.phase_name}, Price: {active_phase.price_per_token}")
else:
    print("No active Phase.")

for p in PresalePhase.objects.all().order_by('phase_number'):
    print(f"Phase {p.phase_number}: {p.phase_name} - {p.price_per_token} USD - Status: {p.status}")
