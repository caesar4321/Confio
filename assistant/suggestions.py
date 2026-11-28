"""What the bubble suggests and which chips the chat starts with, ranked by
the person's situation on the server (the app keeps its built-in list only
as a fallback for older servers or a failed call).

Order of importance:
1. something needs attention (a top-up in progress, a pending verification);
2. never funded in a country with a top-up rail: the one-time probe question,
   then "how do I put my first dollars in";
3. never funded where there is no top-up rail: receiving and cash;
4. funded: the month, paying, saving/investing by eligibility;
5. per-screen help.

Copy is neutral Spanish ("tú", "dinero"). Prompts are sent to Confio
Assistant as the user's own message when a hint or chip is tapped.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone
from security.geo import country_of

logger = logging.getLogger(__name__)

# Countries where a top-up rail exists today (v1 of "Tu primer dólar").
RAIL_COUNTRIES = {'AR', 'BO', 'CL', 'CO', 'MX', 'PE'}

PROBE_ID = 'first_use_2026_10'
PROBE_QUESTION = '¿Para qué te gustaría usar Confío?'
PROBE_ANSWERS = [
    ('devaluation', 'Que mi dinero no pierda valor'),
    ('family', 'Enviar o recibir dinero de mi familia'),
    ('savings', 'Ahorrar en dólares'),
    ('usdt', 'Ya tengo dólares (Binance u otra)'),
    ('pay', 'Pagar en comercios'),
    ('other', 'Otra cosa'),
]
# The guide's opening chips: one saving answer, plus the app's two other jobs.
GUIDE_ANSWERS = [
    ('savings', 'Ahorrar en dólares'),
    ('family', 'Enviar o recibir dinero de mi familia'),
    ('invest', 'Invertir'),
    ('comprar', 'Comprar'),
    ('usdt', 'Ya tengo dólares (Binance u otra)'),
]
# The same answers where room is short: the speech bubble keeps Enviar and
# Recibir in sight.
GUIDE_ANSWERS_SHORT = {'savings': 'Ahorrar', 'family': 'Enviar', 'usdt': 'Ya tengo USDT'}
PROBE_KEYS = {key for key, _ in PROBE_ANSWERS + GUIDE_ANSWERS}
# An unfinished identity verification is worth a nudge for this long.
VERIFICATION_NUDGE_DAYS = 14
MAX_STARTERS = 4
# A question the person already asked stays out of the chips this long, so a
# chip they tapped makes room for the next one (people re-tapped "¿Cómo pongo
# mis primeros dólares?" up to 4 times in 5 minutes, 2026-10-14).
ASKED_WINDOW_HOURS = 24

# ── The conversation home (docs/designs/ai-assistant-first-redesign.md 7) ──
# There the assistant is a general one that also handles the person's money,
# and chips about money alone would say otherwise. The chips are personal
# first (what needs attention, their situation, what they themselves have
# been asking for) and one is a general suggestion of ours.
#
# How far back "what they have been asking for" looks.
HISTORY_DAYS = 30
HISTORY_MESSAGES = 120
# General things people ask an assistant for: (id, chip, words that show the
# person asked for that kind of thing). Matched on their own past messages,
# never on a model's reading of them: no call, no cost, nothing stored.
GENERAL_KINDS = (
    ('general.translate', 'Tradúceme un texto', ('traduc', 'traducir', 'traducción', 'en inglés', 'al inglés', 'al español')),
    ('general.write', 'Ayúdame a escribir un mensaje', ('redact', 'escríbeme', 'escribeme', 'una carta', 'un correo',
                                                         'un mensaje para', 'mejora este texto', 'corrige')),
    ('general.explain', 'Explícame un tema en simple', ('explícame', 'explicame', 'resúmeme', 'resumeme', 'resumen de',
                                                        'mi tarea', 'la tarea', 'qué significa', 'que significa')),
    ('general.plan', 'Ayúdame a planear un viaje', ('viaje', 'vuelo', 'itinerario', 'pasaje', 'hotel')),
    ('general.cook', 'Dame una idea para cocinar hoy', ('receta', 'cocinar', 'qué cocino', 'que cocino', 'almuerzo', 'cena')),
    ('general.news', '¿Qué pasó hoy en las noticias?', ('noticia', 'qué pasó', 'que paso', 'último momento')),
)


@dataclass(frozen=True)
class Suggestion:
    id: str
    text: str
    prompt: str = ''
    # 'prompt': tapping sends `prompt`; 'probe': opens the probe question;
    # 'picker': opens the assistant customizer.
    kind: str = 'prompt'


@dataclass
class Suggestions:
    hints: list = field(default_factory=list)
    starters: list = field(default_factory=list)
    probe: dict | None = None


def _s(id_, text, prompt=None, kind='prompt'):
    return Suggestion(id=id_, text=text, prompt=text if prompt is None else prompt, kind=kind)


# The chips in Portuguese, for people who write in it (or, before they write,
# live in Brazil): a Spanish chip tapped is a Spanish message, and is answered
# in Spanish (Natane, Brazil, 2026-11-28). Keyed by the Spanish text.
PORTUGUESE = {
    '¿Qué es una acción? Te lo explico en 1 minuto.': 'O que é uma ação? Te explico em 1 minuto.',
    '¿Qué es una acción y cómo funciona en Confío?': 'O que é uma ação e como funciona no Confío?',
    '¿Cómo invierto en acciones de EE.UU.?': 'Como invisto em ações dos EUA?',
    '¿Cómo invierto en acciones?': 'Como invisto em ações?',
    '¿Qué significa diversificar?': 'O que significa diversificar?',
    '¿Qué riesgos tiene invertir en una acción?': 'Quais são os riscos de investir em uma ação?',
    '¿Qué riesgos tiene invertir en una sola acción?': 'Quais são os riscos de investir em uma só ação?',
    '¿A quién y cómo puedes enviar? Te guío.': 'Para quem e como você pode enviar? Eu te guio.',
    '¿Cuáles son las formas de enviar dinero?': 'Quais são as formas de enviar dinheiro?',
    '¿Cómo retiro a mi cuenta bancaria?': 'Como transfiro para minha conta bancária?',
    '¿Cómo te pagan desde otro país?': 'Como te pagam de outro país?',
    '¿Cómo me pueden pagar desde otro país?': 'Como podem me pagar de outro país?',
    '¿Comparo este mes con el anterior?': 'Comparo este mês com o anterior?',
    'Compara este mes con el anterior': 'Compare este mês com o anterior',
    'Personaliza a tu asistente: descríbelo o usa una foto de tu mascota.':
        'Personalize seu assistente: descreva-o ou use uma foto do seu pet.',
    '¿Cómo cambio dólares por efectivo?': 'Como troco dólares por dinheiro em espécie?',
    '¿Cómo cambio mis dólares por efectivo?': 'Como troco meus dólares por dinheiro em espécie?',
    '¿A cuánto está el dólar hoy?': 'Quanto está o dólar hoje?',
    '¿Cómo va tu recarga? Te digo en qué estado está.': 'Como vai sua recarga? Te digo em que estado está.',
    '¿En qué estado está mi recarga?': 'Em que estado está minha recarga?',
    'Tu documento venció. ¿Te ayudo a verificarte de nuevo?': 'Seu documento venceu. Te ajudo a se verificar de novo?',
    'Mi documento de identidad venció, ¿cómo me verifico de nuevo?':
        'Meu documento de identidade venceu, como me verifico de novo?',
    '¿Te ayudo a terminar tu verificación de identidad?': 'Te ajudo a terminar sua verificação de identidade?',
    'Empecé mi verificación de identidad y no la terminé, ¿qué hago?':
        'Comecei minha verificação de identidade e não terminei, o que faço?',
    '¿Te ayudo con tu verificación de identidad?': 'Te ajudo com sua verificação de identidade?',
    '¿En qué estado está mi verificación de identidad?': 'Em que estado está minha verificação de identidade?',
    '¿Cómo cobro a un cliente?': 'Como cobro de um cliente?',
    '¿Cómo genero un QR para cobrar?': 'Como gero um QR para cobrar?',
    '¿Qué es Confío y para qué sirve?': 'O que é o Confío e para que serve?',
    '¿Cómo pongo mis primeros dólares?': 'Como coloco meus primeiros dólares?',
    '¿Cómo pongo mis primeros dólares en Confío?': 'Como coloco meus primeiros dólares no Confío?',
    '¿Qué es Confío y para qué me sirve?': 'O que é o Confío e para que me serve?',
    '¿Cuánto cuesta usar Confío?': 'Quanto custa usar o Confío?',
    '¿Es seguro? ¿Quién controla mi dinero?': 'É seguro? Quem controla meu dinheiro?',
    '¿Cuánto rinde Confío Dollar+?': 'Quanto rende o Confío Dollar+?',
    '¿Cómo ahorro en dólares?': 'Como guardo meu dinheiro em dólares?',
    '¿Cómo recibo dólares de otra persona?': 'Como recebo dólares de outra pessoa?',
    '¿Dónde cambio dólares por efectivo?': 'Onde troco dólares por dinheiro em espécie?',
    '¿Cómo recibes dólares de otra persona? Te explico.': 'Como receber dólares de outra pessoa? Te explico.',
    '¿Te cuento en qué se fue tu dinero este mes?': 'Te conto para onde foi seu dinheiro este mês?',
    '¿En qué gasté más este mes?': 'Com o que gastei mais este mês?',
    '¿Cómo envío dinero a otro país?': 'Como envio dinheiro para outro país?',
    'Abre QR para pagar': 'Abrir QR para pagar',
    'Tradúceme un texto': 'Traduza um texto para mim',
    'Ayúdame a escribir un mensaje': 'Me ajude a escrever uma mensagem',
    'Explícame un tema en simple': 'Me explique um assunto de forma simples',
    'Ayúdame a planear un viaje': 'Me ajude a planejar uma viagem',
    'Dame una idea para cocinar hoy': 'Me dê uma ideia para cozinhar hoje',
    '¿Qué pasó hoy en las noticias?': 'O que aconteceu hoje nas notícias?',
}
_CHIP_TEXTS = frozenset(' '.join(text.lower().split()) for pair in PORTUGUESE.items() for text in pair)
# The chips written around a ticker (_own_chips): (Spanish, Portuguese).
_TICKER_CHIPS = ((re.compile(r'^¿Cómo va (\S+) hoy\?$'), '¿Cómo va {} hoy?', 'Como está {} hoje?'),
                 (re.compile(r'^¿Cómo va (\S+) hoy y por qué se movió\?$'), '¿Cómo va {} hoy y por qué se movió?',
                  'Como está {} hoje e por que subiu ou caiu?'))


def _in_portuguese(text):
    if text in PORTUGUESE:
        return PORTUGUESE[text]
    for pattern, _es, pt in _TICKER_CHIPS:
        found = pattern.match(text or '')
        if found:
            return pt.format(found.group(1))
    return text


def _spanish_of(text):
    """The Spanish chip a normalized Portuguese chip stands for, or ''."""
    for es, pt in PORTUGUESE.items():
        if _norm(pt) == text:
            return _norm(es)
    for _pattern, es, pt in _TICKER_CHIPS:
        head, tail = _norm(pt).split('{}')
        middle = text[len(head):len(text) - len(tail)] if text.startswith(head) and text.endswith(tail) else ''
        if len(text) > len(head) + len(tail) and re.fullmatch(r'[a-z0-9.-]{1,10}', middle):  # one ticker
            return _norm(es.format(middle.upper()))
    return ''


def _is_chip(text):
    """A normalized message that is one of our chips, in either language: never the person's own words."""
    if text in _CHIP_TEXTS or _spanish_of(text):
        return True
    return bool(re.fullmatch(r'¿cómo va [a-z0-9.-]{1,10} hoy(?: y por qué se movió)?\?', text))


