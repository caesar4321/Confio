from users.models import User
try:
    user = User.objects.get(username='julianm')
    print(f"Current backup status: {user.backup_provider}")
    user.backup_provider = None
    user.backup_verified_at = None
    user.backup_device_name = None
    user.save()
    print(f"Successfully reset backup status for user: {user.username}")
except User.DoesNotExist:
    print("User 'julianm' not found.")
except Exception as e:
    print(f"An error occurred: {e}")
