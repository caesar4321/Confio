"""
Management command to migrate legacy Firebase UID-based peppers to account-based peppers
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import User, Account, WalletPepper
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Migrate legacy Firebase UID-based peppers to account-based peppers'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run the migration without making changes',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        verbose = options['verbose']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Find all legacy peppers (those with Firebase UIDs)
        legacy_peppers = WalletPepper.objects.exclude(account_key__startswith='user_')
        
        self.stdout.write(f'Found {legacy_peppers.count()} legacy peppers to migrate')
        
        migrated = 0
        skipped = 0
        errors = 0
        
        for pepper in legacy_peppers:
            try:
                # Try to find the user by Firebase UID
                user = User.objects.filter(firebase_uid=pepper.account_key).first()
                
                if not user:
                    if verbose:
                        self.stdout.write(
                            self.style.ERROR(
                                f'Skipping pepper {pepper.account_key}: User not found'
                            )
                        )
                    skipped += 1
                    continue
                
                # Get the user's personal account (index 0)
                account = Account.objects.filter(
                    user=user,
                    account_type='personal',
                    account_index=0
                ).first()
                
                if not account:
                    # Create default personal account if it doesn't exist
                    if not dry_run:
                        account = Account.objects.create(
                            user=user,
                            account_type='personal',
                            account_index=0
                        )
                        if verbose:
                            self.stdout.write(
                                f'Created personal account for user {user.id}'
                            )
                    else:
                        if verbose:
                            self.stdout.write(
                                f'Would create personal account for user {user.id}'
                            )
                
                # Generate new account key
                new_account_key = f"user_{user.id}_personal_0"
                
                if verbose:
                    self.stdout.write(
                        f'Migrating pepper: {pepper.account_key} -> {new_account_key}'
                    )
                
                if not dry_run:
                    # Check if new key already exists
                    existing = WalletPepper.objects.filter(account_key=new_account_key).first()
                    if existing:
                        if verbose:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'Account key {new_account_key} already exists, skipping'
                                )
                            )
                        skipped += 1
                        continue
                    
                    # Update the pepper's account key
                    with transaction.atomic():
                        pepper.account_key = new_account_key
                        pepper.save()
                        migrated += 1
                else:
                    migrated += 1  # Count as would-be migrated in dry run
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error migrating pepper {pepper.account_key}: {str(e)}'
                    )
                )
                errors += 1
        
        # Summary
        self.stdout.write(self.style.SUCCESS('\n=== Migration Summary ==='))
        self.stdout.write(f'Successfully migrated: {migrated}')
        self.stdout.write(f'Skipped: {skipped}')
        self.stdout.write(f'Errors: {errors}')
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    '\nThis was a dry run. Run without --dry-run to apply changes.'
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS('\nMigration complete!'))
        
        # Show current pepper distribution
        self.stdout.write('\n=== Current Pepper Distribution ===')
        personal_count = WalletPepper.objects.filter(account_key__contains='_personal_').count()
        business_count = WalletPepper.objects.filter(account_key__contains='_business_').count()
        legacy_count = WalletPepper.objects.exclude(account_key__startswith='user_').count()
        
        self.stdout.write(f'Personal accounts: {personal_count}')
        self.stdout.write(f'Business accounts: {business_count}')
        self.stdout.write(f'Legacy (unmigrated): {legacy_count}')