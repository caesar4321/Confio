from django.core.management.base import BaseCommand, CommandError

from content_ingestion.canonical_promotion import process_pending_turns


class Command(BaseCommand):
    help = 'Review queued authoritative Telegram turns and promote durable canonical memory.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Extract and validate candidates without changing database state or Git.',
        )

    def handle(self, *args, **options):
        try:
            result = process_pending_turns(
                limit=options['limit'],
                dry_run=options['dry_run'],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f'Canonical promotion {result["status"]}: '
                f'{result["turns"]} turns, {result["candidates"]} candidates, '
                f'{result["promoted"]} promoted, {result["review"]} for review.'
            )
        )
        if result.get('commit'):
            self.stdout.write(f'Commit: {result["commit"]}')
        for path in result.get('paths') or []:
            self.stdout.write(f'Path: {path}')
