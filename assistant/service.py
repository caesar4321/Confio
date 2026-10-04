"""Glue between the support thread (inbox) and the engine: limits, mode, persistence."""
from __future__ import annotations

import base64
import binascii
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from inbox.models import SupportMessage
from inbox.push_service import send_support_staff_push
from inbox.schema import get_or_create_support_conversation

from . import conf
from .engine import AssistantUnavailable, Viewer, human_mode_active, run_turn
from .models import AssistantProfile, AssistantThreadState, AssistantTurn, TurnModality

logger = logging.getLogger(__name__)

UNAVAILABLE_REPLY = (
    'Ahora mismo no puedo responder. Vuelve a intentarlo en un momento, '
    'o escribe "hablar con una persona" y te atiende el equipo de Confío.'
)
LIMIT_REPLY = (
    'Llegaste al límite de mensajes con Confio Assistant por hoy. Mañana seguimos. '
    'Si es urgente, escribe "hablar con una persona".'
)
HANDOFF_NOTICE = 'Te pasé con el equipo de Confío. Te responderán aquí mismo, normalmente en unas horas.'
HUMAN_KEYWORDS = ('hablar con una persona', 'hablar con un humano', 'agente humano', 'persona real')


@dataclass
class AskOutcome:
    user_message: SupportMessage
    reply_message: SupportMessage | None
    actions: list = field(default_factory=list)
    mode: str = 'AI'
    remaining_turns: int | None = None
    transcript: str | None = None
    # The turn changed the user's data (e.g. categorized movements).
    data_changed: bool = False


def _resolve_tz(tz_name, phone_country):
    try:
        from users.cashflow import resolve_timezone
        return resolve_timezone(tz_name, phone_country)
    except ImportError:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            return ZoneInfo(tz_name) if tz_name else ZoneInfo('UTC')
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo('UTC')


def _viewer(user, account, business, jwt_context, *, screen='', tz_name=None):
    from users.models import Account

    account_type = jwt_context.get('account_type', 'personal')
    business_id = business.id if business is not None else None
    is_owner = False
    if business is not None:
        account = Account.objects.filter(
            business_id=business_id, account_type='business',
            account_index=jwt_context.get('account_index', 0), deleted_at__isnull=True,
        ).first() or Account.objects.filter(
            business_id=business_id, account_type='business', deleted_at__isnull=True,
        ).order_by('account_index').first()
        is_owner = Account.objects.filter(
            user=user, business_id=business_id, account_type='business', deleted_at__isnull=True,
        ).exists()
    return Viewer(
        user=user,
        account=account,
        account_type=account_type,
        business_id=business_id,
        is_business_owner=is_owner,
        tz=_resolve_tz(tz_name, getattr(user, 'phone_country', None)),
        screen=(screen or '')[:64],
    )


def thread_state(conversation):
    state, _ = AssistantThreadState.objects.get_or_create(conversation=conversation)
    return state


def last_staff_reply_at(conversation):
    message = (
        conversation.messages.filter(sender_type='AGENT', sender_user__isnull=False)
        .order_by('-created_at').only('created_at').first()
    )
    return message.created_at if message else None


def is_human_mode(conversation, state=None):
    return human_mode_active(state or thread_state(conversation), last_staff_reply_at(conversation))


def awaiting_team(conversation, recent_messages_desc):
    """True while any message routed to the team is unanswered by a person.

    Queries the whole thread (not the portal's 50-message window): a long AI
    conversation after a handoff must not hide it. Threads from before
    Confio Assistant (no AI message at all) keep the old rule.
    """
    last_staff = (conversation.messages.filter(sender_type='AGENT', sender_user__isnull=False)
                  .order_by('-created_at').values_list('created_at', flat=True).first())
    pending = conversation.messages.filter(sender_type='USER', metadata__to_team=True)
    if last_staff is not None:
        pending = pending.filter(created_at__gt=last_staff)
    if pending.exists():
        return True
    if conversation.messages.filter(sender_type='AGENT', metadata__ai=True).exists():
        return False
    latest = next((m for m in recent_messages_desc if m.sender_type != 'SYSTEM'), None)
    return latest is not None and latest.sender_type == 'USER'


def lock_user(user):
    """Serialize a user's metered work (turns, analyses, pets): counts are read
    and spent under this row lock, so parallel requests can't overspend."""
    AssistantProfile.objects.get_or_create(user=user)
    return AssistantProfile.objects.select_for_update().get(user=user)