def _chip_language(viewer, state):
    """'pt' or 'es': the language of this person's own recent messages (never a
    chip they tapped); before they wrote, Portuguese for people in Brazil."""
    own = [text for text in _own_messages(viewer, since=timezone.now() - timedelta(days=HISTORY_DAYS), limit=20)
           if not _is_chip(text)]
    if own:
        try:
            from .confirm import _language_of, language

            # "oi", "bom dia", "pix": no word of either language, so where they live decides.
            if _language_of(own[:5]):
                return 'pt' if language(own[:5]) == 'pt' else 'es'
        except Exception:  # noqa: BLE001 - chips are a nicety
            logger.warning('suggestions: language unknown', exc_info=True)
    return 'pt' if state.country == 'BR' else 'es'


def _translated(items, lang):
    if lang != 'pt':
        return items
    return [Suggestion(id=s.id, text=_in_portuguese(s.text), prompt=_in_portuguese(s.prompt), kind=s.kind)
            for s in items]


# Per-screen help (lowest priority; same content the app shipped with).
SCREEN_HINTS = {
    'Invest': [_s('invest.what_is_stock', '¿Qué es una acción? Te lo explico en 1 minuto.',
                  '¿Qué es una acción y cómo funciona en Confío?'),
               _s('invest.how', '¿Cómo invierto en acciones de EE.UU.?', '¿Cómo invierto en acciones?')],
    'StocksList': [_s('stocks.diversify', '¿Qué significa diversificar?')],
    'StockDetail': [_s('stock.risks', '¿Qué riesgos tiene invertir en una acción?',
                       '¿Qué riesgos tiene invertir en una sola acción?')],
    'Send': [_s('send.ways', '¿A quién y cómo puedes enviar? Te guío.', '¿Cuáles son las formas de enviar dinero?'),
             _s('send.withdraw', '¿Cómo retiro a mi cuenta bancaria?')],
    'Receive': [_s('receive.abroad', '¿Cómo te pagan desde otro país?', '¿Cómo me pueden pagar desde otro país?')],
    'AccountDetail': [_s('account.compare', '¿Comparo este mes con el anterior?', 'Compara este mes con el anterior')],
    'Profile': [_s('profile.pet', 'Personaliza a tu asistente: descríbelo o usa una foto de tu mascota.', '',
                   kind='picker')],
    'Financieras': [_s('cash.exchange', '¿Cómo cambio dólares por efectivo?', '¿Cómo cambio mis dólares por efectivo?')],
}


