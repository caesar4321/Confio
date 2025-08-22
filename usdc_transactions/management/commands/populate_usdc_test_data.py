from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
import uuid
from datetime import timedelta
import random

from usdc_transactions.models import USDCDeposit, USDCWithdrawal
from users.models import Business

User = get_user_model()


class Command(BaseCommand):
    help = 'Populate USDC transactions test data for existing users'

    def handle(self, *args, **options):
        # Get some test users
        users = User.objects.filter(is_active=True)[:5]
        
        if not users:
            self.stdout.write(self.style.ERROR('No active users found. Please create users first.'))
            return
        
        deposit_count = 0
        withdrawal_count = 0
        
        for user in users:
            # Get user's accounts
            accounts = user.accounts.all()
            
            for account in accounts:
                # Create 2-3 deposits for each account
                num_deposits = random.randint(2, 3)
                for i in range(num_deposits):
                    # Determine actor details based on account type
                    if account.account_type == 'business' and account.business:
                        actor_business = account.business
                        actor_type = 'business'
                        actor_display_name = account.business.name
                    else:
                        actor_business = None
                        actor_type = 'user'
                        actor_display_name = f"{user.first_name} {user.last_name}".strip()
                        if not actor_display_name:
                            actor_display_name = user.username or f"User {user.id}"
                    
                    # Create deposit with random data
                    deposit = USDCDeposit.objects.create(
                        actor_user=user,
                        actor_business=actor_business,
                        actor_type=actor_type,
                        actor_display_name=actor_display_name,
                        actor_address=account.algorand_address or f"0x{uuid.uuid4().hex[:40]}",
                        amount=Decimal(random.uniform(50, 500)).quantize(Decimal('0.01')),
                        source_address=f"0x{uuid.uuid4().hex[:40]}",
                        network='ALGORAND',
                        status=random.choice(['COMPLETED', 'COMPLETED', 'COMPLETED', 'PENDING']),  # 75% completed
                        created_at=timezone.now() - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23)),
                        updated_at=timezone.now()
                    )
                    
                    # If completed, set completed_at
                    if deposit.status == 'COMPLETED':
                        deposit.completed_at = deposit.created_at + timedelta(minutes=random.randint(1, 10))
                        deposit.save()
                    
                    deposit_count += 1
                
                # Create 1-2 withdrawals for each account
                num_withdrawals = random.randint(1, 2)
                for i in range(num_withdrawals):
                    # Determine actor details based on account type
                    if account.account_type == 'business' and account.business:
                        actor_business = account.business
                        actor_type = 'business'
                        actor_display_name = account.business.name
                    else:
                        actor_business = None
                        actor_type = 'user'
                        actor_display_name = f"{user.first_name} {user.last_name}".strip()
                        if not actor_display_name:
                            actor_display_name = user.username or f"User {user.id}"
                    
                    # Create withdrawal with random data
                    withdrawal = USDCWithdrawal.objects.create(
                        actor_user=user,
                        actor_business=actor_business,
                        actor_type=actor_type,
                        actor_display_name=actor_display_name,
                        actor_address=account.algorand_address or f"0x{uuid.uuid4().hex[:40]}",
                        amount=Decimal(random.uniform(25, 250)).quantize(Decimal('0.01')),
                        destination_address=f"0x{uuid.uuid4().hex[:40]}",
                        network='ALGORAND',
                        service_fee=Decimal(random.uniform(0, 2)).quantize(Decimal('0.01')),
                        status=random.choice(['COMPLETED', 'COMPLETED', 'COMPLETED', 'PROCESSING']),  # 75% completed
                        created_at=timezone.now() - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23)),
                        updated_at=timezone.now()
                    )
                    
                    # If completed, set completed_at
                    if withdrawal.status == 'COMPLETED':
                        withdrawal.completed_at = withdrawal.created_at + timedelta(minutes=random.randint(5, 30))
                        withdrawal.save()
                    
                    withdrawal_count += 1
        
        self.stdout.write(self.style.SUCCESS(
            f'Successfully created {deposit_count} deposits and {withdrawal_count} withdrawals for {len(users)} users'
        ))
