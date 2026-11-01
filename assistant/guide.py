"""First-steps guide: the assistant starts the conversation and walks a person
to the first top-up, then to a first real use of the money.

The app renders one generic contract (text, chips, pointer), so a new
situation needs a server change, not a build. The server picks the step and
its actions; the model only words the sentence, and a fixed line stands in
when it is slow, wrong or down. The assistant never moves a screen by itself:
every move is a chip the person taps.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, replace
from datetime import timedelta

from django.core.cache import cache
from django.db.models import F
from django.utils import timezone

from security.geo import country_of

from . import conf
from .rails import topup_entry, topup_route
from .suggestions import GUIDE_ANSWERS, GUIDE_ANSWERS_SHORT, PROBE_ID, _didit_stage, _state, record_probe_answer

logger = logging.getLogger(__name__)

# A step is never over by itself: what ends it is the real record (a top-up, a
# send, a purchase). Saying no only rests it, the person still needs the step.
SHOWN_REST = timedelta(hours=24)
ACCEPTED_REST = timedelta(hours=24)
DISMISSED_REST = timedelta(days=3)
MAX_EVENTS_PER_DAY = 200
# A position that really reached Hyperliquid, not a refunded attempt.
PERP_OPENED_STATES = ('funded', 'open', 'closed', 'liquidated', 'returning', 'return_failed', 'landed', 'done')
PREVIEW_SECONDS = 7 * 24 * 3600
OPEN_ORDER_DAYS = 3
TEXT_CACHE_SECONDS = 24 * 3600
FALLBACK_CACHE_SECONDS = 300
MAX_TEXT_CHARS = 240
EVENTS = {'shown', 'accepted', 'dismissed', 'replied', 'opened', 'pointer_shown', 'pointer_missing',
          'pointer_tapped', 'pointer_closed'}
LATER = 'Ahora no'


@dataclass(frozen=True)
class TrailStop:
    """What to say on one screen of a walk. No pointer: only the sentence."""
    route: str
    text: str
    pointer: str = ''


@dataclass(frozen=True)
class Chip:
    label: str
    kind: str  # navigate | probe | dismiss
    destination: str = ''
    pointer: str = ''
    answer: str = ''
    trail: tuple = ()


def _go(label, destination, pointer=''):
    return (Chip(label, 'navigate', destination=destination, pointer=pointer), Chip(LATER, 'dismiss'))


@dataclass(frozen=True)
class Step:
    stage: str
    text: str  # also the fallback when the model doesn't answer
    brief: str = ''  # what the model should say; empty keeps the fixed text
    chips: tuple = ()
    pointer_text: str = ''


STEPS = {
    'opening': Step(
        'opening', '¿Para qué te gustaría usar Confío?',
        brief='Salúdala por su nombre, di que eres su asistente y pregúntale para qué le gustaría usar Confío.',
        chips=(*(Chip(label, 'probe', answer=key) for key, label in GUIDE_ANSWERS), Chip(LATER, 'dismiss'))),
    'verify': Step(
        'verify', 'Para recargar, primero necesitas verificar tu identidad.',
        brief='Dile que para recargar primero debe verificar su identidad y pregúntale si empiezan ahora.',
        chips=_go('Sí, empezar', 'verification', 'verify_start'),
        pointer_text='Toca aquí para verificar tu identidad.'),
    'verifying': Step('verifying', 'Tu verificación sigue en revisión.'),
    'top_up': Step(
        'top_up', 'Ya puedes recargar.',
        brief='Dile que ya puede recargar (en la app se llama {entry}) y que la llevas a Recibir para mostrarle dónde tocar. '
              'Pregúntale si van.',
        chips=_go('Sí, ir a Recargar', 'receive', 'recharge_now'),
        pointer_text='Toca aquí para crear tu recarga.'),
    'top_up_update': Step('top_up_update', 'Actualiza Confío para poder recargar con Pago Móvil.'),
    'awaiting_payment': Step(
        'awaiting_payment', 'Tu orden de recarga sigue esperando el pago.',
        brief='Dile que su orden de recarga sigue esperando el pago y pregúntale si le muestras dónde verla.',
        chips=_go('Sí, muéstrame', 'receive', 'recharge_now'),
        pointer_text='Toca aquí para ver tu recarga.'),  # the order's row, per country below
    'international_soon': Step(
        'international_waitlist', 'La recarga internacional llegará a tu país en unas dos semanas. '
        'Mientras tanto, puedes recibir USDT desde Binance u otra billetera.',
        chips=_go('Ver cómo recibir USDT', 'receive', 'advanced_receive'),
        pointer_text='Toca aquí para ver tu dirección de USDT.'),
    'international': Step(
        'international_top_up', 'Ya puedes recargar desde tu país.',
        chips=_go('Sí, ir a Recargar', 'receive', 'recharge_now'),
        pointer_text='Toca aquí para crear tu recarga.'),
    'usdt': Step(
        'usdt_only', 'Puedes recibir USDT desde Binance u otra billetera.',
        brief='Dile que puede poner dólares recibiendo USDT desde Binance u otra billetera y pregúntale si le muestras cómo.',
        chips=_go('Ver cómo recibir USDT', 'receive', 'advanced_receive'),
        pointer_text='Toca aquí para ver tu dirección de USDT.'),
    'send': Step(
        'first_action', '¿Te muestro cómo enviarle a alguien?',
        brief='Dile que ya tiene dólares en Confío y pregúntale si le muestras cómo enviarle a alguien.',
        chips=_go('Sí, enviar', 'send')),
    # Fixed on purpose: no generated sentence may lean towards an investment.
    # The options come from _invest_options, each with its walk to the purchase.
    'invest': Step('first_action', '¿Qué te gustaría comprar? Tú eliges, y el precio puede subir o bajar.'),
    'comprar': Step(
        'first_action', '¿Quieres conocer Comprar?',
        brief='Pregúntale si quiere conocer Comprar, donde vendedores verificados venden productos.',
        chips=_go('Sí, ver Comprar', 'comprar')),
}
# The walk never names an asset: the person picks, the last tap is theirs.
_CONFIRM = 'Revisa el monto y el costo. Si estás de acuerdo, confirma.'
INVEST_OPTIONS = {
    'stocks': Chip('Acciones', 'navigate', destination='invest', answer='stocks', trail=(
        TrailStop('Invest', 'Toca aquí para ver las acciones.', 'invest_stocks'),
        TrailStop('StocksList', 'Elige la que tú quieras. Yo no te recomiendo ninguna.'),
        TrailStop('StockDetail', 'Si quieres comprarla, toca aquí.', 'asset_buy'),
        TrailStop('BuyStock', _CONFIRM, 'asset_confirm'),
    )),
    'crypto': Chip('Oro y Bitcoin', 'navigate', destination='invest', answer='crypto', trail=(
        TrailStop('Invest', 'Elige aquí oro o Bitcoin.', 'invest_crypto'),
        TrailStop('CryptoDetail', 'Si quieres comprarlo, toca aquí.', 'asset_buy'),
        TrailStop('BuyCrypto', _CONFIRM, 'asset_confirm'),
    )),
    'perps': Chip('Futuros', 'navigate', destination='invest', answer='perps', trail=(
        TrailStop('Invest', 'Toca aquí para ver los futuros.', 'invest_futures'),
        TrailStop('FuturesMarkets', 'Elige el mercado que tú quieras. Yo no te recomiendo ninguno.'),
        TrailStop('FuturesMarket', 'Largo gana si sube y corto si baja. Con apalancamiento puedes perder tu margen.'),
        TrailStop('FuturesOrder', 'Revisa el margen, el apalancamiento y el costo antes de seguir.', 'asset_confirm'),
    )),
}
COUNTRY_ENTRY_STEPS = {'top_up', 'awaiting_payment'}
LADDERS = {
    'invest': ('invest', 'send', 'comprar'),
    'comprar': ('comprar', 'send', 'invest'),
    'family': ('send', 'invest', 'comprar'),
    'devaluation': ('invest', 'send', 'comprar'),
    'savings': ('invest', 'send', 'comprar'),
    'pay': ('comprar', 'send', 'invest'),
}
DEFAULT_LADDER = ('send', 'invest', 'comprar')


# Amounts and promises in words: the digit check can't see these.
_PROMISE = re.compile(r'\b(un|una|uno|dos|tres|cinco|diez|cien|mil)\s+(d[oó]lar|boliviano|peso|sol\b|real)'
                      r'|\bgratis\b|\bsin (costo|comisi[oó]n)|\bgarantiz|\bm[ií]nimo\b', re.I)


@dataclass(frozen=True)
class Guide:
    key: str
    stage: str
    text: str
    chips: tuple
    pointer_text: str
    presentation: str = 'bubble'  # full | bubble; the app treats anything else as bubble


def _resting(row, now):
    """Shown, accepted or refused recently. The opening question is only ever
    optional: once answered or refused it doesn't come back."""
    if row is None:
        return False
    if row.step == 'opening' and (row.dismissed_at or row.accepted_at):
        return True
    return any(moment and now - moment < rest for moment, rest in (
        (row.shown_at, SHOWN_REST), (row.accepted_at, ACCEPTED_REST), (row.dismissed_at, DISMISSED_REST)))