@dataclass
class _State:
    personal: bool
    employee: bool
    country: str
    funded: bool
    topup_in_progress: bool
    verification_pending: bool
    ondo_eligible: bool
    probe_answered: bool
    # Didit's own word for the open attempt: 'unfinished' (not started,
    # abandoned, timed out), 'document_expired' (Kyc Expired) or '' when
    # unknown. In review never nudges.
    verification_stage: str = ''


def _state(viewer, request_meta) -> _State:
    from ramps.models import RampTransaction
    from users.funding import has_funded

    from .models import ProbeAnswer

    user = viewer.user
    on_ramps = RampTransaction.objects.filter(actor_user=user, direction='on_ramp')
    # Money that actually arrived: a confirmed incoming row (top-ups, sends,
    # pay-ins all write one, but start PENDING; failed or unclaimed ones don't count).
    funded = has_funded(user)
    in_progress = on_ramps.filter(status__in=['PENDING', 'PROCESSING', 'AML_REVIEW'],
                                  created_at__gte=timezone.now() - timedelta(days=3)).exists()
    # "pending" also covers attempts started and never finished, and people
    # often verify with a second document (a passport, another country's ID)
    # when they don't have one from their phone's country. So: only when no
    # personal document of any kind is verified, and only for a recent attempt.
    from security.identity_status import personal_documents
    personal_docs = personal_documents(user)
    latest = personal_docs.order_by('-created_at').first()
    now = timezone.now()
    stage = _didit_stage(latest)
    # 'expired' is a dead session (abandoned or timed out): still worth a nudge.
    # A document that expired blocks someone who was verified: no time limit.
    recent = (stage == 'document_expired'
              or now - timedelta(days=VERIFICATION_NUDGE_DAYS) <= latest.created_at <= now - timedelta(hours=24)) \
        if latest else False
    pending = bool(latest and latest.status in ('pending', 'expired') and stage != 'in_review' and recent
                   and not personal_docs.filter(status='verified').exists() and not waits_on_review(user))
    try:
        from cusd_plus.eligibility import ONDO_POLICY
        ondo = ONDO_POLICY.evaluate(user, request_meta or {}).allowed
    except Exception:  # noqa: BLE001 - unknown means "don't offer it"
        logger.warning('suggestions: Ondo eligibility unavailable', exc_info=True)
        ondo = False
    return _State(
        personal=viewer.account_type != 'business',
        employee=viewer.is_employee,
        country=(country_of(user) or '').upper(),
        funded=funded,
        topup_in_progress=in_progress,
        verification_pending=pending,
        verification_stage=stage if pending else '',
        ondo_eligible=ondo,
        probe_answered=ProbeAnswer.objects.filter(user=user, probe_id=PROBE_ID).exists(),
    )


