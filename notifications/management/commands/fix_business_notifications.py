from django.core.management.base import BaseCommand
from notifications.models import Notification
from usdc_transactions.models import USDCDeposit, USDCWithdrawal
from conversion.models import Conversion
from users.models import BusinessEmployee, Account


class Command(BaseCommand):
    help = 'Fix business and account fields for USDC and conversion notifications'

    def handle(self, *args, **options):
        fixed_count = 0
        
        # Fix USDC deposit notifications
        self.stdout.write("Fixing USDC deposit notifications...")
        deposit_notifications = Notification.objects.filter(
            notification_type__in=['USDC_DEPOSIT_COMPLETED', 'USDC_DEPOSIT_PENDING', 'USDC_DEPOSIT_FAILED'],
            business__isnull=True
        )
        
        for notification in deposit_notifications:
            if notification.related_object_type == 'USDCDeposit' and notification.related_object_id:
                try:
                    deposit = USDCDeposit.objects.get(id=notification.related_object_id)
                    if deposit.actor_business:
                        notification.business = deposit.actor_business
                        notification.save()
                        fixed_count += 1
                        self.stdout.write(f"Fixed deposit notification {notification.id} for business {deposit.actor_business.name}")
                    elif deposit.actor_type == 'user' and deposit.actor_user:
                        # Find the user's personal account
                        account = Account.objects.filter(
                            user=deposit.actor_user,
                            account_type='personal'
                        ).first()
                        if account:
                            notification.account = account
                            notification.save()
                            fixed_count += 1
                            self.stdout.write(f"Fixed deposit notification {notification.id} for personal account")
                except USDCDeposit.DoesNotExist:
                    self.stdout.write(f"Deposit {notification.related_object_id} not found for notification {notification.id}")
        
        # Fix USDC withdrawal notifications
        self.stdout.write("\nFixing USDC withdrawal notifications...")
        withdrawal_notifications = Notification.objects.filter(
            notification_type__in=['USDC_WITHDRAWAL_COMPLETED', 'USDC_WITHDRAWAL_PENDING', 'USDC_WITHDRAWAL_FAILED'],
            business__isnull=True
        )
        
        for notification in withdrawal_notifications:
            if notification.related_object_type == 'USDCWithdrawal' and notification.related_object_id:
                try:
                    withdrawal = USDCWithdrawal.objects.get(id=notification.related_object_id)
                    if withdrawal.actor_business:
                        notification.business = withdrawal.actor_business
                        notification.save()
                        fixed_count += 1
                        self.stdout.write(f"Fixed withdrawal notification {notification.id} for business {withdrawal.actor_business.name}")
                    elif withdrawal.actor_type == 'user' and withdrawal.actor_user:
                        # Find the user's personal account
                        account = Account.objects.filter(
                            user=withdrawal.actor_user,
                            account_type='personal'
                        ).first()
                        if account:
                            notification.account = account
                            notification.save()
                            fixed_count += 1
                            self.stdout.write(f"Fixed withdrawal notification {notification.id} for personal account")
                except USDCWithdrawal.DoesNotExist:
                    self.stdout.write(f"Withdrawal {notification.related_object_id} not found for notification {notification.id}")
        
        # Fix conversion notifications
        self.stdout.write("\nFixing conversion notifications...")
        conversion_notifications = Notification.objects.filter(
            notification_type__in=['CONVERSION_COMPLETED', 'CONVERSION_FAILED'],
            business__isnull=True
        )
        
        for notification in conversion_notifications:
            if notification.related_object_type == 'Conversion' and notification.related_object_id:
                try:
                    conversion = Conversion.objects.get(id=notification.related_object_id)
                    if conversion.actor_business:
                        notification.business = conversion.actor_business
                        notification.save()
                        fixed_count += 1
                        self.stdout.write(f"Fixed conversion notification {notification.id} for business {conversion.actor_business.name}")
                    elif conversion.actor_type == 'user' and conversion.actor_user:
                        # Find the user's personal account
                        account = Account.objects.filter(
                            user=conversion.actor_user,
                            account_type='personal'
                        ).first()
                        if account:
                            notification.account = account
                            notification.save()
                            fixed_count += 1
                            self.stdout.write(f"Fixed conversion notification {notification.id} for personal account")
                except Conversion.DoesNotExist:
                    self.stdout.write(f"Conversion {notification.related_object_id} not found for notification {notification.id}")
        
        # Alternative approach: check by user's business employee status
        self.stdout.write("\nChecking remaining notifications by user's business context...")
        remaining_notifications = Notification.objects.filter(
            notification_type__in=[
                'USDC_DEPOSIT_COMPLETED', 'USDC_DEPOSIT_PENDING', 'USDC_DEPOSIT_FAILED',
                'USDC_WITHDRAWAL_COMPLETED', 'USDC_WITHDRAWAL_PENDING', 'USDC_WITHDRAWAL_FAILED',
                'CONVERSION_COMPLETED', 'CONVERSION_FAILED'
            ],
            business__isnull=True,
            user__isnull=False
        )
        
        for notification in remaining_notifications:
            # Check if the user is an employee of any business
            employee_records = BusinessEmployee.objects.filter(
                user=notification.user,
                is_active=True
            ).select_related('business')
            
            if employee_records.exists():
                # If user has only one active business, we can infer it
                if employee_records.count() == 1:
                    business = employee_records.first().business
                    notification.business = business
                    notification.save()
                    fixed_count += 1
                    self.stdout.write(f"Fixed notification {notification.id} for business {business.name} (inferred from user)")
                else:
                    self.stdout.write(f"User {notification.user.email} has multiple businesses, cannot infer for notification {notification.id}")
        
        self.stdout.write(self.style.SUCCESS(f"\nTotal notifications fixed: {fixed_count}"))