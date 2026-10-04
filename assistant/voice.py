"""Realtime voice calls with Confío IA (IA+).

The phone talks to OpenAI directly over WebRTC with a short-lived client
secret minted here. Everything that touches the user's data stays on the
server: the session only declares the tools, and when the model calls one the
app relays it to `run_tool`, which executes it with the same JWT-scoped
Toolbelt as text turns. `navigate` is the one tool the app executes itself.

Minutes are measured from server timestamps (session start → last heartbeat),
never from what the client reports.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import billing, conf
from .engine import AssistantUnavailable, Toolbelt, TurnResult, allowed_destinations
from .models import TurnModality, VoiceSession
from .prompts import build_system_prompt

logger = logging.getLogger(__name__)

VOICE_NOTE = """
# Estás en una llamada de voz
- Habla natural y breve: 1-3 oraciones. Nada de listas, viñetas ni formato.
- Di los montos como se dicen ("doce dólares con cincuenta"), no como se escriben.
- Si abres una pantalla, dilo en pocas palabras mientras se abre.
- Antes de clasificar movimientos, di cuáles encontraste y espera un "sí".
- Si el usuario dice "gracias, eso es todo" o se despide, despídete en una línea.
"""

SERVER_TOOLS = {'escalate_to_human', 'get_month_summary', 'get_transactions',
                'categorize_transactions', 'analyze_finances'}


class VoiceUnavailable(Exception):
    """Shown to the user (Spanish)."""


def month_start(now=None):
    now = now or timezone.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def minutes_used(user, now=None):
    now = now or timezone.now()
    idle = timedelta(seconds=conf.get('CONFIO_IA_VOICE_IDLE_SECONDS'))
    total = 0.0
    for session in VoiceSession.objects.filter(user=user, started_at__gte=month_start(now)):
        end = session.ended_at or min(session.last_seen_at + idle, now)
        total += max((end - session.started_at).total_seconds(), 0)
    return total / 60.0


def minutes_left(user):
    return max(conf.get('CONFIO_IA_PLUS_VOICE_MINUTES') - minutes_used(user), 0.0)


def _realtime_tools(belt):
    tools = []
    for spec in belt.specs():
        tools.append({
            'type': 'function',
            'name': spec['name'],
            'description': spec['description'],
            'parameters': spec['parameters'],
        })
    return tools


def start_session(viewer, conversation, *, first_name, account_label, country):
    user = viewer.user
    if not conf.get('CONFIO_IA_REALTIME_ENABLED'):
        raise VoiceUnavailable('Las llamadas con Confío IA todavía no están disponibles.')
    if not billing.has_ia_plus(user):
        raise VoiceUnavailable('Las llamadas con Confío IA son parte de IA+.')
    left = minutes_left(user)
    if left < 0.5:
        raise VoiceUnavailable('Usaste tus minutos de voz de este mes. Puedes seguir por texto o con audios.')
    api_key = getattr(settings, 'OPENAI_API_KEY', '')
    if not api_key:
        raise VoiceUnavailable('La voz no está disponible ahora.')


    belt = Toolbelt(viewer, TurnResult(reply=''), analyses_left=0)
    local_now = timezone.now().astimezone(viewer.tz)
    instructions = build_system_prompt(
        first_name=first_name, account_label=account_label, country=country,
        screen=viewer.screen, local_now=f'{local_now:%Y-%m-%d %H:%M} ({viewer.tz})',
        destinations=allowed_destinations(viewer),
    ) + VOICE_NOTE
    model = conf.get('CONFIO_IA_REALTIME_MODEL')
    # The secret only has to live until the call connects.
    body = {
        'expires_after': {'anchor': 'created_at', 'seconds': 120},
        'session': {
            'type': 'realtime',
            'model': model,
            'instructions': instructions,
            'audio': {
                'input': {
                    'transcription': {'model': conf.get('CONFIO_IA_REALTIME_TRANSCRIBE_MODEL')},
                    'turn_detection': {'type': 'semantic_vad'},
                },
                'output': {'voice': conf.get('CONFIO_IA_REALTIME_VOICE')},
            },
            'tools': _realtime_tools(belt),
            'tool_choice': 'auto',
            'max_output_tokens': 1200,
        },
    }
    try:
        response = requests.post(
            'https://api.openai.com/v1/realtime/client_secrets',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json=body, timeout=conf.get('CONFIO_IA_REQUEST_TIMEOUT_SECONDS'),
        )
    except requests.RequestException as exc:
        raise VoiceUnavailable('La voz no está disponible ahora.') from exc
    if response.status_code >= 400:
        logger.warning('Realtime client secret failed: %s %s', response.status_code, response.text[:300])
        raise VoiceUnavailable('La voz no está disponible ahora.')
    secret = response.json().get('value')
    if not secret:
        raise VoiceUnavailable('La voz no está disponible ahora.')
    session = VoiceSession.objects.create(
        user=user, conversation=conversation, model=model,
        screen=viewer.screen, tz_name=str(viewer.tz),
        account_id=None if viewer.business_id else getattr(viewer.account, 'id', None),
        business_id=viewer.business_id,
    )
    # The client secret never leaves the server: connect() does the WebRTC
    # handshake with it, so the server always knows the call id and can cut
    # the call (a client can't connect around us).
    cache.set(_secret_key(session.id), secret, 120)
    # One call at a time: a new call ends (and hangs up) any previous one.
    for previous in VoiceSession.objects.filter(user=user, ended_at__isnull=True).exclude(pk=session.pk):
        hang_up(previous)
    return session, int(left)


def _secret_key(session_id):
    return f'confio-ia:voice-secret:{session_id}'


def connect(session, offer_sdp):
    """SDP offer in, SDP answer out; records the provider call id."""
    from django.db import transaction
    # One handshake per session, claimed under the row lock: a second
    # concurrent connect finds the secret gone (or a call already recorded).
    with transaction.atomic():
        row = VoiceSession.objects.select_for_update().get(pk=session.pk)
        secret = cache.get(_secret_key(session.id))
        claimed = bool(secret) and cache.delete(_secret_key(session.id)) is not False
        if not claimed or row.ended_at is not None or row.call_id:
            raise VoiceUnavailable('La llamada expiró. Inténtalo de nuevo.')
    try:
        response = requests.post('https://api.openai.com/v1/realtime/calls', data=(offer_sdp or '').encode(),
                                 headers={'Authorization': f'Bearer {secret}', 'Content-Type': 'application/sdp'},
                                 timeout=conf.get('CONFIO_IA_REQUEST_TIMEOUT_SECONDS'))
    except requests.RequestException as exc:
        raise VoiceUnavailable('No pudimos conectar la llamada.') from exc
    location = response.headers.get('Location', '')
    call_id = location.rstrip('/').rsplit('/', 1)[-1] if location else ''
    if response.status_code >= 400 or not call_id:
        logger.warning('Realtime connect failed: %s %s', response.status_code, response.text[:200])
        raise VoiceUnavailable('No pudimos conectar la llamada.')
    from django.db import transaction
    with transaction.atomic():
        row = VoiceSession.objects.select_for_update().get(pk=session.pk)
        row.call_id = call_id[:128]
        row.remote_ended = False
        row.save(update_fields=['call_id', 'remote_ended'])
        hung_up_meanwhile = row.ended_at is not None
    if hung_up_meanwhile:
        # A hangup landed during the handshake: cut the call it just created.
        hang_up(row)
        raise VoiceUnavailable('La llamada terminó.')
    session.call_id = row.call_id
    return response.text


def get_session(user, session_id):
    session = VoiceSession.objects.filter(id=session_id, user=user).first()
    if session is None:
        raise VoiceUnavailable('Esta llamada ya terminó.')
    return session


def session_belongs(session, account, business):
    """The call was started from this JWT account."""
    if business is not None:
        return session.business_id == business.id
    return session.business_id is None and session.account_id == getattr(account, 'id', None)


def session_allowed(session, account, business):
    """A call may keep using tools only while it is live, on the account it
    started from, with realtime on, IA+ active and minutes left."""
    if session.ended_at is not None or not conf.get('CONFIO_IA_REALTIME_ENABLED'):
        return False
    if not session_belongs(session, account, business):
        return False
    return billing.has_ia_plus(session.user) and minutes_left(session.user) > 0


def hang_up(session):
    """End a call on our side and at OpenAI. Runs under the session row lock
    (the same one connect() takes), so it always sees the latest call id;
    remote_ended only flips once OpenAI confirms (2xx, or 404 = already gone)
    and the sweeper retries until then."""
    from django.db import transaction
    with transaction.atomic():
        row = VoiceSession.objects.select_for_update().get(pk=session.pk)
        update = []
        if row.ended_at is None:
            row.ended_at = timezone.now()
            update.append('ended_at')
        if not row.call_id:
            # Never connected: nothing to cut (a handshake finishing later
            # sees ended_at and cuts its own call).
            if not row.remote_ended:
                row.remote_ended = True
                update.append('remote_ended')
        elif not row.remote_ended:
            api_key = getattr(settings, 'OPENAI_API_KEY', '')
            try:
                response = requests.post(f'https://api.openai.com/v1/realtime/calls/{row.call_id}/hangup',
                                         headers={'Authorization': f'Bearer {api_key}'}, timeout=10)
                if response.status_code < 300 or response.status_code == 404:
                    row.remote_ended = True
                    update.append('remote_ended')
                else:
                    logger.warning('Realtime hangup %s for %s', response.status_code, row.id)
            except requests.RequestException:
                logger.warning('Realtime hangup failed for %s', row.id)
        if update:
            row.save(update_fields=update)
    session.ended_at, session.remote_ended, session.call_id = row.ended_at, row.remote_ended, row.call_id


def enforce_sessions(now=None):
    """Hang up calls whose app stopped heartbeating or whose minutes ran out:
    the WebRTC link runs straight to OpenAI, so only the server can cut it."""
    now = now or timezone.now()
    idle = timedelta(seconds=conf.get('CONFIO_IA_VOICE_IDLE_SECONDS'))
    ended = 0
    for session in VoiceSession.objects.filter(ended_at__isnull=True).select_related('user'):
        stale = session.last_seen_at + idle < now
        if (stale or not conf.get('CONFIO_IA_REALTIME_ENABLED') or not billing.has_ia_plus(session.user)
                or minutes_left(session.user) <= 0):
            hang_up(session)
            ended += 1
    # Retry hangups OpenAI hasn't confirmed (calls cap at 60 minutes anyway).
    for session in VoiceSession.objects.filter(ended_at__isnull=False, remote_ended=False,
                                               started_at__gte=now - timedelta(hours=2)):
        hang_up(session)
    return ended


def heartbeat(session, *, ended=False):
    """Advance the server-side clock; enforce the monthly cap mid-call."""
    now = timezone.now()
    # Conditional update: a stale instance can never write ended_at back to
    # NULL over a concurrent hangup.
    fields = {'last_seen_at': now}
    if ended:
        fields['ended_at'] = now
    VoiceSession.objects.filter(pk=session.pk, ended_at__isnull=True).update(**fields)
    session.refresh_from_db(fields=['last_seen_at', 'ended_at'])
    return session.ended_at is None and minutes_left(session.user) > 0 if not ended else False


def run_tool(session, viewer, name, arguments, analyses_left=0):
    """Execute one server tool the realtime model called. Returns JSON text.
    Analyses claim their slot under the user's lock against a fresh session."""
    if name not in SERVER_TOOLS:
        return json.dumps({'error': f'herramienta no disponible: {name}'}), TurnResult(reply='')
    try:
        args = json.loads(arguments or '{}')
    except (TypeError, ValueError):
        args = {}
    result = TurnResult(reply='')

    def reserve():
        from django.db import transaction

        from .service import analyses_left as left_today, lock_user
        with transaction.atomic():
            lock_user(session.user)
            if left_today(session.user) <= 0:
                return False
            row = VoiceSession.objects.select_for_update().get(pk=session.pk)
            row.tools = (row.tools or []) + [{'name': 'analyze_finances', 'reserved': True}]
            row.save(update_fields=['tools'])
            return True

    belt = Toolbelt(viewer, result, analyses_left=0, reserve_analysis=reserve)
    try:
        output = belt.call(name, args)
    except AssistantUnavailable:
        output = {'error': 'No pude consultarlo ahora.'}
    except Exception:  # noqa: BLE001 - a broken tool must read as broken
        logger.exception('Confío IA voice tool %s failed', name)
        output = {'error': 'La herramienta falló.'}
    from django.db import transaction
    with transaction.atomic():
        row = VoiceSession.objects.select_for_update().get(pk=session.pk)
        tools = list(row.tools or [])
        if name == 'analyze_finances' and any(t.get('reserved') for t in tools):
            # Settle the reservation instead of counting this analysis twice.
            index = max(i for i, t in enumerate(tools) if t.get('reserved'))
            tools[index] = {'name': name, 'ok': 'error' not in output}
        elif name != 'analyze_finances':
            tools.append({'name': name, 'ok': 'error' not in output})
        row.tools = tools
        row.cost_usd = row.cost_usd + result.cost_usd
        row.save(update_fields=['tools', 'cost_usd'])
    return json.dumps(output, ensure_ascii=False)[:12000], result


