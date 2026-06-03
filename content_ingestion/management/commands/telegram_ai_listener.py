import asyncio
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from content_ingestion.ai_client import AIClientError, complete_text
from content_ingestion.telegram_client import _entity_identifier, get_client

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run a Telethon listener that replies to /ai commands in configured Telegram chats.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--chat',
            action='append',
            default=[],
            help='Allowed Telegram chat ID/username. Repeat for multiple chats.',
        )
        parser.add_argument(
            '--command',
            default=getattr(settings, 'CONFIO_AI_TELEGRAM_COMMAND', '/ai'),
            help='Command prefix to listen for. Default: /ai',
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='Start, validate authorization, and exit without listening forever.',
        )

    def handle(self, *args, **options):
        try:
            asyncio.run(self._run(options))
        except KeyboardInterrupt:
            self.stdout.write('Telegram AI listener stopped.')
        except Exception as exc:
            raise CommandError(str(exc)) from exc

    async def _run(self, options):
        command = options['command'].strip()
        if not command.startswith('/'):
            raise CommandError('Command prefix must start with /')

        allowed_chats = options['chat'] or list(getattr(settings, 'CONFIO_AI_TELEGRAM_ALLOWED_CHATS', []))
        if not allowed_chats:
            raise CommandError('No allowed chats configured. Pass --chat -5283806378 or set CONFIO_AI_TELEGRAM_ALLOWED_CHATS.')

        client = get_client()
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise CommandError('Telegram session is not authorized.')

            from telethon import events

            allowed_chat_ids = {str(_entity_identifier(chat)) for chat in allowed_chats}

            @client.on(events.NewMessage)
            async def handler(event):
                event_chat_id = str(event.chat_id)
                if event_chat_id not in allowed_chat_ids:
                    return

                message = event.raw_text or ''
                if not _matches_command(message, command):
                    return

                prompt = message[len(command):].strip()
                if not prompt:
                    await event.reply(f'Usage: {command} your question')
                    return

                logger.info('Handling Telegram AI command in chat %s', event_chat_id)
                await event.reply('Thinking...')
                try:
                    answer = await asyncio.to_thread(complete_text, prompt)
                except AIClientError as exc:
                    answer = f'AI setup error: {exc}'
                except Exception:
                    logger.exception('Telegram AI command failed')
                    answer = 'AI command failed. Check server logs.'

                for chunk in _telegram_chunks(answer):
                    await event.reply(chunk)

            self.stdout.write(
                self.style.SUCCESS(
                    f'Listening for {command} in chats: {", ".join(str(chat) for chat in allowed_chats)}'
                )
            )
            if options['once']:
                return

            await client.run_until_disconnected()
        finally:
            await client.disconnect()


def _matches_command(message: str, command: str) -> bool:
    return message == command or message.startswith(command + ' ')


def _telegram_chunks(text: str, limit: int = 3900):
    text = text.strip() or '(empty response)'
    for start in range(0, len(text), limit):
        yield text[start:start + limit]