def turns_today(user):
    since = timezone.now() - timedelta(hours=24)
    return AssistantTurn.objects.filter(user=user, created_at__gte=since)


def _plus(user):
    from .billing import has_plus
    return has_plus(user)


def daily_turn_cap(user):
    return conf.get('CONFIO_ASSISTANT_PLUS_DAILY_TURNS' if _plus(user) else 'CONFIO_ASSISTANT_DAILY_TURNS')


def remaining_turns(user):
    return max(daily_turn_cap(user) - turns_today(user).count(), 0)


def analyses_left(user):
    from .models import VoiceSession

    since = timezone.now() - timedelta(hours=24)
    tool_lists = list(turns_today(user).values_list('tools', flat=True)) + list(
        VoiceSession.objects.filter(user=user, started_at__gte=since).values_list('tools', flat=True))
    used = sum(1 for tools in tool_lists for tool in (tools or []) if tool.get('name') == 'analyze_finances')
    cap = conf.get('CONFIO_ASSISTANT_PLUS_DAILY_ANALYSES' if _plus(user) else 'CONFIO_ASSISTANT_DAILY_ANALYSES')
    return max(cap - used, 0)


def _account_label(viewer, business):
    if business is not None:
        role = 'dueño' if viewer.is_business_owner else 'empleado'
        return f'negocio "{business.name}" ({role})'
    return 'personal'


def _append(conversation, **kwargs):
    message = SupportMessage.objects.create(conversation=conversation, message_type='TEXT', **kwargs)
    conversation.last_message_at = message.created_at
    conversation.save(update_fields=['last_message_at', 'updated_at'])
    return message


def _route_to_team(message):
    message.metadata = {**(message.metadata or {}), 'to_team': True}
    message.save(update_fields=['metadata'])

    def push():
        try:
            send_support_staff_push(message.id)
        except Exception:
            logger.exception('Confio Assistant: staff push failed', extra={'message_id': message.id})

    # After commit: the push must never point at a message that rolled back.
    transaction.on_commit(push)


