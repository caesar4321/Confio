import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from content_ingestion.ai_client import (
    AIClientError,
    debate,
    complete_with_images,
    complete_with_youtube_video,
    extract_youtube_urls,
    provider_label,
)
from content_ingestion.ai_agent import run_with_tools
from content_ingestion.ai_context import build_system_prompt, search_knowledge
from content_ingestion import conversation_log
from content_ingestion.context_repo import ContextRepoError, write_commit_and_push_context
from content_ingestion.models import AIContextCategory, AIContextDocument
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
WHOAMI_COMMAND = '/whoami'

# How long to wait before reconnecting after a Telegram disconnect/error.
RECONNECT_DELAY_SECONDS = 5

# Ignore messages older than this when we receive them. Telegram replays history
# on connect / when the account is added to a group (via getDifference); those
# carry their original timestamps, so this stops us from answering the backlog.
MAX_MESSAGE_AGE_SECONDS = 60
MAX_IMAGE_BYTES = 12 * 1024 * 1024


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
            close_old_connections()
            try:
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
                    await self._answer(event, client, prompt, provider)
                elif command == DEBATE_COMMAND:
                    if not prompt:
                        await event.reply(f'Usage: {DEBATE_COMMAND} your question')
                        return
                    await event.reply('Convening the panel…')
                    await self._answer(event, client, prompt, default_provider, debate_mode=True)
                elif command == WHOAMI_COMMAND:
                    await event.reply(_whoami_response(sender, getattr(event, 'sender_id', None)))
                elif command is not None:
                    # Unknown slash command (likely meant for another bot) — ignore.
                    return
                else:
                    # Ambient: reply to every human message with the default model.
                    await self._answer(event, client, message, default_provider)
            finally:
                close_old_connections()

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

        # Background task: commit + push conversation logs to ConfioAI on a timer.
        flush_task = asyncio.create_task(self._flush_loop())

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
            flush_task.cancel()
            try:
                await flush_task
            except asyncio.CancelledError:
                pass
            await client.disconnect()

    async def _answer(self, event, client, prompt, provider, *, debate_mode=False):
        sender = None
        try:
            sender = await event.get_sender()
        except Exception:
            pass
        sender_id = getattr(event, 'sender_id', None)
        sender_name = _display_name(sender, sender_id)
        authority = _sender_authority(sender, sender_id)
        history = await _build_history(client, event)
        reply_to = await _reply_target(event)
        user_prompt = _compose_prompt(prompt, history, reply_to, sender_name=sender_name, authority=authority)
        system = build_system_prompt()
        logger.info(
            'Telegram AI %s reply in chat %s',
            'debate' if debate_mode else provider_label(provider),
            event.chat_id,
        )
        try:
            youtube_urls = extract_youtube_urls(user_prompt)
            memory_write_request = _is_memory_write_request(user_prompt)
            if youtube_urls and not debate_mode and not memory_write_request:
                logger.info('Routing YouTube video analysis to Gemini: %s', youtube_urls[:3])
                answer = await asyncio.to_thread(
                    complete_with_youtube_video, user_prompt, system=system
                )
            elif not debate_mode:
                if youtube_urls and memory_write_request:
                    logger.info(
                        'Analyzing YouTube video before memory write: %s',
                        youtube_urls[:3],
                    )
                    user_prompt = await self._prompt_with_youtube_analysis(user_prompt, system)
                images = await _collect_image_inputs(client, event)
                if images and not memory_write_request:
                    logger.info('Routing %s Telegram image(s) to Gemini vision', len(images))
                    answer = await asyncio.to_thread(
                        complete_with_images, user_prompt, images, system=system
                    )
                else:
                    loop = asyncio.get_running_loop()
                    tools = _build_tools(client, event, loop, authority=authority)
                    answer = await asyncio.to_thread(
                        run_with_tools, user_prompt, provider, system, tools
                    )
            elif debate_mode:
                answer = await asyncio.to_thread(debate, user_prompt, system=system)
        except AIClientError as exc:
            answer = f'AI setup error: {exc}'
        except Exception:
            logger.exception('Telegram AI command failed')
            answer = 'AI command failed. Check server logs.'

        for chunk in _telegram_chunks(answer):
            await event.reply(chunk)

        await asyncio.to_thread(
            conversation_log.append_turn,
            event.chat_id, sender_name, event.raw_text or prompt, answer,
        )

    async def _prompt_with_youtube_analysis(self, user_prompt: str, system: str) -> str:
        analysis_prompt = (
            f'{user_prompt}\n\n'
            'Analiza el/los video(s) público(s) de YouTube reales incluidos arriba. '
            'No te limites al texto del usuario. Extrae detalles visuales, auditivos, '
            'estructura narrativa, hook, ritmo, escena, tono, CTA, y cualquier dato '
            'observable útil para una memoria de video. Si el usuario incluyó script, '
            'compáralo con el video real.'
        )
        try:
            analysis = await asyncio.to_thread(
                complete_with_youtube_video, analysis_prompt, system=system
            )
        except AIClientError as exc:
            analysis = (
                'No se pudo completar el análisis visual/auditivo de YouTube antes '
                f'de escribir memoria: {exc}'
            )
        return _with_youtube_analysis(user_prompt, analysis)

    async def _flush_loop(self):
        """Periodically commit + push buffered conversation logs to ConfioAI."""
        interval = getattr(settings, 'CONFIO_AI_LOG_FLUSH_SECONDS', 180)
        while True:
            await asyncio.sleep(interval)
            try:
                close_old_connections()
                result = await asyncio.to_thread(conversation_log.commit_and_push)
                if result not in ('no changes', 'skipped (git busy)', 'disabled', None):
                    logger.info('Conversation log: %s', result)
            except Exception:
                logger.exception('Conversation log flush failed')
            finally:
                close_old_connections()


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