# Didit's raw statuses (risk_factors['didit']['raw_status']); our `status`
# column folds most of them into 'pending' (Expired/Abandoned into 'expired').
DIDIT_UNFINISHED = {'not started', 'in progress', 'abandoned', 'expired'}
DIDIT_DOCUMENT_EXPIRED = {'kyc expired'}
DIDIT_IN_REVIEW = {'in review'}


def _didit_stage(verification):
    if verification is None:
        return ''
    risk = verification.risk_factors or {}
    raw = str((risk.get('didit') or {}).get('raw_status') or '').strip().lower()
    if raw in DIDIT_IN_REVIEW or risk.get('requires_review'):
        return 'in_review'
    if raw in DIDIT_UNFINISHED:
        return 'unfinished'
    if raw in DIDIT_DOCUMENT_EXPIRED:
        return 'document_expired'
    return ''


def waits_on_review(user):
    """A document waits on the reviewers (or on our own retry) and none waits
    on the person. Not just the newest row: "otro documento" creates an empty
    one, and a replaced attempt asks nothing of anybody."""
    from security.didit import _superseded
    from security.identity_status import personal_documents

    waiting = False
    for doc in personal_documents(user).filter(status='pending'):
        if doc.needs_person_action:
            if not _superseded(doc):
                return False
            continue
        raw = str(((doc.risk_factors or {}).get('didit') or {}).get('raw_status') or '').strip().lower()
        # Approved by Didit and still pending: our same-face check is retrying.
        waiting = waiting or raw == 'approved' or _didit_stage(doc) == 'in_review'
    return waiting


