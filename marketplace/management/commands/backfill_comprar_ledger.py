"""Write history/Tu mes rows for Comprar orders mirrored before the ledger
existed. Idempotent: rows are keyed per order and leg."""
from django.core.management.base import BaseCommand

from marketplace.ledger import sync_locked
from marketplace.models import Order


class Command(BaseCommand):
    help = 'Backfill unified ledger rows for funded/settled Comprar orders'

    def handle(self, *args, **options):
        pks = Order.objects.filter(
            status__in=('funded', 'shipped', 'disputed', 'released', 'refunded')
        ).values_list('pk', flat=True)
        count = 0
        for pk in list(pks):
            sync_locked(pk)
            count += 1
        self.stdout.write(f'synced {count} orders')
