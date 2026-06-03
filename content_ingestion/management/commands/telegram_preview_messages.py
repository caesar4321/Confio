import asyncio

from django.core.management.base import BaseCommand, CommandError

from content_ingestion.telegram_client import _entity_identifier, get_client


class Command(BaseCommand):
    help = 'Preview recent Telegram messages without writing to the database.'

    def add_arguments(self, parser):
        parser.add_argument('chat_identifier')
        parser.add_argument('--limit', type=int, default=10)

    def handle(self, *args, **options):
        try:
            asyncio.run(self._preview(options['chat_identifier'], options['limit']))
        except Exception as exc:
            raise CommandError(str(exc)) from exc

    async def _preview(self, chat_identifier, limit):
        client = get_client()
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise CommandError('Telegram session is not authorized.')

            entity = await client.get_entity(_entity_identifier(chat_identifier))
            async for message in client.iter_messages(entity, limit=limit):
                file = getattr(message, 'file', None)
                file_name = getattr(file, 'name', '') or ''
                mime_type = getattr(file, 'mime_type', '') or ''
                media = 'media' if message.media else 'text'
                text = (message.text or '').replace('\n', ' ')[:120]
                self.stdout.write(
                    '\t'.join(
                        [
                            str(message.id),
                            str(message.date),
                            media,
                            mime_type,
                            file_name,
                            text,
                        ]
                    )
                )
        finally:
            await client.disconnect()
