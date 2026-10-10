"""Confio Assistant turn engine.

One turn = the user's message (typed, or a transcribed voice note) answered by
the everyday model with a small tool belt. Tools are scoped to the JWT account
by construction: they close over the viewer resolved from the token, and the
model never names an account, user or id.

Money never moves here. The strongest thing the model can do is ask the app to
open a screen; every transfer is still confirmed by the user in-flow.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import requests
from django.conf import settings
from django.utils import timezone

from users.models_cashflow import CATEGORY_CHOICES

from . import conf, market
from .destinations import DESTINATIONS, FALLBACKS, OWNER_ONLY, PAID_OFFERS, PERSONAL_ONLY
from .prompts import ANALYSIS_PROMPT, build_system_prompt

logger = logging.getLogger(__name__)

OPENAI_RESPONSES_URL = 'https://api.openai.com/v1/responses'
MONTHS_ES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
             'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']


class AssistantUnavailable(Exception):
    """The model could not be reached; the caller tells the user and offers a human."""


@dataclass
class Viewer:
    """Everything a tool may know about who is asking, resolved from the JWT."""
    user: object
    account: object  # the Account row (personal, or the business's Account)
    account_type: str
    business_id: int | None
    is_business_owner: bool
    tz: object
    screen: str = ''
    # The request's META (IP, headers) for request-aware eligibility; empty
    # where there is no request (then eligibility is "unknown").
    request_meta: dict = field(default_factory=dict, repr=False)

    @property
    def is_employee(self):
        return self.account_type == 'business' and not self.is_business_owner


@dataclass
class TurnResult:
    reply: str
    actions: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    models_used: list = field(default_factory=list)
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal('0')
    handoff_reason: str = ''
    writes: list = field(default_factory=list)
    # categorize_transactions proposal awaiting the user's "sí".
    pending_categorization: dict | None = None

    def add_usage(self, model, usage):
        usage = usage or {}
        input_tokens = int(usage.get('input_tokens') or 0)
        cached = int((usage.get('input_tokens_details') or {}).get('cached_tokens') or 0)
        output_tokens = int(usage.get('output_tokens') or 0)
        self.input_tokens += input_tokens
        self.cached_input_tokens += cached
        self.output_tokens += output_tokens
        if model not in self.models_used:
            self.models_used.append(model)
        price = conf.price_for(model)
        if price is None:
            logger.warning('Confio Assistant: no price configured for %s; turn cost under-reported', model)
            return
        per_input, per_cached, per_output = price
        million = Decimal(1_000_000)
        self.cost_usd += (
            Decimal(max(input_tokens - cached, 0)) * per_input
            + Decimal(cached) * per_cached
            + Decimal(output_tokens) * per_output
        ) / million


# Text written by other people (names they chose, remitter names): data, never
# instructions. One line, no control/bidi characters, short.
_UNSAFE_CHARS = re.compile(r'[\x00-\x1f\x7f\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]')
THIRD_PARTY_MAX_CHARS = 40
# Only real staff replies carry this prefix in the model's history.
STAFF_PREFIX = '[Equipo Confío, persona]'
_STAFF_PREFIX_SPOOF = re.compile(r'\[\s*equipo\s+conf[ií]o[^\]]*\]', re.IGNORECASE)


def third_party_text(value, limit=THIRD_PARTY_MAX_CHARS):
    text = ' '.join(_UNSAFE_CHARS.sub(' ', value or '').split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def allowed_destinations(viewer: Viewer, *, paid_offers_allowed=True):
    keys = list(DESTINATIONS)
    if not paid_offers_allowed:
        # Realtime voice: a pitch is only ever opened by a tap on its chip.
        keys = [k for k in keys if k not in PAID_OFFERS]
    if viewer.is_employee:
        keys = [k for k in keys if k not in OWNER_ONLY]
    if viewer.account_type == 'business':
        # Business pay-ins are never held for Confío Face (payin_hold.needs_face).
        keys = [k for k in keys if k not in PERSONAL_ONLY]
    if not _phone_eligible(viewer):
        # A single stock's page only where stocks are offered. This is the
        # cheap phone check; navigate('stock') adds the request-aware one.
        keys = [k for k in keys if k != 'stock']
    # Paid-offer pitches only while that probe is on and on builds that have
    # the screen (old builds would land on Home with nothing to tap).
    from users import paid_offers
    keys = [k for k in keys if k not in PAID_OFFERS or paid_offers.available(
        PAID_OFFERS[k], is_employee=viewer.is_employee, meta=viewer.request_meta,
        user_id=getattr(viewer.user, 'pk', None))]
    return keys


def _phone_eligible(viewer):
    try:
        from cusd_plus.eligibility import is_ondo_eligible
        return viewer.user is not None and bool(is_ondo_eligible(viewer.user))
    except Exception:  # noqa: BLE001 - unknown: don't offer it
        logger.warning('Confio Assistant: phone eligibility unavailable', exc_info=True)
        return False


# --------------------------------------------------------------------------- #
# OpenAI transport
# --------------------------------------------------------------------------- #

def _openai_post(payload):
    api_key = getattr(settings, 'OPENAI_API_KEY', '')
    if not api_key:
        raise AssistantUnavailable('OPENAI_API_KEY is not configured')
    try:
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json=payload,
            timeout=conf.get('CONFIO_ASSISTANT_REQUEST_TIMEOUT_SECONDS'),
        )
    except requests.RequestException as exc:
        raise AssistantUnavailable(f'OpenAI request failed: {exc}') from exc
    if response.status_code >= 400:
        raise AssistantUnavailable(f'OpenAI {response.status_code}: {response.text[:300]}')
    return response.json()


def _output_text(data):
    text = data.get('output_text')
    if isinstance(text, str) and text.strip():
        return text.strip()
    chunks = []
    for item in data.get('output') or []:
        if item.get('type') == 'message':
            for part in item.get('content') or []:
                if part.get('type') in {'output_text', 'text'} and part.get('text'):
                    chunks.append(part['text'])
    return '\n'.join(chunks).strip()


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #

def _usd(value):
    return format(Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')


def _totals_dict(t):
    return {
        'entro_usd': _usd(t.income),
        'salio_usd': _usd(t.spending),
        'recargas_usd': _usd(t.top_ups),
        'retiros_usd': _usd(t.withdrawals),
        'ahorro_neto_usd': _usd(t.savings_net),
        'inversion_neta_usd': _usd(t.investment_net),
        'movimientos': t.movement_count,
    }


def _shift_month(year, month, offset):
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


def month_summary_data(viewer: Viewer, months_back=0):
    """The same numbers the "Tu mes" screen shows, or a reason they're unavailable."""
    if viewer.is_employee:
        return {'disponible': False, 'motivo': 'Solo el dueño del negocio ve el resumen del mes.'}
    try:
        from users.cashflow import summarize
    except ImportError:
        return {'disponible': False, 'motivo': 'El resumen del mes aún no está disponible.'}
    local_now = timezone.now().astimezone(viewer.tz)
    year, month = _shift_month(local_now.year, local_now.month, -int(months_back))
    result = summarize(viewer.user, viewer.account, viewer.account_type, viewer.business_id,
                       year, month, viewer.tz)
    return {
        'disponible': True,
        'mes': f'{MONTHS_ES[month - 1]} {year}',
        'mes_en_curso': months_back == 0,
        'actual': _totals_dict(result.current),
        'comparacion': {
            'tramo': 'mismo período del mes anterior' if result.previous_is_partial else 'mes anterior completo',
            **_totals_dict(result.previous),
        },
        'principales_contactos': [
            {'nombre': third_party_text(c.name) or 'Sin nombre', 'recibido_usd': _usd(c.received),
             'enviado_usd': _usd(c.sent)}
            for c in result.counterparties
        ],
    }


