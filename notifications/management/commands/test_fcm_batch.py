"""
Management command to test FCM batch sending
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from notifications.models import FCMDeviceToken
from notifications.fcm_service import send_test_push

User = get_user_model()


class Command(BaseCommand):
    help = 'Test FCM batch sending functionality'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-email',
            type=str,
            help='Email of user to send test notification to',
        )
        parser.add_argument(
            '--all-users',
            action='store_true',
            help='Send test to all users with active FCM tokens',
        )

    def handle(self, *args, **options):
        if options['user_email']:
            # Send to specific user
            try:
                user = User.objects.get(email=options['user_email'])
                self.stdout.write(f"Sending test notification to {user.email}")
                
                # Check if user has active tokens
                active_tokens = FCMDeviceToken.objects.filter(
                    user=user,
                    is_active=True
                ).count()
                
                if active_tokens == 0:
                    self.stdout.write(
                        self.style.WARNING(f"No active FCM tokens for user {user.email}")
                    )
                    return
                
                self.stdout.write(f"Found {active_tokens} active token(s)")
                
                # Send test notification
                result = send_test_push(user)
                
                if result['success']:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Successfully sent to {result['sent']} device(s)"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Failed to send: {result.get('error', 'Unknown error')}"
                        )
                    )
                
                if result.get('failed', 0) > 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Failed to send to {result['failed']} device(s)"
                        )
                    )
                
                if result.get('invalid_tokens'):
                    self.stdout.write(
                        self.style.WARNING(
                            f"Deactivated {len(result['invalid_tokens'])} invalid token(s)"
                        )
                    )
                    
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"User with email {options['user_email']} not found")
                )
                
        elif options['all_users']:
            # Send to all users with active tokens
            users_with_tokens = User.objects.filter(
                fcm_tokens__is_active=True
            ).distinct()
            
            total_users = users_with_tokens.count()
            self.stdout.write(f"Sending test notifications to {total_users} users")
            
            success_count = 0
            fail_count = 0
            total_sent = 0
            total_failed = 0
            total_invalid = 0
            
            for user in users_with_tokens:
                result = send_test_push(user)
                
                if result['success']:
                    success_count += 1
                    total_sent += result.get('sent', 0)
                else:
                    fail_count += 1
                
                total_failed += result.get('failed', 0)
                total_invalid += len(result.get('invalid_tokens', []))
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nSummary:\n"
                    f"Users: {success_count} successful, {fail_count} failed\n"
                    f"Devices: {total_sent} sent, {total_failed} failed\n"
                    f"Invalid tokens deactivated: {total_invalid}"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    "Please specify either --user-email or --all-users"
                )
            )