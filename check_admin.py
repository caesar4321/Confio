import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from account.models import User, Account
print("Users:", User.objects.count())
