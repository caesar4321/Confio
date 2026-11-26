"""Glue between the support thread (inbox) and the engine: limits, mode, persistence."""
from __future__ import annotations

import base64
import binascii
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from inbox.models import SupportMessage
from inbox.push_service import send_support_staff_push
from inbox.schema import get_or_create_support_conversation

from . import confirm, photos
from . import conf, context as context_rules, guide, memory
from .engine import (AssistantUnavailable, Viewer, categorize_movements, general_while_waiting, human_mode_active,
                     run_turn, third_party_text)
from .models import AssistantProfile, AssistantThreadState, AssistantTurn, TurnModality
from .prompts import prompt_echo, transcribe_hint
from security.geo import country_of

logger = logging.getLogger(__name__)

UNAVAILABLE_REPLY = (
    'Ahora mismo no puedo responder. Vuelve a intentarlo en un momento. '
    'Si te falta dinero, no vuelvas a pagar y guarda el comprobante.'
)
LIMIT_REPLY = (
    'Llegaste al límite de mensajes con Confio Assistant por hoy. Mañana seguimos. '
    'Si te falta dinero, no vuelvas a pagar y guarda el comprobante. Si es un fraude, '
    'no compartas códigos ni claves y repórtalo hoy a tu banco.'
)
# Stored with the message, so the person sees it in their own bubble too.
TRUNCATED_INPUT_NOTE = '… [mensaje recortado]'
# Beside a prepared payment the reply may never say it was paid.
PAID_CLAIM = re.compile(
    r'\b(ya\s+(se\s+|lo\s+|la\s+|está\s+|quedó\s+|fue\s+)?(pag|envi|transfer)'
    r'|(pago|transferencia|env[ií]o)\s+(fue\s+|está\s+|quedó\s+)?(realizad|hech|completad|exitos|enviad|confirmad|list)'
    r'|qued[oó]\s+pagad|fue\s+pagad|se\s+pagó|he\s+pagado|pagué|pagad[oa]\b)', re.IGNORECASE)
CARD_CLAIM = re.compile(r'\b(tarjeta|revisar\s+y\s+pagar)\b', re.IGNORECASE)
from .engine import PAYMENT_PREPARED_REPLY  # noqa: E402


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


def _viewer(user, account, business, jwt_context, *, screen='', tz_name=None, request_meta=None):
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
        tz=_resolve_tz(tz_name, country_of(user)),
        screen=(screen or '')[:64],
        request_meta=dict(request_meta or {}),
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


def _tool_uses_today(user, name):
    from .models import VoiceSession

    since = timezone.now() - timedelta(hours=24)
    tool_lists = list(turns_today(user).values_list('tools', flat=True)) + list(
        VoiceSession.objects.filter(user=user, started_at__gte=since).values_list('tools', flat=True))
    return sum(1 for tools in tool_lists for tool in (tools or []) if tool.get('name') == name)


def analyses_left(user):
    cap = conf.get('CONFIO_ASSISTANT_PLUS_DAILY_ANALYSES' if _plus(user) else 'CONFIO_ASSISTANT_DAILY_ANALYSES')
    return max(cap - _tool_uses_today(user, 'analyze_finances'), 0)


def news_searches_left(user):
    cap = conf.get('CONFIO_ASSISTANT_PLUS_DAILY_NEWS_SEARCHES' if _plus(user)
                   else 'CONFIO_ASSISTANT_DAILY_NEWS_SEARCHES')
    return max(cap - _tool_uses_today(user, 'search_market_news'), 0)


def web_searches_left(user):
    cap = conf.get('CONFIO_ASSISTANT_PLUS_DAILY_WEB_SEARCHES' if _plus(user)
                   else 'CONFIO_ASSISTANT_DAILY_WEB_SEARCHES')
    return max(cap - _tool_uses_today(user, 'search_web'), 0)


def _account_label(viewer, business):
    if business is not None:
        role = 'dueño' if viewer.is_business_owner else 'empleado'
        # Set by the owner: quoted, one line, short (it sits in the instructions).
        return f'negocio "{third_party_text(business.name, 60)}" ({role})'
    return 'personal'


def _append(conversation, **kwargs):
    message = SupportMessage.objects.create(conversation=conversation, message_type='TEXT', **kwargs)
    conversation.last_message_at = message.created_at
    conversation.save(update_fields=['last_message_at', 'updated_at'])
    return message


def send_team_notice(conversation, body, tag, *, user_id, hand_back=True):
    """A team message written outside the support portal (an ops script),
    pushed to the person after commit, idempotent on ``tag`` per conversation.

    It has no staff user, so it never counts as the team answering: without
    ``hand_back`` a thread in human mode (after a handoff or a staff reply)
    stays with the team and the AI goes silent on the person's next questions
    (Johan, 2026-11-16). By default the thread goes back to the AI; a later
    handoff or staff reply takes it again. The portal still lists the thread
    as awaiting the team until a person replies there, as with return_to_ai.
    Always shown as the team, never as Confio Assistant.
    Returns (message, created)."""
    from inbox.push_service import send_support_reply_push
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError('tag required')
    if not (body or '').strip():
        raise ValueError('body required')
    if conversation.user_id != user_id:
        raise ValueError('conversation does not belong to that user')
    with transaction.atomic():
        lock_user(conversation.user)
        existing = conversation.messages.filter(metadata__notice=tag).first()
        if existing is not None:
            return existing, False
        state = thread_state(conversation)
        message = _append(conversation, sender_type='AGENT', body=body, metadata={'notice': tag})
        if hand_back and is_human_mode(conversation, state):
            state.returned_to_ai_at = timezone.now()
            state.save(update_fields=['returned_to_ai_at', 'updated_at'])

        def push():
            try:
                send_support_reply_push(message.id)
            except Exception:  # noqa: BLE001 - the message is in the thread either way
                logger.exception('Team notice push failed: %s', message.id)
        transaction.on_commit(push)
    return message, True


def _withdraw_while_human(user, account, conversation, clean, user_message):
    from types import SimpleNamespace

    from . import sends
    try:
        withdrawn = sends.withdraw_declined(conversation, SimpleNamespace(account=account), clean, user_message)
        if withdrawn is not None:
            _note_in_thread(conversation, withdrawn[1], f'withdrawn:{user_message.pk}', answered=withdrawn[2])
    except Exception:  # noqa: BLE001 - the team has the message either way
        logger.exception('Confio Assistant: a card could not be withdrawn while the team has the thread')


_DONE = {'alert_deleted': {'es': 'borré la alerta', 'pt': 'apaguei o alerta', 'en': 'I deleted the alert'},
         'target_allocation': {'es': 'olvidé tu objetivo de reparto', 'pt': 'esqueci seu objetivo de divisão',
                               'en': 'I forgot your target split'}}


def _done_already(result, lang):
    """What this reply already did (a card withdrawn, result.writes), said when its words are replaced."""
    refused = f' {result.payment_refusal}' if result.declined and result.payment_refusal else ''
    return refused + _writes_said(result, lang)


def _writes_said(result, lang):
    """What this reply already changed (result.writes), as one sentence, or ''."""
    lang = lang if lang in ('es', 'pt', 'en') else 'es'
    done = [(_DONE.get(write) or {}).get(lang) for write in (result.writes or [])]
    done = [d for d in dict.fromkeys(done) if d]
    if not done:
        return ''
    return {'es': ' Además, {}.', 'pt': ' Além disso, {}.', 'en': ' Also, {}.'}[lang].format(', '.join(done))


def _say_anyway(conversation, result, lang, user_message):
    """The team has the thread and the assistant stays quiet: what code already did is still a server line."""
    said = _done_already(result, lang).strip()
    if said:
        try:
            # A card withdrawn or a code refused in that reply: the line is code's answer to that code too.
            answered = {'declined': True, 'refused_code': getattr(result, 'refused_code', '')} if getattr(
                result, 'declined', False) else None
            _note_in_thread(conversation, said, f'done:{user_message.pk}', answered=answered)
        except Exception:  # noqa: BLE001 - the team has the message either way
            logger.exception('Confio Assistant: what was already done could not be said')


def _note_in_thread(conversation, body, tag, answered=None):
    """A server line in this very thread (the one the card is in), once per tag. `answered`: a withdrawal's
    extra, so the line counts as code's answer to that code (sends._warned, confirm._ends)."""
    answered = answered or {}
    said = {key: answered[key] for key in ('declined', 'refused_code') if answered.get(key)}
    with transaction.atomic():
        lock_user(conversation.user)
        if conversation.messages.filter(metadata__notice=tag).exists():
            return
        message = SupportMessage.objects.create(conversation=conversation, sender_type='SYSTEM', message_type='TEXT',
                                                body=body, metadata={'notice': tag, 'system_note': True,
                                                                     'actions': [], **said})
        conversation.last_message_at = message.created_at
        conversation.save(update_fields=['last_message_at', 'updated_at'])


