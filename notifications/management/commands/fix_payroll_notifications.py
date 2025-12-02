from django.core.management.base import BaseCommand
from notifications.models import Notification
from users.models_unified import UnifiedTransactionTable


class Command(BaseCommand):
    help = 'Fix existing payroll notifications to use PAYROLL_RECEIVED type'

    def handle(self, *args, **options):
        # Find all notifications with SEND_FROM_EXTERNAL type that are actually payroll
        external_notifications = Notification.objects.filter(
            notification_type='SEND_FROM_EXTERNAL'
        )
        
        self.stdout.write(f"Found {external_notifications.count()} SEND_FROM_EXTERNAL notifications")
        
        # Check which ones are related to payroll transactions
        updated_count = 0
        for notif in external_notifications:
            # Check if related to PayrollItem
            if notif.related_object_type == 'PayrollItem' and notif.related_object_id:
                # Get the PayrollItem to extract item_id for action_url
                try:
                    from payroll.models import PayrollItem
                    payroll_item = PayrollItem.objects.get(id=notif.related_object_id)
                    
                    # Update notification
                    notif.notification_type = 'PAYROLL_RECEIVED'
                    notif.title = 'Pago de nómina recibido'
                    notif.action_url = f"confio://transaction/{payroll_item.item_id}"
                    notif.save()
                    updated_count += 1
                    self.stdout.write(f"  Updated notification {notif.id} for payroll item {notif.related_object_id}")
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Failed to update notification {notif.id}: {e}"))
        
        self.stdout.write(self.style.SUCCESS(f"Updated {updated_count} notifications to PAYROLL_RECEIVED"))