KIND_LABELS = {
    'income_person': 'recibido de una persona', 'sale': 'venta / cobro', 'payroll_in': 'nómina recibida',
    'bonus': 'bono', 'merchant': 'pago a comercio', 'p2p_send': 'envío a una persona',
    'payroll_out': 'nómina pagada', 'donation': 'donación', 'top_up': 'recarga desde tu banco',
    'withdrawal': 'retiro a tu banco', 'savings_in': 'a tus ahorros', 'savings_out': 'desde tus ahorros',
    'investment_in': 'compra de inversión', 'investment_out': 'venta de inversión',
}
MOVEMENT_GROUPS = {'income': 'income', 'spending': 'spending', 'own_money': 'own_money'}
# The same categories as "Tu mes" (one source: adding one there adds it here).
CATEGORY_LABELS = dict(CATEGORY_CHOICES)


def movements_data(viewer: Viewer, months_back=0, group='all', search='', limit=30):
    """The user's own classified movements (same rows and rules as "Tu mes")."""
    if viewer.is_employee:
        return {'disponible': False, 'motivo': 'Solo el dueño del negocio ve los movimientos.'}
    try:
        from users.cashflow import month_movements
    except ImportError:
        return {'disponible': False, 'motivo': 'Los movimientos aún no están disponibles.'}
    local_now = timezone.now().astimezone(viewer.tz)
    year, month = _shift_month(local_now.year, local_now.month, -int(months_back))
    groups = [group] if group in MOVEMENT_GROUPS else list(MOVEMENT_GROUPS)
    movements = []
    for g in groups:
        movements += month_movements(viewer.user, viewer.account, viewer.account_type, viewer.business_id,
                                     year, month, viewer.tz, g)
    needle = (search or '').strip().lower()
    if needle:
        movements = [m for m in movements if needle in (m.counterparty_name or '').lower()]
    movements.sort(key=lambda m: m.when, reverse=True)
    limit = max(1, min(int(limit or 30), 50))
    return {
        'disponible': True,
        'mes': f'{MONTHS_ES[month - 1]} {year}',
        'total_encontrados': len(movements),
        'mostrados': min(len(movements), limit),
        'movimientos': [
            {
                'id': m.row_id,
                'fecha': m.when.astimezone(viewer.tz).strftime('%Y-%m-%d %H:%M') if m.when else '',
                'tipo': KIND_LABELS.get(m.kind, m.kind),
                'sentido': {'received': 'entró', 'sent': 'salió'}.get(m.direction, m.direction),
                'monto_usd': _usd(m.amount),
                'contraparte': third_party_text(m.counterparty_name),
                'categoria': CATEGORY_LABELS.get(m.category) if m.category else (
                    'sin categoría' if m.kind in {'merchant', 'p2p_send', 'payroll_out', 'donation'} else None),
            }
            for m in movements[:limit]
        ],
    }


def _known_usd(value):
    return _usd(value) if value is not None else 'desconocido'


