from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import Business, Account
from users.models_employee import BusinessEmployee


class Command(BaseCommand):
    help = 'Creates owner BusinessEmployee records for existing businesses'

    def handle(self, *args, **options):
        self.stdout.write('Looking for businesses without owner records...')
        
        # Find all businesses that don't have an owner employee record
        businesses_without_owner = []
        
        for business in Business.objects.all():
            # Check if business has an owner
            has_owner = BusinessEmployee.objects.filter(
                business=business,
                role='owner',
                deleted_at__isnull=True
            ).exists()
            
            if not has_owner:
                businesses_without_owner.append(business)
        
        if not businesses_without_owner:
            self.stdout.write(self.style.SUCCESS('All businesses already have owner records!'))
            return
        
        self.stdout.write(f'Found {len(businesses_without_owner)} businesses without owner records')
        
        # Create owner records
        created_count = 0
        
        with transaction.atomic():
            for business in businesses_without_owner:
                # Find the user who created the business account
                # Get the first business account for this business
                business_account = Account.objects.filter(
                    business=business,
                    account_type='business'
                ).order_by('created_at').first()
                
                if business_account:
                    # Create owner employee record
                    BusinessEmployee.objects.create(
                        business=business,
                        user=business_account.user,
                        role='owner',
                        hired_by=business_account.user,
                        is_active=True
                    )
                    created_count += 1
                    self.stdout.write(f'Created owner record for {business.name} (owner: {business_account.user.username})')
                else:
                    self.stdout.write(
                        self.style.WARNING(f'Could not find account for business: {business.name} (ID: {business.id})')
                    )
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} owner records!')
        )