def _is_memory_write_request(text: str) -> bool:
    value = (text or '').lower()
    return any(
        term in value
        for term in (
            'push',
            'pushear',
            'pushed',
            'commit',
            'git',
            'github',
            'guardar',
            'guarda',
            'guardalo',
            'guárdalo',
            'registrar',
            'registra',
            'archivar',
            'archiva',
            'memoria',
            'memory',
            'revise',
            'revisar',
            'actualizar',
            'actualiza',
            'update',
            'docs',
            'documento',
        )
    )


def _with_youtube_analysis(user_prompt: str, analysis: str) -> str:
    return (
        f'{user_prompt}\n\n'
        '## Análisis real del video de YouTube vía Gemini\n'
        f'{analysis.strip() if analysis else "(sin análisis devuelto)"}\n\n'
        'Instrucción obligatoria: si escribes o actualizas una memoria de video, '
        'incorpora el análisis real anterior. No escribas una memoria basada solo '
        'en los links o en campos sueltos proporcionados por el usuario.'
    )


def _build_tools(client, event, loop, *, authority='client'):
    """Build the tool callables the model can invoke, bound to this chat.

    The completion runs in a worker thread, but Telethon lives on the main event
    loop, so chat-data tools hop back via run_coroutine_threadsafe.
    """
    chat_id = event.chat_id

    def get_chat_files(args=''):
        """Lista los archivos/documentos del chat (nombre, tamaño, caption). Aquí están los videos ORIGINALES, que se guardan como archivos. Sin argumentos."""
        return asyncio.run_coroutine_threadsafe(
            _fetch_chat_files(client, chat_id), loop
        ).result(timeout=45)

    def get_chat_videos(args=''):
        """Lista los videos enviados como video de Telegram (normalmente solo clips de prueba; los originales están en archivos, usa get_chat_files). Sin argumentos."""
        return asyncio.run_coroutine_threadsafe(
            _fetch_chat_videos(client, chat_id), loop
        ).result(timeout=45)

    def search_chat_history(args=''):
        """Busca mensajes antiguos de este chat por palabra clave. Argumento: la consulta."""
        return asyncio.run_coroutine_threadsafe(
            _search_chat_history(client, chat_id, args), loop
        ).result(timeout=45)

    def knowledge_search(args=''):
        """Busca en la base de conocimiento de Confío. Argumento: la consulta."""
        return search_knowledge(args)

    def write_memory(args=''):
        """Crea/actualiza memoria curada en ConfioAI y hace commit+push. Formato: primera línea 'category: <videos|strategy|decision-log|meeting-notes|weekly-reports|social-stats|legal|user-reports|other>'; segunda línea 'title: <título>'; opcional 'folder: <subcarpeta>'; resto: markdown completo."""
        return _write_memory_tool(args)

    def write_video_memory(args=''):
        """Crea una memoria de video en docs/videos y hace commit+push. Formato: opcional 'folder: Vida y filosofía'; línea 'title: <título del video>'; resto: markdown completo incluyendo links, stats, análisis y script."""
        return _write_memory_tool(f'category: videos\ntitle: {_first_title(args)}\n{_strip_title_line(args)}')

    tools = {
        'get_chat_files': get_chat_files,
        'get_chat_videos': get_chat_videos,
        'search_chat_history': search_chat_history,
        'search_knowledge': knowledge_search,
    }
    if authority in {'owner', 'trusted'}:
        tools['write_memory'] = write_memory
        tools['write_video_memory'] = write_video_memory
    return tools