def post_system_note(user, body, tag, *, actions=None, rule_proposal=None, payment_intent=None):
    """A server-side notice in the user's PERSONAL assistant thread (the
    support thread Confio Assistant answers), e.g. a claim on their Cuenta
    inteligente. Shown as a system line, like the greeting: never as the
    team (no staff user, no hand-back) and never as an AI reply. Idempotent
    on ``tag`` per thread, so a retried caller does not post twice. No push:
    the caller's own notification carries one. ``actions`` are chips written
    by code; ``rule_proposal`` is a Cuenta inteligente rule proposal the app
    opens through assistantRuleProposal; ``payment_intent`` ({'id': ...}) is a
    prepared payment the app draws through assistantPaymentIntent. Returns (message, created),
    or (None, False) for a user without a personal account."""
    from users.models import Account
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError('tag required')
    if not (body or '').strip():
        raise ValueError('body required')
    personal = Account.objects.filter(
        user=user, account_type='personal', account_index=0, deleted_at__isnull=True).first()
    if personal is None:
        return None, False
    with transaction.atomic():
        lock_user(user)
        conversation = get_or_create_support_conversation(user, personal, None)
        existing = conversation.messages.filter(metadata__notice=tag).first()
        if existing is not None:
            return existing, False
        message = SupportMessage.objects.create(
            conversation=conversation, sender_type='SYSTEM', message_type='TEXT', body=body,
            metadata={'notice': tag, 'system_note': True, 'actions': list(actions or []),
                      **({'rule_proposal': rule_proposal} if rule_proposal else {}),
                      **({'payment_intent': payment_intent} if payment_intent else {})})
        conversation.last_message_at = message.created_at
        conversation.save(update_fields=['last_message_at', 'updated_at'])
    return message, True


TEAM_PUSH_WINDOW = timedelta(minutes=10)
TEAM_PUSHES_PER_WINDOW = 5


def _route_to_team(message):
    message.metadata = {**(message.metadata or {}), 'to_team': True}
    message.save(update_fields=['metadata'])
    # Every message still reaches the team's queue; only the phone pings are
    # rate-limited, so one person can't flood the team's notifications.
    recent = SupportMessage.objects.filter(
        conversation_id=message.conversation_id, metadata__to_team=True,
        created_at__gte=timezone.now() - TEAM_PUSH_WINDOW).count()
    if recent > TEAM_PUSHES_PER_WINDOW:
        return

    def push():
        try:
            send_support_staff_push(message.id)
        except Exception:
            logger.exception('Confio Assistant: staff push failed', extra={'message_id': message.id})

    # After commit: the push must never point at a message that rolled back.
    transaction.on_commit(push)


def card_actions(actions):
    """What may stand in a reply that carries a payment card: the card, and the
    top-up form left for a balance that does not cover it (engine.SHORT_TOPUP_FORM)."""
    from .engine import SHORT_TOPUP_FORM
    return [a for a in actions if a.get('target') == 'payment_intent'
            or all(a.get(key) == value for key, value in SHORT_TOPUP_FORM.items())]