def record_usage(session, usage):
    """Accumulate response.done usage for cost reporting."""
    usage = usage or {}
    details_in = usage.get('input_token_details') or {}
    details_out = usage.get('output_token_details') or {}
    counts = {
        'audio_in': int(details_in.get('audio_tokens') or 0),
        'text_in': int(details_in.get('text_tokens') or 0),
        'cached_in': int(details_in.get('cached_tokens') or 0),
        'audio_out': int(details_out.get('audio_tokens') or 0),
        'text_out': int(details_out.get('text_tokens') or 0),
    }
    totals = dict(session.usage or {})
    for key, value in counts.items():
        totals[key] = int(totals.get(key, 0)) + max(value, 0)
    session.usage = totals
    prices = (conf.get('CONFIO_IA_REALTIME_PRICES') or {}).get(session.model)
    if prices:
        audio_in, audio_out, text_in, text_out, cached_in = (Decimal(str(p)) for p in prices)
        million = Decimal(1_000_000)
        session.cost_usd = session.cost_usd + (
            Decimal(counts['audio_in']) * audio_in + Decimal(counts['audio_out']) * audio_out
            + Decimal(max(counts['text_in'] - counts['cached_in'], 0)) * text_in
            + Decimal(counts['cached_in']) * cached_in + Decimal(counts['text_out']) * text_out
        ) / million
    session.save(update_fields=['usage', 'cost_usd'])


MODALITY = TurnModality.REALTIME