def _write_memory_tool(args: str) -> str:
    parsed = _parse_memory_tool_args(args)
    if not parsed['body'].strip():
        return 'No escribí nada: falta el cuerpo markdown.'
    try:
        close_old_connections()
        metadata = {'source': 'telegram_ai_tool'}
        if parsed.get('folder'):
            metadata['folder'] = parsed['folder']
        document = AIContextDocument.objects.create(
            category=parsed['category'],
            title=parsed['title'],
            slug='',
            body=parsed['body'],
            metadata=metadata,
        )
        document = write_commit_and_push_context(document, push=True)
    except (ContextRepoError, OSError) as exc:
        logger.exception('write_memory tool failed')
        return f'No pude escribir/pushear la memoria: {exc}'
    except Exception as exc:  # noqa: BLE001
        logger.exception('write_memory unexpected failure')
        return f'No pude escribir/pushear la memoria por un error inesperado: {exc}'
    finally:
        close_old_connections()
    return (
        'Memoria escrita y pusheada.\n'
        f'- Archivo: {document.relative_path}\n'
        f'- Commit: {document.commit_sha[:12] if document.commit_sha else "(sin commit)"}\n'
        f'- Status: {document.status}'
    )


def _parse_memory_tool_args(args: str) -> dict:
    lines = (args or '').strip().splitlines()
    category = AIContextCategory.OTHER
    title = 'Untitled memory'
    folder = ''
    body_start = 0
    for idx, line in enumerate(lines[:5]):
        key, sep, value = line.partition(':')
        if not sep:
            continue
        normalized = key.strip().lower()
        if normalized == 'category':
            category = value.strip()
            body_start = max(body_start, idx + 1)
        elif normalized == 'title':
            title = value.strip() or title
            body_start = max(body_start, idx + 1)
        elif normalized == 'folder':
            folder = value.strip()
            body_start = max(body_start, idx + 1)
    if category not in AIContextCategory.values:
        allowed = ', '.join(AIContextCategory.values)
        raise ContextRepoError(f'Categoría inválida: {category}. Usa una de: {allowed}')
    if category == AIContextCategory.VIDEOS and not folder and '/' in title:
        maybe_folder, maybe_title = re.split(r'\s*/\s*', title, maxsplit=1)
        if maybe_folder.strip() and maybe_title.strip():
            folder = maybe_folder.strip()
            title = maybe_title.strip()
    body = '\n'.join(lines[body_start:]).strip()
    return {'category': category, 'title': title, 'folder': folder, 'body': body}


def _first_title(text: str) -> str:
    for line in (text or '').splitlines()[:5]:
        key, sep, value = line.partition(':')
        if sep and key.strip().lower() == 'title':
            return value.strip() or 'Untitled video memory'
    return 'Untitled video memory'


def _strip_title_line(text: str) -> str:
    lines = (text or '').strip().splitlines()
    if lines:
        key, sep, _ = lines[0].partition(':')
        if sep and key.strip().lower() == 'title':
            return '\n'.join(lines[1:]).strip()
    return text or ''


def _human_size(num) -> str:
    if not num:
        return ''
    value = float(num)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(value) < 1024 or unit == 'TB':
            return f'{value:.0f}{unit}' if unit == 'B' else f'{value:.1f}{unit}'
        value /= 1024
    return f'{value:.1f}TB'


async def _fetch_chat_files(client, chat_id, limit=80) -> str:
    from telethon.tl.types import InputMessagesFilterDocument

    items = []
    try:
        async for m in client.iter_messages(chat_id, limit=limit, filter=InputMessagesFilterDocument):
            file = getattr(m, 'file', None)
            name = getattr(file, 'name', None) if file else None
            size = getattr(file, 'size', None) if file else None
            caption = (getattr(m, 'message', '') or '').strip()
            date = m.date.date().isoformat() if getattr(m, 'date', None) else '?'
            bits = [f'- {date}: {name or caption or "(sin nombre)"}']
            human = _human_size(size)
            if human:
                bits.append(human)
            if caption and name:
                bits.append(f'“{caption[:120]}”')
            items.append(' · '.join(bits))
    except Exception as exc:  # noqa: BLE001
        logger.exception('get_chat_files failed for %s', chat_id)
        return f'(no pude listar los archivos: {exc})'
    if not items:
        return 'No encontré archivos en este chat.'
    return f'Archivos en este chat ({len(items)}):\n' + '\n'.join(items)


