from django.core.management.base import BaseCommand
from send.models import SendTransaction
from decimal import Decimal

# ⚠️ WARNING: This command should only be used to fix existing data.
# The backend now has safeguards to prevent incorrect amount storage.
# DO NOT use this command on data that is already in correct format.


class Command(BaseCommand):
    help = 'Fix send transaction amounts from smallest unit to decimal format'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Get all send transactions
        transactions = SendTransaction.objects.all()
        
        fixed_count = 0
        skipped_count = 0
        
        for transaction in transactions:
            try:
                amount_str = str(transaction.amount)
                
                # Check if amount is already in decimal format (contains a dot)
                if '.' in amount_str:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipping transaction {transaction.id}: already in decimal format ({transaction.amount})'
                        )
                    )
                    skipped_count += 1
                    continue
                
                # Check if amount is a large integer (likely in smallest unit)
                amount_int = int(amount_str)
                if amount_int < 1000000:  # Less than 1 million, probably already in decimal
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipping transaction {transaction.id}: small amount, probably already correct ({transaction.amount})'
                        )
                    )
                    skipped_count += 1
                    continue
                
                # Convert from smallest unit to decimal
                # For cUSD and USDC: 6 decimal places
                # For CONFIO: 6 decimal places
                amount_decimal = Decimal(amount_int) / Decimal('1000000')  # 6 decimal places
                
                if dry_run:
                    self.stdout.write(
                        f'Would fix transaction {transaction.id}: {transaction.amount} -> {amount_decimal}'
                    )
                else:
                    transaction.amount = str(amount_decimal)
                    transaction.save()
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Fixed transaction {transaction.id}: {transaction.amount} -> {amount_decimal}'
                        )
                    )
                
                fixed_count += 1
                
            except (ValueError, TypeError) as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error processing transaction {transaction.id}: {e}'
                    )
                )
        
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'DRY RUN: Would fix {fixed_count} transactions, skip {skipped_count}'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Fixed {fixed_count} transactions, skipped {skipped_count}'
                )
            ) 