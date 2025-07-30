"""
Management command to send scheduled broadcast notifications
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from notifications.models import Notification
from notifications.fcm_service import send_push_notification


class Command(BaseCommand):
    help = 'Send scheduled broadcast notifications'

    def handle(self, *args, **options):
        # Find scheduled broadcasts that are due
        now = timezone.now()
        
        scheduled_broadcasts = Notification.objects.filter(
            is_broadcast=True,
            push_sent=False,
            data__schedule_time__lte=now.isoformat()
        )
        
        if not scheduled_broadcasts.exists():
            self.stdout.write('No scheduled broadcasts to send')
            return
        
        for broadcast in scheduled_broadcasts:
            self.stdout.write(f'Sending scheduled broadcast: {broadcast.title}')
            
            try:
                result = send_push_notification(broadcast)
                
                if result.get('success'):
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Successfully sent to {result.get("sent", 0)} devices'
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f'Failed to send: {result.get("error", "Unknown error")}'
                        )
                    )
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Error sending broadcast {broadcast.id}: {str(e)}')
                )