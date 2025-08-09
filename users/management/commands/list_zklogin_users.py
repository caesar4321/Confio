from django.core.management.base import BaseCommand
from users.models import User, Account


class Command(BaseCommand):
    help = 'List users with zkLogin (algorand_address) that are not test users'

    def handle(self, *args, **options):
        # Get accounts with algorand_address
        zklogin_accounts = Account.objects.filter(
            algorand_address__isnull=False
        ).exclude(
            algorand_address=''
        ).select_related('user').order_by('user__created_at')
        
        # Filter out auto-generated test users
        real_users = []
        test_users = []
        
        for account in zklogin_accounts:
            user = account.user
            # Test users typically have usernames like test_123456
            if user.username.startswith('test_') and user.username[5:].isdigit():
                test_users.append((user, account))
            else:
                real_users.append((user, account))
        
        self.stdout.write(self.style.SUCCESS(f'\nFound {len(real_users)} real zkLogin users:'))
        self.stdout.write('='*80)
        
        for user, account in real_users:
            self.stdout.write(
                f'Username: {self.style.WARNING(user.username.ljust(20))} '
                f'Created: {user.created_at.strftime("%Y-%m-%d %H:%M")} '
                f'Sui: {account.algorand_address[:20]}...'
            )
        
        if not real_users:
            self.stdout.write(self.style.ERROR('No real zkLogin users found!'))
            self.stdout.write('\nYou may want to create a test user with zkLogin enabled.')
        
        self.stdout.write(f'\n{self.style.SUCCESS(f"Also found {len(test_users)} auto-generated test users")}')