def _unfunded_key(viewer, state, answer):
    from ramps.koywe import on_ramp_paused, on_ramp_rejection_locked
    from ramps.models import RampTransaction
    from security.identity_status import personal_documents

    from .engine import _identity_status, _ve_topup

    if answer == 'usdt':
        return 'usdt'
    route = topup_route(state.country)
    if route == 'international_soon' or route == 'international':
        return route
    if route == 'usdt' or on_ramp_paused(state.country) or on_ramp_rejection_locked(viewer.user):
        return 'usdt'
    if state.country == 'VE':
        topup = _ve_topup(viewer, state.country)
        if topup is None:
            return 'usdt'
        if topup == 'update':
            return 'top_up_update'
    recent = timezone.now() - timedelta(days=OPEN_ORDER_DAYS)
    orders = RampTransaction.objects.filter(actor_user=viewer.user, direction='on_ramp', created_at__gte=recent)
    if orders.filter(status='PENDING').exists():
        return 'awaiting_payment'
    if state.topup_in_progress:
        return None  # paid, on its way: nothing to teach
    identity = _identity_status(viewer)
    if identity is None:
        return None
    if identity == 'pending':
        # "pending" also covers a session never finished: that one still has a step.
        latest = personal_documents(viewer.user).order_by('-created_at').first()
        return 'verifying' if _didit_stage(latest) == 'in_review' else 'verify'
    return 'top_up' if identity == 'verified' else 'verify'