def portfolio_data(viewer: Viewer):
    """What the user holds and spends, from the same cached sources the app
    shows. A value we couldn't read is "desconocido", never a confident 0."""
    if viewer.is_employee:
        return {'disponible': False, 'motivo': 'Solo el dueño del negocio ve el saldo.'}
    address = getattr(viewer.account, 'bsc_address', '') or ''
    allowed, why_not = _ondo_decision(viewer)
    result = {'disponible': True, 'acciones_y_confio_dollar_plus_disponibles': allowed}
    if why_not:
        result['motivo_no_disponible'] = why_not
    if not address:
        result.update(confio_dollar_usd='desconocido', confio_dollar_plus_usd='desconocido', acciones='desconocido')
    else:
        from blockchain.bsc_balance_service import BscBalanceService

        raw = BscBalanceService.balances_raw(address)
        cusd = raw.get('CUSD_BSC')
        result['confio_dollar_usd'] = _known_usd(Decimal(cusd) / Decimal(10 ** 18) if cusd is not None else None)
        result['confio_dollar_plus_usd'] = _plus_usd(raw.get('CUSD_PLUS'))
        # Holdings regardless of eligibility: someone whose country changed
        # still owns their stocks (eligibility only gates buying).
        result['acciones'] = _holdings(address)
    # Only full months the account existed: a month before it opened is not
    # a month of $0 spending.
    opened = getattr(viewer.account, 'created_at', None)
    local_now = timezone.now().astimezone(viewer.tz)
    spent = []
    for back in (1, 2, 3):
        year, month = _shift_month(local_now.year, local_now.month, -back)
        if opened is not None and opened.astimezone(viewer.tz).date() > date(year, month, 1):
            break
        summary = month_summary_data(viewer, back)
        if summary.get('disponible') and summary.get('actual'):
            spent.append(Decimal(summary['actual']['salio_usd'].replace(',', '')))
    result['gasto_mensual_promedio_usd'] = _usd(sum(spent) / len(spent)) if spent else 'sin datos'
    result['meses_completos_considerados'] = len(spent)
    if result['acciones_y_confio_dollar_plus_disponibles'] is not False:
        result['confio_dollar_plus_rendimiento_anual_hoy'] = _plus_net_apy()
    result['nota'] = 'El rendimiento ganado este mes en Confío Dollar+ aún no está disponible: no lo menciones.'
    if not spent:
        # New accounts: saying "no tengo datos de tus gastos" on every answer
        # was the most repeated filler in real replies (2026-10-08 review).
        result['nota'] += (' Todavía no tiene un mes completo de gastos: no menciones sus gastos ni cuánto '
                           'dejar disponible; explica sus opciones.')
    return result


def _plus_net_apy():
    """Today's net annual yield of Confío Dollar+ (after Confío's share), the
    same live number the Confío Dollar+ screen shows. Only a rate actually read
    from the chain is quoted: apy_split() caches every real read, and on a
    failure serves the settings fallback (0% or a hand-set number), which is
    never presented as today's rate."""
    from django.core.cache import cache

    from cusd_plus import vault
    try:
        vault.apy_split()  # warms the cache; a failure is remembered briefly, so turns don't stall
    except Exception:  # noqa: BLE001 - the rate must never break the portfolio answer
        logger.warning('Confio Assistant: Confío Dollar+ APY read failed', exc_info=True)
    read = cache.get('cusd_plus_apy') or cache.get('cusd_plus_apy_last')
    net = read[1] if read else None
    if not net or net <= 0:
        return 'desconocido'
    return f'{net:.2f}'.replace('.', ',') + '% anual (variable, no garantizado)'


def _ondo_decision(viewer):
    """(allowed, why-not) for stocks and Confío Dollar+: request-aware (IP
    and phone), like every screen. No request in hand means "unknown"."""
    if not viewer.request_meta:
        return 'desconocido', None
    try:
        from cusd_plus.eligibility import ONDO_POLICY
        decision = ONDO_POLICY.evaluate(viewer.user, viewer.request_meta)
    except Exception:  # noqa: BLE001 - unknown, not "no"
        logger.warning('Confio Assistant: Ondo eligibility unavailable', exc_info=True)
        return 'desconocido', None
    if decision.allowed:
        return True, None
    if getattr(decision, 'blocked_by', None) == 'ip':
        # A phone from an eligible country connecting from a blocked one (a
        # Brazil IP, 2026-10-10): the model blamed the phone country.
        from security.geo import country_for_request
        try:
            where = country_for_request(viewer.request_meta)
        except Exception:  # noqa: BLE001
            where = None
        return False, (f'Se está conectando desde {where or "otro país"}, donde el emisor (Ondo) no permite estas '
                       'inversiones; no es por el país de su teléfono.')
    from security.geo import phone_country_of
    if not phone_country_of(viewer.user):
        return False, 'Su cuenta no tiene un país de teléfono verificado.'
    return False, 'El emisor (Ondo) no permite estas inversiones en el país de su teléfono.'


def _ondo_allowed(viewer):
    return _ondo_decision(viewer)[0]


def _plus_usd(shares):
    """Confío Dollar+ value from the shares already read; any piece we can't
    read (shares, vault, price with no last-known) is "desconocido"."""
    from django.core.cache import cache

    from cusd_plus import vault

    if shares is None:
        return 'desconocido'
    if not shares:
        return _usd(Decimal(0))
    if not vault.vault_address():
        return 'desconocido'
    try:
        price = vault.p_plus_wad()
    except Exception:  # noqa: BLE001 - fall back to the last price, never to 0
        logger.warning('Confio Assistant: Confío Dollar+ price unavailable', exc_info=True)
        price = cache.get('cusd_plus_pplus_last')
        if price is None:
            return 'desconocido'
    return _usd(Decimal(shares) * Decimal(price) / Decimal(10 ** 36))


def _holdings(address):
    from cusd_plus import gm_api
    from cusd_plus.gm_holdings import known_holdings_units
    from cusd_plus.schema import _gm_listing

    # No chain scan inside a chat turn: what the app last read (minutes old
    # at most after any visit to the stocks screen), else "desconocido".
    units = known_holdings_units(address)
    if units is None:
        return 'desconocido'
    if not units:
        return []
    try:
        market = {(item.get('primaryMarket') or {}).get('symbol'): item for item in gm_api.all_market()}
    except Exception:  # noqa: BLE001 - unknown, not empty
        logger.warning('Confio Assistant: market unavailable for holdings', exc_info=True)
        return 'desconocido'
    rows = []
    for symbol, amount in units.items():
        pm = (market.get(symbol) or {}).get('primaryMarket') or {}
        if pm.get('price') is None:
            continue
        listing = _gm_listing(market.get(symbol) or {}) or (symbol, symbol.removesuffix('on'), '')
        ticker, name = listing[1], third_party_text(listing[2], 40)
        rows.append({'ticker': ticker, 'nombre': name or ticker,
                     'valor_usd': _usd(Decimal(str(amount)) * Decimal(str(pm['price'])))})
    rows.sort(key=lambda r: Decimal(r['valor_usd'].replace(',', '')), reverse=True)
    return rows[:15]