def probe_payload():
    return {'id': PROBE_ID, 'question': PROBE_QUESTION,
            'answers': [{'key': k, 'label': label} for k, label in PROBE_ANSWERS]}


def wants_probe(state: _State) -> bool:
    return state.personal and not state.funded and state.country in RAIL_COUNTRIES and not state.probe_answered


def _norm(text):
    return ' '.join((text or '').lower().split())


def _own_messages(viewer, *, since, limit):
    """What this person sent the assistant from this account since `since`,
    newest first, normalized. Empty on any failure: chips are a nicety."""
    user = getattr(viewer, 'user', None)
    if user is None or not getattr(user, 'pk', None):
        return []
    try:
        from inbox.models import SupportMessage

        # This account's thread only: a question asked from the business account
        # doesn't hide the chip in the personal one.
        scope = {'conversation__user': user}
        if getattr(viewer, 'account_type', '') == 'business' and getattr(viewer, 'business_id', None):
            scope['conversation__business_id'] = viewer.business_id
        elif getattr(viewer, 'account', None) is not None:
            scope['conversation__account'] = viewer.account
        bodies = (SupportMessage.objects.filter(sender_type='USER', created_at__gte=since, **scope)
                  .order_by('-created_at').values_list('body', flat=True)[:limit])
        return [_norm(b) for b in bodies]
    except Exception:  # noqa: BLE001 - chips are a nicety: never fail the screen over them
        logger.warning('suggestions: recent questions unavailable', exc_info=True)
        return []


def _recently_asked(viewer) -> set:
    """What this person sent the assistant in the last ASKED_WINDOW_HOURS."""
    return set(_own_messages(viewer, since=timezone.now() - timedelta(hours=ASKED_WINDOW_HOURS), limit=50))


def _general_chips(viewer, now=None):
    """(theirs, ours) for the conversation home.

    theirs: the general things this person has actually been asking for,
    most asked first (a chip to do it again). ours: the one general
    suggestion of the day, the same all day for one person and different
    from the next person's, taken from the kinds they have not shown yet,
    so it also tells them something the assistant can do that they have
    not tried."""
    now = now or timezone.now()
    history = _own_messages(viewer, since=now - timedelta(days=HISTORY_DAYS), limit=HISTORY_MESSAGES)
    counts = []
    for id_, chip, words in GENERAL_KINDS:
        hits = sum(1 for body in history if any(word in body for word in words))
        counts.append((hits, _s(id_, chip)))
    theirs = [chip for hits, chip in sorted(counts, key=lambda pair: -pair[0]) if hits > 0]
    untried = [chip for hits, chip in counts if hits == 0] or [chip for _hits, chip in counts]
    user_id = getattr(getattr(viewer, 'user', None), 'pk', None) or 0
    ours = untried[(now.toordinal() + user_id) % len(untried)]
    return theirs, ours


