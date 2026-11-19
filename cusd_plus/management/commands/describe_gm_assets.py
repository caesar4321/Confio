"""Write descriptions for listed Ondo assets that have none (see
cusd_plus/gm_profiles.py). The daily task does the same with a cap; this
runs it by hand, e.g. to backfill or to preview with --dry-run."""
from django.core.management.base import BaseCommand

from cusd_plus.gm_profiles import describe_new_assets, missing_listed


class Command(BaseCommand):
    help = 'Describe listed Ondo GM assets that have no description yet'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=40)
        parser.add_argument('--dry-run', action='store_true', help='Generate and log, write nothing')
        parser.add_argument('--list', action='store_true', help='Only list what is missing')

    def handle(self, *args, **options):
        if options['list']:
            missing = missing_listed()
            for ticker, name in missing:
                self.stdout.write(f'{ticker}\t{name}')
            self.stdout.write(f'{len(missing)} missing')
            return
        result = describe_new_assets(limit=options['limit'], dry_run=options['dry_run'])
        self.stdout.write(f"missing {result['missing']}, written {len(result['written'])}, failed {result['failed']}")
