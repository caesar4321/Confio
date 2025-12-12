from django.core.management.base import BaseCommand
from usdc_transactions.models import USDCWithdrawal
from notifications.utils import create_notification
from notifications.models import NotificationType as NotificationTypeChoices
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Fix stuck USDC withdrawals by marking them as COMPLETED and sending notifications'

    def handle(self, *args, **options):
        # Find all pending withdrawals
        pending_withdrawals = USDCWithdrawal.objects.filter(status='PENDING').order_by('created_at')
        
        count = pending_withdrawals.count()
        self.stdout.write(f"Found {count} pending withdrawals")
        
        if count == 0:
            return

        for withdrawal in pending_withdrawals:
            self.stdout.write(f"Processing withdrawal {withdrawal.id} ({withdrawal.amount} USDC) for user {withdrawal.actor_user}")
            
            # Simulate completion
            withdrawal.status = 'COMPLETED'
            withdrawal.completed_at = timezone.now()
            withdrawal.save(update_fields=['status', 'completed_at', 'updated_at'])
            
            # Create notification
            try:
                notification = create_notification(
                    user=withdrawal.actor_user,
                    notification_type=NotificationTypeChoices.USDC_WITHDRAWAL_COMPLETED,
                    title="Retiro USDC completado",
                    message=f"Tu retiro de {withdrawal.amount} USDC se ha completado exitosamente",
                    data={
                        'transaction_id': str(withdrawal.withdrawal_id),
                        'transaction_type': 'withdrawal',
                        'type': 'withdrawal',
                        'amount': str(withdrawal.amount),
                        'currency': 'USDC',
                        'destination_address': withdrawal.destination_address,
                        'status': 'completed',
                        'notification_type': 'USDC_WITHDRAWAL_COMPLETED'
                    },
                    related_object_type='USDCWithdrawal',
                    related_object_id=str(withdrawal.id),
                    action_url=f"confio://transaction/{withdrawal.withdrawal_id}"
                )
                self.stdout.write(self.style.SUCCESS(f"  - Marked COMPLETED and notification sent (ID: {notification.id})"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  - Marked COMPLETED but failed to send notification: {e}"))