def _ladder_done(user, key):
    if key == 'send':
        from users.models_unified import UnifiedTransactionTable
        return UnifiedTransactionTable.objects.filter(
            sender_user=user, status='CONFIRMED', deleted_at__isnull=True,
            transaction_type__in=('send', 'payment')).exists()
    if key == 'invest':
        from blockchain.models import PerpPosition, SponsoredBatch
        return (SponsoredBatch.objects.filter(user=user, kind__in=('stock_buy', 'crypto_buy'),
                                              status='confirmed').exists()
                or PerpPosition.objects.filter(user=user, state__in=PERP_OPENED_STATES).exists())
    from marketplace.models import Order
    return Order.objects.filter(buyer=user).exists()


def _invest_options(viewer, state):
    """What this person may buy, by the same rules the Invertir tab uses."""
    from django.conf import settings

    from cusd_plus import crypto_risk, perps_risk
    from cusd_plus.eligibility import check_stock_buy_eligibility, perps_promotion_blocked
    from cusd_plus.schema import _stock_execution_ready

    meta = viewer.request_meta or {}
    # Buying, not only seeing: the walk ends on the Comprar button.
    stocks = (getattr(settings, 'CUSD_PLUS_STOCKS_ENABLED', False) and _stock_execution_ready()
              and check_stock_buy_eligibility(viewer.user, meta))
    options = ['stocks'] if stocks else []
    if crypto_risk.buy_enabled(viewer.user, meta):
        options.append('crypto')
    # Where Futuros may be used but never promoted, the guide doesn't offer it.
    if perps_risk.open_enabled(viewer.user, meta) and not perps_promotion_blocked(viewer.user):
        options.append('perps')
    return options


def _ladder_usable(viewer, state, key):
    if key == 'invest':
        return bool(_invest_options(viewer, state))
    if key == 'comprar':
        from marketplace.checkout import live_city_names
        return bool(live_city_names(state.country))
    return True