def _top_holding(viewer):
    """The ticker of the stock this person holds most of, by value; None when
    they hold none or it cannot be read without a chain scan."""
    address = getattr(getattr(viewer, 'account', None), 'bsc_address', '') or ''
    if not address:
        return None
    try:
        from cusd_plus.gm_holdings import known_holdings_units

        if not known_holdings_units(address):
            return None  # nothing held (or never read): no price lookup either
        from .engine import _holdings

        rows = _holdings(address, limit=1)
        return rows[0]['ticker'] if isinstance(rows, list) and rows else None
    except Exception:  # noqa: BLE001 - a chip, never a failed screen
        logger.warning('suggestions: holdings unavailable', exc_info=True)
        return None


def _has_local_rate(country):
    """There is a dollar rate to tell for this person's own currency (the
    one the app shows beside their balance)."""
    try:
        from exchange_rates.currency_mapping import COUNTRY_TO_CURRENCY
        from exchange_rates.services import exchange_rate_service

        code = COUNTRY_TO_CURRENCY.get((country or '').upper())
        if not code or code == 'USD':
            return False
        return any(getattr(exchange_rate_service.get_current_rate_row(code, 'USD', kind), 'rate', None)
                   for kind in ('parallel', 'average', 'official'))
    except Exception:  # noqa: BLE001
        logger.warning('suggestions: local rate unavailable', exc_info=True)
        return False


def _own_chips(viewer, state):
    """(stock, rate): chips written from this person's own facts, each None
    when the fact is not there. No amounts and no other people's names: a
    chip is on screen even while the balance is hidden, and its text is sent
    as the person's own message."""
    if state.employee:
        return None, None
    ticker = _top_holding(viewer)
    stock = _s('own.stock', f'¿Cómo va {ticker} hoy?', f'¿Cómo va {ticker} hoy y por qué se movió?') if ticker else None
    rate = _s('own.rate', '¿A cuánto está el dólar hoy?') if _has_local_rate(state.country) else None
    return stock, rate