def ask(user, account, business, jwt_context, body=None, *, audio=None, screen='', tz_name=None,
        can_navigate=True, request_meta=None, guide_step='', pending_message=None, photo=None):
    """Answer `body` (or a voice note: audio=(base64, mime, duration_ms)) in
    the user's support thread. photo=(base64, mime): a picture sent with the
    typed words (or with none); see assistant/photos.py.

    Quota is RESERVED under a short per-user lock (a pending AssistantTurn
    counts at once); transcription and model calls run outside the lock, so a
    slow model never blocks the user's other requests.

    can_navigate=False for app builds that predate Confio Assistant: they can't
    open screens, so the model must not claim it did.
    pending_message: answer this already-recorded user message (written while
    the team had the thread) instead of recording a new one.
    Raises ValueError (bad input) / AssistantUnavailable (transcription down).
    """
    screen = (screen or '')[:64]
    remembering = memory.screen_on(request_meta)
    photo = photo if photo and not audio else None
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
        if photo:
            # Refused in words before the costly part, and nothing is recorded:
            # people cannot open a photo (it is not kept), and a photo is
            # never read for someone with no turns left.
            if human:
                raise ValueError(photos.TEAM_CANNOT_SEE)
            if remaining <= 0:
                raise ValueError(photos.NO_TURNS)

    # Checked and shrunk before the message is recorded: a bad file is a plain
    # error, never a message in the thread.
    photo_url = None
    if photo:
        with photos.reading(user):
            photo_url = photos.prepare(*photo)

    # 2. Transcribe (no lock).
    modality, audio_seconds, transcript = TurnModality.TEXT, 0, None
    if audio:
        try:
            transcript, audio_seconds = transcribe(*audio, country=country_of(user) or '')
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

    limit = conf.get('CONFIO_ASSISTANT_MAX_INPUT_CHARS')
    clean = (body or '').strip()
    if not clean and photo_url:
        clean = photos.ONLY_BODY
    if not clean:
        raise ValueError('Message body is required')
    if len(clean) > limit:
        # Pasted text: the person and the assistant both see it was cut.
        clean = clean[:limit] + TRUNCATED_INPUT_NOTE

    # 3. Record the message and route it (short lock). Human mode is checked
    # again here: staff may have replied while the note was transcribing.
    with transaction.atomic():
        lock_user(user)
        state = thread_state(conversation)
        human = is_human_mode(conversation, state) or not conf.get('CONFIO_ASSISTANT_ENABLED')
        if pending_message is not None:
            # Re-checked under the lock: a second tap, or a reply that landed
            # meanwhile, means there is nothing left to answer.
            if (human or pending_message.conversation_id != conversation.id
                    or pending_message.id != getattr(_last_message(conversation), 'id', None)
                    # Answered, or being answered by an overlapping tap. A voice
                    # note's metering turn (no reply, not pending) doesn't count.
                    or AssistantTurn.objects.filter(user_message=pending_message)
                    .filter(Q(reply_message__isnull=False) | Q(error='pending')).exists()):
                return None
            user_message, proposal = pending_message, None
            pending_watch = pending_action = None
        else:
            if photo_url and (human or remaining_turns(user) <= 0):
                # Changed while the photo was being read (the team took the
                # thread, the last turn went to another message): the same
                # refusals as above, and still nothing recorded.
                raise ValueError(photos.TEAM_CANNOT_SEE if human else photos.NO_TURNS)
            user_message = _append(conversation, sender_type='USER', sender_user=user, body=clean,
                                   metadata={'modality': photos.MODALITY if photo_url else modality,
                                             'screen': screen})
            if remembering:
                memory.saw(conversation, user_message)
            # A proposal lives for exactly one user message, whatever path it takes.
            proposal = take_pending_categorization(conversation)
            pending_watch = take_pending_watch(conversation)
            pending_action = confirm.take(conversation)
        if turn is not None:
            turn.user_message = user_message
            turn.save(update_fields=['user_message'])
        # The team owns the thread: the message always reaches them, and a plain
        # question about how the app works still gets an answer meanwhile.
        waiting = human and conf.get('CONFIO_ASSISTANT_ENABLED') and general_while_waiting(clean)
        if remembering and memory.asks_to_forget(conversation, clean) and (
                human or (turn is None and remaining_turns(user) <= 0)):
            # "olvida todo" needs no model and no turn: it holds while the team
            # has the thread and after the day's last turn too.
            memory.forget_unanswered(conversation, user_message, clean)
        if human:
            _route_to_team(user_message)
            # "No lo pagues" under a card is still honoured while the team has the thread, also inside a how-to
            # question answered meanwhile ("¿cómo sé si un pix es golpe?"): the card is withdrawn (after this lock
            # is let go) and a server line says so; the message is the team's.
            transaction.on_commit(lambda: _withdraw_while_human(user, account, conversation, clean,
                                                                user_message))
            if not waiting:
                return AskOutcome(user_message=user_message, reply_message=None, mode='HUMAN',
                                  transcript=transcript)
        if turn is None:
            remaining = remaining_turns(user)
            if remaining <= 0 and not human:
                # No turn left: "no lo pagues" under a card is still honoured (no model is needed for it).
                transaction.on_commit(lambda: _withdraw_while_human(user, account, conversation, clean,
                                                                    user_message))
            if remaining <= 0 and waiting:
                # Out of turns while waiting: the team answers, no limit notice.
                return AskOutcome(user_message=user_message, reply_message=None, mode='HUMAN',
                                  transcript=transcript)
            if remaining <= 0:
                reply = _append(conversation, sender_type='AGENT', body=LIMIT_REPLY,
                                metadata={'ai': True, 'limit': True})
                return AskOutcome(user_message=user_message, reply_message=reply, remaining_turns=0,
                                  transcript=transcript)
            turn = AssistantTurn.objects.create(user=user, conversation=conversation, user_message=user_message,
                                                screen=screen, modality=modality, error='pending')

    if photo_url:
        # Held for follow-up questions only once its turn is reserved, and
        # outside the lock (a slow cache must not hold the person's row).
        photos.keep(user_message, photo_url)

    # 4. Answer (no lock; analyses reserve their own slot).
    viewer = _viewer(user, account, business, jwt_context, screen=screen, tz_name=tz_name,
                     request_meta=request_meta)
    if remembering and memory.asks_to_forget(conversation, clean):
        # "ok olvida todo" is not the yes to a pending question; "olvídalo" to code's question is its no.
        proposal = pending_watch = None
        if not (pending_action and confirm.is_no(clean)):
            pending_action = None
    if pending_action and not waiting and not photo_url:
        answered = confirm.answer(conversation, viewer, clean, pending_action, user_message,
                                  can_navigate=can_navigate)
        if answered is not None:
            return _answer_to_question(conversation, viewer, user_message, turn, pending_action, answered,
                                       remaining=remaining - 1, transcript=transcript)
    if not waiting:          # a photo's caption ("no lo pagues, es estafa") withdraws too
        from . import sends
        withdrawn = sends.withdraw_declined(conversation, viewer, clean, user_message)
        if withdrawn is not None:
            return _answer_to_question(conversation, viewer, user_message, turn, {'kind': 'payment', 'lang': (
                confirm.language([clean])), 'withdrawal': True}, withdrawn, remaining=remaining - 1,
                transcript=transcript)
    confirmed = None
    if proposal is not None or pending_watch is not None:
        # The "sí" that saves a category or an alert: under the person's lock, and never once the team took the
        # thread or anyone wrote after it (a reply from the team, their own "no, cancela").
        with transaction.atomic():
            lock_user(user)
            taken = is_human_mode(conversation, thread_state(conversation)) or any(
                not (m.sender_type == 'USER' and confirm.plain(m.body) == confirm.plain(clean))   # a "sí" sent twice
                for m in conversation.messages.filter(created_at__gt=user_message.created_at).exclude(
                    sender_type='SYSTEM'))
            if not taken:
                confirmed = confirm_pending_categorization(conversation, viewer, clean, proposal, user_message)
                confirmed_tool = 'categorize_transactions:confirmed'
                if confirmed is None:
                    confirmed = confirm_pending_watch(conversation, viewer, clean, pending_watch, user_message)
                    confirmed_tool = ('notify_rail:confirmed' if (pending_watch or {}).get('notice_rail')
                                      else 'smart_account_alerts:confirmed')
                if confirmed is not None:
                    applied, reply_text = confirmed
                    reply = _append(conversation, sender_type='AGENT', body=reply_text, metadata={'ai': True})
    if confirmed is not None:
        turn.reply_message = reply
        turn.tools = [{'name': confirmed_tool, 'ok': applied > 0}]
        turn.error = ''
        turn.save(update_fields=['reply_message', 'tools', 'error'])
        return AskOutcome(user_message=user_message, reply_message=reply, remaining_turns=remaining - 1,
                          mode='HUMAN' if waiting else 'AI', transcript=transcript, data_changed=applied > 0)
    if waiting:
        # Only this question: without the thread (their case, the team's
        # replies) and without personal tools, the answer can't touch the case.
        history = [user_message]
    else:
        history = list(conversation.messages.order_by('-created_at')[:conf.get('CONFIO_ASSISTANT_HISTORY_MESSAGES')])
        history.reverse()
    started = time.monotonic()
    # "recuerda…" / "olvida…": the write and its confirmation are code's. Read
    # after `history`, so nothing that arrives meanwhile becomes the message answered.
    remembered = None if waiting or not remembering else memory.handle_message(conversation, user_message, clean)
    if remembered is not None and remembered.reply:
        return _memory_reply(user, conversation, user_message, turn, remembered, remaining, transcript,
                             audio_seconds, started)
    # Only what the model is shown. Every guard goes on reading `history`.
    turn_context = None if waiting else context_rules.load(
        conversation, history, memory_note=remembered.note if remembered else '', answering=user_message,
        remembering=remembering)
    # The photo sent just now is seen even if the cache lost it.
    seen_photos = {**photos.for_history(history), **({user_message.id: photo_url} if photo_url else {})}
    try:
        result = run_turn(
            viewer, history,
            first_name=user.first_name,
            account_label=_account_label(viewer, business),
            country=country_of(user),
            analyses_left=0,
            reserve_analysis=_analysis_reserver(user, turn),
            reserve_news=_tool_reserver(user, turn, 'search_market_news', news_searches_left),
            reserve_web=_tool_reserver(user, turn, 'search_web', web_searches_left),
            can_navigate=can_navigate,
            waiting_for_team=bool(waiting),
            photos=seen_photos,
            **({'context': turn_context} if turn_context is not None else {}),
            guide_note='' if waiting else guide.steering_note(
                guide_step, country_of(user), viewer=viewer, request_meta=viewer.request_meta),
        )
    except AssistantUnavailable as exc:
        logger.warning('Confio Assistant unavailable: %s', exc)
        if seen_photos:
            photos.forget([m for m in history if m.id in seen_photos])
        metered = _meter_partial(turn, getattr(exc, 'partial', None))
        if remembered is not None:
            metered = _meter_partial(turn, remembered.usage) or metered
        if waiting or _team_took_over(user, conversation, user_message):
            if getattr(exc, 'partial', None) is not None:
                _say_anyway(conversation, exc.partial, confirm.language([clean]), user_message)
            if remembered is not None and memory.said_by_code(remembered):
                memory.note_to_thread(conversation, memory.said_by_code(remembered, confirm.language([clean])),
                                      user_message.id)
            turn.error = (f'unavailable while waiting for the team ({str(exc)[:200]})' if waiting
                          else f'superseded by human handoff ({str(exc)[:200]})')
            turn.latency_ms = int((time.monotonic() - started) * 1000)
            turn.save(update_fields=['error', 'latency_ms', *metered])
            return AskOutcome(user_message=user_message, reply_message=None, mode='HUMAN',
                              remaining_turns=remaining - 1, transcript=transcript)
        # What they asked of memory already happened, or didn't: said whether or not the model can answer.
        lang = confirm.language([clean])
        line = memory.said_by_code(remembered, lang) if remembered is not None else ''
        unavailable = {'pt': 'Agora não consigo responder. Tente de novo em um momento. Se faltar dinheiro, não pague '
                             'de novo e guarde o comprovante.',
                       'en': "I can't answer right now. Try again in a moment. If money is missing, don't pay again "
                             'and keep the receipt.'}.get(lang, UNAVAILABLE_REPLY)
        partial = getattr(exc, 'partial', None)
        if getattr(partial, 'declined', False) and partial.payment_refusal:
            unavailable = partial.payment_refusal     # why the code was refused is the reply: it needs no model
        reply = _append(conversation, sender_type='AGENT',
                        body=f'{line}\n\n{unavailable}' if line else unavailable,
                        # A code they said not to pay stays refused: pasted again alone, it gets its card.
                        metadata={'ai': True, 'error': True,
                                  **({'declined': True} if getattr(partial, 'declined', False) else {}),
                                  **({'refused_code': partial.refused_code}
                                     if getattr(partial, 'declined', False) and getattr(partial, 'refused_code', '')
                                     else {})})
        turn.refresh_from_db(fields=['tools'])
        turn.error = str(exc)[:280]
        turn.reply_message = reply
        turn.latency_ms = int((time.monotonic() - started) * 1000)
        turn.save()
        return AskOutcome(user_message=user_message, reply_message=reply, remaining_turns=remaining - 1,
                          transcript=transcript)

    if remembered is not None:
        _add_spend(result, remembered.usage)

    # The team may have taken the thread while the model was answering: then
    # the AI stays quiet (no reply, no screen actions) and the message waits
    # for people. The turn is still metered.
    if not waiting and _team_took_over(user, conversation, user_message):
        _retire_unshown(result.payment_intent)
        _say_anyway(conversation, result, confirm.language([clean]), user_message)
        if remembered is not None and memory.said_by_code(remembered):
            # The team has the thread and the assistant stays quiet: what happened to their memory is code's note.
            memory.note_to_thread(conversation, memory.said_by_code(remembered, confirm.language([clean])),
                                  user_message.id)
        turn.models_used = result.models_used
        turn.input_tokens = result.input_tokens
        turn.cached_input_tokens = result.cached_input_tokens
        turn.output_tokens = result.output_tokens
        turn.cost_usd = result.cost_usd + transcription_cost(audio_seconds)
        turn.google_cost_usd = result.google_cost_usd
        turn.tools = result.tools
        turn.error = 'superseded by human handoff'
        turn.latency_ms = int((time.monotonic() - started) * 1000)
        turn.save()
        return AskOutcome(user_message=user_message, reply_message=None, mode='HUMAN',
                          remaining_turns=remaining - 1, transcript=transcript,
                          data_changed=bool(result.writes))

    # At most one paid-offer chip, chosen and capped by the server.
    paid_chip = None
    if result.payment_intent or waiting:
        result.pending_action = None
    if result.payment_intent:
        result.pending_categorization = result.pending_watch = None     # the card is the one thing in it
    elif result.declined and result.payment_refusal:
        # They said not to pay it: code says so, and the message ends what a later payment reads; what else this
        # reply already changed (an alert deleted, a split forgotten) is said beside it. Nothing to fill, pay or
        # sign stays beside the "no".
        result.reply = result.payment_refusal + _writes_said(result, confirm.language([clean]))
        if getattr(result, 'store_task_started', False) and not getattr(result, 'store_task_said', False):
            result.reply += {'pt': ' A compra na loja que comecei nesta mensagem continua em andamento: confira ou '
                                   'cancele lá.',
                             'en': ' The store purchase I started in this message is still going: check or cancel '
                                   'it there.'}.get(confirm.language([clean]),
                                                    ' La compra en la tienda que empecé en este mensaje sigue en '
                                                    'curso: revísala o cancélala ahí.')
        result.rule_proposal = result.pending_action = None
        result.pending_watch = result.pending_categorization = None
        result.actions = [a for a in result.actions if a.get('type') not in ('trade', 'form', 'payment')
                          and a.get('target') not in ('payment_intent', 'smart_account_rule', 'ia_plus',
                                                      'cuenta_inteligente')]
    if result.pending_action:
        # The question is written by code and is the whole reply: nothing beside it to answer, open or sign.
        result.actions, result.rule_proposal = [], None
        result.pending_categorization = result.pending_watch = None
        result.reply = result.pending_action['question']
    if result.payment_intent:
        # The card is the reply's one action (see engine.PAYMENT_CHIP).
        result.actions = card_actions(result.actions)
        # One thing to sign per reply: the card.
        result.rule_proposal = None
        if PAID_CLAIM.search(result.reply or ''):
            # Nothing is paid until the owner signs: a reply that says
            # otherwise is replaced by the plain fact.
            result.reply = PAYMENT_PREPARED_REPLY
    elif result.payment_refusal and (PAID_CLAIM.search(result.reply or '') or CARD_CLAIM.search(result.reply or '')):
        # No payment was prepared: a reply that points at a card or claims a
        # payment is replaced by the reason the server gave.
        result.reply = result.payment_refusal
    from_memory = bool(turn_context is not None and turn_context.used_data)
    # A WhatsApp reply card (whatsapp_link/chat.py, posted by its tool) is a card too: no offer beside it.
    whatsapp_card = bool(getattr(result, 'whatsapp_card', False))
    if waiting or from_memory or result.rule_proposal or result.payment_intent or whatsapp_card:
        # No offers while a person is handling their case, and none beside a
        # Cuenta inteligente proposal (its chip is the reply's one chip). The
        # proposal chip targets 'smart_account_rule', so it stays.
        result.actions = [a for a in result.actions if a.get('target') not in ('ia_plus', 'cuenta_inteligente')]
    try:
        from . import paid_chips
        from .engine import allowed_destinations
        if (not waiting and not from_memory and not result.rule_proposal and not result.payment_intent
                and not result.pending_action and not result.declined and not whatsapp_card):
            earlier = ' · '.join(m.body or '' for m in [m for m in history if m.sender_type == 'USER'][-3:-1])
            paid_chip = paid_chips.choose(viewer, clean, result, set(allowed_destinations(viewer)), earlier)
    except Exception:  # noqa: BLE001 - a probe must never break the answer
        logger.exception('Confio Assistant: paid chip selection failed')
        result.actions = [a for a in result.actions if a.get('target') not in ('ia_plus', 'cuenta_inteligente')]
    body = result.reply
    # What happened to their memory, in code's words: said whenever the reply is code's (the model's words,
    # and with them what a note asked it to say, are not in it).
    line = ''
    if remembered is not None:
        # In the language of the reply it goes beside: code's own lines are Spanish, a question is in theirs.
        from .engine import NOTICE_LEAD
        # The notice's lead is said in their language below (pending_watch), so its line follows them too.
        line = memory.said_by_code(remembered, (result.pending_action or {}).get('lang') or confirm.language(
            [result.reply if _written_by_code(result) and result.reply != NOTICE_LEAD else clean]))
    if line and _written_by_code(result):
        body = f'{line}\n\n{body}'
    if result.pending_categorization:
        # The question the user answers is written by code from the stored
        # proposal, never by the model, in the language they wrote in.
        result.pending_categorization['lang'] = confirm.language([clean])
        body = f'{body}\n\n{confirmation_question(result.pending_categorization)}'
    elif result.pending_watch:
        result.pending_watch['lang'] = confirm.language([clean])
        from .engine import NOTICE_LEAD
        if result.reply == NOTICE_LEAD and result.pending_watch['lang'] in _NOTICE_LEADS:
            body = body.replace(NOTICE_LEAD, _NOTICE_LEADS[result.pending_watch['lang']])
        body = f'{body}\n\n{watch_confirmation_question(result.pending_watch)}'
    metadata = {'ai': True, 'actions': result.actions}
    # Her kept WhatsApp messages were read for this answer, so it may quote them: tagged, to go with that link
    # (whatsapp_link.chat.erase). Unlinked while it was being thought: what it found is not kept at all.
    whatsapp_read = getattr(result, 'whatsapp_read', None)
    if (whatsapp_read is None and _follows_whatsapp_answer(history) and _whatsapp_grant(user)
            and not (result.payment_intent or result.rule_proposal or result.pending_action)):
        # No search this time, but the answer right before this question quoted them, so this one may too ("¿y a qué
        # hora dijo?"): it goes with the link as well. One step only, under its own mark: an answer after this one
        # is not marked by it, or one search would mark, and one unlink blank, the whole conversation.
        metadata['whatsapp_follow'] = True
    if whatsapp_read is not None:
        if _whatsapp_still_linked(user, whatsapp_read):
            metadata['whatsapp_read'] = True
        else:
            body = _with_line(line, _WHATSAPP_UNLINKED.get(confirm.language([clean]), _WHATSAPP_UNLINKED['es']))
            result.actions = metadata['actions'] = []
    if result.rule_proposal:
        metadata['rule_proposal'] = result.rule_proposal
    if result.payment_intent:
        # Only the id: the app draws the card from the server's row
        # (assistantPaymentIntent), never from this reply's text.
        metadata['payment_intent'] = {'id': result.payment_intent['id']}
    if turn_context is not None and turn_context.used_data:
        metadata['recalled'] = True
    if result.declined and not result.payment_intent:
        metadata['declined'] = True
        if getattr(result, 'refused_code', ''):
            metadata['refused_code'] = result.refused_code     # the code this answered (sends._warned)
    if result.payment_intent and result.payment_intent.get('code'):
        metadata['payment_intent']['code'] = result.payment_intent['code']
    with transaction.atomic():
        lock_user(user)
        reply = None
        if not waiting and is_human_mode(conversation, thread_state(conversation)):
            # The team took the thread after the last look: nothing from the assistant, the message is theirs.
            _retire_unshown(result.payment_intent)
            transaction.on_commit(lambda: _say_anyway(conversation, result, confirm.language([clean]), user_message))
            _route_to_team(user_message)
        else:
            later = list(conversation.messages.filter(created_at__gt=user_message.created_at)
                         .exclude(sender_type='SYSTEM'))
            if (result.payment_intent or result.rule_proposal) and not any(m.sender_type == 'USER' for m in later) and any(
                    m.sender_type == 'AGENT' and not (m.metadata or {}).get('ai') for m in later):
                # The team spoke while this was being thought ("no pagues nada ahora"): no card under their words.
                said = confirm.language([clean])
                body = _with_line(line, ({
                    'pt': 'Não preparei o cartão: chegou uma mensagem da equipe nesse meio-tempo. Se ainda quiser, '
                          'cole o código de novo.',
                    'en': "I didn't prepare the card: a message from the team arrived meanwhile. If you still want "
                          'it, paste the code again.'} if result.payment_intent else {
                    'pt': 'Não preparei a proposta: chegou uma mensagem da equipe nesse meio-tempo. Se ainda quiser, '
                          'me peça de novo.',
                    'en': "I didn't prepare the proposal: a message from the team arrived meanwhile. If you still "
                          'want it, ask me again.'}).get(said,
                    'No preparé la tarjeta: llegó un mensaje del equipo mientras tanto. Si todavía lo quieres, pega '
                    'el código de nuevo.' if result.payment_intent else
                    'No preparé la propuesta: llegó un mensaje del equipo mientras tanto. Si todavía la quieres, '
                    'pídemela de nuevo.') + _writes_said(result, said))
                _retire_unshown(result.payment_intent)
                result.pending_action = result.payment_intent = result.rule_proposal = None
                metadata.pop('payment_intent', None)
                metadata.pop('rule_proposal', None)
                result.actions = metadata['actions'] = []
            elif (result.pending_action or result.payment_intent or result.pending_watch
                  or result.pending_categorization or result.rule_proposal) and any(
                    m.sender_type == 'USER' for m in later):
                # They wrote while this was being thought ("no lo pagues", "no espera, mejor a 150"): no question,
                # no card and nothing to save about the older message. (The team writing puts the thread in their
                # hands: checked just above.)
                said = (result.pending_action or {}).get('lang') or confirm.language([clean])
                body = _with_line(line, {'pt': 'Vi sua mensagem nova: me diga de novo o que você quer fazer.',
                                         'en': 'I saw your new message: tell me again what you want to do.'}.get(
                    said, 'Vi tu mensaje nuevo: dime de nuevo qué quieres hacer.') + _done_already(result, said))
                _retire_unshown(result.payment_intent)
                result.pending_action = result.payment_intent = None     # an unattached card is unreachable
                result.pending_watch = result.pending_categorization = None     # their questions are not stored
                result.rule_proposal = None
                metadata.pop('payment_intent', None)
                metadata.pop('rule_proposal', None)
                result.actions = metadata['actions'] = []
            reply = _append(conversation, sender_type='AGENT', body=body, metadata=metadata)
            if result.pending_action:
                try:
                    confirm.store(conversation, viewer, result.pending_action, reply)
                except Exception:  # noqa: BLE001 - a question nobody can answer is not left in the thread
                    logger.exception('Confio Assistant: a question could not be kept')
                    lost_lang = (result.pending_action or {}).get('lang')
                    result.pending_action = None
                    reply.body = _with_line(line, _COULD_NOT_KEEP_QUESTION.get(
                        lost_lang, _COULD_NOT_KEEP_QUESTION['es']))
                    reply.save(update_fields=['body'])
    if reply is not None and metadata.get('whatsapp_read'):
        # Unlinked between the check above and this save: that unlink's erase may have run before this reply
        # existed. Erasing again is harmless; it blanks this one too. Checked now, for what is answered, and once
        # more when everything around this is committed: an unlink after that erases the reply itself.
        if not _erase_if_unlinked(user, whatsapp_read):
            reply.refresh_from_db()
            result.actions = []
        transaction.on_commit(lambda: _erase_if_unlinked(user, whatsapp_read))
    if reply is None:
        if line:
            memory.note_to_thread(conversation, line, user_message.id)   # it happened: said all the same
        turn.models_used = result.models_used
        turn.input_tokens = result.input_tokens
        turn.cached_input_tokens = result.cached_input_tokens
        turn.output_tokens = result.output_tokens
        turn.cost_usd = result.cost_usd + transcription_cost(audio_seconds)
        turn.google_cost_usd = result.google_cost_usd
        turn.tools = result.tools
        turn.error = 'superseded by human handoff'
        turn.latency_ms = int((time.monotonic() - started) * 1000)
        turn.save()
        return AskOutcome(user_message=user_message, reply_message=None, mode='HUMAN',
                          remaining_turns=remaining - 1, transcript=transcript, data_changed=bool(result.writes))
    if turn_context is not None:
        memory.after_reply(conversation, turn_context.forgot, reply)
    if result.payment_intent and not _attach(result.payment_intent['id'], reply, line, confirm.language([clean]),
                                             also=_writes_said(result, confirm.language([clean]))):
        result.actions = []
    if paid_chip is not None:
        try:
            paid_chips.log_shown(viewer, paid_chip)
        except Exception:  # noqa: BLE001 - analytics never break the reply
            logger.exception('Confio Assistant: paid chip logging failed')
    if result.pending_categorization:
        _store_pending_categorization(conversation, viewer, result.pending_categorization, reply)
    elif result.pending_watch:
        _store_pending_watch(conversation, viewer, result.pending_watch, reply)
    turn.reply_message = reply
    turn.models_used = result.models_used
    turn.input_tokens = result.input_tokens
    turn.cached_input_tokens = result.cached_input_tokens
    turn.output_tokens = result.output_tokens
    turn.cost_usd = result.cost_usd + transcription_cost(audio_seconds)
    turn.google_cost_usd = result.google_cost_usd
    turn.tools = result.tools
    turn.actions = result.actions
    turn.error = ''
    turn.latency_ms = int((time.monotonic() - started) * 1000)
    turn.save()
    if remembering and not waiting:
        memory.schedule_summary(conversation)

    return AskOutcome(user_message=user_message, reply_message=reply, actions=result.actions,
                      mode='HUMAN' if waiting else 'AI',
                      remaining_turns=remaining - 1, transcript=transcript, data_changed=bool(result.writes))


