import os
import sys

# Setup Django (mimic manage.py)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
from django.conf import settings

def main():
    print(f"CONFIO_ENV: {os.environ.get('CONFIO_ENV')}")
    print(f"BASE_DIR: {settings.BASE_DIR}")
    print(f"DB HOST: '{settings.DATABASES['default']['HOST']}'")
    print(f"DB PRESENCE: {bool(settings.DATABASES['default']['HOST'])}")

if __name__ == '__main__':
    # We don't call django.setup() to avoid loading app configs that might touch DB
    # But accessing settings should work if configured.
    # Actually to be safe we might need configure.
    try:
        from decouple import config
        print(f"Decouple DB_HOST: {config('DB_HOST', default='NOT_FOUND')}")
    except ImportError:
        print("Decouple not installed?")

    # access settings
    try:
        print(f"Settings DB HOST: {settings.DATABASES['default']['HOST']}")
    except Exception as e:
        print(f"Error accessing settings: {e}")