def ask(user, account, business, jwt_context, body=None, *, audio=None, screen='', tz_name=None,
        can_navigate=True):
    """Answer `body` (or a voice note: audio=(base64, mime, duration_ms)) in
    the user's support thread.

    Quota is RESERVED under a short per-user lock (a pending AssistantTurn
    counts at once); transcription and model calls run outside the lock, so a
    slow model never blocks the user's other requests.

    can_navigate=False for app builds that predate Confio Assistant: they can't
    open screens, so the model must not claim it did.
    Raises ValueError (bad input) / AssistantUnavailable (transcription down).
    """
    screen = (screen or '')[:64]
    # 1. Reserve (short lock).
    with transaction.atomic():
        lock_user(user)
        conversation = get_or_create_support_conversation(user, account, business)
        state = thread_state(conversation)
        human = is_human_mode(conversation, state) or not conf.get('CONFIO_ASSISTANT_ENABLED')
        remaining = remaining_turns(user)
        turn = None
        if audio:
            # Transcription is paid work, even when people answer: always metered.
            if remaining <= 0:
                reply = _append(conversation, sender_type='AGENT', body=LIMIT_REPLY,
                                metadata={'ai': True, 'limit': True})
                return AskOutcome(user_message=reply, reply_message=None, remaining_turns=0)
            turn = AssistantTurn.objects.create(user=user, conversation=conversation, screen=screen,
                                                modality=TurnModality.VOICE_NOTE, error='pending')

    # 2. Transcribe (no lock).
    modality, audio_seconds, transcript = TurnModality.TEXT, 0, None
    if audio:
        try:
            transcript, audio_seconds = transcribe(*audio)
        except Exception as exc:
            turn.error = str(exc)[:280] or 'transcription failed'
            turn.save(update_fields=['error'])
            raise
        turn.audio_seconds = Decimal(str(audio_seconds))
        turn.cost_usd = transcription_cost(audio_seconds)
        turn.error = ''
        turn.save(update_fields=['audio_seconds', 'cost_usd', 'error'])
        if not transcript:
            raise ValueError('No escuché nada en el audio.')
        body, modality = transcript, TurnModality.VOICE_NOTE

    clean = (body or '').strip()[:conf.get('CONFIO_ASSISTANT_MAX_INPUT_CHARS')]
    if not clean:
        raise ValueError('Message body is required')
    wants_human = any(k in clean.lower() for k in HUMAN_KEYWORDS)

    # 3. Record the message and route it (short lock). Human mode is checked
    # again here: staff may have replied while the note was transcribing.
    with transaction.atomic():
        lock_user(user)
        state = thread_state(conversation)
        human = is_human_mode(conversation, state) or not conf.get('CONFIO_ASSISTANT_ENABLED')
        user_message = _append(conversation, sender_type='USER', sender_user=user, body=clean,
                               metadata={'modality': modality, 'screen': screen})
        if turn is not None:
            turn.user_message = user_message
            turn.save(update_fields=['user_message'])
        if human:
            _route_to_team(user_message)
            return AskOutcome(user_message=user_message, reply_message=None, mode='HUMAN', transcript=transcript)
        if wants_human:
            outcome = _handoff(conversation, state, user_message, 'El usuario pidió hablar con una persona')
            outcome.transcript = transcript
            return outcome
        if turn is None:
            remaining = remaining_turns(user)
            if remaining <= 0:
                reply = _append(conversation, sender_type='AGENT', body=LIMIT_REPLY,
                                metadata={'ai': True, 'limit': True})
                return AskOutcome(user_message=user_message, reply_message=reply, remaining_turns=0,
                                  transcript=transcript)
            turn = AssistantTurn.objects.create(user=user, conversation=conversation, user_message=user_message,
                                                screen=screen, modality=modality, error='pending')

    # 4. Answer (no lock; analyses reserve their own slot).
    viewer = _viewer(user, account, business, jwt_context, screen=screen, tz_name=tz_name)
    history = list(conversation.messages.order_by('-created_at')[:conf.get('CONFIO_ASSISTANT_HISTORY_MESSAGES')])
    history.reverse()
    started = time.monotonic()
    try:
        result = run_turn(
            viewer, history,
            first_name=user.first_name,
            account_label=_account_label(viewer, business),
            country=getattr(user, 'phone_country', ''),
            analyses_left=0,
            reserve_analysis=_analysis_reserver(user, turn),
            can_navigate=can_navigate,
        )
    except AssistantUnavailable as exc:
        logger.warning('Confio Assistant unavailable: %s', exc)
        if _team_took_over(user, conversation, user_message):
            turn.error = f'superseded by human handoff ({str(exc)[:200]})'
            turn.latency_ms = int((time.monotonic() - started) * 1000)
            turn.save(update_fields=['error', 'latency_ms'])
            return AskOutcome(user_message=user_message, reply_message=None, mode='HUMAN',
                              remaining_turns=remaining - 1, transcript=transcript)
        reply = _append(conversation, sender_type='AGENT', body=UNAVAILABLE_REPLY, metadata={'ai': True, 'error': True})
        turn.refresh_from_db(fields=['tools'])
        turn.error = str(exc)[:280]
        turn.reply_message = reply
        turn.latency_ms = int((time.monotonic() - started) * 1000)
        turn.save()
        return AskOutcome(user_message=user_message, reply_message=reply, remaining_turns=remaining - 1,
                          transcript=transcript)

    # The team may have taken the thread while the model was answering: then
    # the AI stays quiet (no reply, no screen actions) and the message waits
    # for people. The turn is still metered.
    # Always re-check (an escalation intent from the model doesn't mean the
    # team hasn't already taken over meanwhile).
    if _team_took_over(user, conversation, user_message):
        turn.models_used = result.models_used
        turn.input_tokens = result.input_tokens
        turn.cached_input_tokens = result.cached_input_tokens
        turn.output_tokens = result.output_tokens
        turn.cost_usd = result.cost_usd + transcription_cost(audio_seconds)
        turn.tools = result.tools
        turn.error = 'superseded by human handoff'
        turn.latency_ms = int((time.monotonic() - started) * 1000)
        turn.save()
        return AskOutcome(user_message=user_message, reply_message=None, mode='HUMAN',
                          remaining_turns=remaining - 1, transcript=transcript,
                          data_changed=bool(result.writes))

    reply = _append(conversation, sender_type='AGENT', body=result.reply,
                    metadata={'ai': True, 'actions': result.actions})
    turn.reply_message = reply
    turn.models_used = result.models_used
    turn.input_tokens = result.input_tokens
    turn.cached_input_tokens = result.cached_input_tokens
    turn.output_tokens = result.output_tokens
    turn.cost_usd = result.cost_usd + transcription_cost(audio_seconds)
    turn.tools = result.tools
    turn.actions = result.actions
    turn.error = ''
    turn.latency_ms = int((time.monotonic() - started) * 1000)
    turn.save()

    if result.handoff_reason:
        with transaction.atomic():
            outcome = _handoff(conversation, state, user_message, result.handoff_reason, ai_reply=reply)
        outcome.actions = result.actions
        outcome.remaining_turns = remaining - 1
        outcome.transcript = transcript
        outcome.data_changed = bool(result.writes)
        return outcome
    return AskOutcome(user_message=user_message, reply_message=reply, actions=result.actions,
                      remaining_turns=remaining - 1, transcript=transcript, data_changed=bool(result.writes))