_WHATSAPP_UNLINKED = {
    'es': 'Tu WhatsApp se desvinculó mientras te respondía, así que no guardé lo que encontré en tus mensajes.',
    'pt': 'Seu WhatsApp foi desvinculado enquanto eu respondia, então não guardei o que encontrei nas suas mensagens.',
    'en': 'Your WhatsApp was unlinked while I was answering, so I did not keep what I found in your messages.',
}


def _follows_whatsapp_answer(history) -> bool:
    """Is the last thing said before the message being answered an answer that read her WhatsApp messages?"""
    for said in reversed(history):
        if getattr(said, 'sender_type', '') == 'USER':
            continue
        return bool((getattr(said, 'metadata', None) or {}).get('whatsapp_read'))
    return False


def _whatsapp_grant(user) -> str:
    try:
        from whatsapp_link import assistant_tool
        return assistant_tool.grant_of(user)
    except Exception as exc:  # noqa: BLE001 - by type only; '' reads as unlinked: the answer is not kept
        logger.warning('Confio Assistant: WhatsApp link lookup failed (%s)', type(exc).__name__)
        return ''


def _whatsapp_still_linked(user, grant) -> bool:
    """Is the WhatsApp an answer read still the one linked? Unknown counts as no: the answer is not kept."""
    try:
        from whatsapp_link import assistant_tool
        return bool(grant) and assistant_tool.reading(user, grant)
    except Exception as exc:  # noqa: BLE001 - by type only
        logger.warning('Confio Assistant: WhatsApp link check failed (%s)', type(exc).__name__)
        return False


