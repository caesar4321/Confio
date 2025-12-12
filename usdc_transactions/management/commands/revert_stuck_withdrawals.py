from django.core.management.base import BaseCommand
from usdc_transactions.models import USDCWithdrawal
from notifications.utils import create_notification
from notifications.models import NotificationType as NotificationTypeChoices
from django.utils import timezone
import logging

class Command(BaseCommand):
    help = 'Revert erroneously completed withdrawals to FAILED'

    def handle(self, *args, **options):
        # Allow passing IDs or just revert the ones we just touched (hard to track)
        # Instead, we will look for 'COMPLETED' withdrawals created recently that have NO transaction hash in UnifiedUSDCTransactionTable
        
        from usdc_transactions.models_unified import UnifiedUSDCTransactionTable
        
        # Withdrawals completed in the last hour
        recent_time = timezone.now() - timezone.timedelta(hours=1)
        
        candidates = USDCWithdrawal.objects.filter(
            status='COMPLETED', 
            completed_at__gte=recent_time
        )
        
        count = 0
        for w in candidates:
            # Check unified
            unified = UnifiedUSDCTransactionTable.objects.filter(usdc_withdrawal=w).first()
            if unified and not unified.transaction_hash:
                self.stdout.write(f"Reverting withdrawal {w.id} ({w.amount} USDC) - No Tx Hash")
                
                w.status = 'FAILED'
                w.error_message = "Transaction was not found on blockchain. Please retry."
                w.save()
                
                unified.status = 'FAILED'
                unified.error_message = w.error_message
                unified.save()
                
                # Notify user of failure
                try:
                    create_notification(
                        user=w.actor_user,
                        notification_type=NotificationTypeChoices.USDC_WITHDRAWAL_FAILED,
                        title="Retiro USDC fallido",
                        message=f"Tu retiro de {w.amount} USDC no se pudo procesar. Por favor intenta nuevamente.",
                        data={
                            'transaction_id': str(w.withdrawal_id),
                            'status': 'failed',
                        },
                        related_object_type='USDCWithdrawal',
                        related_object_id=str(w.id)
                    )
                except Exception as e:
                    self.stdout.write(f"Failed to send failure notification: {e}")
                
                count += 1
        
        self.stdout.write(f"Reverted {count} withdrawals.")
