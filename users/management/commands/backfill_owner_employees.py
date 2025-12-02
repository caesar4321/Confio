from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import Business, Account
from users.models_employee import BusinessEmployee

class Command(BaseCommand):
    help = 'Backfill missing BusinessEmployee records for business owners'

    def handle(self, *args, **options):
        self.stdout.write('Starting backfill of owner employees...')
        
        businesses = Business.objects.filter(deleted_at__isnull=True)
        created_count = 0
        skipped_count = 0
        
        for business in businesses:
            # Find the owner account
            owner_account = Account.objects.filter(
                business=business,
                account_type='business',
                deleted_at__isnull=True
            ).order_by('created_at').first()
            
            if not owner_account:
                self.stdout.write(self.style.WARNING(f'Business {business.id} ({business.name}) has no owner account'))
                continue
                
            owner_user = owner_account.user
            
            # Check if employee record exists
            exists = BusinessEmployee.objects.filter(
                business=business,
                user=owner_user,
                deleted_at__isnull=True
            ).exists()
            
            if exists:
                skipped_count += 1
                continue
                
            # Create employee record
            try:
                with transaction.atomic():
                    BusinessEmployee.objects.create(
                        business=business,
                        user=owner_user,
                        role='owner',
                        hired_by=owner_user,
                        is_active=True
                    )
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(f'Created owner record for business {business.id} ({business.name})'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed to create record for business {business.id}: {e}'))
                
        self.stdout.write(self.style.SUCCESS(f'Finished! Created: {created_count}, Skipped: {skipped_count}'))
