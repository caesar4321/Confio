import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from users.models import User
emails = ['placidocastellanos@hotmail.com', 'scalant284@gmail.com', 'yoyi.18.87@gmail.com']

for email in emails:
    u = User.objects.filter(email__iexact=email).first()
    if u:
        print(f"Found: {u.id} {repr(u.email)} (Active: {u.is_active})")
    else:
        print(f"NOT Found: {repr(email)}")
