from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from notifications.models import NotificationPreference
from django.db import transaction

User = get_user_model()


class Command(BaseCommand):
    help = 'Create missing notification preferences for existing users'

    def handle(self, *args, **options):
        users_without_prefs = User.objects.filter(
            notification_preferences__isnull=True
        )
        
        count = users_without_prefs.count()
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('All users already have notification preferences'))
            return
        
        self.stdout.write(f'Found {count} users without notification preferences')
        
        created_count = 0
        
        with transaction.atomic():
            for user in users_without_prefs:
                try:
                    NotificationPreference.objects.create(
                        user=user,
                        push_enabled=True,
                        push_transactions=True,
                        push_p2p=True,
                        push_security=True,
                        push_promotions=True,
                        push_announcements=True,
                        in_app_enabled=True,
                        in_app_transactions=True,
                        in_app_p2p=True,
                        in_app_security=True,
                        in_app_promotions=True,
                        in_app_announcements=True,
                    )
                    created_count += 1
                    self.stdout.write(f'Created preferences for user {user.id} ({user.username})')
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'Error creating preferences for user {user.id}: {e}')
                    )
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} notification preferences')
        )