import os
import sys
import django

# Add project root to path
sys.path.insert(0, '/opt/confio')

print(f"CWD: {os.getcwd()}")
print(f"sys.path: {sys.path}")

try:
    import config
    print(f"Imported config from: {config.__file__}")
    import config.settings
    print(f"Imported config.settings from: {config.settings.__file__}")
except Exception as e:
    print(f"Import failed: {e}")
    # List directory contents of /opt/confio to be sure
    print(f"Contents of /opt/confio: {os.listdir('/opt/confio')}")

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from notifications.models import Notification, NotificationType
from notifications.fcm_service import send_push_notification

def send_christmas_broadcast():
    print("Preparing to send Christmas broadcast...")
    
    # Create the notification object
    # Title: "¡Feliz Navidad! 🎄"
    # Body: "Actualice la app y manténgase atento. Nos acercamos a la 1ra Preventa. 🚀"
    
    title = "¡Feliz Navidad! 🎄"
    message = "Actualice la app y manténgase atento. Nos acercamos a la 1ra Preventa. 🚀"
    
    notification = Notification.objects.create(
        is_broadcast=True,
        broadcast_target='all',
        notification_type=NotificationType.ANNOUNCEMENT,
        title=title,
        message=message
    )
    
    print(f"Notification created: {notification}")
    print("Sending push notification...")
    
    try:
        result = send_push_notification(notification)
        
        if result.get('success'):
            print(f"SUCCESS: Successfully sent to {result.get('sent', 0)} devices")
            if result.get('failed', 0) > 0:
                print(f"WARNING: Failed to send to {result.get('failed')} devices")
                print(f"Errors: {result.get('errors')}")
        else:
            print(f"ERROR: Failed to send: {result.get('error', 'Unknown error')}")
            
    except Exception as e:
        print(f"EXCEPTION: Error sending broadcast: {str(e)}")

if __name__ == '__main__':
    send_christmas_broadcast()
