from django.core.management.base import BaseCommand

from inbox.portfolio_returns import BACKFILL_DAYS, sync_all


class Command(BaseCommand):
    help = ('Rebuild the last N days of investment-sleeve returns per wallet from the trade ledger and '
            'daily closes. Idempotent: a re-run changes no day that is already proven.')

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=BACKFILL_DAYS)
        parser.add_argument('--wallet', default='', help='Only this BSC wallet (0x...).')
        parser.add_argument('--recompute', action='store_true',
                            help='Recompute proven days too (after a price fix).')
        parser.add_argument('--budget-minutes', type=float, default=24 * 60)

    def handle(self, *args, **options):
        totals = sync_all(budget_seconds=options['budget_minutes'] * 60, days=options['days'],
                          recompute=options['recompute'], wallet=options['wallet'], log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(str(totals)))