def _erase_if_unlinked(user, grant) -> bool:
    """True while the WhatsApp an answer read is still linked; else what was said about it is erased now."""
    if _whatsapp_still_linked(user, grant):
        return True
    from whatsapp_link import chat as whatsapp_chat
    whatsapp_chat.erase(user)
    return False


def _by_team(message):
    """A person of the team wrote it. Never the assistant, never a notice: the server's (a SYSTEM line) nor the
    team's (send_team_notice, which hands the thread back to the assistant)."""
    return (message.sender_type == 'AGENT' and getattr(message, 'sender_user_id', None) is not None
            and not (message.metadata or {}).get('ai'))


def _with_line(line, text):
    return f'{line}\n\n{text}' if line else text


_COULD_NOT_KEEP_QUESTION = {
    'es': 'No pude dejarte la pregunta ahora. Pídemelo de nuevo en un momento.',
    'pt': 'Não consegui deixar a pergunta agora. Me peça de novo em um momento.',
    'en': "I couldn't keep the question now. Ask me again in a moment."}


def _retire_unshown(intent):
    """A card made for this answer and then dropped (the team spoke, they wrote again): nobody can reach it, and
    it is closed so it never counts as one of the hour's cards."""
    intent_id = (intent or {}).get('id') if isinstance(intent, dict) else None
    if not intent_id:
        return
    try:
        from django.utils import timezone as tz

        from payment_accounts.models import PaymentIntent
        with transaction.atomic():     # a savepoint: a failure here never breaks the reply around it
            PaymentIntent.objects.filter(internal_id=intent_id, state__in=('quoted', 'awaiting_signature')).update(
                state='expired', state_reason='dropped_in_chat', updated_at=tz.now())
    except Exception:  # noqa: BLE001 - it stays unreachable all the same
        logger.warning('Confio Assistant: a dropped card could not be closed', exc_info=True)


