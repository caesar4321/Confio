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
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import requests
from django.conf import settings
from django.utils import timezone

from . import conf, market
from .destinations import DESTINATIONS, OWNER_ONLY, PERSONAL_ONLY
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


def allowed_destinations(viewer: Viewer):
    keys = list(DESTINATIONS)
    if viewer.is_employee:
        keys = [k for k in keys if k not in OWNER_ONLY]
    if viewer.account_type == 'business':
        # Business pay-ins are never held for Confío Face (payin_hold.needs_face).
        keys = [k for k in keys if k not in PERSONAL_ONLY]
    return keys


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
            {'nombre': c.name or 'Sin nombre', 'recibido_usd': _usd(c.received), 'enviado_usd': _usd(c.sent)}
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
CATEGORY_LABELS = {'food': 'Comida', 'transport': 'Transporte', 'home': 'Casa',
                   'family': 'Familia', 'work': 'Trabajo', 'other': 'Otro'}


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
                'contraparte': m.counterparty_name or '',
                'categoria': CATEGORY_LABELS.get(m.category) if m.category else (
                    'sin categoría' if m.kind in {'merchant', 'p2p_send', 'payroll_out', 'donation'} else None),
            }
            for m in movements[:limit]
        ],
    }


def categorize_movements(viewer: Viewer, movement_ids, category, apply_to):
    """Label the user's own spending movements, exactly like the Tu mes chips."""
    if viewer.is_employee:
        return {'ok': False, 'motivo': 'Solo el dueño del negocio puede clasificar movimientos.'}
    if category not in CATEGORY_LABELS or apply_to not in ('counterparty', 'movement'):
        return {'ok': False, 'motivo': 'categoría no válida'}
    try:
        from users.cashflow import SPENDING_KINDS, resolve_movement
        from users.models_cashflow import CounterpartyRule, MovementOverride
    except ImportError:
        return {'ok': False, 'motivo': 'La clasificación aún no está disponible.'}
    done, skipped, counterparties = [], [], set()
    for movement_id in list(dict.fromkeys(movement_ids or []))[:50]:
        # Scoped lookup: an id outside this account resolves to nothing.
        row, movement = resolve_movement(viewer.user, viewer.account, viewer.account_type,
                                         viewer.business_id, movement_id=movement_id)
        if row is None or movement is None or movement.kind not in SPENDING_KINDS:
            skipped.append(movement_id)
            continue
        if apply_to == 'counterparty':
            if not movement.counterparty_key:
                skipped.append(movement_id)
                continue
            if movement.counterparty_key not in counterparties:
                CounterpartyRule.objects.update_or_create(
                    account=viewer.account, counterparty_key=movement.counterparty_key,
                    defaults={'category': category, 'created_by': viewer.user})
                counterparties.add(movement.counterparty_key)
        else:
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
    }


class Toolbelt:
    """The model's tools for one turn, bound to one viewer."""

    def __init__(self, viewer: Viewer, result: TurnResult, *, analyses_left: int, can_navigate: bool = True,
                 reserve_analysis=None, reserve_news=None):
        self.viewer = viewer
        self.result = result
        self.analyses_left = analyses_left
        # When given, claims a slot under the caller's quota lock (preferred).
        self.reserve_analysis = reserve_analysis
        # Market tools only where the caller meters news searches (text turns;
        # realtime voice has its own server-tool list).
        self.reserve_news = reserve_news
        self.saw_web = False
        self.can_navigate = can_navigate
        self.destinations = allowed_destinations(viewer)

    def specs(self):
        specs = [] if not self.can_navigate else [
            {
                'type': 'function',
                'name': 'navigate',
                'description': 'Abre una pantalla de la app Confío para el usuario.',
                'parameters': {
                    'type': 'object',
                    'properties': {'destination': {'type': 'string', 'enum': self.destinations}},
                    'required': ['destination'],
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
            'search_market_news': self.search_market_news,
        }.get(name)
        if name in {'get_stock_quote', 'search_market_news'} and self.reserve_news is None:
            handler = None
        if handler is None:
            return {'error': f'herramienta desconocida: {name}'}
        return handler(**args)

    def navigate(self, destination):
        if not self.can_navigate or destination not in self.destinations:
            return {'ok': False, 'error': 'pantalla no disponible'}
        action = {'type': 'navigate', 'destination': destination}
        if action not in self.result.actions:
            self.result.actions.append(action)
        return {'ok': True}

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
        result = categorize_movements(self.viewer, ids, category, apply_to)
        if result.get('ok'):
            self.result.writes.append({'type': 'categorize', 'count': result['clasificados'],
                                       'category': category, 'apply_to': apply_to})
        return result

    def analyze_finances(self, question):
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

    def get_stock_quote(self, query):
        return market.stock_quote(query, user=self.viewer.user)

    def search_market_news(self, topic, timeframe='esta semana', language='español'):
        if market.resolve_topic(topic) is None:
            return {'encontrado': False, '_denied': True,
                    'motivo': 'Solo puedo buscar noticias de una empresa, ticker o índice.'}
        if not self.reserve_news():
            return {'disponible': False, '_denied': True,
                    'motivo': 'Llegaste al límite de búsquedas de noticias de hoy.'}
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
        if message.sender_type == 'USER':
            items.append({'role': 'user', 'content': body})
        elif message.sender_type == 'AGENT' and not (message.metadata or {}).get('ai'):
            items.append({'role': 'assistant', 'content': f'[Equipo Confío, persona] {body}'})
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
            name = call.get('name')
            try:
                args = json.loads(call.get('arguments') or '{}')
            except (TypeError, ValueError):
                args = {}
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
            input_items.append({
                'type': 'function_call_output',
                'call_id': call.get('call_id'),
                'output': json.dumps({k: v for k, v in tool_output.items() if not str(k).startswith('_')},
                                     ensure_ascii=False)[:12000],
            })
        payload = {**payload, 'input': input_items}
        if belt.saw_web:
            payload['tool_choice'] = 'none'
    else:
        payload = {**payload, 'input': input_items, 'tool_choice': 'none'}
        data = _openai_post(payload)
        result.add_usage(model, data.get('usage'))
        result.reply = _output_text(data)

    if not result.reply:
        if result.actions:
            result.reply = 'Listo.'
        elif result.handoff_reason:
            result.reply = 'Te paso con el equipo de Confío. Te responderán aquí mismo.'
        else:
            raise AssistantUnavailable('empty reply')
    return result


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
