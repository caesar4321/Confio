import asyncio
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from content_ingestion.ai_client import (
    AIClientError,
    complete_text,
    debate,
    provider_label,
)
from content_ingestion.telegram_client import _entity_identifier, get_client

logger = logging.getLogger(__name__)

# Slash command -> canonical provider. Routes a single message to one model.
PROVIDER_COMMANDS = {
    '/chatgpt': 'openai',
    '/gpt': 'openai',
    '/claude': 'claude',
    '/grok': 'grok',
    '/gemini': 'gemini',
    '/deepseek': 'deepseek',
}
DEBATE_COMMAND = '/debate'

# How long to wait before reconnecting after a Telegram disconnect/error.
RECONNECT_DELAY_SECONDS = 5

# Ignore messages older than this when we receive them. Telegram replays history
# on connect / when the account is added to a group (via getDifference); those
# carry their original timestamps, so this stops us from answering the backlog.
MAX_MESSAGE_AGE_SECONDS = 60


class Command(BaseCommand):
    help = (
        'Run a Telethon listener that replies to every message in configured Telegram '
        'chats. Slash commands (/chatgpt, /claude, /grok, /gemini, /deepseek) route to a '
        'single model; /debate asks every configured model and synthesizes the discussion.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--chat',
            action='append',
            default=[],
            help='Restrict to this chat ID/username (repeatable). Default: all group chats the account is in.',
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
        allowed_chats = options['chat'] or list(getattr(settings, 'CONFIO_AI_TELEGRAM_ALLOWED_CHATS', []))

        from telethon import events
        from telethon.errors import AuthKeyDuplicatedError

        allowed_chat_ids = {str(_entity_identifier(chat)) for chat in allowed_chats}
        include_dms = getattr(settings, 'CONFIO_AI_TELEGRAM_INCLUDE_DMS', False)
        default_provider = getattr(settings, 'CONFIO_AI_PROVIDER', 'openai')

        client = get_client()

        @client.on(events.NewMessage(incoming=True))
        async def handler(event):
            if event.out:  # never react to our own messages
                return
            if not _chat_in_scope(event, allowed_chat_ids, include_dms):
                return
            if _is_stale(event):  # don't answer replayed history/backlog
                return

            message = (event.raw_text or '').strip()
            if not message:
                return

            # Don't get into bot-to-bot loops in the group.
            try:
                sender = await event.get_sender()
                if getattr(sender, 'bot', False):
                    return
            except Exception:
                pass

            command, prompt = _split_command(message)

            if command in PROVIDER_COMMANDS:
                provider = PROVIDER_COMMANDS[command]
                if not prompt:
                    await event.reply(f'Usage: {command} your question')
                    return
                await self._answer_single(event, prompt, provider)
            elif command == DEBATE_COMMAND:
                if not prompt:
                    await event.reply(f'Usage: {DEBATE_COMMAND} your question')
                    return
                await self._answer_debate(event, prompt)
            elif command is not None:
                # Unknown slash command (likely meant for another bot) — ignore.
                return
            else:
                # Ambient: reply to every human message with the default model.
                await self._answer_single(event, message, default_provider, announce=False)

        # Connect once up front so --once can validate, and so we fail fast on bad config.
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise CommandError('Telegram session is not authorized. Re-run telegram authentication.')

        if allowed_chat_ids:
            scope = 'chats: ' + ', '.join(str(chat) for chat in allowed_chats)
        else:
            scope = 'all group chats' + (' and DMs' if include_dms else '')
        logger.info(
            'Telegram AI listener active — replying in %s (default model: %s)',
            scope,
            provider_label(default_provider),
        )
        self.stdout.write(
            self.style.SUCCESS(f'Telegram AI listener active — replying in {scope}')
        )
        if options['once']:
            await client.disconnect()
            return

        # Self-healing loop: a Telegram disconnect should never take the process down.
        try:
            while True:
                try:
                    if not client.is_connected():
                        await client.connect()
                    if not await client.is_user_authorized():
                        raise CommandError('Telegram session is not authorized. Re-run telegram authentication.')
                    await client.run_until_disconnected()
                    logger.warning(
                        'Telegram client disconnected; reconnecting in %ss', RECONNECT_DELAY_SECONDS
                    )
                except CommandError:
                    raise
                except (KeyboardInterrupt, asyncio.CancelledError):
                    raise
                except AuthKeyDuplicatedError as exc:
                    # The session is being used elsewhere (e.g. a second listener). This is
                    # fatal — the session must be re-authorized — so surface it loudly.
                    raise CommandError(
                        'Telegram session is duplicated (used by another client). '
                        'Stop other listeners and re-authorize the session.'
                    ) from exc
                except Exception:
                    logger.exception(
                        'Telegram listener error; retrying in %ss', RECONNECT_DELAY_SECONDS
                    )
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)
        finally:
            await client.disconnect()

    async def _answer_single(self, event, prompt, provider, *, announce=True):
        prompt = await _with_reply_context(event, prompt)
        logger.info(
            'Telegram AI %s reply in chat %s', provider_label(provider), event.chat_id
        )
        try:
            answer = await asyncio.to_thread(complete_text, prompt, provider)
        except AIClientError as exc:
            answer = f'AI setup error: {exc}'
        except Exception:
            logger.exception('Telegram AI command failed')
            answer = 'AI command failed. Check server logs.'

        for chunk in _telegram_chunks(answer):
            await event.reply(chunk)

    async def _answer_debate(self, event, prompt):
        prompt = await _with_reply_context(event, prompt)
        logger.info('Telegram AI debate in chat %s', event.chat_id)
        await event.reply('Convening the panel…')
        try:
            answer = await asyncio.to_thread(debate, prompt)
        except AIClientError as exc:
            answer = f'AI setup error: {exc}'
        except Exception:
            logger.exception('Telegram AI debate failed')
            answer = 'AI debate failed. Check server logs.'

        for chunk in _telegram_chunks(answer):
            await event.reply(chunk)


