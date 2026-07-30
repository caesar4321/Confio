"""
Operate the Algorand→BSC presale migration-credit pipeline by hand.

Usage:
  manage.py presale_migration_credits sync
      Create pending rows for users with completed purchases + bsc_address.
  manage.py presale_migration_credits batch [--limit N]
      Queue pending rows and print the Safe transaction (to / data) for
      creditMigrated. Paste into the Safe Transaction Builder.
  manage.py presale_migration_credits batch --batch-id <id>
      Reprint an existing batch's calldata (idempotent).
  manage.py presale_migration_credits verify
      Read the vault back and mark executed batches as credited.
  manage.py presale_migration_credits status
      Pipeline overview.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Sync, batch, and verify Algorand→BSC presale migration credits"

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['sync', 'batch', 'verify', 'status'])
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--batch-id', default=None)

    def handle(self, *args, **options):
        from presale.tasks import (
            sync_presale_migration_credits,
            build_presale_credit_batch,
            verify_presale_migration_credits,
        )
        from presale.models import PresaleMigrationCredit

        action = options['action']

        if action == 'sync':
            res = sync_presale_migration_credits()
            self.stdout.write(self.style.SUCCESS(f"sync: {res}"))

        elif action == 'batch':
            try:
                res = build_presale_credit_batch(
                    limit=options['limit'], batch_id=options['batch_id']
                )
            except RuntimeError as e:
                raise CommandError(str(e))
            if not res.get('data'):
                self.stdout.write("No rows to batch.")
                return
            self.stdout.write(self.style.SUCCESS(
                f"Batch {res['batch_id']}: {res['count']} credits, {res['total_confio']} CONFIO"
            ))
            self.stdout.write("Safe transaction (Transaction Builder → custom data):")
            self.stdout.write(f"  to:    {res['to']}")
            self.stdout.write(f"  value: 0")
            self.stdout.write(f"  data:  {res['data']}")

        elif action == 'verify':
            res = verify_presale_migration_credits()
            self.stdout.write(self.style.SUCCESS(f"verify: {res}"))

        elif action == 'status':
            qs = PresaleMigrationCredit.objects.all()
            total = Decimal('0')
            for status in ('pending', 'queued', 'credited', 'failed'):
                rows = qs.filter(status=status)
                amount = sum((r.confio_amount for r in rows), Decimal('0'))
                if status != 'failed' or rows.exists():
                    self.stdout.write(f"{status:>9}: {rows.count():>5} rows  {amount} CONFIO")
                total += amount
            self.stdout.write(f"{'total':>9}: {qs.count():>5} rows  {total} CONFIO")
