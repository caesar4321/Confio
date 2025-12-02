"""
Management command to backfill PAYROLL_SENT notifications for existing confirmed payroll items.
"""
from django.core.management.base import BaseCommand
from payroll.models import PayrollItem
from users.models import Account
from notifications import utils as notif_utils
from notifications.models import NotificationType as NotificationTypeChoices


class Command(BaseCommand):
    help = 'Backfill PAYROLL_SENT notifications for existing confirmed payroll items'

    def handle(self, *args, **options):
        # Get all confirmed payroll items
        payroll_items = PayrollItem.objects.filter(
            status='CONFIRMED',
            deleted_at__isnull=True
        ).select_related('run__business', 'recipient_user')

        created_count = 0
        skipped_count = 0

        for item in payroll_items:
            try:
                business = item.run.business
                recipient_user = item.recipient_user

                # Get business account
                business_account = Account.objects.filter(
                    business=business,
                    account_type='business',
                    deleted_at__isnull=True
                ).first()

                if not business_account:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipping payroll item {item.item_id}: No business account found'
                        )
                    )
                    skipped_count += 1
                    continue

                # Normalize token type for display
                token_type = (item.token_type or 'CUSD').upper()
                display_token = 'cUSD' if token_type == 'CUSD' else token_type

                recipient_name = f"{recipient_user.first_name} {recipient_user.last_name}".strip() or recipient_user.username

                # Check if notification already exists
                existing = notif_utils.Notification.objects.filter(
                    user=business_account.user,
                    notification_type=NotificationTypeChoices.PAYROLL_SENT,
                    related_object_type='PayrollItem',
                    related_object_id=str(item.id)
                ).exists()

                if existing:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipping payroll item {item.item_id}: Notification already exists'
                        )
                    )
                    skipped_count += 1
                    continue

                # Create notification for business owner
                notif_utils.create_notification(
                    user=business_account.user,
                    account=business_account,
                    business=business,
                    notification_type=NotificationTypeChoices.PAYROLL_SENT,
                    title="Nómina enviada",
                    message=f"Enviaste {item.net_amount} {display_token} a {recipient_name}",
                    data={
                        'transaction_id': item.item_id,
                        'transaction_hash': item.transaction_hash,
                        'transaction_type': 'payroll',
                        'amount': str(item.net_amount),
                        'token_type': token_type,
                        'recipient_name': recipient_name,
                    },
                    related_object_type='PayrollItem',
                    related_object_id=str(item.id),
                    action_url=f"confio://transaction/{item.item_id}",
                )

                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Created PAYROLL_SENT notification for payroll item {item.item_id}'
                    )
                )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error processing payroll item {item.item_id}: {str(e)}'
                    )
                )
                skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'\nBackfill complete: {created_count} notifications created, {skipped_count} skipped'
            )
        )
