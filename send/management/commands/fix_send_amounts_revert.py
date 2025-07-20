from django.core.management.base import BaseCommand
from send.models import SendTransaction
from decimal import Decimal


class Command(BaseCommand):
    help = 'Revert incorrect send transaction amount conversions'

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
                
                # Check if amount is a very large number (incorrectly converted)
                if amount_str.isdigit() and int(amount_str) > 1000000:
                    # This was incorrectly converted - revert it
                    amount_int = int(amount_str)
                    amount_decimal = Decimal(amount_int) / Decimal('1000000')  # Convert back to decimal
                    
                    if dry_run:
                        self.stdout.write(
                            f'Would revert transaction {transaction.id}: {transaction.amount} -> {amount_decimal}'
                        )
                    else:
                        transaction.amount = str(amount_decimal)
                        transaction.save()
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'Reverted transaction {transaction.id}: {transaction.amount} -> {amount_decimal}'
                            )
                        )
                    
                    fixed_count += 1
                else:
                    # Amount is already correct (decimal format or small number)
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipping transaction {transaction.id}: already correct ({transaction.amount})'
                        )
                    )
                    skipped_count += 1
                
            except (ValueError, TypeError) as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error processing transaction {transaction.id}: {e}'
                    )
                )
        
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'DRY RUN: Would revert {fixed_count} transactions, skip {skipped_count}'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Reverted {fixed_count} transactions, skipped {skipped_count}'
                )
            ) 