def build(viewer, screen: str = '', request_meta=None) -> Suggestions:
    state = _state(viewer, request_meta)
    asked = _recently_asked(viewer)
    # A Portuguese chip tapped is that chip asked: it makes room as the Spanish one does.
    asked |= {es for es in map(_spanish_of, asked) if es}
    attention, situation = [], []

    if state.topup_in_progress and not state.employee:
        attention.append(_s('attention.topup', '¿Cómo va tu recarga? Te digo en qué estado está.',
                            '¿En qué estado está mi recarga?'))
    if state.verification_pending and state.personal:
        if state.verification_stage == 'document_expired':
            attention.append(_s('attention.verification', 'Tu documento venció. ¿Te ayudo a verificarte de nuevo?',
                                'Mi documento de identidad venció, ¿cómo me verifico de nuevo?'))
        elif state.verification_stage == 'unfinished':
            attention.append(_s('attention.verification', '¿Te ayudo a terminar tu verificación de identidad?',
                                'Empecé mi verificación de identidad y no la terminé, ¿qué hago?'))
        else:  # Didit's status unknown: words that fit an attempt in any state
            attention.append(_s('attention.verification', '¿Te ayudo con tu verificación de identidad?',
                                '¿En qué estado está mi verificación de identidad?'))

    if state.employee:
        starters = [_s('emp.charge', '¿Cómo cobro a un cliente?'), _s('emp.charge_qr', '¿Cómo genero un QR para cobrar?'),
                    _s('app.what', '¿Qué es Confío y para qué sirve?')]
    elif not state.funded and state.country in RAIL_COUNTRIES:
        if wants_probe(state):
            situation.append(_s('probe.first_use', PROBE_QUESTION, '', kind='probe'))
        situation.append(_s('first.how', '¿Cómo pongo mis primeros dólares?',
                            '¿Cómo pongo mis primeros dólares en Confío?'))
        starters = [_s('first.how', '¿Cómo pongo mis primeros dólares?',
                       '¿Cómo pongo mis primeros dólares en Confío?'),
                    _s('app.what', '¿Qué es Confío y para qué me sirve?'),
                    _s('app.cost', '¿Cuánto cuesta usar Confío?'),
                    _s('app.safe', '¿Es seguro? ¿Quién controla mi dinero?'),
                    # Next in line once the ones above were asked.
                    (_s('save.plus', '¿Cuánto rinde Confío Dollar+?') if state.ondo_eligible
                     else _s('save.dollars', '¿Cómo ahorro en dólares?')),
                    _s('norail.receive', '¿Cómo recibo dólares de otra persona?'),
                    _s('norail.cash', '¿Dónde cambio dólares por efectivo?')]
    elif not state.funded:
        situation.append(_s('norail.receive', '¿Cómo recibes dólares de otra persona? Te explico.',
                            '¿Cómo recibo dólares de otra persona?'))
        starters = [_s('norail.receive', '¿Cómo recibo dólares de otra persona?'),
                    _s('norail.cash', '¿Dónde cambio dólares por efectivo?'),
                    _s('app.what', '¿Qué es Confío y para qué me sirve?'),
                    _s('app.cost', '¿Cuánto cuesta usar Confío?'),
                    _s('app.safe', '¿Es seguro? ¿Quién controla mi dinero?')]
    else:
        situation.append(_s('month.where', '¿Te cuento en qué se fue tu dinero este mes?', '¿En qué gasté más este mes?'))
        save = (_s('save.plus', '¿Cuánto rinde Confío Dollar+?') if state.ondo_eligible
                else _s('save.dollars', '¿Cómo ahorro en dólares?'))
        grow = (_s('invest.how', '¿Cómo invierto en acciones?') if state.ondo_eligible
                else _s('send.abroad', '¿Cómo envío dinero a otro país?'))
        starters = [_s('month.where', '¿En qué gasté más este mes?'), _s('pay.qr', 'Abre QR para pagar'), save, grow,
                    _s('app.cost', '¿Cuánto cuesta usar Confío?'), _s('app.safe', '¿Es seguro? ¿Quién controla mi dinero?')]

    def fresh(items):
        # Attention items stay (something is pending); asked prompts make room.
        return [s for s in items if s in attention or s.kind != 'prompt' or _norm(s.prompt) not in asked]

    hints = fresh(attention + (situation if screen in ('', 'Home') else []) + SCREEN_HINTS.get(screen, []))
    # Starters never filter down to nothing: an empty list makes the app fall back
    # to its own built-in chips, which don't fit employees or no-rail countries.
    ranked = list({s.id: s for s in (fresh(attention + starters) or attention + starters)}.values())
    from .prompts import conversation_home

    if conversation_home(request_meta):
        # Personal first, one general suggestion of ours last: what needs
        # attention, their own facts (a stock they hold, the dollar in their
        # currency) around the top of their money situation, what they
        # themselves keep asking for, then more of their situation.
        theirs, ours = _general_chips(viewer)
        theirs = fresh(theirs)
        if not fresh([ours]):  # asked today already: the next one they have not
            ours = next((c for c in (_s(i, t) for i, t, _w in GENERAL_KINDS)
                         if c.id != ours.id and fresh([c]) and c not in theirs), ours)
        stock, rate = _own_chips(viewer, state)
        # Pagar is the round button beside these chips: no chip for it here.
        money = [s for s in ranked if s not in attention and s.id != 'pay.qr']
        personal = (attention + fresh([stock] if stock else []) + money[:1] + fresh([rate] if rate else [])
                    + theirs[:1] + money[1:] + theirs[1:])
        personal = [s for s in {s.id: s for s in personal}.values() if s.id != ours.id]
        starters = personal[:MAX_STARTERS - 1] + [ours]
    else:
        starters = ranked[:MAX_STARTERS]
    lang = _chip_language(viewer, state)
    return Suggestions(hints=_translated(hints, lang), starters=_translated(starters, lang),
                       probe=probe_payload() if wants_probe(state) else None)


def record_probe_answer(user, probe_id, answer, *, funded):
    """Store the first answer only (a second tap changes nothing)."""
    from .models import ProbeAnswer

    if probe_id != PROBE_ID or answer not in PROBE_KEYS:
        raise ValueError('Respuesta no válida')
    ProbeAnswer.objects.get_or_create(
        user=user, probe_id=probe_id,
        defaults={'answer': answer, 'phone_country': (country_of(user) or '')[:2].upper(),
                  'funded': funded},
    )


def answer_label(answer):
    return dict(PROBE_ANSWERS).get(answer, '')
