from django.core.management.base import BaseCommand
from users.models import Account

class Command(BaseCommand):
    help = 'Reset is_keyless_migrated to False for all accounts'

    def handle(self, *args, **options):
        # Update all accounts (including soft-deleted ones)
        count = Account.all_objects.update(is_keyless_migrated=False)
        self.stdout.write(self.style.SUCCESS(f'Successfully reset {count} accounts to not migrated'))