async def _fetch_chat_videos(client, chat_id, limit=80) -> str:
    from telethon.tl.types import InputMessagesFilterVideo

    items = []
    try:
        async for m in client.iter_messages(chat_id, limit=limit, filter=InputMessagesFilterVideo):
            caption = (getattr(m, 'message', '') or '').strip()
            file = getattr(m, 'file', None)
            name = getattr(file, 'name', None) if file else None
            duration = getattr(file, 'duration', None) if file else None
            date = m.date.date().isoformat() if getattr(m, 'date', None) else '?'
            title = caption or name or '(sin título ni caption)'
            extra = f' · {int(duration)}s' if duration else ''
            items.append(f'- {date}: {title}{extra}')
    except Exception as exc:  # noqa: BLE001
        logger.exception('get_chat_videos failed for %s', chat_id)
        return f'(no pude listar los videos: {exc})'
    if not items:
        return 'No encontré videos en este chat.'
    return f'Videos en este chat ({len(items)}):\n' + '\n'.join(items)


async def _search_chat_history(client, chat_id, query, limit=15) -> str:
    query = (query or '').strip()
    if not query:
        return 'Falta la consulta de búsqueda.'
    items = []
    try:
        async for m in client.iter_messages(chat_id, limit=limit, search=query):
            text = (getattr(m, 'message', '') or '').strip()
            if not text:
                continue
            who = _display_name(getattr(m, 'sender', None), getattr(m, 'sender_id', None))
            date = m.date.date().isoformat() if getattr(m, 'date', None) else '?'
            items.append(f'- [{date}] {who}: {text[:200]}')
    except Exception as exc:  # noqa: BLE001
        logger.exception('search_chat_history failed for %s', chat_id)
        return f'(no pude buscar en el historial: {exc})'
    return '\n'.join(items) if items else 'Sin resultados para esa búsqueda.'


async def _build_history(client, event) -> str:
    """Fetch this chat's recent messages as a transcript (oldest first), annotating
    media so the model can see videos/files shared in the room."""
    limit = getattr(settings, 'CONFIO_AI_HISTORY_LIMIT', 25)
    max_chars = getattr(settings, 'CONFIO_AI_HISTORY_MAX_CHARS', 6000)
    try:
        messages = await client.get_messages(event.chat_id, limit=limit)
    except Exception:
        logger.warning('Could not fetch chat history for %s', event.chat_id, exc_info=True)
        return ''
    lines = []
    for m in reversed(list(messages)):  # oldest -> newest
        if getattr(m, 'out', False):
            who = 'Confío AI'
        else:
            who = _display_name(getattr(m, 'sender', None), getattr(m, 'sender_id', None))
        text = (getattr(m, 'message', '') or '').strip()
        media = _media_label(m)
        body = f'{text} {media}'.strip() if (text and media) else (text or media)
        if not body:
            continue
        lines.append(f'{who}: {body}')
    transcript = '\n'.join(lines)
    if len(transcript) > max_chars:
        transcript = transcript[-max_chars:]
    return transcript


async def _reply_target(event) -> str:
    """The text of the message this one is replying to, if any."""
    if not getattr(event, 'is_reply', False):
        return ''
    try:
        replied = await event.get_reply_message()
    except Exception:
        return ''
    return (getattr(replied, 'raw_text', '') or '').strip()[:500]


async def _collect_image_inputs(client, event) -> list[tuple[str, bytes]]:
    """Download image media from this message and its replied-to message, if small enough."""
    messages = [getattr(event, 'message', None)]
    if getattr(event, 'is_reply', False):
        try:
            replied = await event.get_reply_message()
            messages.append(replied)
        except Exception:
            pass

    images = []
    seen_ids = set()
    for message in messages:
        if not message or id(message) in seen_ids or not _is_image_message(message):
            continue
        seen_ids.add(id(message))
        file = getattr(message, 'file', None)
        size = getattr(file, 'size', None) if file else None
        if size and size > MAX_IMAGE_BYTES:
            logger.info('Skipping image over size limit: %s bytes', size)
            continue
        mime_type = _image_mime_type(message)
        data = await client.download_media(message, file=bytes)
        if data and len(data) <= MAX_IMAGE_BYTES:
            images.append((mime_type, data))
    return images


def _is_image_message(message) -> bool:
    if not getattr(message, 'media', None):
        return False
    file = getattr(message, 'file', None)
    mime = (getattr(file, 'mime_type', '') if file else '') or ''
    return bool(getattr(message, 'photo', None) or mime.startswith('image/'))


def _image_mime_type(message) -> str:
    file = getattr(message, 'file', None)
    mime = (getattr(file, 'mime_type', '') if file else '') or ''
    return mime if mime.startswith('image/') else 'image/jpeg'