def _attach(intent_id, reply, line='', lang='es', also=''):
    """The card is on this message. If it can't be, the message says so and offers no button."""
    try:
        from payment_accounts import payment_intents
        payment_intents.attach_message(intent_id, reply.pk, retire_earlier=True)
        return True
    except Exception:  # noqa: BLE001 - the card stays unreachable (fails closed)
        logger.exception('Confio Assistant: payment intent not attached to its message')
        _retire_unshown({'id': intent_id})
        lines = {'es': 'No pude dejarte la tarjeta del pago. Pídemelo de nuevo en un momento.',
                 'pt': 'Não consegui deixar o cartão do pagamento. Me peça de novo em um momento.',
                 'en': "I couldn't leave the payment card. Ask me again in a moment."}
        reply.body = _with_line(line, lines.get(lang, lines['es']) + also)
        reply.metadata = {**(reply.metadata or {}), 'actions': [], 'payment_intent': None}
        reply.save(update_fields=['body', 'metadata'])
        return False


def _written_by_code(result):
    """The reply holds none of the model's words (so none of what a note asked it to say)."""
    from .engine import CUT_EMPTY, DONE_REPLY, NOTICE_LEAD, PAYMENT_PREPARED_REPLY, SAVED_CHANGES_REPLY
    return bool(result.pending_action) or result.reply in {
        PAYMENT_PREPARED_REPLY, DONE_REPLY, SAVED_CHANGES_REPLY, CUT_EMPTY, NOTICE_LEAD,
        *([result.payment_refusal] if result.payment_refusal else [])}


def _answer_to_question(conversation, viewer, user_message, turn, pending, answered, *, remaining, transcript):
    """The reply to an answer to code's question (confirm.py): written by code, never the model.

    Under the person's lock: if the team took the thread (or a person of the team wrote) meanwhile, the
    assistant says nothing and the answer goes to them; if they wrote something else after it, no card is left
    and nothing is saved (a save waits for these checks: `deferred`, assistant/asked.py)."""
    done, text, extra = answered
    lang = pending.get('lang') if pending.get('lang') in ('es', 'pt', 'en') else 'es'
    made = extra.get('payment_intent')
    with transaction.atomic():
        lock_user(viewer.user)
        later = list(conversation.messages.filter(created_at__gt=user_message.created_at))
        reply = None
        if is_human_mode(conversation, thread_state(conversation)) or any(_by_team(m) for m in later):
            if pending.get('withdrawal') and text:
                # The card was withdrawn already: that is said, as a server line, while the team has the thread.
                said = dict(extra)
                transaction.on_commit(lambda: _note_in_thread(conversation, text, f'withdrawn:{user_message.pk}',
                                                              answered=said))
            done, extra = False, {}
            _route_to_team(user_message)
        else:
            wrote_again = any(m.sender_type == 'USER' and not confirm.same_answer(m.body, user_message.body, pending)
                              for m in later)
            # A team notice (send_team_notice: the team's words, no staff user) after the answer ends it too.
            team_spoke = any(m.sender_type == 'AGENT' and not (m.metadata or {}).get('ai') for m in later)
            # Asking again is preparing too: once the team spoke or they wrote again, the question stays closed.
            # (A refusal's top-up form is not something prepared.)
            preparing = ((done and extra.get('actions')) or extra.get('deferred') or extra.get('rule_proposal')
                         or extra.get('ask_again'))
            if preparing and team_spoke and not wrote_again:
                done, extra = False, {}
                text = {'es': 'No preparé nada: llegó un mensaje del equipo mientras tanto. Si todavía lo quieres, '
                              'pídemelo de nuevo.',
                        'pt': 'Não preparei nada: chegou uma mensagem da equipe nesse meio-tempo. Se ainda quiser, '
                              'me peça de novo.',
                        'en': "I didn't prepare anything: a message from the team arrived meanwhile. If you still "
                              'want it, ask me again.'}[lang]
            elif preparing and wrote_again:
                # They wrote again while it was being prepared ("no, cancela"): no card, nothing saved.
                done, extra = False, {}
                text = {'es': 'No preparé nada: escribiste algo después. Si todavía lo quieres, pídemelo de nuevo.',
                        'pt': 'Não preparei nada: você escreveu depois. Se ainda quiser, me peça de novo.',
                        'en': "I didn't prepare anything: you wrote after that. If you still want it, ask me "
                              'again.'}[lang]
            elif extra.get('deferred'):
                try:
                    with transaction.atomic():      # a failed save leaves nothing half-saved, and the reply goes out
                        done, text, extra = extra['deferred']()
                except Exception:  # noqa: BLE001 - nothing saved is said as such
                    logger.exception('Confio Assistant: an answered change could not be saved')
                    done, extra = False, {}
                    text = {'es': 'No pude guardarlo ahora. Inténtalo de nuevo.',
                            'pt': 'Não consegui salvar agora. Tente de novo.',
                            'en': "I couldn't save it now. Please try again."}[lang]
            actions = list(extra.get('actions') or [])
            metadata = {'ai': True, 'actions': actions}
            if extra.get('payment_intent'):
                metadata['payment_intent'] = extra['payment_intent']
            if extra.get('declined'):
                metadata['declined'] = True     # answered: never asked again (confirm.recent_texts)
            if extra.get('refused_code'):
                metadata['refused_code'] = extra['refused_code']     # the code this answered (sends._warned)
            if extra.get('rule_proposal'):
                metadata['rule_proposal'] = extra['rule_proposal']     # the proposal they review and sign
            reply = _append(conversation, sender_type='AGENT', body=text, metadata=metadata)
        if made and not extra.get('payment_intent'):
            _retire_unshown(made)
        if reply is not None and extra.get('ask_again'):
            try:
                confirm.store(conversation, viewer, pending, reply)
            except Exception:  # noqa: BLE001 - a question nobody can answer is not left in the thread
                logger.exception('Confio Assistant: a question could not be kept')
                reply.body = _COULD_NOT_KEEP_QUESTION[lang]
                reply.save(update_fields=['body'])
    if reply is None:
        turn.tools = [{'name': f"{pending.get('kind')}:answered", 'ok': False}]
        turn.error = 'superseded by human handoff'
        turn.save(update_fields=['tools', 'error'])
        return AskOutcome(user_message=user_message, reply_message=None, mode='HUMAN', remaining_turns=remaining,
                          transcript=transcript)
    actions = list(extra.get('actions') or [])
    if extra.get('payment_intent') and not _attach(extra['payment_intent']['id'], reply, lang=lang):
        actions = []
    turn.reply_message = reply
    turn.tools = [{'name': f"{pending.get('kind')}:answered", 'ok': bool(done)}]
    turn.actions = actions
    turn.error = ''
    turn.save(update_fields=['reply_message', 'tools', 'actions', 'error'])
    return AskOutcome(user_message=user_message, reply_message=reply, actions=actions, remaining_turns=remaining,
                      mode='AI', transcript=transcript, data_changed=bool(extra.get('writes')))


# --------------------------------------------------------------------------- #
# Categorizing needs the user's own "sí"
# --------------------------------------------------------------------------- #

PENDING_CATEGORIZATION_SECONDS = 15 * 60


def is_affirmative(text, kind='alert'):
    """The yes that saves an alert or a category: a whole answer of yes and courtesy words (confirm.is_save_yes).
    "sí, mañana", "ok lo pienso" and "sí ❌" are none."""
    return confirm.is_save_yes(text, kind)


def _not_typed(message):
    """A photo's caption, a voice note, or a line a client relayed, answers no question (as for a card)."""
    metadata = message.metadata or {}
    return bool(metadata.get('client_reported')) or str(metadata.get('modality') or 'TEXT').upper() != 'TEXT'


def _pending_key(conversation):
    return f'assistant:pending-categorization:{conversation.id}'


