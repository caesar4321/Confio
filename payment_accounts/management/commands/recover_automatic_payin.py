from django.core.management.base import BaseCommand, CommandError
from payment_accounts.models import LedgerEntry
from payment_accounts.auto_payin import enqueue, process


class Command(BaseCommand):
    help = 'Explicitly recover one historical Infinia pay-in. Dry-run unless --apply.'

    def add_arguments(self, parser):
        parser.add_argument('--provider-entry-id', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        try:
            entry = LedgerEntry.objects.select_related('financial_account__provider_profile').get(
                provider='infinia', provider_entry_id=options['provider_entry_id'])
        except LedgerEntry.DoesNotExist as exc:
            raise CommandError('Deposit not found') from exc
        self.stdout.write(f'{entry.provider_entry_id}: {entry.amount} {entry.asset}')
        if not options['apply']:
            self.stdout.write('Dry run. --apply authorizes automatic processing of this deposit only.')
            return
        row = enqueue(entry)
        if row is None:
            raise CommandError('Not an external fiat pay-in')
        row = process(row.pk)
        self.stdout.write(f'{row.status}: {row.reason}')
