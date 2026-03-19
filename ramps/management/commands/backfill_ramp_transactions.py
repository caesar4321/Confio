from django.core.management.base import BaseCommand

from ramps.signals import sync_ramp_transaction_from_guardarian, sync_unified_transaction_from_ramp
from usdc_transactions.models import GuardarianTransaction


class Command(BaseCommand):
    help = 'Backfill RampTransaction and unified activity rows from existing Guardarian transactions'

    def handle(self, *args, **options):
        total = 0
        for guardarian_tx in GuardarianTransaction.objects.all().order_by('created_at'):
            ramp_tx = sync_ramp_transaction_from_guardarian(guardarian_tx)
            sync_unified_transaction_from_ramp(ramp_tx)
            total += 1

        self.stdout.write(self.style.SUCCESS(f'Backfilled {total} ramp transactions'))
