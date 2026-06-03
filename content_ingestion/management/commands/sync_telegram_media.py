import asyncio

from django.core.management.base import BaseCommand, CommandError

from content_ingestion.telegram_client import TelegramIngestionError, sync_chat_media


class Command(BaseCommand):
    help = 'Sync media metadata from a Telegram chat via Telethon.'

    def add_arguments(self, parser):
        parser.add_argument('chat_identifier')
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--download', action='store_true', help='Download media files locally.')

    def handle(self, *args, **options):
        try:
            result = asyncio.run(
                sync_chat_media(
                    options['chat_identifier'],
                    limit=options['limit'],
                    download=options['download'],
                )
            )
        except TelegramIngestionError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(str(result)))