def confirmation_question(proposal):
    count = proposal['count']
    noun = 'movimiento' if count == 1 else 'movimientos'
    who = f' ({", ".join(proposal["contacts"])})' if proposal.get('contacts') else ''
    scope = ', también los pagos futuros a esos contactos' if proposal['apply_to'] == 'counterparty' else ''
    lang = proposal.get('lang')
    if lang == 'pt':
        noun = 'movimento' if count == 1 else 'movimentos'
        scope = ', também os pagamentos futuros a esses contatos' if proposal['apply_to'] == 'counterparty' else ''
        return f'Confirma classificar {count} {noun}{who} como {proposal["label"]}{scope}? Responda "sim" para salvar.'
    if lang == 'en':
        noun = 'movement' if count == 1 else 'movements'
        scope = ', and future payments to those contacts too' if proposal['apply_to'] == 'counterparty' else ''
        return f'Shall I classify {count} {noun}{who} as {proposal["label"]}{scope}? Reply "yes" to save it.'
    return f'¿Confirmas clasificar {count} {noun}{who} como {proposal["label"]}{scope}? Responde "sí" para guardarlo.'


def _store_pending_categorization(conversation, viewer, proposal, reply):
    cache.set(_pending_key(conversation), {**proposal, 'account_id': viewer.account.id, 'reply_id': reply.id},
              PENDING_CATEGORIZATION_SECONDS)


def take_pending_categorization(conversation):
    """Remove and return the open proposal: every user message consumes it."""
    key = _pending_key(conversation)
    proposal = cache.get(key)
    if proposal is not None:
        cache.delete(key)
    return proposal


_SAVED_NOTHING = {'es': 'Listo, no guardé nada.', 'pt': 'Certo, não salvei nada.', 'en': 'OK, I saved nothing.'}


def confirm_pending_categorization(conversation, viewer, text, proposal, user_message):
    """Apply `proposal` if this message is the user's yes to it.

    The model only proposes (its tool input can be steered by text other
    people wrote, like a sender's name); the write happens here, in code, on
    the user's own reply — and only as the answer to the very message that
    showed the code-written question. Returns (applied_count, reply) or None."""
    if proposal is None or proposal.get('account_id') != viewer.account.id or _not_typed(user_message):
        return None
    yes, no = is_affirmative(text, 'category'), confirm.is_no(text)
    if not yes and not no:
        return None
    previous = confirm.previous_message(conversation, user_message)     # a server notice is nobody's words
    if previous != proposal.get('reply_id'):
        return None
    if no:
        return 0, _SAVED_NOTHING.get(proposal.get('lang'), _SAVED_NOTHING['es'])
    result = categorize_movements(viewer, proposal['ids'], proposal['category'], proposal['apply_to'])
    count = int(result.get('clasificados') or 0)
    lang = proposal.get('lang')
    future = proposal['apply_to'] == 'counterparty'
    if not result.get('ok'):
        return 0, {'pt': 'Não consegui salvar essa classificação; talvez esses movimentos não estejam mais disponíveis.',
                   'en': "I couldn't save that classification; those movements may no longer be available."}.get(
            lang, 'No pude guardar esa clasificación; puede que esos movimientos ya no estén disponibles.')
    if lang == 'pt':
        noun = 'movimento' if count == 1 else 'movimentos'
        scope = ' Também vale para os pagamentos futuros a esses contatos.' if future else ''
        return count, f'Pronto, classifiquei {count} {noun} como {result["categoria"]}.{scope} Você vê em Tu mes.'
    if lang == 'en':
        noun = 'movement' if count == 1 else 'movements'
        scope = ' It also applies to future payments to those contacts.' if future else ''
        return count, f'Done, I classified {count} {noun} as {result["categoria"]}.{scope} You can see it in Tu mes.'
    noun = 'movimiento' if count == 1 else 'movimientos'
    scope = ' También aplica a los pagos futuros a esos contactos.' if future else ''
    return count, f'Listo, clasifiqué {count} {noun} como {result["categoria"]}.{scope} Puedes verlo en Tu mes.'


# A Cuenta inteligente alert (smart_account/watches.py) is saved the same way:
# the model only drafts it, the question is written by code, and the row is
# written here on the person's own "sí" to that very message.

def _pending_watch_key(conversation):
    return f'assistant:pending-watch:{conversation.id}'


def _watch_terms(draft):
    """The alert's terms in the language of the question (describe() is Spanish)."""
    from decimal import Decimal

    from smart_account import watches
    lang = draft.get('lang')
    if lang not in ('pt', 'en'):
        return draft['texto']
    return watches.describe_in(lang, draft['kind'], asset_key=draft.get('asset_key') or '',
                               currency=draft.get('currency') or '', threshold=Decimal(draft['threshold']),
                               action=draft.get('action') or None)


_NOTICE_QUESTION = {'es': '¿Te aviso aquí cuando esté disponible? Responde "sí" para anotarte.',
                    'pt': 'Aviso você aqui quando estiver disponível? Responda "sim" para eu anotar.',
                    'en': 'Shall I let you know here when it is available? Reply "yes" to sign up.'}
_NOTICE_JOINED = {'es': 'Listo, te anoté: te aviso cuando esté disponible. Todavía no hay fecha.',
                  'pt': 'Pronto, anotei: aviso você quando estiver disponível. Ainda não há data.',
                  'en': "Done, you're on the list: I'll let you know when it's available. There's no date yet."}
_NOTICE_LEADS = {'pt': 'Por enquanto não está disponível, e ainda não há data.',
                 'en': "It isn't available yet, and there's no date."}
_NOTICE_UPDATE = {'es': 'Ya está disponible: actualiza Confío desde la tienda para usarlo.',
                  'pt': 'Já está disponível: atualize o Confío na loja para usar.',
                  'en': "It's available now: update Confío from the store to use it."}
_NOTICE_OTHER = {'es': 'Ya no hace falta anotarte: pregúntame por ese medio y te digo cómo está para ti.',
                 'pt': 'Não precisa mais anotar: me pergunte por esse meio e eu digo como está para você.',
                 'en': "There's nothing to sign up for anymore: ask me about it and I'll tell you where it stands "
                       'for you.'}
_NOTICE_UNKNOWN = {'es': 'No pude anotarte ahora. Pídemelo otra vez en un rato.',
                   'pt': 'Não consegui anotar agora. Peça de novo daqui a pouco.',
                   'en': "I couldn't sign you up right now. Ask me again in a bit."}
_NOTICE_OPEN = {'es': 'Ya está disponible, así que no hace falta anotarte: pregúntame cómo usarlo.',
                'pt': 'Já está disponível, então não precisa anotar: me pergunte como usar.',
                'en': "It's available already, so there's nothing to sign up for: ask me how to use it."}


def watch_confirmation_question(draft):
    if draft.get('notice_rail'):
        # A payment method's "Próximamente" notice (pay_rails.notify): the same yes path as an alert.
        return _NOTICE_QUESTION.get(draft.get('lang'), _NOTICE_QUESTION['es'])
    terms = _watch_terms(draft)
    if draft.get('lang') == 'pt':
        return f'Salvo este alerta? {terms} Responda "sim" para salvar.'
    if draft.get('lang') == 'en':
        return f'Shall I save this alert? {terms} Reply "yes" to save it.'
    return f'¿Guardo esta alerta? {terms} Responde "sí" para guardarla.'


def _store_pending_watch(conversation, viewer, draft, reply):
    cache.set(_pending_watch_key(conversation), {**draft, 'user_id': viewer.user.pk, 'reply_id': reply.id},
              PENDING_CATEGORIZATION_SECONDS)


def take_pending_watch(conversation):
    key = _pending_watch_key(conversation)
    draft = cache.get(key)
    if draft is not None:
        cache.delete(key)
    return draft


def confirm_pending_watch(conversation, viewer, text, draft, user_message):
    """Save the drafted alert if this message is the yes to it. Returns
    (saved, reply) or None."""
    if draft is None or draft.get('user_id') != viewer.user.pk or _not_typed(user_message):
        return None
    yes, no = is_affirmative(text, 'notice' if draft.get('notice_rail') else 'alert'), confirm.is_no(text)
    if not yes and not no:
        return None
    previous = confirm.previous_message(conversation, user_message)     # a server notice is nobody's words
    if previous != draft.get('reply_id'):
        return None
    if no and draft.get('notice_rail'):
        return 0, {'pt': 'Certo, não anotei.', 'en': "OK, I didn't sign you up."}.get(draft.get('lang'),
                                                                                    'Listo, no te anoté.')
    if no:
        return 0, _SAVED_NOTHING.get(draft.get('lang'), _SAVED_NOTHING['es'])
    if draft.get('notice_rail'):
        from . import pay_rails
        lang = draft.get('lang') if draft.get('lang') in ('pt', 'en') else 'es'
        joined = pay_rails.join(viewer, draft['notice_rail'])
        if joined == 'joined':
            return 1, _NOTICE_JOINED[lang]
        return 0, {'open': _NOTICE_OPEN, 'update': _NOTICE_UPDATE, 'other': _NOTICE_OTHER}.get(
            joined, _NOTICE_UNKNOWN)[lang]
    from smart_account import watches
    from smart_account.assistant_ops import OpsRefused
    try:
        watches.save(viewer.user, draft)
    except OpsRefused as exc:
        return 0, exc.message
    terms = _watch_terms(draft)
    if draft.get('lang') == 'pt':
        return 1, (f'Pronto, salvei seu alerta. {terms} Só aviso: nada é comprado nem vendido sem sua assinatura. '
                   'Você o vê na sua Cuenta inteligente → Alertas.')
    if draft.get('lang') == 'en':
        return 1, (f"Done, I saved your alert. {terms} I only let you know: nothing is bought or sold without your "
                   'signature. You can see it in your Cuenta inteligente → Alertas.')
    return 1, (f'Listo, guardé tu alerta. {terms} Solo te aviso: nada se compra ni se vende sin tu firma. '
               'La ves en tu Cuenta inteligente → Alertas.')