def categorize_movements(viewer: Viewer, movement_ids, category, apply_to, *, dry_run=False):
    """Label the user's own spending movements, exactly like the Tu mes chips.
    dry_run: validate and count only (the proposal the user must confirm)."""
    if viewer.is_employee:
        return {'ok': False, 'motivo': 'Solo el dueño del negocio puede clasificar movimientos.'}
    if category not in CATEGORY_LABELS or apply_to not in ('counterparty', 'movement'):
        return {'ok': False, 'motivo': 'categoría no válida'}
    try:
        from users.cashflow import SPENDING_KINDS, resolve_movement
        from users.models_cashflow import CounterpartyRule, MovementOverride
    except ImportError:
        return {'ok': False, 'motivo': 'La clasificación aún no está disponible.'}
    done, skipped, counterparties, names = [], [], set(), []
    for movement_id in list(dict.fromkeys(movement_ids or []))[:50]:
        # Scoped lookup: an id outside this account resolves to nothing.
        row, movement = resolve_movement(viewer.user, viewer.account, viewer.account_type,
                                         viewer.business_id, movement_id=movement_id)
        if row is None or movement is None or movement.kind not in SPENDING_KINDS:
            skipped.append(movement_id)
            continue
        name = third_party_text(getattr(movement, 'counterparty_name', ''), 24)
        if name and name not in names:
            names.append(name)
        if apply_to == 'counterparty':
            if not movement.counterparty_key:
                skipped.append(movement_id)
                continue
            if dry_run:
                counterparties.add(movement.counterparty_key)
            elif movement.counterparty_key not in counterparties:
                CounterpartyRule.objects.update_or_create(
                    account=viewer.account, counterparty_key=movement.counterparty_key,
                    defaults={'category': category, 'created_by': viewer.user})
                counterparties.add(movement.counterparty_key)
        elif not dry_run:
            MovementOverride.objects.update_or_create(
                account=viewer.account, movement=row,
                defaults={'category': category, 'created_by': viewer.user})
        done.append(movement_id)
    return {
        'ok': bool(done),
        'clasificados': len(done),
        'omitidos': skipped,
        'categoria': CATEGORY_LABELS[category],
        'alcance': 'todos los pagos pasados y futuros a esos contactos' if apply_to == 'counterparty'
                   else 'solo esos movimientos',
        'contactos': names[:5],
    }


# Public documents in this repo (also on GitHub) the model may read in full.
PUBLIC_DOCUMENTS = {
    'tokenomics': 'docs/tokenomics/README.md',
    'whitepaper': 'docs/whitepaper/README.md',
}
PUBLIC_DOCUMENT_MAX_CHARS = 60_000
# Facts newer than a document's text, verified on-chain; returned first so the
# model never repeats a stale passage. Empty while the documents are current.
PUBLIC_DOCUMENT_ERRATA: dict[str, str] = {}


