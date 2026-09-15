from django.core.management.base import BaseCommand
from payment_accounts.models import InfiniaJourney
from payment_accounts.activity import sync_activity


class Command(BaseCommand):
    help = 'Rebuild local-transfer activity and correct linked raw entries. No fund movement.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--journey')

    def handle(self, *args, **options):
        rows = InfiniaJourney.objects.all()
        if options['journey']:
            rows = rows.filter(internal_id=options['journey'])
        self.stdout.write(f'{rows.count()} journeys; ' + ('applying' if options['apply'] else 'dry run (use --apply)'))
        if options['apply']:
            for pk in rows.values_list('pk', flat=True).iterator():
                sync_activity(pk, notify=False)
