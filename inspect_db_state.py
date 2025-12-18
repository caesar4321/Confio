import os
import django
from django.db import connection

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

def inspect_tables():
    tables = ['guardarian_transactions', 'usdc_deposits', 'usdc_withdrawals']
    with connection.cursor() as cursor:
        for t in tables:
            print(f"\n--- Table: {t} ---")
            try:
                cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{t}'")
                cols = [row[0] for row in cursor.fetchall()]
                print(cols)
            except Exception as e:
                print(f"Error: {e}")

if __name__ == "__main__":
    inspect_tables()