def _team_took_over(user, conversation, user_message):
    """Re-read ownership after the model ran: if people own the thread now,
    the message is routed to them and the AI publishes nothing."""
    with transaction.atomic():
        lock_user(user)
        if is_human_mode(conversation, thread_state(conversation)):
            _route_to_team(user_message)
            return True
    return False


def _meter_partial(turn, partial):
    """Add usage a failed turn already spent (tokens, searches) to its row.
    Returns the fields to save."""
    if partial is None:
        return []
    turn.models_used = list(dict.fromkeys([*(turn.models_used or []), *partial.models_used]))
    turn.input_tokens += partial.input_tokens
    turn.cached_input_tokens += partial.cached_input_tokens
    turn.output_tokens += partial.output_tokens
    turn.cost_usd = (turn.cost_usd or 0) + partial.cost_usd
    turn.google_cost_usd = (turn.google_cost_usd or 0) + partial.google_cost_usd
    return ['models_used', 'input_tokens', 'cached_input_tokens', 'output_tokens', 'cost_usd', 'google_cost_usd']


def _add_spend(result, extra):
    """A second model call of the same turn (reading a memory request)."""
    result.models_used = list(dict.fromkeys([*result.models_used, *extra.models_used]))
    result.input_tokens += extra.input_tokens
    result.cached_input_tokens += extra.cached_input_tokens
    result.output_tokens += extra.output_tokens
    result.cost_usd += extra.cost_usd
    result.google_cost_usd += extra.google_cost_usd


def _memory_reply(user, conversation, user_message, turn, remembered, remaining, transcript, audio_seconds,
                  started):
    """The code-written answer to "recuerda…" / "olvida…"."""
    usage = remembered.usage
    turn.models_used = usage.models_used
    turn.input_tokens = usage.input_tokens
    turn.cached_input_tokens = usage.cached_input_tokens
    turn.output_tokens = usage.output_tokens
    turn.cost_usd = usage.cost_usd + transcription_cost(audio_seconds)
    turn.google_cost_usd = usage.google_cost_usd
    turn.tools = [{'name': 'memory', 'ok': True}]
    turn.latency_ms = int((time.monotonic() - started) * 1000)
    taken = _team_took_over(user, conversation, user_message)
    if taken:
        memory.note_to_thread(conversation, remembered.reply, user_message.id)   # it happened: said all the same
    reply = None if taken else _append(conversation, sender_type='AGENT', body=remembered.reply,
                                       metadata={'ai': True, 'memory': True})
    turn.reply_message = reply
    turn.error = 'superseded by human handoff' if taken else ''
    turn.save()
    return AskOutcome(user_message=user_message, reply_message=reply, mode='HUMAN' if taken else 'AI',
                      remaining_turns=remaining - 1, transcript=transcript)


def _tool_reserver(user, turn, name, left):
    """Claim one metered slot (short lock) before an expensive tool runs."""
    def reserve():
        with transaction.atomic():
            lock_user(user)
            if left(user) <= 0:
                return False
            row = AssistantTurn.objects.select_for_update().get(pk=turn.pk)
            row.tools = (row.tools or []) + [{'name': name, 'reserved': True}]
            row.save(update_fields=['tools'])
            return True
    return reserve


def _analysis_reserver(user, turn):
    """Claim one analysis slot before the model calls Sol."""
    return _tool_reserver(user, turn, 'analyze_finances', analyses_left)


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
            # Relayed by the client, not produced here: shown in the thread
            # but never fed back to the model, and marked for the team.
            saved.append(_append(conversation, sender_type='AGENT', body=text,
                                 metadata={'ai': True, 'client_reported': True,
                                           'modality': TurnModality.REALTIME}))
    return saved


def _last_message(conversation):
    # A WhatsApp notice the server posted (whatsapp_link/chat.py) answers nobody: it never hides their last message.
    return conversation.messages.exclude(sender_type='SYSTEM').exclude(metadata__has_key='whatsapp').order_by(
        '-created_at', '-id').first()


def unanswered_after_handoff(conversation, state):
    """The user's last message when nobody has answered it since the handoff
    (they wrote while the team had the thread and then came back), else None."""
    last = _last_message(conversation)
    # Human mode starts at a handoff or at the team's own first reply.
    since = max([t for t in (state.handoff_at, last_staff_reply_at(conversation)) if t], default=None)
    if last is None or last.sender_type != 'USER' or since is None or last.created_at < since:
        return None
    if (last.metadata or {}).get('handoff_note') or not (last.body or '').strip():
        return None
    return last


def return_to_ai(user, account, business, jwt_context=None, *, request_meta=None, screen='', tz_name=None):
    """Back to the AI. A question left unanswered while the team had the
    thread is answered now (Brahayan, 2026-11-11: two questions, no reply)."""
    conversation = get_or_create_support_conversation(user, account, business)
    state = thread_state(conversation)
    pending = unanswered_after_handoff(conversation, state)
    state.returned_to_ai_at = timezone.now()
    state.save(update_fields=['returned_to_ai_at', 'updated_at'])
    # Out of turns: no limit notice just for coming back.
    if (pending is not None and jwt_context is not None and conf.get('CONFIO_ASSISTANT_ENABLED')
            and remaining_turns(user) > 0):
        try:
            outcome = ask(user, account, business, jwt_context, pending.body, screen=screen, tz_name=tz_name,
                          request_meta=request_meta, pending_message=pending)
            if outcome is not None and outcome.mode == 'HUMAN':
                conversation.returned_mode = 'HUMAN'  # people took the thread meanwhile
        except Exception:  # noqa: BLE001 - coming back must work even if the answer fails
            logger.exception('Confio Assistant: answering the pending message after return failed')
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
        stsz = (_child(data, *stbl, b'stsz') or _child(data, *stbl, b'stz2')) if stbl else None
        if mdhd is None or stts is None or stsz is None:
            continue
        try:
            version = data[mdhd[0]]
            timescale = struct.unpack('>I', data[mdhd[0] + (20 if version == 1 else 12):][:4])[0]
            count = struct.unpack('>I', data[stts[0] + 4:stts[0] + 8])[0]
            if stts[0] + 8 + count * 8 > stts[1]:
                continue
            total = 0
            timed_samples = 0
            for n in range(count):
                samples, delta = struct.unpack('>II', data[stts[0] + 8 + n * 8:stts[0] + 16 + n * 8])
                total += samples * delta
                timed_samples += samples
            # A short timing table with more samples than it times makes
            # decoders reuse the last delta: the file plays longer than stts says.
            if struct.unpack('>I', data[stsz[0] + 8:stsz[0] + 12])[0] != timed_samples:
                continue
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


def transcribe(audio_base64, mime_type, duration_ms, *, country=''):
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
            data={'model': conf.get('CONFIO_ASSISTANT_TRANSCRIBE_MODEL'), 'response_format': 'json',
                  'prompt': transcribe_hint(country)},
            timeout=conf.get('CONFIO_ASSISTANT_REQUEST_TIMEOUT_SECONDS'),
        )
    except requests.RequestException as exc:
        raise AssistantUnavailable(f'transcription failed: {exc}') from exc
    if response.status_code >= 400:
        raise AssistantUnavailable(f'transcription {response.status_code}: {response.text[:200]}')
    try:
        data = response.json()
    except ValueError as exc:
        # Never show a parser message to the user (AskAssistant returns ValueError text).
        raise AssistantUnavailable('transcription returned an unreadable response') from exc
    usage = data.get('usage') or {}
    if usage.get('type') == 'duration' and usage.get('seconds'):
        # The provider measured the audio: meter what it actually billed.
        seconds = max(seconds, float(usage['seconds']))
    text = (data.get('text') or '').strip()
    # On a silent note the transcriber can return its own hint: no question was asked.
    return ('' if prompt_echo(text) else text), seconds
