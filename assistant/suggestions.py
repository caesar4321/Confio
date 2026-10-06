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
from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

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
PROBE_KEYS = {key for key, _ in PROBE_ANSWERS}
# An unfinished identity verification is worth a nudge for this long.
VERIFICATION_NUDGE_DAYS = 14
MAX_STARTERS = 4


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
    from django.db.models import Q

    from security.models import IdentityVerification
    from users.models_unified import UnifiedTransactionTable

    from .models import ProbeAnswer

    user = viewer.user
    on_ramps = RampTransaction.objects.filter(actor_user=user, direction='on_ramp')
    # Money that actually arrived: a confirmed incoming row (top-ups, sends,
    # pay-ins all write one, but start PENDING; failed or unclaimed ones don't count).
    funded = UnifiedTransactionTable.objects.filter(
        counterparty_user=user, status='CONFIRMED', deleted_at__isnull=True,
    ).exclude(is_invitation=True, invitation_claimed=False).exists()
    in_progress = on_ramps.filter(status__in=['PENDING', 'PROCESSING', 'AML_REVIEW'],
                                  created_at__gte=timezone.now() - timedelta(days=3)).exists()
    # "pending" also covers attempts started and never finished, and people
    # often verify with a second document (a passport, another country's ID)
    # when they don't have one from their phone's country. So: only when no
    # personal document of any kind is verified, and only for a recent attempt.
    personal_docs = IdentityVerification.all_documents.filter(user=user).filter(
        Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
    latest = personal_docs.order_by('-created_at').first()
    now = timezone.now()
    stage = _didit_stage(latest)
    # 'expired' is a dead session (abandoned or timed out): still worth a nudge.
    # A document that expired blocks someone who was verified: no time limit.
    recent = (stage == 'document_expired'
              or now - timedelta(days=VERIFICATION_NUDGE_DAYS) <= latest.created_at <= now - timedelta(hours=24)) \
        if latest else False
    pending = bool(latest and latest.status in ('pending', 'expired') and stage != 'in_review' and recent
                   and not personal_docs.filter(status='verified').exists())
    try:
        from cusd_plus.eligibility import ONDO_POLICY
        ondo = ONDO_POLICY.evaluate(user, request_meta or {}).allowed
    except Exception:  # noqa: BLE001 - unknown means "don't offer it"
        logger.warning('suggestions: Ondo eligibility unavailable', exc_info=True)
        ondo = False
    return _State(
        personal=viewer.account_type != 'business',
        employee=viewer.is_employee,
        country=(getattr(user, 'phone_country', '') or '').upper(),
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


def probe_payload():
    return {'id': PROBE_ID, 'question': PROBE_QUESTION,
            'answers': [{'key': k, 'label': label} for k, label in PROBE_ANSWERS]}


def wants_probe(state: _State) -> bool:
    return state.personal and not state.funded and state.country in RAIL_COUNTRIES and not state.probe_answered


def build(viewer, screen: str = '', request_meta=None) -> Suggestions:
    state = _state(viewer, request_meta)
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
                    _s('app.safe', '¿Es seguro? ¿Quién controla mi dinero?')]
    elif not state.funded:
        situation.append(_s('norail.receive', '¿Cómo recibes dólares de otra persona? Te explico.',
                            '¿Cómo recibo dólares de otra persona?'))
        starters = [_s('norail.receive', '¿Cómo recibo dólares de otra persona?'),
                    _s('norail.cash', '¿Dónde cambio dólares por efectivo?'),
                    _s('app.what', '¿Qué es Confío y para qué me sirve?'),
                    _s('app.cost', '¿Cuánto cuesta usar Confío?')]
    else:
        situation.append(_s('month.where', '¿Te cuento en qué se fue tu dinero este mes?', '¿En qué gasté más este mes?'))
        save = (_s('save.plus', '¿Cuánto rinde Confío Dollar+?') if state.ondo_eligible
                else _s('save.dollars', '¿Cómo ahorro en dólares?'))
        grow = (_s('invest.how', '¿Cómo invierto en acciones?') if state.ondo_eligible
                else _s('send.abroad', '¿Cómo envío dinero a otro país?'))
        starters = [_s('month.where', '¿En qué gasté más este mes?'), _s('pay.qr', 'Abre QR para pagar'), save, grow]

    hints = attention + (situation if screen in ('', 'Home') else []) + SCREEN_HINTS.get(screen, [])
    starters = list({s.id: s for s in attention + starters}.values())[:MAX_STARTERS]
    return Suggestions(hints=hints, starters=starters, probe=probe_payload() if wants_probe(state) else None)


def record_probe_answer(user, probe_id, answer, *, funded):
    """Store the first answer only (a second tap changes nothing)."""
    from .models import ProbeAnswer

    if probe_id != PROBE_ID or answer not in PROBE_KEYS:
        raise ValueError('Respuesta no válida')
    ProbeAnswer.objects.get_or_create(
        user=user, probe_id=probe_id,
        defaults={'answer': answer, 'phone_country': (getattr(user, 'phone_country', '') or '')[:2].upper(),
                  'funded': funded},
    )


def answer_label(answer):
    return dict(PROBE_ANSWERS).get(answer, '')