def _is_stale(event):
    """True for backlog/history messages replayed by Telegram on connect or on join."""
    msg_date = getattr(getattr(event, 'message', None), 'date', None)
    if msg_date is None:
        return False
    return (datetime.now(timezone.utc) - msg_date).total_seconds() > MAX_MESSAGE_AGE_SECONDS


def _chat_in_scope(event, allowed_chat_ids, include_dms):
    """Decide whether to act on a message.

    With an explicit allowlist, only those chats. Otherwise every group chat the
    account belongs to (and DMs only when explicitly enabled). Broadcast channels
    are always ignored.
    """
    if allowed_chat_ids:
        return str(event.chat_id) in allowed_chat_ids
    if event.is_group:
        return True
    if include_dms and event.is_private:
        return True
    return False


def _split_command(message: str):
    """Return (command, rest). command is None when the message is not a slash command."""
    if not message.startswith('/'):
        return None, message
    parts = message.split(None, 1)
    command = parts[0].lower()
    if '@' in command:  # e.g. /claude@SomeBot
        command = command.split('@', 1)[0]
    rest = parts[1].strip() if len(parts) > 1 else ''
    return command, rest


async def _with_reply_context(event, prompt: str) -> str:
    """If the message replies to another message, prepend that text as context."""
    if not getattr(event, 'is_reply', False):
        return prompt
    try:
        replied = await event.get_reply_message()
    except Exception:
        return prompt
    context = (getattr(replied, 'raw_text', '') or '').strip()
    if not context:
        return prompt
    return f'Context (the message being replied to):\n{context}\n\nMessage:\n{prompt}'


def _telegram_chunks(text: str, limit: int = 3900):
    text = text.strip() or '(empty response)'
    for start in range(0, len(text), limit):
        yield text[start:start + limit]