def _funded_key(viewer, state, rows, answer, now):
    for key in LADDERS.get(answer, DEFAULT_LADDER):
        if _ladder_usable(viewer, state, key) and not _ladder_done(viewer.user, key):
            return None if _resting(rows.get(key), now) else key
    return None


def is_preview_user(user_id):
    return user_id in conf.get('ASSISTANT_GUIDE_PREVIEW_USER_IDS')


def _preview_key(user_id):
    return f'assistant:guide:preview:{user_id}'


def set_preview(user_id, key):
    """Show a test account this step on every app start; None goes back to normal."""
    if not is_preview_user(user_id) or (key is not None and key not in STEPS):
        raise ValueError('Solo cuentas de prueba y pasos conocidos')
    cache.delete(_preview_key(user_id)) if key is None else cache.set(_preview_key(user_id), key, PREVIEW_SECONDS)


def current_key(viewer, request_meta):
    from .models import AssistantGuideStep, ProbeAnswer

    if not conf.get('ASSISTANT_GUIDE_ENABLED') or viewer.user is None or viewer.account_type == 'business':
        return None
    if is_preview_user(viewer.user.pk):
        previewed = cache.get(_preview_key(viewer.user.pk))
        if previewed in STEPS:
            return previewed
    state = _state(viewer, request_meta)
    if not state.personal or state.employee:
        return None
    now = timezone.now()
    rows = {r.step: r for r in AssistantGuideStep.objects.filter(user=viewer.user)}
    answer = ProbeAnswer.objects.filter(user=viewer.user, probe_id=PROBE_ID).values_list('answer', flat=True).first()
    if state.funded:
        return _funded_key(viewer, state, rows, answer, now)
    if not answer and not _resting(rows.get('opening'), now):
        return 'opening'
    key = _unfunded_key(viewer, state, answer)
    return None if key is None or _resting(rows.get(key), now) else key


def _usable_text(text, fallback):
    text = ' '.join((text or '').split())
    if not text or len(text) > MAX_TEXT_CHARS or '*' in text:
        return None
    # Numbers come from code, and a model's "US$1" here would be a promise.
    allowed = set(re.findall(r'\d+', fallback))
    if set(re.findall(r'\d+', text)) > allowed or _PROMISE.search(text):
        return None
    return text


def _generate(viewer, step, *, conversation, first_name, account_label, country):
    from .engine import _identity_status, _openai_post, _output_text, TurnResult, _ve_topup, allowed_destinations
    from .models import AssistantTurn
    from .prompts import GUIDE_OPENING_NOTE, build_system_prompt

    local_now = timezone.now().astimezone(viewer.tz)
    system = build_system_prompt(
        first_name=first_name, account_label=account_label, country=country, screen=viewer.screen,
        local_now=f'{local_now:%Y-%m-%d %H:%M} ({viewer.tz})', destinations=allowed_destinations(viewer),
        identity=_identity_status(viewer), ve_topup=_ve_topup(viewer, country),
    ) + GUIDE_OPENING_NOTE
    model = conf.get('CONFIO_ASSISTANT_MODEL')
    data = _openai_post({
        'model': model, 'instructions': system, 'input': step.brief, 'max_output_tokens': 600,
        'reasoning': {'effort': conf.get('CONFIO_ASSISTANT_REASONING_EFFORT')}, 'store': False,
    }, timeout=conf.get('ASSISTANT_GUIDE_MODEL_TIMEOUT_SECONDS'))
    usage = TurnResult(reply='')
    usage.add_usage(model, data.get('usage'))
    AssistantTurn.objects.create(
        user=viewer.user, conversation=conversation, screen='guide', models_used=usage.models_used,
        input_tokens=usage.input_tokens, cached_input_tokens=usage.cached_input_tokens,
        output_tokens=usage.output_tokens, cost_usd=usage.cost_usd)
    return _output_text(data)


def _text(viewer, key, step, **context):
    if not step.brief:
        return step.text
    wording = hashlib.sha256(step.brief.encode()).hexdigest()[:16]
    cache_key = f'assistant:guide:{viewer.user.pk}:{key}:{wording}'
    cached = cache.get(cache_key)
    if cached:
        return cached
    try:
        text = _usable_text(_generate(viewer, step, **context), step.text)
    except Exception:  # noqa: BLE001 - the card never waits on the model
        logger.warning('assistant guide: wording unavailable for %s', key, exc_info=True)
        text = None
    # A miss is only remembered briefly: the next app start can get the real one.
    cache.set(cache_key, text or step.text, TEXT_CACHE_SECONDS if text else FALLBACK_CACHE_SECONDS)
    return text or step.text


