from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from usdc_transactions.models import USDCWithdrawal
from notifications.utils import create_notification
from notifications.models import NotificationType as NotificationTypeChoices
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Test USDC withdrawal notification creation'

    def add_arguments(self, parser):
        parser.add_argument('user_email', type=str, help='Email of the user to test with')
        parser.add_argument('--amount', type=str, default='100', help='Amount to withdraw')

    def handle(self, *args, **options):
        # Enable debug logging
        logging.basicConfig(level=logging.DEBUG)
        
        user_email = options['user_email']
        amount = options['amount']
        
        try:
            user = User.objects.get(email=user_email)
            self.stdout.write(f"Found user: {user.email} (ID: {user.id})")
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User with email {user_email} not found"))
            return
        
        # Create a test withdrawal
        self.stdout.write("Creating test withdrawal...")
        withdrawal = USDCWithdrawal.objects.create(
            actor_user=user,
            actor_type='user',
            actor_display_name=f"{user.first_name} {user.last_name}".strip() or user.username,
            actor_address='0x123...test',
            amount=Decimal(amount),
            destination_address='0xabc...external',
            status='COMPLETED',
            completed_at=timezone.now()
        )
        self.stdout.write(f"Created withdrawal with ID: {withdrawal.withdrawal_id}")
        
        # Try to create notification
        self.stdout.write("Creating notification...")
        try:
            notification = create_notification(
                user=user,
                notification_type=NotificationTypeChoices.USDC_WITHDRAWAL_COMPLETED,
                title="Retiro USDC completado",
                message=f"Tu retiro de {amount} USDC se ha completado exitosamente",
                data={
                    'transaction_id': str(withdrawal.withdrawal_id),
                    'transaction_type': 'withdrawal',
                    'type': 'withdrawal',
                    'amount': str(amount),
                    'currency': 'USDC',
                    'destination_address': withdrawal.destination_address,
                    'status': 'completed',
                    'notification_type': 'USDC_WITHDRAWAL_COMPLETED'
                },
                related_object_type='USDCWithdrawal',
                related_object_id=str(withdrawal.id),
                action_url=f"confio://transaction/{withdrawal.withdrawal_id}"
            )
            
            self.stdout.write(self.style.SUCCESS(f"Notification created successfully with ID: {notification.id}"))
            
            # Check if notification was saved
            from notifications.models import Notification
            saved_notification = Notification.objects.filter(id=notification.id).first()
            if saved_notification:
                self.stdout.write(self.style.SUCCESS("Notification verified in database"))
                self.stdout.write(f"  - User: {saved_notification.user.email}")
                self.stdout.write(f"  - Type: {saved_notification.notification_type}")
                self.stdout.write(f"  - Title: {saved_notification.title}")
                self.stdout.write(f"  - Created at: {saved_notification.created_at}")
                self.stdout.write(f"  - Push sent: {saved_notification.push_sent}")
            else:
                self.stdout.write(self.style.ERROR("Notification NOT found in database!"))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating notification: {e}"))
            import traceback
            traceback.print_exc()