class Toolbelt:
    """The model's tools for one turn, bound to one viewer."""

    def __init__(self, viewer: Viewer, result: TurnResult, *, analyses_left: int, can_navigate: bool = True,
                 reserve_analysis=None, reserve_news=None, paid_offers_allowed: bool = True):
        self.viewer = viewer
        self.result = result
        self.analyses_left = analyses_left
        # When given, claims a slot under the caller's quota lock (preferred).
        self.reserve_analysis = reserve_analysis
        # Market tools only where the caller meters news searches (text turns;
        # realtime voice has its own server-tool list).
        self.reserve_news = reserve_news
        self.saw_web = False
        self.docs_read = set()
        # Paid tools run at most once per user message, whatever the model asks.
        self.paid_used = set()
        self.can_navigate = can_navigate
        self.destinations = allowed_destinations(viewer, paid_offers_allowed=paid_offers_allowed)

    def specs(self):
        specs = [] if not self.can_navigate else [
            {
                'type': 'function',
                'name': 'navigate',
                'description': 'Abre una pantalla de la app Confío para el usuario. Para una acción o ETF '
                               'concreto usa destination "stock", su ticker en `asset` y en `label` un nombre corto '
                               'como lo conoce una persona (máx. 22 caracteres, p. ej. "S&P 500 (SPY)"); si no, '
                               'asset y label = null.',
                'parameters': {
                    'type': 'object',
                    'properties': {'destination': {'type': 'string', 'enum': self.destinations},
                                   'asset': {'type': ['string', 'null']},
                                   'label': {'type': ['string', 'null']}},
                    'required': ['destination', 'asset', 'label'],
                    'additionalProperties': False,
                },
                'strict': True,
            },
        ]
        specs += [
            {
                'type': 'function',
                'name': 'escalate_to_human',
                'description': (
                    'Pasa la conversación al equipo humano de Confío. Úsalo para dinero atascado o '
                    'perdido, fraude, cuenta bloqueada, o si el usuario pide una persona.'
                ),
                'parameters': {
                    'type': 'object',
                    'properties': {'reason': {'type': 'string', 'description': 'Resumen breve del problema para el equipo.'}},
                    'required': ['reason'],
                    'additionalProperties': False,
                },
                'strict': True,
            },
        ]
        if not self.viewer.is_employee:
            specs += [
                {
                    'type': 'function',
                    'name': 'get_month_summary',
                    'description': (
                        'Resumen de un mes de la cuenta activa: entró, salió, recargas, retiros, '
                        'ahorro e inversión neta y principales contactos. months_back=0 es el mes en curso.'
                    ),
                    'parameters': {
                        'type': 'object',
                        'properties': {'months_back': {'type': 'integer', 'minimum': 0, 'maximum': 5}},
                        'required': ['months_back'],
                        'additionalProperties': False,
                    },
                    'strict': True,
                },
                {
                    'type': 'function',
                    'name': 'get_transactions',
                    'description': (
                        'Movimientos de la cuenta activa en un mes (fecha, tipo, monto, contraparte, '
                        'categoría, id). Filtra por grupo (income=entró, spending=salió, own_money=recargas/'
                        'retiros/ahorro/inversión, all) y por nombre de contraparte. Úsalo para responder '
                        'sobre pagos concretos o antes de clasificar.'
                    ),
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'months_back': {'type': 'integer', 'minimum': 0, 'maximum': 11},
                            'group': {'type': 'string', 'enum': ['all', 'income', 'spending', 'own_money']},
                            'search': {'type': 'string', 'description': 'Parte del nombre de la contraparte, o vacío.'},
                            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50},
                        },
                        'required': ['months_back', 'group', 'search', 'limit'],
                        'additionalProperties': False,
                    },
                    'strict': True,
                },
                {
                    'type': 'function',
                    'name': 'categorize_transactions',
                    'description': (
                        'Clasifica gastos del usuario (solo cuando él lo pide o confirma). ids = los id de '
                        'get_transactions. apply_to=counterparty aplica a todos los pagos pasados y futuros '
                        'a esa contraparte; movement solo a esos movimientos.'
                    ),
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'ids': {'type': 'array', 'items': {'type': 'integer'}},
                            'category': {'type': 'string', 'enum': list(CATEGORY_LABELS)},
                            'apply_to': {'type': 'string', 'enum': ['counterparty', 'movement']},
                        },
                        'required': ['ids', 'category', 'apply_to'],
                        'additionalProperties': False,
                    },
                    'strict': True,
                },
                {
                    'type': 'function',
                    'name': 'analyze_finances',
                    'description': (
                        'Análisis a fondo de la actividad de los últimos meses para responder una '
                        'pregunta del usuario sobre sus finanzas. Más lento: úsalo solo cuando un '
                        'resumen no basta.'
                    ),
                    'parameters': {
                        'type': 'object',
                        'properties': {'question': {'type': 'string'}},
                        'required': ['question'],
                        'additionalProperties': False,
                    },
                    'strict': True,
                },
            ]
        if not self.viewer.is_employee:
            specs += [{
                'type': 'function',
                'name': 'get_portfolio',
                'description': (
                    'Lo que el usuario tiene y gasta: saldo en Confío Dollar y Confío Dollar+, sus acciones, '
                    'gasto mensual promedio de los últimos meses, el rendimiento anual de hoy de Confío Dollar+ '
                    'y si acciones/Confío Dollar+ están disponibles en su país. Úsala antes de orientar sobre '
                    'inversiones o ahorro, y cuando pregunten cuánto rinde Confío Dollar+.'
                ),
                'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
                'strict': True,
            }]
        specs += [
            {
                'type': 'function',
                'name': 'read_public_document',
                'description': (
                    'Lee un documento público de Confío publicado en GitHub, para detalles que no están en las '
                    'respuestas aprobadas: "tokenomics" ($CONFIO: suministro, distribución, preventa, recompensas, '
                    'vesting, riesgos) o "whitepaper" (la empresa, el producto, BNB Smart Chain, contratos, modelo '
                    'de negocio, cumplimiento, hoja de ruta). Edición en inglés (la oficial).'
                ),
                'parameters': {
                    'type': 'object',
                    'properties': {'document': {'type': 'string', 'enum': list(PUBLIC_DOCUMENTS)}},
                    'required': ['document'],
                    'additionalProperties': False,
                },
                'strict': True,
            },
        ]
        if self.reserve_news is not None:
            specs += [
                {
                    'type': 'function',
                    'name': 'get_stock_quote',
                    'description': (
                        'Precio actual, cambio de 24 horas y de 1 mes de una acción o ETF de EE.UU. que muestra '
                        'Confío (fuente: Ondo Global Markets). query = ticker o nombre, p. ej. "AAPL" o "Apple".'
                    ),
                    'parameters': {
                        'type': 'object',
                        'properties': {'query': {'type': 'string'}},
                        'required': ['query'],
                        'additionalProperties': False,
                    },
                    'strict': True,
                },
                {
                    'type': 'function',
                    'name': 'search_market_news',
                    'description': (
                        'Busca en la web, con fuentes, qué se informó sobre por qué se movió una acción, un índice '
                        'o el mercado. Solo hechos ya ocurridos. Después de usarla respondes sin más herramientas. '
                        'topic = una acción que muestra Confío (nombre o ticker, p. ej. "Apple", "TSLA") o un mercado ("S&P 500", '
                        '"Nasdaq", "Dow Jones", "bolsa", "oro", "petróleo"); language = idioma del usuario.'
                    ),
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'topic': {'type': 'string'},
                            'timeframe': {'type': 'string', 'enum': list(market.TIMEFRAMES)},
                            'language': {'type': 'string', 'enum': list(market.LANGUAGES)},
                        },
                        'required': ['topic', 'timeframe', 'language'],
                        'additionalProperties': False,
                    },
                    'strict': True,
                },
            ]
        return specs

    def call(self, name, args):
        handler = {
            'navigate': self.navigate,
            'escalate_to_human': self.escalate_to_human,
            'get_month_summary': self.get_month_summary,
            'get_transactions': self.get_transactions,
            'categorize_transactions': self.categorize_transactions,
            'analyze_finances': self.analyze_finances,
            'get_stock_quote': self.get_stock_quote,
            'read_public_document': self.read_public_document,
            'get_portfolio': self.get_portfolio,
            'search_market_news': self.search_market_news,
        }.get(name)
        if name in {'get_stock_quote', 'search_market_news'} and self.reserve_news is None:
            handler = None
        if handler is None:
            return {'error': f'herramienta desconocida: {name}'}
        return handler(**args)

    def navigate(self, destination, asset=None, label=None):
        if not self.can_navigate or destination not in self.destinations:
            return {'ok': False, 'error': 'pantalla no disponible'}
        if destination in PAID_OFFERS:
            from .paid_chips import capped
            if self.viewer.user is not None and capped(self.viewer.user, destination):
                # Shown this week already: no chip, so the reply must not pitch it
                # again either (if the person asks by name, the server adds it).
                return {'ok': False, 'error': 'Ya se la ofreciste esta semana: no la vuelvas a ofrecer en esta '
                                              'respuesta, salvo que la persona pregunte por ella.'}
        # `destination` stays a key every build knows; newer builds open
        # `target` (and `ticker`) instead.
        action = {'type': 'navigate', 'destination': FALLBACKS.get(destination, destination)}
        # What actually opened, for the model to describe (not the fallback key).
        reply = {'ok': True, 'pantalla_abierta': DESTINATIONS[destination]}
        if destination in FALLBACKS:
            action['target'] = destination
        if destination == 'stock':
            if _ondo_allowed(self.viewer) is not True:
                return {'ok': False, 'error': 'Las acciones no están disponibles para este usuario.'}
            found = market.listed_asset(asset)
            if found is None:
                return {'ok': False, 'error': 'No encontré esa acción o ETF entre las que muestra Confío.'}
            ticker, name = found
            # The model's short label only when it names this exact ticker, so
            # the chip can't promise one fund and open another.
            short = third_party_text(label or '', 22)
            if '…' in short or not re.search(rf'\b{re.escape(ticker)}\b', short, re.I):
                short = ''
            if not short:
                short = name if len(name) <= 22 else ticker
            action.update(ticker=ticker, label=f'Ver {short}')
            reply['activo'] = f'{name} ({ticker})'
        if action not in self.result.actions:
            self.result.actions.append(action)
        return {**reply, **{k: v for k, v in action.items() if k != 'type'}}

    def escalate_to_human(self, reason):
        self.result.handoff_reason = (reason or '').strip()[:280] or 'Solicitud del usuario'
        return {'ok': True, 'nota': 'El equipo humano verá esta conversación. Díselo al usuario en una línea.'}

    def get_month_summary(self, months_back=0):
        if self.viewer.is_employee:
            return {'disponible': False, 'motivo': 'Solo el dueño del negocio ve el resumen del mes.'}
        months_back = max(0, min(int(months_back or 0), 5))
        return month_summary_data(self.viewer, months_back)

    def get_transactions(self, months_back=0, group='all', search='', limit=30):
        months_back = max(0, min(int(months_back or 0), 11))
        return movements_data(self.viewer, months_back, group, search, limit)

    def categorize_transactions(self, ids, category, apply_to):
        # Never written here: text in tool data (a sender's name) could have
        # asked for it. The proposal is kept and applied only if the user's
        # next message says yes (service.confirm_pending_categorization).
        if self.result.pending_categorization is not None:
            return {'ok': False, '_denied': True, 'motivo': 'Una propuesta de clasificación por mensaje.'}
        result = categorize_movements(self.viewer, ids, category, apply_to, dry_run=True)
        if not result.get('ok'):
            return result
        self.result.pending_categorization = {
            'ids': list(dict.fromkeys(ids or []))[:50], 'category': category, 'apply_to': apply_to,
            'count': result['clasificados'], 'label': result['categoria'], 'contacts': result.get('contactos') or []}
        return {
            'pendiente_de_confirmacion': True,
            'movimientos': result['clasificados'],
            'omitidos': result['omitidos'],
            'categoria': result['categoria'],
            'alcance': result['alcance'],
            'instruccion': 'Todavía NO está guardado. La app agrega debajo de tu respuesta la pregunta de '
                           'confirmación exacta; no hagas otra pregunta distinta en este mensaje.',
        }

    def analyze_finances(self, question):
        if 'analyze_finances' in self.paid_used:
            return {'disponible': False, '_denied': True, 'motivo': 'Un análisis por mensaje.'}
        if self.viewer.is_employee:
            return {'disponible': False, 'motivo': 'Solo el dueño del negocio puede analizar la cuenta.'}
        if self.reserve_analysis is not None:
            allowed = self.reserve_analysis()
        else:
            allowed = self.analyses_left > 0
            self.analyses_left -= 1
        if not allowed:
            return {'disponible': False, '_denied': True,
                    'motivo': 'Llegaste al límite de análisis de hoy. Mañana puedes pedir otro.'}
        self.paid_used.add('analyze_finances')
        months = [month_summary_data(self.viewer, back) for back in range(3)]
        if not any(m.get('disponible') for m in months):
            return months[0]
        # The movements behind this month's numbers, so the analysis can name
        # what changed (earlier months go in as totals only: half the input
        # tokens, measured ~US$0.019 → ~0.01 per analysis).
        detail = [movements_data(self.viewer, 0, 'all', '', 50)]
        model = conf.get('CONFIO_ASSISTANT_ANALYSIS_MODEL')
        payload = {
            'model': model,
            'instructions': ANALYSIS_PROMPT,
            'input': [{
                'role': 'user',
                'content': json.dumps({'pregunta': question, 'meses': months, 'movimientos_recientes': detail},
                                      ensure_ascii=False),
            }],
            'max_output_tokens': 3000,
            # Financial details: never retained by the provider.
            'store': False,
        }
        effort = conf.get('CONFIO_ASSISTANT_ANALYSIS_REASONING_EFFORT')
        if effort:
            payload['reasoning'] = {'effort': effort}
        data = _openai_post(payload)
        self.result.add_usage(model, data.get('usage'))
        return {'analisis': _output_text(data) or 'Sin análisis.'}

    def get_portfolio(self):
        return portfolio_data(self.viewer)

    def read_public_document(self, document):
        path = PUBLIC_DOCUMENTS.get(document)
        if path is None:
            return {'error': 'Documento no disponible.'}
        # The transcript is re-sent every step: one copy per turn is enough.
        if document in self.docs_read:
            return {'documento': document, 'nota': 'Ya lo leíste en este turno; usa ese texto.'}
        self.docs_read.add(document)
        text = (Path(settings.BASE_DIR) / path).read_text(encoding='utf-8')
        result = {
            'documento': document,
            'fuente': f'https://github.com/caesar4321/Confio/blob/main/{path}',
        }
        if document in PUBLIC_DOCUMENT_ERRATA:
            result['correccion_mas_reciente'] = PUBLIC_DOCUMENT_ERRATA[document]
        result['texto'] = text[:PUBLIC_DOCUMENT_MAX_CHARS]
        return result

    def get_stock_quote(self, query):
        return market.stock_quote(query, user=self.viewer.user)

    def search_market_news(self, topic, timeframe='esta semana', language='español'):
        if market.resolve_topic(topic) is None:
            return {'encontrado': False, '_denied': True,
                    'motivo': 'Solo puedo buscar noticias de una empresa, ticker o índice.'}
        if 'search_market_news' in self.paid_used:
            return {'disponible': False, '_denied': True, 'motivo': 'Una búsqueda de noticias por mensaje.'}
        if not self.reserve_news():
            return {'disponible': False, '_denied': True,
                    'motivo': 'Llegaste al límite de búsquedas de noticias de hoy.'}
        self.paid_used.add('search_market_news')
        try:
            found = market.market_news(topic, timeframe=timeframe, language=language)
        except AssistantUnavailable:
            # A search outage must not sink the whole answer.
            logger.warning('Confio Assistant: market news search failed', exc_info=True)
            return {'error': 'No pude buscar noticias ahora.'}
        self.result.add_usage(conf.get('CONFIO_ASSISTANT_MODEL'), found.get('_usage'))
        self.result.cost_usd += market.search_cost(found.get('_search_calls') or 0)
        if found.get('encontrado'):
            # Web text is untrusted: the answer that follows gets no tools.
            self.saw_web = True
        return found


