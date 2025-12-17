"""
Management command to update existing PAYROLL_SENT notifications with missing fields.
Adds recipient_username, recipient_phone, and business_name to existing notifications.
"""
from django.core.management.base import BaseCommand
from payroll.models import PayrollItem
from notifications.models import Notification, NotificationType as NotificationTypeChoices
import json


class Command(BaseCommand):
    help = 'Update existing PAYROLL_SENT notifications with missing recipient_username, recipient_phone, and business_name'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be updated without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Get all PAYROLL_SENT notifications
        notifications = Notification.objects.filter(
            notification_type=NotificationTypeChoices.PAYROLL_SENT,
        ).select_related('business')

        updated_count = 0
        skipped_count = 0

        for notif in notifications:
            try:
                # Parse existing data
                data = notif.data if isinstance(notif.data, dict) else json.loads(notif.data or '{}')
                
                # Check if already has the new fields
                if data.get('recipient_username') and data.get('business_name'):
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipping notification {notif.id}: Already has new fields'
                        )
                    )
                    skipped_count += 1
                    continue

                # Get related PayrollItem
                payroll_item = None
                if notif.related_object_type == 'PayrollItem' and notif.related_object_id:
                    try:
                        payroll_item = PayrollItem.objects.select_related(
                            'run__business', 'recipient_user'
                        ).get(id=notif.related_object_id)
                    except PayrollItem.DoesNotExist:
                        pass

                if not payroll_item:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipping notification {notif.id}: PayrollItem not found'
                        )
                    )
                    skipped_count += 1
                    continue

                recipient_user = payroll_item.recipient_user
                business = payroll_item.run.business

                # Add missing fields
                data['recipient_username'] = recipient_user.username if recipient_user else ''
                data['recipient_phone'] = recipient_user.phone_number if recipient_user else ''
                data['business_name'] = business.name if business else 'Empresa'

                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'[DRY RUN] Would update notification {notif.id}: '
                            f'recipient_username={data["recipient_username"]}, '
                            f'recipient_phone={data["recipient_phone"]}, '
                            f'business_name={data["business_name"]}'
                        )
                    )
                else:
                    notif.data = data
                    notif.save(update_fields=['data'])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Updated notification {notif.id}'
                        )
                    )

                updated_count += 1

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error processing notification {notif.id}: {str(e)}'
                    )
                )
                skipped_count += 1

        action = 'Would update' if dry_run else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(
                f'\nBackfill complete: {action} {updated_count} notifications, {skipped_count} skipped'
            )
        )
