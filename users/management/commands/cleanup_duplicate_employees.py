from django.core.management.base import BaseCommand
from django.db import transaction
from users.models_employee import BusinessEmployee
from collections import defaultdict

class Command(BaseCommand):
    help = 'Clean up duplicate BusinessEmployee records, keeping only the owner record'

    def handle(self, *args, **options):
        self.stdout.write('Starting cleanup of duplicate employee records...')
        
        # Find all active employee records
        employees = BusinessEmployee.objects.filter(
            deleted_at__isnull=True
        ).select_related('business', 'user').order_by('business_id', 'user_id', 'role')
        
        # Group by business + user
        grouped = defaultdict(list)
        for emp in employees:
            key = (emp.business_id, emp.user_id)
            grouped[key].append(emp)
        
        deleted_count = 0
        
        for (business_id, user_id), records in grouped.items():
            if len(records) <= 1:
                continue
                
            # Multiple records for same user in same business
            business_name = records[0].business.name
            user_name = records[0].user.get_full_name() or records[0].user.username
            
            self.stdout.write(f'\nFound {len(records)} records for {user_name} in {business_name}:')
            for rec in records:
                self.stdout.write(f'  - ID: {rec.id}, Role: {rec.role}, Created: {rec.created_at}')
            
            # Keep the owner record if it exists, otherwise keep the oldest
            owner_record = next((r for r in records if r.role == 'owner'), None)
            
            if owner_record:
                keep = owner_record
                to_delete = [r for r in records if r.id != keep.id]
                self.stdout.write(self.style.SUCCESS(f'  Keeping owner record (ID: {keep.id})'))
            else:
                # No owner record, keep the oldest
                keep = min(records, key=lambda r: r.created_at)
                to_delete = [r for r in records if r.id != keep.id]
                self.stdout.write(self.style.WARNING(f'  No owner record found, keeping oldest (ID: {keep.id}, Role: {keep.role})'))
            
            # Soft delete duplicates
            for rec in to_delete:
                try:
                    with transaction.atomic():
                        rec.soft_delete()
                        deleted_count += 1
                        self.stdout.write(self.style.SUCCESS(f'  Deleted duplicate record (ID: {rec.id}, Role: {rec.role})'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  Failed to delete record {rec.id}: {e}'))
        
        self.stdout.write(self.style.SUCCESS(f'\nFinished! Deleted {deleted_count} duplicate records'))
