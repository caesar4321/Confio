from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import Account, User, Business
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Backfill display names and avatar letters for existing accounts'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
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
            self.stdout.write(
                self.style.WARNING('DRY RUN MODE - No changes will be made')
            )
        
        # Get all accounts
        accounts = Account.objects.select_related('user', 'business').all()
        total_accounts = accounts.count()
        
        self.stdout.write(f"Found {total_accounts} accounts to process")
        
        updated_count = 0
        errors = []
        
        with transaction.atomic():
            for account in accounts:
                try:
                    # Force recalculation of display_name and avatar_letter
                    # by accessing the properties
                    old_display_name = getattr(account, '_display_name_cache', None)
                    old_avatar_letter = getattr(account, '_avatar_letter_cache', None)
                    
                    # Access the properties to trigger recalculation
                    new_display_name = account.display_name
                    new_avatar_letter = account.avatar_letter
                    
                    # Check if we need to update
                    needs_update = (
                        old_display_name != new_display_name or 
                        old_avatar_letter != new_avatar_letter
                    )
                    
                    if needs_update:
                        if verbose:
                            self.stdout.write(
                                f"Account {account.account_id}: "
                                f"'{old_display_name}' -> '{new_display_name}', "
                                f"'{old_avatar_letter}' -> '{new_avatar_letter}'"
                            )
                        
                        if not dry_run:
                            # Touch the account to trigger the signal and update timestamps
                            account.save(update_fields=['updated_at'])
                        
                        updated_count += 1
                    elif verbose:
                        self.stdout.write(
                            f"Account {account.account_id}: No changes needed "
                            f"('{new_display_name}', '{new_avatar_letter}')"
                        )
                        
                except Exception as e:
                    error_msg = f"Error processing account {account.account_id}: {str(e)}"
                    errors.append(error_msg)
                    self.stdout.write(
                        self.style.ERROR(error_msg)
                    )
        
        # Summary
        self.stdout.write("\n" + "="*50)
        self.stdout.write("BACKFILL SUMMARY")
        self.stdout.write("="*50)
        self.stdout.write(f"Total accounts processed: {total_accounts}")
        self.stdout.write(f"Accounts updated: {updated_count}")
        self.stdout.write(f"Errors: {len(errors)}")
        
        if errors:
            self.stdout.write("\nERRORS:")
            for error in errors:
                self.stdout.write(f"  - {error}")
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('\nThis was a dry run. Run without --dry-run to apply changes.')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS('\nBackfill completed successfully!')
            ) 