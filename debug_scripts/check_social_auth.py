
import os
import django
from django.db import connection

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

def check_social_auth_raw(user_id):
    print(f"Checking social auth for User {user_id}...")
    with connection.cursor() as cursor:
        try:
            cursor.execute("SELECT provider, uid FROM social_auth_usersocialauth WHERE user_id = %s", [user_id])
            rows = cursor.fetchall()
            if not rows:
                print("No social auth records found.")
            else:
                for row in rows:
                    print(f"Provider: {row[0]}, UID: {row[1]}")
        except Exception as e:
            print(f"Error querying social_auth table: {e}")

if __name__ == "__main__":
    check_social_auth_raw(8)
