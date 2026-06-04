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
    complete_with_video_files,
    complete_with_youtube_video,
    extract_youtube_urls,
    provider_label,
)
from content_ingestion.ai_agent import run_with_tools
from content_ingestion.ai_context import build_media_system_prompt, build_system_prompt, search_knowledge
from content_ingestion import conversation_log
from content_ingestion.context_repo import (
    ContextRepoError,
    list_memory_documents,
    list_video_memories,
    read_context_documents,
    revise_context_documents,
    write_commit_and_push_context,
)
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
# Memory writes to ConfioAI (git) ONLY happen via these explicit commands. Without
# one, the bot just analyzes/answers and never commits anything.
MEMORY_COMMANDS = {'/memory', '/save', '/recordar', '/guardar', '/savevideo'}

# How long to wait before reconnecting after a Telegram disconnect/error.
RECONNECT_DELAY_SECONDS = 5

# Ignore messages older than this when we receive them. Telegram replays history
# on connect / when the account is added to a group (via getDifference); those
# carry their original timestamps, so this stops us from answering the backlog.
MAX_MESSAGE_AGE_SECONDS = 60
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_VIDEO_BYTES = getattr(settings, 'CONFIO_AI_MAX_TELEGRAM_VIDEO_BYTES', 120 * 1024 * 1024)
ANSWER_TIMEOUT_SECONDS = getattr(settings, 'CONFIO_AI_TELEGRAM_ANSWER_TIMEOUT_SECONDS', 180)


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
                if not message and not getattr(getattr(event, 'message', None), 'media', None):
                    return

                # Don't get into bot-to-bot loops in the group.
                try:
                    sender = await event.get_sender()
                    if getattr(sender, 'bot', False):
                        return
                except Exception:
                    pass

                command, prompt = _split_command(message) if message else (None, _media_only_prompt(event.message))

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
                elif command in MEMORY_COMMANDS:
                    has_media = bool(getattr(getattr(event, 'message', None), 'media', None))
                    if not prompt and not has_media:
                        await event.reply(
                            f'Usage: {command} <qué guardar> — envíalo como caption del video, '
                            'o describe la memoria (incluye la carpeta, p. ej. "Vida y filosofía").'
                        )
                        return
                    await self._answer(
                        event, client, prompt or _media_only_prompt(event.message),
                        default_provider, explicit_memory=True,
                    )
                elif command is not None:
                    # Unknown slash command (likely meant for another bot) — ignore.
                    return
                else:
                    # Ambient: reply to every human message with the default model.
                    # No explicit_memory -> the bot analyzes/answers but never writes to git.
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

    async def _answer(self, event, client, prompt, provider, *, debate_mode=False, explicit_memory=False):
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
            answer = await asyncio.wait_for(
                self._generate_answer(
                    event, client, user_prompt, provider, system, authority, debate_mode,
                    explicit_memory=explicit_memory,
                ),
                timeout=ANSWER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning('Telegram AI answer timed out after %ss in chat %s', ANSWER_TIMEOUT_SECONDS, event.chat_id)
            answer = (
                'Esta operación tardó demasiado para un solo turno de Telegram. '
                'Divide el pedido en lotes más pequeños, por ejemplo un video o 2-3 docs por vez.'
            )
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

    async def _generate_answer(self, event, client, user_prompt, provider, system, authority, debate_mode, explicit_memory=False):
        youtube_urls = extract_youtube_urls(user_prompt)
        # Direct Gemini media analysis (video/image/YouTube) must NOT receive tool
        # instructions — these are generateContent calls with no function declarations, so
        # tool-talk makes Gemini emit MALFORMED_FUNCTION_CALL. Use a tool-free system prompt.
        media_system = build_media_system_prompt()
        # Write turn = explicit /memory command OR a clearly-worded save/push/update intent
        # (precise detection, not loose keywords). Even then, the system prompt + the model
        # are the final gate on whether to actually call a write tool — casual chat never
        # auto-commits.
        memory_write_request = explicit_memory or _is_memory_write_request(user_prompt)
        existing_doc_revision = memory_write_request and _is_existing_doc_revision_request(user_prompt)
        if youtube_urls and not debate_mode and not memory_write_request:
            logger.info('Routing YouTube video analysis to Gemini: %s', youtube_urls[:3])
            return await asyncio.to_thread(
                complete_with_youtube_video, user_prompt, system=media_system
            )
        if not debate_mode:
            if youtube_urls and memory_write_request:
                logger.info(
                    'Analyzing YouTube video before memory write: %s',
                    youtube_urls[:3],
                )
                user_prompt = await self._prompt_with_youtube_analysis(user_prompt, media_system)
            images = await _collect_image_inputs(client, event)
            videos = await _collect_video_inputs(client, event)
            if videos and memory_write_request:
                logger.info('Analyzing %s Telegram video(s) before memory write', len(videos))
                user_prompt = await self._prompt_with_telegram_video_analysis(user_prompt, videos, media_system)
                videos = []
            if images and not memory_write_request:
                logger.info('Routing %s Telegram image(s) to Gemini vision', len(images))
                return await asyncio.to_thread(
                    complete_with_images, user_prompt, images, system=media_system
                )
            if videos:
                logger.info('Routing %s Telegram video(s) to Gemini video analysis', len(videos))
                return await asyncio.to_thread(
                    complete_with_video_files, user_prompt, videos, system=media_system
                )
            loop = asyncio.get_running_loop()
            tools = _build_tools(
                client,
                event,
                loop,
                authority=authority,
                allow_writes=memory_write_request,
                allow_new_memory=not existing_doc_revision,
            )
            # Memory writes need a backend that handles large function args reliably
            # (Gemini Flash malforms/truncates them); read-only chat stays on the default.
            write_backend = (
                getattr(settings, 'CONFIO_AI_AGENT_WRITE_BACKEND', 'openai')
                if memory_write_request else None
            )
            return await asyncio.to_thread(
                run_with_tools, user_prompt, provider, system, tools, backend=write_backend
            )
        return await asyncio.to_thread(debate, user_prompt, system=system)

    async def _prompt_with_youtube_analysis(self, user_prompt: str, system: str) -> str:
        analysis_prompt = (
            f'{user_prompt}\n\n'
            'Analiza el/los video(s) público(s) de YouTube reales incluidos arriba. '
            'No te limites al texto del usuario. Extrae detalles visuales, auditivos, '
            'estructura narrativa, hook, ritmo, escena, tono, CTA, y cualquier dato '
            'observable útil para una memoria de video. Si el usuario incluyó script, '
            'compáralo con el video real. El resultado debe ser accionable: observaciones '
            'por segmento/timestamp aproximado, diagnóstico de hook y retención, plan de '
            'edición, hooks alternativos, CTAs/captions, recomendación por plataforma e '
            'incertidumbres. Evita frases genéricas sin evidencia.'
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

    async def _prompt_with_telegram_video_analysis(
        self,
        user_prompt: str,
        videos: list[tuple[str, bytes, str]],
        system: str,
    ) -> str:
        analysis_prompt = (
            f'{user_prompt}\n\n'
            'Analiza el/los video(s) adjunto(s) de Telegram reales. No te limites al caption. '
            'Extrae detalles visuales, auditivos, estructura narrativa, hook, ritmo, escena, tono, '
            'CTA y potencial en TikTok/Instagram/YouTube Shorts usando la memoria de ConfíoAI, '
            'la narrativa de Julian, su filosofía e identidad. El resultado debe ser accionable: '
            'observaciones por segmento/timestamp aproximado, diagnóstico de hook y retención, '
            'plan de edición, hooks alternativos, CTAs/captions, recomendación por plataforma e '
            'incertidumbres. Evita frases genéricas sin evidencia.'
        )
        try:
            analysis = await asyncio.to_thread(
                complete_with_video_files, analysis_prompt, videos, system=system
            )
        except AIClientError as exc:
            analysis = (
                'No se pudo completar el análisis visual/auditivo del video de Telegram antes '
                f'de escribir memoria: {exc}'
            )
        return _with_telegram_video_analysis(user_prompt, analysis)

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


# Precise save/push/commit intent: clear verbs of persisting to memory/git, NOT bare
# nouns like "video"/"git"/"docs"/"memoria" (which fired far too often and dumped random
# things). The system prompt + the model are still the final gate on actually writing.
_MEMORY_WRITE_RE = re.compile(
    r'\b('
    r'gu[aá]rda(?:lo|la|los|las|me|melo|r)?'                      # guarda/guárdalo/guardar
    r'|reg[ií]stra(?:lo|la|los|las|r)?'                           # registra/regístralo
    r'|arch[ií]va(?:lo|la|los|las|r)?'                            # archiva/archívalo
    r'|memor[ií]za(?:lo|la|r)?'                                   # memoriza/memorízalo
    r'|pushe(?:a(?:lo|la|los|las|r)?)?|push'                      # pushea/pushéalo/push
    r'|comm?it(?:ea(?:r|lo)?)?'                                   # commit/commitea
    r'|s[uú]be(?:lo|la)?\s+a\s+git'                               # sube(lo) a git
    r'|save(?:\s+(?:it|this|that|to|in))?'                        # save / save it / save to
    r'|record\s+(?:it|this|that)'                                 # record this
    r'|(?:add|write|put)\s+(?:(?:it|this|that)\s+)?(?:to|in|into)\s+(?:the\s+)?(?:memory|git|docs?)'
    r'|(?:escr[ií]be|an[oó]ta|ap[uú]nta)(?:lo)?\s+en\s+(?:la\s+)?memoria'
    r'|(?:actualiza|edita|revisa)\s+(?:el|la|los|las)\s+(?:doc|documento|documentos|memoria|archivo|archivos)'
    r')\b',
    re.IGNORECASE,
)


def _is_memory_write_request(text: str) -> bool:
    """True when the message clearly asks to save/record/push/update memory. Precise on
    purpose so casual mentions of videos/docs/memory don't trigger a write turn."""
    return bool(_MEMORY_WRITE_RE.search(text or ''))


def _is_existing_doc_revision_request(text: str) -> bool:
    value = (text or '').lower()
    has_revision = any(term in value for term in (
        'revise',
        'revisar',
        'actualizar',
        'actualiza',
        'update',
        'edit',
        'editar',
        'modify',
        'modificar',
    ))
    has_existing_target = any(term in value for term in (
        'existing',
        'current',
        'actual',
        'docs',
        'document',
        'documento',
        'git',
        'github',
        'memory',
        'memoria',
        'analysis',
        'analisis',
        'análisis',
    ))
    return has_revision and has_existing_target


def _with_youtube_analysis(user_prompt: str, analysis: str) -> str:
    return (
        f'{user_prompt}\n\n'
        '## Análisis real del video de YouTube vía Gemini\n'
        f'{analysis.strip() if analysis else "(sin análisis devuelto)"}\n\n'
        'Instrucción obligatoria: si escribes o actualizas una memoria de video, '
        'incorpora el análisis real anterior. No escribas una memoria basada solo '
        'en los links o en campos sueltos proporcionados por el usuario.'
    )


def _with_telegram_video_analysis(user_prompt: str, analysis: str) -> str:
    return (
        f'{user_prompt}\n\n'
        '## Análisis real del video de Telegram vía Gemini\n'
        f'{analysis.strip() if analysis else "(sin análisis devuelto)"}\n\n'
        'Instrucción obligatoria: si escribes o actualizas una memoria de video, '
        'incorpora el análisis real anterior. No escribas una memoria basada solo '
        'en el caption, nombre del archivo o campos sueltos proporcionados por el usuario.'
    )


def _build_tools(client, event, loop, *, authority='client', allow_writes=False, allow_new_memory=True):
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
        """Busca en la memoria Git de ConfioAI. Úsala por defecto para videos/docs/memoria existentes, catálogo actual, "más videos" o contexto ya registrado antes de pedir listas o links al usuario. Argumento: la consulta."""
        return search_knowledge(args)

    def list_videos(args=''):
        """Lista determinísticamente todas las memorias de video existentes en docs/videos, con total, título canónico y path. Úsala para "cuántos videos", "lista los videos", catálogo, títulos actuales o inventario."""
        try:
            return list_video_memories()
        except (ContextRepoError, OSError) as exc:
            logger.exception('list_video_memories tool failed')
            return f'No pude listar las memorias de video: {exc}'

    def list_memory_docs(args=''):
        """Lista determinísticamente memorias Markdown en ConfioAI, con total, categoría, título y path. Argumento opcional: categoría como videos, strategy, social-stats, legal, decision-log, weekly-reports; vacío lista todo excepto conversations."""
        try:
            return list_memory_documents(args)
        except (ContextRepoError, OSError) as exc:
            logger.exception('list_memory_documents tool failed')
            return f'No pude listar las memorias: {exc}'

    def write_memory(args=''):
        """Crea/actualiza memoria curada en ConfioAI y hace commit+push. Formato: primera línea 'category: <videos|strategy|decision-log|meeting-notes|weekly-reports|social-stats|legal|user-reports|other>'; segunda línea 'title: <título>'; opcional 'folder: <subcarpeta>'; resto: markdown completo."""
        return _write_memory_tool(args)

    def write_video_memory(args=''):
        """Crea una memoria de video en docs/videos y hace commit+push. Formato: opcional 'folder: <playlist>'; línea 'title: <título del video>'; resto: markdown completo. Las carpetas son playlists explícitas, no categorías inferidas: no crees carpetas nuevas ni uses Vida y filosofía como comodín. Para clips comprimidos de Telegram sin playlist indicada, usa folder: Instagram. Debe ser accionable: links/stats/script si existen, observaciones del video real, diagnóstico de hook/retención, plan de edición, hooks alternativos, CTA/captions, plataforma y huecos."""
        return _write_memory_tool(f'category: videos\ntitle: {_first_title(args)}\n{_strip_title_line(args)}')

    def read_memory_docs(args=''):
        """Lee uno o varios Markdown exactos de ConfioAI. Formato: un path por línea, por ejemplo docs/videos/Vida y filosofía/video.md."""
        return _read_memory_docs_tool(args)

    def revise_memory_docs(args=''):
        """Revisa varios Markdown existentes en ConfioAI en un solo commit+push. Formato: opcional 'message: <commit>'; luego bloques 'FILE: docs/.../archivo.md' + markdown completo, o 'DELETE' para borrar. Rechaza reemplazos mucho más cortos salvo 'allow_shrink: yes'."""
        return _revise_memory_docs_tool(args)

    tools = {
        'get_chat_files': get_chat_files,
        'get_chat_videos': get_chat_videos,
        'search_chat_history': search_chat_history,
        'search_knowledge': knowledge_search,
        'list_memory_docs': list_memory_docs,
        'list_video_memories': list_videos,
    }
    if authority in {'owner', 'trusted'}:
        # read is always safe; WRITES (create/revise/delete -> git push) require an
        # explicit /memory-style command (allow_writes), never an inferred keyword.
        tools['read_memory_docs'] = read_memory_docs
        if allow_writes:
            if allow_new_memory:
                tools['write_memory'] = write_memory
                tools['write_video_memory'] = write_video_memory
            tools['revise_memory_docs'] = revise_memory_docs
    return tools


def _write_memory_tool(args: str) -> str:
    parsed = _parse_memory_tool_args(args)
    if not parsed['body'].strip():
        return 'No escribí nada: falta el cuerpo markdown.'
    quality_issue = _video_memory_quality_issue(parsed)
    if quality_issue:
        return f'No escribí la memoria de video: {quality_issue}'
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


def _video_memory_quality_issue(parsed: dict) -> str:
    if parsed.get('category') != AIContextCategory.VIDEOS:
        return ''
    body = parsed.get('body') or ''
    normalized = body.lower()
    if len(body.strip()) < 900:
        return (
            'el análisis es demasiado corto para ser útil. Incluye observaciones reales, '
            'hook/retención, plan de edición, hooks alternativos, CTA/captions y huecos.'
        )
    required_groups = [
        ('observaciones', 'escena', 'timestamp', 'segmento'),
        ('hook', '0-3', 'primeros 3'),
        ('retención', 'retencion', 'ritmo'),
        ('edición', 'edicion', 'cortes', 'subtítulos', 'subtitulos', 'b-roll'),
        ('cta', 'caption', 'copy'),
    ]
    hits = sum(1 for group in required_groups if any(term in normalized for term in group))
    if hits < 4:
        return (
            'faltan secciones accionables. Debe cubrir observaciones/segmentos, hook, '
            'retención, edición concreta y CTA/captions.'
        )
    generic_phrases = (
        'alto potencial',
        'conecta emocionalmente',
        'top of funnel',
        'fortalece tu posicionamiento',
    )
    if any(phrase in normalized for phrase in generic_phrases) and hits < len(required_groups):
        return 'suena genérico; ata cada conclusión a evidencia observable y acciones concretas.'
    return ''


def _read_memory_docs_tool(args: str) -> str:
    paths = [line.strip() for line in (args or '').splitlines() if line.strip()]
    if not paths:
        return 'No leí nada: falta al menos un path Markdown.'
    try:
        return read_context_documents(paths)
    except (ContextRepoError, OSError) as exc:
        logger.exception('read_memory_docs tool failed')
        return f'No pude leer los documentos: {exc}'


def _revise_memory_docs_tool(args: str) -> str:
    parsed = _parse_revise_memory_docs_args(args)
    if not parsed['edits']:
        return 'No revisé nada: faltan bloques FILE.'
    try:
        result = revise_context_documents(parsed['edits'], message=parsed['message'], push=True)
    except (ContextRepoError, OSError) as exc:
        logger.exception('revise_memory_docs tool failed')
        return f'No pude revisar/pushear los documentos: {exc}'
    except Exception as exc:  # noqa: BLE001
        logger.exception('revise_memory_docs unexpected failure')
        return f'No pude revisar/pushear los documentos por un error inesperado: {exc}'
    return (
        'Documentos revisados y pusheados.\n'
        f'- Archivos: {", ".join(result["paths"]) if result["paths"] else "(sin cambios)"}\n'
        f'- Commit: {result["commit"][:12] if result["commit"] else "(sin commit)"}\n'
        f'- Status: {result["status"]}'
    )


def _parse_revise_memory_docs_args(args: str) -> dict:
    message = 'Revise AI context docs'
    edits = []
    current_path = ''
    current_lines = []
    current_allow_shrink = False

    def flush():
        nonlocal current_path, current_lines, current_allow_shrink
        if not current_path:
            return
        body = '\n'.join(current_lines).strip()
        if body == '<<<\n>>>':
            body = ''
        if body.startswith('<<<') and body.endswith('>>>'):
            body = body[3:-3].strip()
        action = 'delete' if body.strip().upper() == 'DELETE' else 'write'
        edits.append({
            'path': current_path,
            'action': action,
            'body': '' if action == 'delete' else body,
            'allow_shrink': current_allow_shrink,
        })
        current_path = ''
        current_lines = []
        current_allow_shrink = False

    for raw_line in (args or '').splitlines():
        key, sep, value = raw_line.partition(':')
        normalized = key.strip().lower()
        if sep and normalized == 'message' and not current_path and not edits:
            message = value.strip() or message
            continue
        if sep and normalized == 'file':
            flush()
            current_path = value.strip()
            continue
        if sep and normalized == 'allow_shrink' and current_path and not current_lines:
            current_allow_shrink = value.strip().lower() in {'1', 'true', 'yes', 'si', 'sí'}
            continue
        if current_path:
            current_lines.append(raw_line)
    flush()
    return {'message': message, 'edits': edits}


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


async def _collect_video_inputs(client, event) -> list[tuple[str, bytes, str]]:
    """Download compressed Telegram video media from this message, if within limit."""
    message = getattr(event, 'message', None)
    if not message or not _is_video_message(message):
        return []
    file = getattr(message, 'file', None)
    size = getattr(file, 'size', None) if file else None
    if size and size > MAX_VIDEO_BYTES:
        logger.info('Skipping video over size limit: %s bytes', size)
        return []
    mime_type = _video_mime_type(message)
    display_name = _video_display_name(message)
    data = await client.download_media(message, file=bytes)
    if data and len(data) <= MAX_VIDEO_BYTES:
        return [(mime_type, data, display_name)]
    if data:
        logger.info('Skipping downloaded video over size limit: %s bytes', len(data))
    return []


def _is_image_message(message) -> bool:
    if not getattr(message, 'media', None):
        return False
    file = getattr(message, 'file', None)
    mime = (getattr(file, 'mime_type', '') if file else '') or ''
    return bool(getattr(message, 'photo', None) or mime.startswith('image/'))


def _is_video_message(message) -> bool:
    if not getattr(message, 'media', None):
        return False
    # Only TRUE Telegram videos (compressed/inline). Videos sent as files/documents
    # (archives, up to several GB) are intentionally NOT auto-analyzed — they're just
    # answered. Analyzing an original file is opt-in via an explicit command (File API),
    # not an inline RAM download on every send.
    return bool(getattr(message, 'video', None) or getattr(message, 'video_note', None))


def _image_mime_type(message) -> str:
    file = getattr(message, 'file', None)
    mime = (getattr(file, 'mime_type', '') if file else '') or ''
    return mime if mime.startswith('image/') else 'image/jpeg'


def _video_mime_type(message) -> str:
    file = getattr(message, 'file', None)
    mime = (getattr(file, 'mime_type', '') if file else '') or ''
    return mime if mime.startswith('video/') else 'video/mp4'


def _video_display_name(message) -> str:
    file = getattr(message, 'file', None)
    name = getattr(file, 'name', None) if file else None
    return name or f'telegram-video-{getattr(message, "id", "unknown")}.mp4'


def _media_only_prompt(message) -> str:
    if _is_image_message(message):
        return (
            'Analiza esta imagen enviada sin caption. Describe lo observable y extrae '
            'implicaciones útiles para ConfíoAI, contenido, producto o estrategia.'
        )
    if _is_video_message(message):
        return (
            'Analiza este video comprimido enviado sin caption. Evalúalo como pieza de '
            'TikTok/Instagram/YouTube Shorts usando la ecuación de éxito social de ConfíoAI, '
            'los datos propios disponibles, y la narrativa, filosofía e identidad de Julian.'
        )
    return 'Analiza este archivo enviado sin caption y responde con lo útil para ConfíoAI.'


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