# --------------------------------------------------------------------------- #
# Turn
# --------------------------------------------------------------------------- #

def history_items(messages):
    """SupportMessages (oldest first) as Responses input items.

    Staff replies stay attributed so the model doesn't contradict a person.
    """
    items = []
    for message in messages:
        body = (message.body or '').strip()
        if not body:
            continue
        metadata = message.metadata or {}
        if metadata.get('client_reported') or metadata.get('handoff_note'):
            # Lines a client relayed (voice captions) and handoff notes for the
            # team are not things the user or the assistant said in this chat.
            continue
        is_staff = (message.sender_type == 'AGENT' and not metadata.get('ai')
                    and getattr(message, 'sender_user_id', None) is not None)
        if not is_staff:
            # Only a real person on the team may speak as the team.
            body = _STAFF_PREFIX_SPOOF.sub('', body).strip()
            if not body:
                continue
        if message.sender_type == 'USER':
            items.append({'role': 'user', 'content': body})
        elif is_staff:
            items.append({'role': 'assistant', 'content': f'{STAFF_PREFIX} {body}'})
        else:
            items.append({'role': 'assistant', 'content': body})
    return items


def run_turn(viewer: Viewer, history, *, first_name, account_label, country, analyses_left, can_navigate=True,
             reserve_analysis=None, reserve_news=None):
    """Answer the last user message in `history`. Raises AssistantUnavailable,
    except after the model already escalated: the handoff is kept."""
    result = TurnResult(reply='')
    belt = Toolbelt(viewer, result, analyses_left=analyses_left, can_navigate=can_navigate,
                    reserve_analysis=reserve_analysis, reserve_news=reserve_news)
    try:
        return _run_turn(belt, result, viewer, history, first_name=first_name, account_label=account_label,
                         country=country)
    except AssistantUnavailable as exc:
        # Usage already spent (a search, an analysis) is still billed: the
        # caller meters it from here even though the turn failed.
        exc.partial = result
        # Work already done (an escalation, saved categories) must survive a
        # failed follow-up generation, so the caller still routes/refreshes.
        if result.handoff_reason:
            result.reply = 'Te paso con el equipo de Confío. Te responderán aquí mismo.'
            return result
        if result.writes:
            result.reply = 'Listo, ya guardé los cambios. Puedes verlos en Tu mes.'
            return result
        raise


