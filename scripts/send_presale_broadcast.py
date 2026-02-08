import os
import sys

# Add project root to path (EC2 path)
sys.path.insert(0, '/opt/confio')

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from notifications.models import Notification, NotificationType
from notifications.fcm_service import send_push_notification

def send_presale_broadcast():
    print("Preparing to send Presale broadcast...")
    
    # Title: "¡La primera preventa de $CONFIO ya comenzó! 🚀"
    # Body: "Ya puedes invertir en la app Confío. Si no funciona, actualiza tu app. Cualquier consulta a través del grupo de Telegram."
    
    title = "¡La primera preventa de $CONFIO ya comenzó! 🚀"
    message = "Ya puedes invertir en la app Confío. Si no funciona, actualiza tu app. Cualquier consulta a través del grupo de Telegram."
    
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
    send_presale_broadcast()
