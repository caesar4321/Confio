from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
import random
from decimal import Decimal
from usdc_transactions.models import USDCDeposit, USDCWithdrawal
import uuid

User = get_user_model()


class Command(BaseCommand):
    help = 'Populate test USDC data for Julian users'

    def handle(self, *args, **options):
        # Target specific users that Julian can access
        target_usernames = ['julianmoonluna', '3db2c9a11e2c156']
        users = User.objects.filter(username__in=target_usernames)
        
        if not users.exists():
            self.stdout.write(
                self.style.ERROR('No target users found. Please check usernames.')
            )
            return

        self.stdout.write(f'Creating test data for {users.count()} users...')

        # Sample external addresses for realistic test data
        external_addresses = [
            '0x742d35cc6ba1b9f4e5cfd9c7b6ed6b8bb4231234',
            '0x8ba1b9f4e5cfd9c7b6ed6b8bb42312340x742d35c',
            '0xb9f4e5cfd9c7b6ed6b8bb42312340x742d35cc6ba',
            '0xe5cfd9c7b6ed6b8bb42312340x742d35cc6ba1b9f',
            '0xd9c7b6ed6b8bb42312340x742d35cc6ba1b9f4e5c',
        ]

        for user in users:
            self.stdout.write(f'\nCreating transactions for user: {user.username}')
            
            # Create transactions for each account type the user has
            for account in user.accounts.all():
                self.stdout.write(f'  - Creating for {account.account_type} account')
                
                # Determine actor details
                actor_business = None
                actor_type = 'user'
                actor_display_name = f"{user.first_name} {user.last_name}".strip()
                if not actor_display_name:
                    actor_display_name = user.username or f"User {user.id}"
                
                if account.account_type == 'business' and account.business:
                    actor_business = account.business
                    actor_type = 'business'
                    actor_display_name = account.business.name

                # Create 3-5 deposits for each account
                deposits_count = random.randint(3, 5)
                for i in range(deposits_count):
                    amount = Decimal(str(round(random.uniform(50.0, 2000.0), 2)))
                    created_time = timezone.now() - timedelta(
                        days=random.randint(0, 30),
                        hours=random.randint(0, 23),
                        minutes=random.randint(0, 59)
                    )
                    
                    # Most should be completed
                    status = random.choice(['COMPLETED', 'COMPLETED', 'COMPLETED', 'COMPLETED', 'PENDING'])
                    
                    deposit = USDCDeposit.objects.create(
                        actor_user=user,
                        actor_business=actor_business,
                        actor_type=actor_type,
                        actor_display_name=actor_display_name,
                        actor_address=account.algorand_address or '',
                        amount=amount,
                        source_address=random.choice(external_addresses),
                        network='SUI',
                        status=status,
                        created_at=created_time,
                        completed_at=created_time + timedelta(minutes=random.randint(1, 10)) if status == 'COMPLETED' else None
                    )
                    self.stdout.write(f'    + Deposit: ${amount} USDC - {status}')

                # Create 2-4 withdrawals for each account
                withdrawals_count = random.randint(2, 4)
                for i in range(withdrawals_count):
                    amount = Decimal(str(round(random.uniform(25.0, 1000.0), 2)))
                    created_time = timezone.now() - timedelta(
                        days=random.randint(0, 30),
                        hours=random.randint(0, 23),
                        minutes=random.randint(0, 59)
                    )
                    
                    status = random.choice(['COMPLETED', 'COMPLETED', 'COMPLETED', 'PENDING', 'PROCESSING'])
                    
                    withdrawal = USDCWithdrawal.objects.create(
                        actor_user=user,
                        actor_business=actor_business,
                        actor_type=actor_type,
                        actor_display_name=actor_display_name,
                        actor_address=account.algorand_address or '',
                        amount=amount,
                        destination_address=random.choice(external_addresses),
                        network='SUI',
                        service_fee=Decimal(str(round(random.uniform(0.5, 2.0), 2))),
                        status=status,
                        created_at=created_time,
                        completed_at=created_time + timedelta(minutes=random.randint(5, 30)) if status == 'COMPLETED' else None
                    )
                    self.stdout.write(f'    - Withdrawal: ${amount} USDC - {status}')

        self.stdout.write(
            self.style.SUCCESS('\nSuccessfully created test data for Julian\'s users!')
        )