def _first_meeting(viewer):
    """The full screen happens once, ever. Stored here, so a reinstall or a new
    phone doesn't repeat it. Test accounts see it every time."""
    from .models import AssistantGuideStep

    if is_preview_user(viewer.user.pk):
        return True
    return not AssistantGuideStep.objects.filter(user=viewer.user, step='opening', shown_count__gt=0).exists()


def _for_country(step, entry):
    chip = step.chips[0]
    label = entry.chip if chip.label == 'Sí, ir a Recargar' else chip.label
    return replace(step, brief=step.brief.format(entry=entry.name),
                   pointer_text=entry.pointer_text if label == entry.chip else step.pointer_text,
                   chips=(replace(chip, label=label, pointer=entry.pointer), *step.chips[1:]))


def current(viewer, request_meta, **context):
    """The step to show now, or None. Any doubt means no guide."""
    key = current_key(viewer, request_meta)
    if key is None:
        return None
    step = STEPS[key]
    presentation = 'bubble'
    if key in COUNTRY_ENTRY_STEPS:
        step = _for_country(step, topup_entry(context.get('country'), viewer.user, request_meta))
    if key == 'opening':
        state = _state(viewer, request_meta)
        hidden = {job for job in ('invest', 'comprar') if not _ladder_usable(viewer, state, job)}
        chips = tuple(c for c in step.chips if c.answer not in hidden)
        if _first_meeting(viewer):
            presentation = 'full'
        else:
            chips = tuple(replace(c, label=GUIDE_ANSWERS_SHORT.get(c.answer, c.label)) for c in chips)
        step = replace(step, chips=chips)
    if key == 'invest':
        options = _invest_options(viewer, _state(viewer, request_meta))
        step = replace(step, chips=(*(INVEST_OPTIONS[o] for o in options), Chip(LATER, 'dismiss')))
    return Guide(key=key, stage=step.stage, text=_text(viewer, key, step, **context), chips=step.chips,
                 pointer_text=step.pointer_text, presentation=presentation)


def steering_note(key):
    """For a question typed in the card: answer it, then back to this step."""
    from .prompts import GUIDE_STEERING_NOTE

    step = STEPS.get(key)
    return GUIDE_STEERING_NOTE.format(step=step.brief or step.text) if step else ''


def prune_guide_events(cutoff):
    """Runs with the nightly funnel rollup, on the same 90-day retention."""
    from .models import AssistantGuideEvent

    deleted, _ = AssistantGuideEvent.objects.filter(created_at__lt=cutoff).delete()
    return deleted


def record_event(viewer, key, event, *, answer=None, funded=False, detail=''):
    from .models import AssistantGuideEvent, AssistantGuideStep

    if key not in STEPS or event not in EVENTS:
        raise ValueError('Evento no válido')
    now = timezone.now()
    today = AssistantGuideEvent.objects.filter(user=viewer.user, created_at__gte=now - timedelta(days=1)).count()
    if today >= MAX_EVENTS_PER_DAY:
        return
    AssistantGuideEvent.objects.create(user=viewer.user, step=key, stage=STEPS[key].stage, event=event,
                                       detail=(detail or '')[:40],
                                       country=(country_of(viewer.user) or '')[:2].upper())
    row, _ = AssistantGuideStep.objects.get_or_create(user=viewer.user, step=key)
    if event == 'shown':
        AssistantGuideStep.objects.filter(pk=row.pk).update(shown_count=F('shown_count') + 1, shown_at=now)
    elif event == 'dismissed':
        AssistantGuideStep.objects.filter(pk=row.pk).update(dismissed_at=now)
    elif event == 'accepted':
        AssistantGuideStep.objects.filter(pk=row.pk).update(accepted_at=now)
        if key == 'opening' and answer:
            record_probe_answer(viewer.user, PROBE_ID, answer, funded=funded)
            # A test account walks on from the first meeting to the bubble.
            if is_preview_user(viewer.user.pk) and cache.get(_preview_key(viewer.user.pk)) == 'opening':
                set_preview(viewer.user.pk, 'top_up')