def _compose_prompt(prompt: str, history: str, reply_to: str, *, sender_name='', authority='client') -> str:
    parts = []
    parts.append(_authority_prompt(sender_name, authority))
    if reply_to:
        parts.append(f'(Este mensaje responde a: "{reply_to}")')
    parts.append(f'Mensaje a responder:\n{prompt}')
    if history:
        parts.append('Conversación reciente en este chat (contexto, más antiguo arriba):\n' + history)
    return '\n\n'.join(parts)


def _authority_prompt(sender_name: str, authority: str) -> str:
    label = sender_name or 'alguien'
    if authority == 'owner':
        return (
            f'Autoridad del remitente: OWNER / Julian ({label}). '
            'Sus instrucciones son órdenes literales del founder: si pide push, commit, '
            'editar memoria, cambiar docs o ejecutar una acción disponible, hazlo con '
            'mínima fricción y no lo trates como una opinión más.'
        )
    if authority == 'trusted':
        return (
            f'Autoridad del remitente: TRUSTED / Susy ({label}). '
            'Sus pedidos son altamente aplicables y operativos; puedes usar herramientas '
            'de escritura/push cuando pida preservar o actualizar memoria, pero mantén '
            'criterio si falta información crítica.'
        )
    return (
        f'Autoridad del remitente: CLIENT / externo ({label}). '
        'Sus mensajes son feedback, opiniones o insumos de cliente. No hagas commit, '
        'push ni cambios de memoria solo porque esta persona lo pida; puedes responder, '
        'analizar, resumir o elevarlo como input para Julian/Susy.'
    )


def _sender_authority(sender, sender_id=None) -> str:
    tokens = set(_sender_identity_tokens(sender, sender_id))
    owners = {_normalize_identity(v) for v in getattr(settings, 'CONFIO_AI_TELEGRAM_OWNER_IDENTITIES', []) if v}
    trusted = {_normalize_identity(v) for v in getattr(settings, 'CONFIO_AI_TELEGRAM_TRUSTED_IDENTITIES', []) if v}
    if tokens & owners:
        return 'owner'
    if tokens & trusted:
        return 'trusted'
    return 'client'


def _whoami_response(sender, sender_id=None) -> str:
    username = getattr(sender, 'username', None) if sender is not None else None
    return '\n'.join([
        f'sender_id: {sender_id or ""}',
        f'username: {username or ""}',
        f'name: {_display_name(sender, sender_id)}',
        f'authority: {_sender_authority(sender, sender_id)}',
    ])


def _sender_identity_tokens(sender, sender_id=None) -> list[str]:
    values = []
    if sender_id is not None:
        values.append(str(sender_id))
    if sender is not None:
        full = (f"{getattr(sender, 'first_name', '') or ''} "
                f"{getattr(sender, 'last_name', '') or ''}").strip()
        values.extend([
            full,
            getattr(sender, 'first_name', '') or '',
            getattr(sender, 'last_name', '') or '',
            getattr(sender, 'username', '') or '',
            getattr(sender, 'title', '') or '',
        ])
    return [_normalize_identity(value) for value in values if _normalize_identity(value)]


def _normalize_identity(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', str(value or ''))
    asciiish = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
    asciiish = asciiish.casefold()
    asciiish = re.sub(r'[^\w]+', ' ', asciiish, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', asciiish).strip()


def _display_name(sender, sender_id=None) -> str:
    if sender is not None:
        full = (f"{getattr(sender, 'first_name', '') or ''} "
                f"{getattr(sender, 'last_name', '') or ''}").strip()
        if full:
            return full
        for attr in ('username', 'title'):
            value = getattr(sender, attr, None)
            if value:
                return value
    return f'usuario {sender_id}' if sender_id else 'alguien'


def _media_label(m) -> str:
    if not getattr(m, 'media', None):
        return ''
    file = getattr(m, 'file', None)
    name = getattr(file, 'name', None) if file else None
    mime = (getattr(file, 'mime_type', '') if file else '') or ''
    if getattr(m, 'video', None) or getattr(m, 'video_note', None) or 'video' in mime:
        return f'[video: {name}]' if name else '[video]'
    if getattr(m, 'photo', None) or 'image' in mime:
        return '[imagen]'
    if getattr(m, 'voice', None) or getattr(m, 'audio', None) or 'audio' in mime:
        return '[audio]'
    return f'[archivo: {name}]' if name else '[archivo]'


def _telegram_chunks(text: str, limit: int = 3900):
    text = text.strip() or '(empty response)'
    for start in range(0, len(text), limit):
        yield text[start:start + limit]