def _team_took_over(user, conversation, user_message):
    """Re-read ownership after the model ran: if people own the thread now,
    the message is routed to them and the AI publishes nothing."""
    with transaction.atomic():
        lock_user(user)
        if is_human_mode(conversation, thread_state(conversation)):
            _route_to_team(user_message)
            return True
    return False


def _analysis_reserver(user, turn):
    """Claim one analysis slot (short lock) before the model calls Sol."""
    def reserve():
        with transaction.atomic():
            lock_user(user)
            if analyses_left(user) <= 0:
                return False
            row = AssistantTurn.objects.select_for_update().get(pk=turn.pk)
            row.tools = (row.tools or []) + [{'name': 'analyze_finances', 'reserved': True}]
            row.save(update_fields=['tools'])
            return True
    return reserve


def _handoff(conversation, state, user_message, reason, ai_reply=None):
    with transaction.atomic():
        state.handoff_at = timezone.now()
        state.handoff_reason = reason[:280]
        state.save(update_fields=['handoff_at', 'handoff_reason', 'updated_at'])
        reply = ai_reply or _append(conversation, sender_type='AGENT', body=HANDOFF_NOTICE,
                                    metadata={'ai': True, 'handoff': True})
    _route_to_team(user_message)
    return AskOutcome(user_message=user_message, reply_message=reply, mode='HUMAN')


def append_voice_transcript(conversation, user, entries):
    """Realtime turns land in the same thread as text, marked REALTIME."""
    saved = []
    for entry in entries[:40]:
        text = (entry.get('text') or '').strip()[:conf.get('CONFIO_ASSISTANT_MAX_INPUT_CHARS')]
        if not text:
            continue
        if entry.get('role') == 'user':
            saved.append(_append(conversation, sender_type='USER', sender_user=user, body=text,
                                 metadata={'modality': TurnModality.REALTIME}))
        else:
            saved.append(_append(conversation, sender_type='AGENT', body=text,
                                 metadata={'ai': True, 'modality': TurnModality.REALTIME}))
    return saved


def handoff_from_voice(conversation, reason):
    """escalate_to_human during a call: same handoff as text turns."""
    state = thread_state(conversation)
    state.handoff_at = timezone.now()
    state.handoff_reason = (reason or 'Llamada con Confio Assistant')[:280]
    state.save(update_fields=['handoff_at', 'handoff_reason', 'updated_at'])
    note = _append(conversation, sender_type='USER', sender_user=conversation.user,
                   body=f'(Desde una llamada con Confio Assistant) {state.handoff_reason}',
                   metadata={'modality': TurnModality.REALTIME})
    _route_to_team(note)


def return_to_ai(user, account, business):
    conversation = get_or_create_support_conversation(user, account, business)
    state = thread_state(conversation)
    state.returned_to_ai_at = timezone.now()
    state.save(update_fields=['returned_to_ai_at', 'updated_at'])
    return conversation


def profile_for(user):
    profile, _ = AssistantProfile.objects.get_or_create(user=user)
    return profile


# --------------------------------------------------------------------------- #
# Voice notes
# --------------------------------------------------------------------------- #

# Only what the app records (AAC in MPEG-4): its duration is in the file, so
# metering and the length cap never depend on what the client reports.
AUDIO_EXTENSIONS = {'audio/mp4': 'm4a', 'audio/m4a': 'm4a', 'audio/x-m4a': 'm4a'}


