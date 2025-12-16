import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from users.models import User
email = 'placidocastellanos@hotmail.com'
u = User.objects.filter(email__iexact=email).first()
if u:
    print(f"Found user: {u.id} {repr(u.email)}")
else:
    print(f"User not found: {repr(email)}")
    # Partial search
    matches = User.objects.filter(email__icontains='placidocastellanos')
    for m in matches:
        print(f"Partial match: {m.id} {repr(m.email)}")
