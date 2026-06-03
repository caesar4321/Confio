import asyncio

from django.core.management.base import BaseCommand, CommandError

from content_ingestion.telegram_client import get_client


class Command(BaseCommand):
    help = 'List Telegram dialogs visible to the configured Telethon session.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50)

    def handle(self, *args, **options):
        try:
            asyncio.run(self._list_dialogs(options['limit']))
        except Exception as exc:
            raise CommandError(str(exc)) from exc

    async def _list_dialogs(self, limit):
        client = get_client()
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise CommandError('Telegram session is not authorized.')

            async for dialog in client.iter_dialogs(limit=limit):
                entity = dialog.entity
                username = getattr(entity, 'username', '') or ''
                self.stdout.write(
                    '\t'.join(
                        [
                            str(dialog.id),
                            dialog.name or '',
                            f'@{username}' if username else '',
                            type(entity).__name__,
                        ]
                    )
                )
        finally:
            await client.disconnect()