def _run_turn(belt, result, viewer, history, *, first_name, account_label, country):
    local_now = timezone.now().astimezone(viewer.tz)
    system = build_system_prompt(
        first_name=first_name,
        account_label=account_label,
        country=country,
        screen=viewer.screen,
        local_now=f'{local_now:%Y-%m-%d %H:%M} ({viewer.tz})',
        destinations=belt.destinations,
        can_navigate=belt.can_navigate,
    )
    model = conf.get('CONFIO_ASSISTANT_MODEL')
    effort = conf.get('CONFIO_ASSISTANT_REASONING_EFFORT')
    specs = belt.specs()
    if model.startswith('claude-'):
        return _run_turn_claude(belt, result, history, system, model, effort, specs)
    payload = {
        'model': model,
        'instructions': system,
        'input': history_items(history),
        'tools': specs,
        'max_output_tokens': 2000,
        # No server-side retention of customer turns; reasoning is carried
        # forward encrypted between tool steps instead.
        'store': False,
        'include': ['reasoning.encrypted_content'],
    }
    if effort:
        payload['reasoning'] = {'effort': effort}

    input_items = list(payload['input'])
    for _ in range(conf.get('CONFIO_ASSISTANT_MAX_TOOL_STEPS')):
        data = _openai_post(payload)
        result.add_usage(model, data.get('usage'))
        output = data.get('output') or []
        calls = [item for item in output if item.get('type') == 'function_call']
        if not calls:
            result.reply = _output_text(data)
            break
        # store=False: carry the whole transcript forward instead of previous_response_id.
        input_items.extend(item for item in output if item.get('type') in {'function_call', 'reasoning'})
        for call in calls:
            try:
                args = json.loads(call.get('arguments') or '{}')
            except (TypeError, ValueError):
                args = {}
            input_items.append({
                'type': 'function_call_output',
                'call_id': call.get('call_id'),
                'output': _run_tool(belt, result, call.get('name'), args),
            })
        payload = {**payload, 'input': input_items}
        if belt.saw_web:
            payload['tool_choice'] = 'none'
    else:
        payload = {**payload, 'input': input_items, 'tool_choice': 'none'}
        data = _openai_post(payload)
        result.add_usage(model, data.get('usage'))
        result.reply = _output_text(data)

    return _finish(result)


