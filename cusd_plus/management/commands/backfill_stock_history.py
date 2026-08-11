"""Repair account-history rows for already-confirmed Ondo stock trades."""

from django.core.management.base import BaseCommand, CommandError

from blockchain.models import SponsoredBatch
from cusd_plus.tasks import _rpc
from cusd_plus.unified import sync_unified_from_stock_batch


class Command(BaseCommand):
    help = 'Backfill exact event-backed account history for confirmed Ondo stock trades'

    def add_arguments(self, parser):
        parser.add_argument(
            '--check', action='store_true',
            help='Report missing rows without fetching receipts or writing',
        )

    def handle(self, *args, **options):
        missing = SponsoredBatch.objects.filter(
            kind__in=('stock_buy', 'stock_sell'),
            status='confirmed',
            unified_transaction__isnull=True,
        ).order_by('created_at')
        count = missing.count()
        if options['check']:
            if count:
                raise CommandError(f'{count} confirmed stock trades are missing history rows')
            self.stdout.write(self.style.SUCCESS('All confirmed stock trades have history rows'))
            return

        repaired = 0
        for batch in missing.iterator():
            receipt = _rpc('eth_getTransactionReceipt', [batch.tx_hash])
            if not receipt or receipt.get('status') != '0x1':
                raise CommandError(f'No successful receipt for stock batch {batch.id}')
            try:
                sync_unified_from_stock_batch(
                    batch, receipt, require_event=True, strict=True)
            except Exception as exc:
                raise CommandError(
                    f'Could not backfill stock batch {batch.id}: {exc}') from exc
            repaired += 1
        self.stdout.write(self.style.SUCCESS(f'Backfilled {repaired} stock history rows'))