def _boxes(data, start=0, end=None):
    """Yield (type, payload_start, box_end) for MPEG-4 boxes in data[start:end]."""
    import struct
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack('>I4s', data[pos:pos + 8])
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack('>Q', data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, pos + header, pos + size
        pos += size


def _child(data, start, end, kind):
    for k, s, e in _boxes(data, start, end):
        if k == kind:
            return s, e
    return None


def mp4_duration_seconds(data):
    """Seconds of audio a decoder will actually play: the longest track's
    sample table (stts) over its media timescale (mdhd). Walks the real box
    tree (a decoy header inside a free/skip box is never read). Fragmented
    files (moof) and anything unparseable return None."""
    import struct
    top = list(_boxes(data))
    if not top or any(k == b'moof' for k, _, _ in top):
        return None
    moov = next(((s, e) for k, s, e in top if k == b'moov'), None)
    if moov is None:
        return None
    longest = None
    for kind, ts, te in _boxes(data, *moov):
        if kind != b'trak':
            continue
        mdia = _child(data, ts, te, b'mdia')
        if mdia is None:
            continue
        mdhd = _child(data, *mdia, b'mdhd')
        minf = _child(data, *mdia, b'minf')
        stbl = _child(data, *minf, b'stbl') if minf else None
        stts = _child(data, *stbl, b'stts') if stbl else None
        if mdhd is None or stts is None:
            continue
        try:
            version = data[mdhd[0]]
            timescale = struct.unpack('>I', data[mdhd[0] + (20 if version == 1 else 12):][:4])[0]
            count = struct.unpack('>I', data[stts[0] + 4:stts[0] + 8])[0]
            if stts[0] + 8 + count * 8 > stts[1]:
                continue
            total = 0
            for n in range(count):
                samples, delta = struct.unpack('>II', data[stts[0] + 8 + n * 8:stts[0] + 16 + n * 8])
                total += samples * delta
        except (IndexError, struct.error):
            continue
        if timescale:
            seconds = total / timescale
            longest = seconds if longest is None else max(longest, seconds)
    return longest


def transcription_cost(seconds):
    if not seconds:
        return Decimal('0')
    per_minute = Decimal(str(conf.get('CONFIO_ASSISTANT_TRANSCRIBE_PRICE_PER_MINUTE')))
    return Decimal(str(seconds)) / Decimal(60) * per_minute


def transcribe(audio_base64, mime_type, duration_ms):
    """Voice note → text. The audio is never stored; only the transcript is."""
    extension = AUDIO_EXTENSIONS.get((mime_type or '').lower())
    if extension is None:
        raise ValueError('Formato de audio no soportado')
    seconds = max(float(duration_ms or 0) / 1000.0, 0)
    if seconds > conf.get('CONFIO_ASSISTANT_MAX_AUDIO_SECONDS') + 1:
        raise ValueError('El audio es demasiado largo')
    try:
        audio = base64.b64decode(audio_base64 or '', validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError('Audio inválido') from exc
    if not audio:
        raise ValueError('Audio vacío')
    if len(audio) > conf.get('CONFIO_ASSISTANT_MAX_AUDIO_BYTES'):
        raise ValueError('El audio es demasiado grande')
    # The file's own header decides the length; the reported value can only
    # raise it. No readable duration, no transcription.
    actual = mp4_duration_seconds(audio)
    if not actual:
        # No readable sample table (or fragmented / empty): refuse.
        raise ValueError('Audio inválido')
    # The decoded length decides; the byte cap above bounds size separately.
    seconds = max(seconds, actual)
    if seconds > conf.get('CONFIO_ASSISTANT_MAX_AUDIO_SECONDS') + 1:
        raise ValueError('El audio es demasiado largo')
    api_key = getattr(settings, 'OPENAI_API_KEY', '')
    if not api_key:
        raise AssistantUnavailable('OPENAI_API_KEY is not configured')
    try:
        response = requests.post(
            'https://api.openai.com/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {api_key}'},
            files={'file': (f'nota.{extension}', audio, mime_type)},
            data={'model': conf.get('CONFIO_ASSISTANT_TRANSCRIBE_MODEL'), 'response_format': 'json'},
            timeout=conf.get('CONFIO_ASSISTANT_REQUEST_TIMEOUT_SECONDS'),
        )
    except requests.RequestException as exc:
        raise AssistantUnavailable(f'transcription failed: {exc}') from exc
    if response.status_code >= 400:
        raise AssistantUnavailable(f'transcription {response.status_code}: {response.text[:200]}')
    data = response.json()
    usage = data.get('usage') or {}
    if usage.get('type') == 'duration' and usage.get('seconds'):
        # The provider measured the audio: meter what it actually billed.
        seconds = max(seconds, float(usage['seconds']))
    return (data.get('text') or '').strip(), seconds