def _run_tool(belt, result, name, args):
    """Run one model tool call and return its output as the JSON text the model reads."""
    started = time.monotonic()
    try:
        tool_output = belt.call(name, args)
    except AssistantUnavailable:
        raise
    except Exception:  # noqa: BLE001 - a broken tool must read as broken, not as "no data"
        logger.exception('Confio Assistant tool %s failed', name)
        tool_output = {'error': 'La herramienta falló. Dile al usuario que no pudiste consultarlo ahora.'}
    denied = bool(tool_output.get('_denied'))
    result.tools.append({
        # Quotas count tool names; a refused call must not use a slot.
        'name': f'{name}:denied' if denied else name,
        'args': args,
        'ok': 'error' not in tool_output,
        'ms': int((time.monotonic() - started) * 1000),
    })
    # Public documents are read whole; everything else stays small.
    return json.dumps({k: v for k, v in tool_output.items() if not str(k).startswith('_')},
                      ensure_ascii=False)[:(PUBLIC_DOCUMENT_MAX_CHARS + 2000
                                           if name == 'read_public_document' else 12000)]


def _finish(result):
    if not result.reply:
        if result.actions:
            result.reply = 'Listo.'
        elif result.handoff_reason:
            result.reply = 'Te paso con el equipo de Confío. Te responderán aquí mismo.'
        else:
            raise AssistantUnavailable('empty reply')
    return result


# --------------------------------------------------------------------------- #
# Claude transport (evaluation; production stays on CONFIO_ASSISTANT_MODEL)
# --------------------------------------------------------------------------- #

def _claude_client():
    import anthropic

    api_key = getattr(settings, 'ANTHROPIC_API_KEY', '') or None
    return anthropic.Anthropic(api_key=api_key, max_retries=1,
                               timeout=conf.get('CONFIO_ASSISTANT_REQUEST_TIMEOUT_SECONDS'))


_CLAUDE_STRICT_UNSUPPORTED = ('minimum', 'maximum', 'minLength', 'maxLength', 'minItems', 'maxItems')


def _claude_schema(schema):
    """Claude's strict mode rejects numeric/length bounds: keep them as words in the description."""
    if isinstance(schema, list):
        return [_claude_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out = {key: _claude_schema(value) for key, value in schema.items() if key not in _CLAUDE_STRICT_UNSUPPORTED}
    bounds = ', '.join(f'{key}={schema[key]}' for key in _CLAUDE_STRICT_UNSUPPORTED if key in schema)
    if bounds:
        out['description'] = f"{schema.get('description', '')} ({bounds})".strip()
    return out


def _claude_tools(specs):
    return [{'name': spec['name'], 'description': spec['description'],
             'input_schema': _claude_schema(spec['parameters']) if spec.get('strict') else spec['parameters'],
             **({'strict': True} if spec.get('strict') else {})} for spec in specs]


def _claude_usage(usage):
    """Anthropic usage in the Responses shape add_usage reads."""
    read = getattr(usage, 'cache_read_input_tokens', 0) or 0
    written = getattr(usage, 'cache_creation_input_tokens', 0) or 0
    return {'input_tokens': (usage.input_tokens or 0) + read + written,
            'input_tokens_details': {'cached_tokens': read},
            'output_tokens': usage.output_tokens or 0}


def _run_turn_claude(belt, result, history, system, model, effort, specs):
    import anthropic

    client = _claude_client()
    messages = [{'role': item['role'], 'content': item['content']} for item in history_items(history)]
    while messages and messages[0]['role'] != 'user':
        messages.pop(0)
    request = {
        'model': model,
        'max_tokens': 4000,
        'system': [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
        'tools': _claude_tools(specs),
    }
    if effort:
        request['output_config'] = {'effort': effort}

    def send(**extra):
        try:
            response = client.messages.create(**request, messages=messages, **extra)
        except anthropic.APIError as exc:
            raise AssistantUnavailable(f'Claude request failed: {exc}') from exc
        result.add_usage(model, _claude_usage(response.usage))
        if response.stop_reason == 'refusal':
            raise AssistantUnavailable('Claude refused')
        return response

    def text_of(response):
        return '\n'.join(b.text for b in response.content if b.type == 'text').strip()

    for _ in range(conf.get('CONFIO_ASSISTANT_MAX_TOOL_STEPS')):
        response = send(**({'tool_choice': {'type': 'none'}} if belt.saw_web else {}))
        calls = [b for b in response.content if b.type == 'tool_use']
        if not calls:
            result.reply = text_of(response)
            break
        messages.append({'role': 'assistant', 'content': response.content})
        messages.append({'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': call.id,
             'content': _run_tool(belt, result, call.name, dict(call.input or {}))}
            for call in calls]})
    else:
        result.reply = text_of(send(tool_choice={'type': 'none'}))
    return _finish(result)

def human_mode_active(state, last_staff_reply_at, now=None):
    """True while the human team owns the thread (see AssistantThreadState)."""
    now = now or timezone.now()
    window = timedelta(hours=conf.get('CONFIO_ASSISTANT_HUMAN_MODE_HOURS'))
    signals = [t for t in (getattr(state, 'handoff_at', None), last_staff_reply_at) if t]
    if not signals:
        return False
    latest = max(signals)
    returned = getattr(state, 'returned_to_ai_at', None)
    if returned and returned >= latest:
        return False
    return now - latest < window
