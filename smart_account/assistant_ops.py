"""Confío IA+ operates the owner's Cuenta inteligente (spec decision 34).

"The assistant executes", within hard limits:

- It reads the account (rules, next runs, last results, a period review).
- It PROPOSES rule changes the owner asked for. A proposal is data: it is
  shown in plain Spanish with a chip that opens the existing rule screen
  prefilled. Nothing is prepared, signed or stored on chain here; the change
  exists only after the owner reviews it on that screen and signs it through
  the normal prepare -> sign flow, whose server side re-validates everything.
- It never chooses what to buy, how much, or a target split: every asset
  and percentage must be in the owner's own words (the caller passes them in
  `said`), and an amount is only the number the owner typed answering the
  server's "¿Cuántos dólares?" (`amount_given`, assistant/asked.py). Re-splitting the next buys toward a target the owner set
  is computed here from that target, never invented by the model.
- It never sells. A target allocation is kept by new buys only.

Maps from what people ask to what the contract has (no new capabilities):
"pausar" = stop (cancelRule; the owner can create it again later); a weekday
or a day of the month = frequency + firstRunAt; "guarda / ahorra X" has no
rule (decision 17: their dollar already is their balance).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import abi, assets as assets_mod, chain, context, services
from .models import (
    SmartAccount, SmartAccountCardPull, SmartAccountCharge, SmartAccountEvent, SmartAccountPreparedAction, SmartAccountRule,
    SmartAccountRuleRun, SmartAccountTargetAllocation,
)

logger = logging.getLogger(__name__)

OPERABLE = ('active', 'cancel_pending')
# Who gets money every month, read out of a sentence: paused (founder, 2026-11-22).
# Stopping a rule, and the buy rules, still work from the chat. Lifting it is the founder's call.
PAYING_RULES_PAUSED = True
PAYING_RULES_REFUSAL = ('Por ahora no creo ni cambio desde el chat reglas que envían o pagan a alguien. Hazlo en tu '
                        'Cuenta inteligente, en Reglas: ahí escribes el monto y lo ves antes de firmar.')
FREQUENCIES = ('daily', 'weekly', 'biweekly', 'monthly')
WEEKDAYS_ES = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
FIRST_RUN_HOUR = 10  # local time of the owner
BPS = 10_000
CENT = Decimal('0.01')
# Asked as a word, the catalog's name for it.
ASSET_ALIASES = {'oro': 'gold', 'bitcoin': 'btc', 'bitcóin': 'btc'}


class OpsRefused(Exception):
    """A request the account cannot do, with the sentence the model relays."""

    def __init__(self, message: str, code: str = 'refused'):
        self.message, self.code = message, code
        super().__init__(code)


# ── who may use it ─────────────────────────────────────────────────────

def operable_account(user):
    """The user's own account while it can carry rules, or None."""
    own = context.own_account(user)
    return own if own is not None and own.status in OPERABLE else None


def entitled(user) -> bool:
    """IA+ through a current Cuenta inteligente: has_plus AND an own account
    that can carry rules. An inherited account never counts."""
    from assistant.billing import has_plus
    try:
        return operable_account(user) is not None and has_plus(user)
    except Exception:  # noqa: BLE001 — no tools is always safe
        logger.warning('smart account ops: entitlement check failed', exc_info=True)
        return False


def _viewer(user, meta=None):
    personal = context.personal_account(user)
    if personal is None:
        raise OpsRefused('Tu cuenta personal no está lista todavía.')
    return context.Viewer(user=user, personal_account=personal, context_type='personal', meta=dict(meta or {}))


def _clean(value, limit=40):
    from assistant.engine import third_party_text
    return third_party_text(str(value or ''), limit)


def _usd(value) -> str:
    return services.usd_text(value)


def _local(dt, tz):
    return dt.astimezone(tz).strftime('%Y-%m-%d') if dt else None


# ── the owner's own words ──────────────────────────────────────────────

_NUMBER = re.compile(r'\d[\d.,]*')


def numbers_in(text: str) -> set[Decimal]:
    """Every number written in `text`, by what it means: "1.02" is never 102, "2,5" never 25."""
    from payment_accounts.payment_intents import _amount_values
    out = set()
    for raw in _NUMBER.findall(text or ''):
        try:
            out |= _amount_values(raw.rstrip('.,'))
        except ArithmeticError:
            continue
    return out


def said_number(said: str, value) -> bool:
    try:
        return Decimal(str(value)) in numbers_in(said)
    except Exception:  # noqa: BLE001
        return False


def said_percent(said: str, value) -> bool:
    """They wrote this as a percentage ("5%", "5 por ciento"), not as money."""
    found = re.findall(r'([0-9]+(?:[.,][0-9]+)?) ?(?:%|por ?ciento\b|por ?cento\b|percent\b)',
                       _norm(said))
    try:
        return any(Decimal(str(value)) == Decimal(number.replace(',', '.')) for number in found)
    except ArithmeticError:
        return False


def _norm(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize('NFKD', (text or '').lower())
    return ''.join(c for c in text if not unicodedata.combining(c))


def said_asset(said: str, query: str, asset: dict) -> bool:
    """The asset is in the owner's own words: the query they used, its
    ticker or its name."""
    words = _norm(said)
    name = asset.get('name') or ''
    # "Nvidia Corp" is said "Nvidia": the name without its company suffix.
    short = re.sub(r'(?:[\s,]+(?:corp(?:oration)?|inc|incorporated|ltd|limited|plc|co|company|holdings?|group|s\.?a|ag|n\.?v)\.?)+\s*$',
                   '', name, flags=re.IGNORECASE)
    probes = [query, asset.get('symbol'), name, short] + _asset_queries(query or '')
    probes += [k for k, v in ASSET_ALIASES.items() if v in _norm(asset.get('name', '') + ' ' + asset.get('symbol', ''))]
    for probe in probes:
        probe = _norm(probe or '').strip()
        if len(probe) >= 2 and re.search(rf'(?<![\w]){re.escape(probe)}(?![\w])', words):
            return True
    return False


# Who gets the money is matched strictly. People pick their own username
# and display name, so anything looser lets a stranger named @mama or
# "Mamá Semana" pass when the owner says "envíale a mi mamá cada semana".
# Never a single name part, never a bank or rail name, never digits joined
# across different numbers, never a tail of a phone.

# One written number for account digits: digits with at most single
# separators between them. Different numbers stay apart.
_NUMBER_TOKEN = re.compile(r'\+?\(?\d(?:[\s\-.()]{0,2}\d)*')
_NAME_SPLIT = re.compile(r'[\s·,.\-]+')
MIN_ACCOUNT_TAIL = 4

# A written phone: digit groups joined by 1-3 of space - . ( ) /, with an
# optional leading '+'. Unicode dashes and spaces are folded first; ',' '_'
# and letters always end a number.
_FOLD_DASHES_SPACES = str.maketrans(
    {**{c: '-' for c in '‐‑‒–—―−﹣－'},
     **{c: ' ' for c in '            　'}})
# Never glued to a letter, '_' or '@' on either side: '@juan04141234567' and
# 'ID4141234567' are not phones. A '+' (fullwidth too) may be followed by
# spaces ('+ 1 ...').
_PHONE_CANDIDATE = re.compile(r'(?<![\w@])(?:[+＋]\s*)?\d+(?:[\s\-.()/]{1,3}\d+)*(?![\w@])')
MIN_NATIONAL_DIGITS = 6


def number_tokens(text: str) -> list[str]:
    """The digits of each separate number written in `text`."""
    return [re.sub(r'\D', '', m) for m in _NUMBER_TOKEN.findall(text or '')]


def _phone_candidates(text: str) -> list[tuple[list[str], bool]]:
    """Each number written in `text`, in order: its digit groups and whether
    it was written with a leading '+'."""
    folded = str(text or '').translate(_FOLD_DASHES_SPACES)
    return [(re.findall(r'\d+', m.group()), m.group()[:1] in '+＋')
            for m in _PHONE_CANDIDATE.finditer(folded)]


def _without_mobile_prefix(national: str, calling: str) -> str:
    """Argentina's mobile 9 and Mexico's old mobile 1 written after the
    calling code (+54 9 11..., +52 1 55...): both national numbers are 10
    digits, so only an 11-digit number loses it."""
    if len(national) == 11 and ((calling == '54' and national.startswith('9'))
                                or (calling == '52' and national.startswith('1'))):
        return national[1:]
    return national


def _phone_readings(digits: str, international: bool, calling: str) -> set[str]:
    """The national numbers one written number can be. International ('+'
    or '00') must start with the person's OWN calling code exactly, then
    loses one trunk 0. Local loses one leading trunk 0; in Argentina a 15
    after a 2-4 digit area code ("011 15 1234-5678") is dropped too."""
    if international:
        body = digits if not digits.startswith('00') else digits[2:]
        if not calling or not body.startswith(calling):
            return set()
        national = body[len(calling):]
        national = national[1:] if national.startswith('0') else national
        return {_without_mobile_prefix(national, calling)}
    national = digits[1:] if digits.startswith('0') else digits
    out = {national}
    if calling == '54' and len(national) == 12:
        out |= {national[:k] + national[k + 2:] for k in (2, 3, 4) if national[k:k + 2] == '15'}
    return out


def _calling_code(person) -> str:
    """The resolved person's calling code as digits ('58'), or ''."""
    try:
        calling = getattr(person, 'phone_country_code', None)
    except Exception:  # noqa: BLE001 - an unknown country only loses the long form
        return ''
    return re.sub(r'\D', '', calling) if isinstance(calling, str) else ''


def _national_number(person) -> str:
    """The resolved person's stored phone, digits only, without a trunk 0.
    Never the handle the model looked them up by: usernames may be all
    digits."""
    local = getattr(person, 'phone_number', None)
    digits = re.sub(r'\D', '', local) if isinstance(local, str) else ''
    return digits[1:] if digits.startswith('0') else digits


def _said_phone(said: str, person) -> bool:
    """One number the owner wrote IS the person's phone, exactly: the whole
    national number, or the person's calling code and national number. No
    tails, no extra leading digits. A local number may follow other groups
    it got joined to ("envía 20 0414 1234567"), so a run of its groups
    that ends the number is read too, but only one starting with a trunk 0:
    "1 414 123 4567" (a calling code written without '+') is never
    414 123 4567. An international one ('+' or '00') is only read whole."""
    national, calling = _national_number(person), _calling_code(person)
    if len(national) < MIN_NATIONAL_DIGITS:
        return False
    targets = {national, _without_mobile_prefix(national, calling)}
    for groups, plus in _phone_candidates(said):
        whole = ''.join(groups)
        starts = [0] if plus or whole.startswith('00') else (
            [0] + [i for i in range(1, len(groups)) if groups[i].startswith('0')])
        for i in starts:
            digits = ''.join(groups[i:])
            international = (plus and i == 0) or digits.startswith('00')
            if _phone_readings(digits, international, calling) & targets:
                return True
    return False


def _said_handle(said: str, username: str) -> bool:
    """The exact @usuario as its own token. A bare username counts only when
    it cannot be an ordinary word or a number (it has a letter and a digit,
    '_' or '.'); a plain alphabetic or all-digit one needs its '@'.
    Compared on the raw text, never accent-folded, so 'mamá' is never
    '@mama'."""
    username = (username or '').strip().lstrip('@')
    if len(username) < 2:
        return False
    text = (said or '').lower()
    tail = r'(?![\w@]|[.\-][\w])'
    if re.search(rf'(?<![\w@])@{re.escape(username.lower())}{tail}', text):
        return True
    if re.fullmatch(r'[^\W\d_]+', username) or username.isdigit():
        return False
    return re.search(rf'(?<![\w@.]){re.escape(username.lower())}{tail}', text) is not None


def _said_full_name(said: str, name: str) -> bool:
    """Every part of a name of two or more parts, in order and together,
    as whole words (accent-insensitive). One part alone never counts."""
    parts = [_norm(p) for p in _NAME_SPLIT.split(' '.join(str(name or '').split())) if p.strip()]
    if len(parts) < 2:
        return False
    words = _NAME_SPLIT.split(_norm(said))
    n = len(parts)
    return any(words[i:i + n] == parts for i in range(len(words) - n + 1))


def said_payee(said: str, handle: str, person) -> bool:
    """The payee is in the owner's own words this turn: the exact @usuario,
    the person's full phone number written as one number, or the person's
    FULL name. Never only in tool output or a page the model read, never a
    single name part, never a tail of the phone. `handle` (what the model
    looked the person up by) is never evidence: only the resolved person's
    own username, phone and name are."""
    if person is None:
        return False
    if _said_handle(said, getattr(person, 'username', '') or ''):
        return True
    # Against the RESOLVED person's own phone, whatever handle the model
    # passed: "+58 0414-123-4567" with @jperez is still Juana's number.
    if _said_phone(said, person):
        return True
    named = ' '.join(p for p in [(person.first_name or '').strip(), (person.last_name or '').strip()] if p)
    return _said_full_name(said, named)


def _account_digits(label: str) -> str:
    """The account's trailing digits as its label shows them."""
    groups = re.findall(r'\d+', str(label or ''))
    return groups[-1] if groups else ''


def said_destination(said: str, row: dict) -> bool:
    """A saved bank destination is in the owner's words: its holder's FULL
    name, or the account's last 4+ digits written as one number. Never just
    a bank name, the rail's name or a single name part."""
    if _said_full_name(said, row.get('holder_name') or ''):
        return True
    shown = _account_digits(row.get('label'))
    if len(shown) < MIN_ACCOUNT_TAIL:
        return False
    # A written number, or any single digit group in it ("termina en 4321"):
    # either must be a tail of the account number.
    tokens = set(number_tokens(said)) | set(re.findall(r'\d+', said or ''))
    for token in tokens:
        if len(token) >= MIN_ACCOUNT_TAIL and (shown.endswith(token) or token.endswith(shown)):
            return True
    return False


def _existing_payees(own) -> set:
    return set(SmartAccountRule.objects.filter(smart_account=own, state='onchain', kind='send')
               .exclude(payee_user__isnull=True).values_list('payee_user_id', flat=True))


def _existing_destinations(own) -> set:
    out = set()
    for rule in SmartAccountRule.objects.filter(smart_account=own, state='onchain', kind='payout').select_related(
            'payout_method', 'pagomovil_destination'):
        dest = rule.payout_method or rule.pagomovil_destination
        if dest is not None:
            out.add(str(dest.internal_id))
    return out


# ── reading ────────────────────────────────────────────────────────────

def _rule_target(rule) -> dict:
    if rule.kind == 'send':
        name = services.display_name(rule.payee_user) if rule.payee_user else ''
        return {'persona': _clean(name), 'usuario': _clean(getattr(rule.payee_user, 'username', '') or '', 30)}
    if rule.kind == 'payout':
        dest = rule.payout_method or rule.pagomovil_destination
        return {'cuenta': _clean(getattr(dest, 'label', '') or rule.payout_rail, 60),
                'cuenta_id': str(dest.internal_id) if dest is not None else None}
    if rule.kind == 'card':
        # Decision 35: a card issuer pulls up to the cap per fixed period;
        # Confío never runs it. Described, never proposed.
        from . import cards
        _start, end, spent = cards.current_period(rule)
        return {'tarjeta': _clean(cards.spender_label(rule.payee_address), 60),
                'limite_por_periodo_usd': cards.money(rule.amount),
                'periodo_dias': cards.period_days(rule.frequency),
                'usado_este_periodo_usd': cards.money(spent),
                'disponible_este_periodo_usd': cards.money(cards.remaining_usd(rule.amount, spent)),
                'periodo_termina': end.isoformat() if end else None,
                'nota': 'La tarjeta usa este saldo cuando pagas con ella; Confío no la ejecuta en fechas.'}
    if rule.kind != 'buy':
        return {'detalle': 'regla automática'}
    resolved = assets_mod.resolve_asset_key(rule.asset_key) if rule.asset_key else None
    symbol = (resolved[1].removesuffix('on') if resolved and resolved[0] == 'stock'
              else resolved[1] if resolved else rule.asset_key)
    return {'inversion': symbol, 'asset_key': rule.asset_key}


def _live_rules(own):
    return list(SmartAccountRule.objects.filter(smart_account=own, state='onchain')
                .select_related('payee_user', 'payout_method', 'pagomovil_destination').order_by('id'))


def rules_snapshot(user, *, meta=None, tz=None) -> dict:
    own = operable_account(user)
    if own is None:
        return {'disponible': False, 'motivo': 'No tienes una Cuenta inteligente activa.'}
    tz = tz or timezone.get_current_timezone()
    rules = []
    for rule in _live_rules(own):
        last = rule.runs.exclude(status__in=('pending', 'sent')).order_by('-scheduled_for').first()
        rules.append({
            'regla_id': str(rule.internal_id), 'tipo': rule.kind, 'monto_usd': format(rule.amount, 'f'),
            'frecuencia': rule.frequency, 'activa': rule.active,
            'proxima_ejecucion': (_local(services.next_run_shown(rule), tz)
                                  if rule.active and rule.kind in abi.EXECUTABLE_RULE_KINDS else None),
            **_rule_target(rule),
            'ultima_ejecucion': ({'fecha': _local(last.scheduled_for, tz), 'estado': last.status,
                                  'motivo': _clean(last.message, 160) or None} if last else None),
        })
    try:
        methods = services.payout_method_rows(_viewer(user, meta))
    except Exception:  # noqa: BLE001 — the rules stand without the list
        logger.warning('smart account ops: payout methods unavailable', exc_info=True)
        methods = []
    out = {
        'disponible': True, 'estado_cuenta': own.status, 'cobro': own.billing_status,
        'reglas_en_pausa_por_cobro': own.billing_status != 'current',
        'reglas': rules,
        'cuentas_bancarias_guardadas': [
            {'cuenta_id': m['payout_method_id'], 'nombre': _clean(m['label'], 60), 'medio': m['rail'],
             'admite_pagos_automaticos': m['available']} for m in methods],
    }
    allocation = current_allocation(own)
    if allocation is not None:
        out['objetivo_de_inversion'] = allocation_view(own, allocation)
    return out


def rule_chip() -> dict:
    """The one chip that opens a rule proposal on the rule screen. Newer
    builds open `target`; `destination` is the key older builds know (the
    Cuenta inteligente door, which sends a subscriber on to the account)."""
    return {'type': 'navigate', 'destination': 'cuenta_inteligente', 'target': 'smart_account_rule',
            'label': 'Revisar y firmar'}


# ── first run ──────────────────────────────────────────────────────────

def first_run(frequency, *, tz, weekday=None, day_of_month=None, start_date=None, now=None):
    """The first run the owner asked for, as an aware datetime, or None."""
    if weekday is None and day_of_month is None and not start_date:
        return None
    if frequency == 'daily':
        raise OpsRefused('Una regla diaria se ejecuta todos los días: no lleva día de inicio.')
    now = now or timezone.now()
    today = now.astimezone(tz).date()
    if start_date:
        try:
            day = date.fromisoformat(str(start_date))
        except ValueError as exc:
            raise OpsRefused('No entendí la fecha de inicio.') from exc
        if day <= today or day > today + timedelta(days=services.MAX_FIRST_RUN_DAYS - 1):
            raise OpsRefused('La fecha de inicio tiene que ser desde mañana y dentro de los próximos dos meses.')
    elif weekday is not None:
        if frequency not in ('weekly', 'biweekly'):
            raise OpsRefused('Un día de la semana sirve para reglas semanales o quincenales. Para una regla '
                             'mensual dime un día del mes (del 1 al 28).')
        weekday = int(weekday)
        if not 0 <= weekday <= 6:
            raise OpsRefused('No entendí el día de la semana.')
        ahead = (weekday - today.weekday()) % 7 or 7
        day = today + timedelta(days=ahead)
    else:
        if frequency != 'monthly':
            raise OpsRefused('Un día del mes sirve para reglas mensuales. Para una regla semanal o quincenal '
                             'dime un día de la semana.')
        dom = int(day_of_month)
        if not 1 <= dom <= 28:
            raise OpsRefused('Elige un día del mes del 1 al 28, para que la regla caiga todos los meses el mismo día.')
        year, month = today.year, today.month
        if today.day >= dom:
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        day = date(year, month, dom)
    local = datetime.combine(day, time(FIRST_RUN_HOUR), tzinfo=tz)
    return local.astimezone(dt_timezone.utc)


# ── proposals ──────────────────────────────────────────────────────────

FREQUENCY_ES = services.FREQUENCY_LABELS


def _schedule_text(frequency, when, tz):
    if when is None:
        return FREQUENCY_ES[frequency]
    local = when.astimezone(tz)
    if frequency == 'monthly':
        return f'cada mes, el día {local.day} (la primera vez el {local:%d/%m})'
    if frequency in ('weekly', 'biweekly'):
        every = 'cada semana' if frequency == 'weekly' else 'cada dos semanas'
        return f'{every}, los {WEEKDAYS_ES[local.weekday()]} (la primera vez el {local:%d/%m})'
    return f'{FREQUENCY_ES[frequency]}, desde el {local:%d/%m}'


def _amount(value, *, required: bool, given: bool) -> Decimal | None:
    """The amount, only the number the person typed answering code's "¿Cuántos dólares?" (`given`: the
    assistant's confirm.answer). Never one the model passed: it is not read out of their words."""
    if value in (None, ''):
        if required:
            raise OpsRefused('El servidor le pregunta cuántos dólares: no se lo preguntes tú.', 'not_said')
        return None
    if not given:
        raise OpsRefused('El monto no se pone aquí: el servidor le pregunta cuántos dólares.', 'not_said')
    try:
        return services._parse_usd(Decimal(str(value)).quantize(CENT))
    except services.PrepareError as exc:
        raise OpsRefused(f'El monto de cada vez tiene que estar entre {_usd(services.MIN_RULE_USD)} y '
                         f'{_usd(services.MAX_RULE_USD)}.') from exc


def _find_rule(own, rule_id, kind=None):
    try:
        rule = SmartAccountRule.objects.filter(
            smart_account=own, state='onchain', internal_id=uuid.UUID(str(rule_id))).select_related(
            'payee_user', 'payout_method', 'pagomovil_destination').first()
    except (ValueError, TypeError):
        rule = None
    if rule is None or rule.onchain_id is None:
        raise OpsRefused('No encontré esa regla en tu cuenta. Revisa tus reglas con smart_account_rules.')
    if kind and rule.kind != kind:
        raise OpsRefused('Esa regla es de otro tipo: para cambiar de tipo, detén esta y crea una nueva.')
    return rule


def _asset_queries(query: str) -> list[str]:
    """The model often names an asset as "NVIDIA (NVDA)": try the whole text,
    then the ticker in parentheses, then the name before them."""
    q = _norm(query).strip()
    out = [q]
    m = re.match(r'^(.*?)\s*\(([^()]+)\)\s*$', q)
    if m:
        out += [m.group(2).strip(), m.group(1).strip()]
    return [ASSET_ALIASES.get(x, x) for x in out if x]


def find_buyable(viewer, query: str):
    """(asset dict, None) for one match, (None, options) otherwise."""
    items = services.buyable_assets(viewer, '')
    options: list = []
    for q in _asset_queries(query):
        exact = [a for a in items if _norm(a['symbol']) == q or _norm(a['asset_key']) == q]
        if len(exact) == 1:
            return exact[0], None
        loose = [a for a in items if q in _norm(a['symbol']) or q in _norm(a['name'])]
        if len(loose) == 1:
            return loose[0], None
        if not options:
            options = [f"{a['name']} ({a['symbol']})" for a in (exact or loose)[:5]]
    return None, options


def _resolve_asset(viewer, query, said, *, check_said=True):
    asset, options = find_buyable(viewer, query or '')
    if asset is None:
        if options:
            raise OpsRefused('Encontré varias opciones: ' + '; '.join(options) + '. ¿Cuál quieres?', 'ambiguous')
        raise OpsRefused('Esa inversión no está disponible para compras automáticas en tu cuenta.')
    if check_said and not said_asset(said, query, asset):
        # What to buy is always the owner's choice.
        raise OpsRefused('Dime tú en qué quieres invertir: yo no elijo inversiones.', 'not_said')
    return asset


def _asset_minimum(asset_key: str) -> Decimal:
    if asset_key.startswith('stock:'):
        from . import quotes
        try:
            return max(services.MIN_RULE_USD, quotes.min_stock_rule_amount())
        except quotes.QuoteUnavailable as exc:
            raise OpsRefused('No pude revisar el mínimo para acciones ahora. Inténtalo en un momento.') from exc
    return services.MIN_RULE_USD


def _check_buy_amount(asset_key: str, amount: Decimal, name: str):
    minimum = _asset_minimum(asset_key)
    if amount < minimum:
        raise OpsRefused(f'Para comprar {name} automáticamente el mínimo es {_usd(minimum)} cada vez.')


def _identity_ok(user):
    from security.identity_reuse import outgoing_identity_restriction
    restriction = outgoing_identity_restriction(user)
    if restriction:
        raise OpsRefused(restriction)


def _step(action, kind, *, rule_id=None, amount=None, frequency=None, first_run_at=None, sentence='', **extra):
    return {'action': action, 'kind': kind, 'rule_id': rule_id,
            'amount_usd': format(amount, 'f') if amount is not None else None, 'frequency': frequency,
            'first_run_at': first_run_at.isoformat() if first_run_at else None,
            'payee_handle': extra.get('payee_handle'), 'payee_name': extra.get('payee_name'),
            'payout_method_id': extra.get('payout_method_id'), 'payout_label': extra.get('payout_label'),
            'asset_key': extra.get('asset_key'), 'asset_name': extra.get('asset_name'),
            'sentence': sentence}


def propose_rule(user, *, said: str, action: str, kind: str | None = None, rule_id=None, payee=None,
                 payout_method_id=None, asset=None, amount_usd=None, frequency=None, weekday=None,
                 day_of_month=None, start_date=None, meta=None, tz=None, now=None, amount_given=False,
                 probe=False) -> dict:
    """One rule change, validated like the prepare it leads to. `probe`: everything but the amount, before
    code asks it ({'probe': True, 'asset': name}). Returns the
    proposal (steps the app opens prefilled). Raises OpsRefused."""
    tz = tz or timezone.get_current_timezone()
    own = operable_account(user)
    if own is None:
        raise OpsRefused('No tienes una Cuenta inteligente activa.')
    if action == 'cancel':
        if not chain.factory_address():
            raise OpsRefused('Ahora no puedo preparar ese cambio. Inténtalo más tarde.')
        rule = _find_rule(own, rule_id)
        what = _rule_target(rule)
        label = (services.payee_label(rule.payee_user, _clean) if rule.kind == 'send' and rule.payee_user
                 else what.get('persona') or what.get('cuenta') or what.get('inversion') or what.get('tarjeta')
                 or '')
        sentence = (f'Detener la regla de {_usd(rule.amount)} {FREQUENCY_ES[rule.frequency]} ({label}). '
                    'Se borra de tu cuenta; si después quieres retomarla, se crea de nuevo.')
        return {'steps': [_step('cancel', rule.kind, rule_id=str(rule.internal_id), amount=rule.amount,
                                frequency=rule.frequency, sentence=sentence)]}
    if action not in ('create', 'update'):
        raise OpsRefused('Puedo crear, cambiar o detener una regla.')
    if not chain.enabled():
        raise OpsRefused('Ahora no puedo preparar reglas nuevas. Inténtalo más tarde.')
    existing = _find_rule(own, rule_id, kind) if action == 'update' else None
    kind = existing.kind if existing is not None else kind
    if kind not in ('send', 'payout', 'buy'):
        raise OpsRefused('Una regla puede enviar a alguien de Confío, pagar a una cuenta bancaria guardada o invertir.')
    if PAYING_RULES_PAUSED and kind in ('send', 'payout'):
        raise OpsRefused(PAYING_RULES_REFUSAL, 'paused')
    frequency = frequency or (existing.frequency if existing else None)
    if frequency not in FREQUENCIES:
        raise OpsRefused('¿Cada cuánto? Puede ser cada día, cada semana, cada dos semanas o cada mes.')
    if probe and kind != 'buy':
        raise OpsRefused('El monto de esa regla se cambia en tu Cuenta inteligente, en Reglas.')
    amount = None if probe else (_amount(amount_usd, required=existing is None, given=amount_given)
                                 or existing.amount)
    when = first_run(frequency, tz=tz, weekday=weekday, day_of_month=day_of_month, start_date=start_date, now=now)
    viewer = _viewer(user, meta)
    schedule = _schedule_text(frequency, when, tz)
    verb = 'Cambiar la regla para que' if existing else 'Nueva regla:'
    rid = str(existing.internal_id) if existing else None

    if kind == 'send':
        _identity_ok(user)
        if payee:
            person = services.resolve_handle(payee)
            if person is None:
                raise OpsRefused('No encontré a esa persona en Confío. Dime su @usuario o su número completo con +código de país.')
            if not said_payee(said, payee, person) and person.pk not in _existing_payees(own):
                # Who gets the money is always the owner's words, never a
                # name the model picked up from a tool result or a page.
                raise OpsRefused('Dime tú a quién le envías: su @usuario, su número completo o su nombre completo.',
                                 'not_said')
        elif existing is not None:
            person = existing.payee_user
        else:
            raise OpsRefused('¿A quién le envías? Dime su @usuario de Confío o su número completo.')
        if person is None or person.pk == user.pk:
            raise OpsRefused('Una regla de envío es para otra persona de Confío.')
        payee_account = context.personal_account(person)
        if payee_account is None or not payee_account.bsc_address:
            raise OpsRefused('Esa persona todavía no tiene su billetera lista para recibir.')
        name = _clean(services.display_name(person))
        # Always the @usuario next to the name: names are self-chosen, the
        # handle is what tells two people with the same name apart.
        sentence = (f'{verb} envía {_usd(amount)} a {services.payee_label(person, _clean)} {schedule}. '
                    'Le llega en su dólar de Confío.')
        return {'steps': [_step(action, 'send', rule_id=rid, amount=amount, frequency=frequency, first_run_at=when,
                                payee_handle=person.username or '', payee_name=name, sentence=sentence)]}

    if kind == 'payout':
        _identity_ok(user)
        rows = services.payout_method_rows(viewer)
        method_id = payout_method_id or (_rule_target(existing).get('cuenta_id') if existing else None)
        if not method_id:
            usable = [r for r in rows if r['available']]
            if not usable:
                raise OpsRefused('No tienes una cuenta bancaria guardada que admita pagos automáticos. Guárdala '
                                 'primero desde Enviar.')
            raise OpsRefused('¿A cuál de tus cuentas guardadas? ' + '; '.join(
                _clean(r['label'], 60) for r in usable[:5]))
        row = next((r for r in rows if r['payout_method_id'] == str(method_id)), None)
        if row is None:
            raise OpsRefused('No encontré esa cuenta bancaria entre las tuyas guardadas.')
        if not row['available']:
            raise OpsRefused('Esa cuenta todavía no admite pagos automáticos.')
        if (payout_method_id and not said_destination(said, row)
                and str(row['payout_method_id']) not in _existing_destinations(own)):
            raise OpsRefused('Dime tú a cuál de tus cuentas guardadas pagas: el nombre completo de quien recibe o '
                             'los últimos 4 dígitos de la cuenta.', 'not_said')
        label = _clean(row['label'], 60)
        sentence = (f'{verb} paga {_usd(amount)} a {label} {schedule}. El monto en dólares es fijo; lo que llega '
                    'en moneda local sigue el tipo de cambio del día.')
        return {'steps': [_step(action, 'payout', rule_id=rid, amount=amount, frequency=frequency, first_run_at=when,
                                payout_method_id=row['payout_method_id'], payout_label=label, sentence=sentence)]}

    if asset:
        picked = _resolve_asset(viewer, asset, said)
    elif existing is not None:
        picked = {'asset_key': existing.asset_key, 'symbol': _rule_target(existing)['inversion'],
                  'name': _rule_target(existing)['inversion']}
    else:
        raise OpsRefused('¿En qué quieres invertir? Dime el nombre o el símbolo.')
    if probe:
        return {'probe': True, 'asset': _clean(picked['name']), 'frequency': frequency}
    _check_buy_amount(picked['asset_key'], amount, picked['name'])
    sentence = f'{verb} invierte {_usd(amount)} en {picked["name"]} {schedule}. Compra, nunca vende.'
    return {'steps': [_step(action, 'buy', rule_id=rid, amount=amount, frequency=frequency, first_run_at=when,
                            asset_key=picked['asset_key'], asset_name=_clean(picked['name']), sentence=sentence)]}


# ── target allocation: kept by new buys only ───────────────────────────

def drift_threshold_pp() -> Decimal:
    return Decimal(str(getattr(settings, 'SMART_ACCOUNT_ALLOCATION_DRIFT_PP', 5)))


def current_allocation(own):
    return SmartAccountTargetAllocation.objects.filter(smart_account=own).order_by('-id').first()


def split_amounts(total: Decimal, weights: dict[str, int]) -> dict[str, Decimal]:
    """total x weight per asset, in cents; the rounding remainder goes to the
    largest weight so the parts add up to the total exactly."""
    out = {k: (total * w / BPS).quantize(CENT, rounding=ROUND_DOWN) for k, w in weights.items()}
    rest = total - sum(out.values())
    if rest and out:
        out[max(weights, key=lambda k: (weights[k], k))] += rest
    return out


def actual_weights_pp(weights: dict[str, int], holdings: dict[str, Decimal]) -> dict[str, Decimal] | None:
    """Each target asset's share of the target assets' value, in percent."""
    value = sum((holdings.get(k, Decimal(0)) for k in weights), Decimal(0))
    if value <= 0:
        return None
    return {k: holdings.get(k, Decimal(0)) * 100 / value for k in weights}


def drift_pp(weights: dict[str, int], holdings: dict[str, Decimal]) -> Decimal:
    actual = actual_weights_pp(weights, holdings)
    if actual is None:
        return Decimal(0)
    return max(abs(actual[k] - Decimal(w) / 100) for k, w in weights.items())


def drift_split(total: Decimal, weights: dict[str, int], holdings: dict[str, Decimal],
                minimums: dict[str, Decimal]) -> dict[str, Decimal] | None:
    """The next buys, same total, steered toward the target with new money
    only: every asset keeps at least its minimum (its rule keeps running),
    and what is left goes to the underweight assets in proportion to how
    far each is below the target after this period. Never a sale, never a
    negative amount. None when the minimums alone exceed the total."""
    floor = {k: minimums.get(k, services.MIN_RULE_USD) for k in weights}
    spare = total - sum(floor.values())
    if spare < 0:
        return None
    after = sum((holdings.get(k, Decimal(0)) for k in weights), Decimal(0)) + total
    gaps = {k: max(Decimal(0), after * w / BPS - holdings.get(k, Decimal(0)) - floor[k]) for k, w in weights.items()}
    gap_total = sum(gaps.values())
    if gap_total <= 0:
        return split_amounts(total, weights)
    out = {k: floor[k] + (spare * gaps[k] / gap_total).quantize(CENT, rounding=ROUND_DOWN) for k in weights}
    rest = total - sum(out.values())
    if rest:
        out[max(gaps, key=lambda k: (gaps[k], k))] += rest
    return out


def periods_to_target(total, weights, holdings, split_fn, threshold, limit=60):
    """Periods of buying `split_fn` until the drift is under the threshold."""
    held = dict(holdings)
    for n in range(1, limit + 1):
        split = split_fn(held)
        if split is None:
            return None
        for k, v in split.items():
            held[k] = held.get(k, Decimal(0)) + v
        if drift_pp(weights, held) < threshold:
            return n
    return None


def _holdings_usd(own, keys) -> dict[str, Decimal]:
    held = {}
    for asset in assets_mod.assets_of(own.contract_address):
        if asset.key in keys:
            if asset.value_usd is None:
                raise OpsRefused('No tengo el precio de una de tus inversiones ahora. Inténtalo más tarde.')
            held[asset.key] = asset.value_usd
    return held


def _weights(allocation) -> dict[str, int]:
    return {w['asset_key']: int(w['weight_bps']) for w in allocation.weights}


def _asset_label(key: str) -> str:
    resolved = assets_mod.resolve_asset_key(key)
    if not resolved:
        return key
    return resolved[1].removesuffix('on') if resolved[0] == 'stock' else resolved[1]


def allocation_view(own, allocation) -> dict:
    weights = _weights(allocation)
    rules = {r.asset_key: r for r in _live_rules(own) if r.kind == 'buy' and r.active}
    view = {
        'total_por_periodo_usd': format(allocation.total_usd, 'f'), 'frecuencia': allocation.frequency,
        'objetivo': [{'inversion': _asset_label(k), 'asset_key': k, 'porcentaje': float(Decimal(w) / 100)}
                     for k, w in weights.items()],
        'reglas_firmadas': all(k in rules for k in weights),
        'regla_de_oro': 'Se mantiene solo con compras nuevas; nunca se vende nada.',
    }
    try:
        held = _holdings_usd(own, set(weights))
    except Exception:  # noqa: BLE001 — target without the actual split
        logger.warning('smart account ops: holdings unavailable for allocation', exc_info=True)
        view['actual'] = 'desconocido'
        return view
    actual = actual_weights_pp(weights, held)
    view['actual'] = ([{'inversion': _asset_label(k), 'porcentaje': float(actual[k].quantize(Decimal('0.1')))}
                       for k in weights] if actual else 'todavía no hay compras')
    if actual:
        drift = drift_pp(weights, held)
        view['desvio_maximo_puntos'] = float(drift.quantize(Decimal('0.1')))
        view['fuera_de_objetivo'] = drift >= drift_threshold_pp()
    return view


def _parse_weights(viewer, items, said) -> dict[str, int]:
    if not items or len(items) < 2:
        raise OpsRefused('Dime al menos dos inversiones y qué porcentaje quieres de cada una.')
    if len(items) > 8:
        raise OpsRefused('Un objetivo puede tener hasta 8 inversiones.')
    weights, total = {}, 0
    for item in items:
        percent = item.get('percent')
        if percent is None or not said_number(said, percent):
            # The ratio is always the owner's; the assistant never proposes one.
            raise OpsRefused('Dime tú qué porcentaje quieres en cada inversión: yo no elijo cómo repartir tu dinero.',
                             'not_said')
        bps = Decimal(str(percent)) * 100
        if bps != bps.to_integral_value() or bps <= 0:
            raise OpsRefused('Usa porcentajes enteros o con un decimal, mayores que cero.')
        asset = _resolve_asset(viewer, item.get('asset'), said)
        if asset['asset_key'] in weights:
            raise OpsRefused('Nombraste la misma inversión dos veces.')
        weights[asset['asset_key']] = int(bps)
        total += int(bps)
    if total != BPS:
        raise OpsRefused(f'Los porcentajes suman {Decimal(total) / 100}%: tienen que sumar 100%.')
    return weights


def _allocation_steps(own, weights, amounts, frequency, when, tz, *, why: str) -> list[dict]:
    rules = {r.asset_key: r for r in _live_rules(own) if r.kind == 'buy' and r.active}
    steps = []
    for key, amount in amounts.items():
        name = _asset_label(key)
        rule = rules.get(key)
        if rule is not None and rule.amount == amount and rule.frequency == frequency and when is None:
            continue
        schedule = _schedule_text(frequency, when, tz)
        if rule is not None:
            steps.append(_step('update', 'buy', rule_id=str(rule.internal_id), amount=amount, frequency=frequency,
                               first_run_at=when, asset_key=key, asset_name=name,
                               sentence=f'{why}: la regla de {name} pasa de {_usd(rule.amount)} a {_usd(amount)} '
                                        f'{schedule}.'))
        else:
            steps.append(_step('create', 'buy', amount=amount, frequency=frequency, first_run_at=when, asset_key=key,
                               asset_name=name, sentence=f'{why}: nueva regla, invierte {_usd(amount)} en {name} '
                                                         f'{schedule}.'))
    return steps


def propose_target_allocation(user, *, said: str, action: str, assets=None, total_usd=None, frequency=None,
                              weekday=None, day_of_month=None, start_date=None, meta=None, tz=None,
                              now=None, amount_given=False, probe=False) -> dict:
    """`probe` (set only): everything but the total, before code asks it ({'probe': True, 'split': text}).
    `set`: save the owner's own split and propose one Buy rule per asset
    (amount = total x weight). `next_split`: from the saved target and the
    account's holdings, propose the next buys re-split toward it (same
    total, new money only). `delete`: forget the target (rules stay)."""
    tz = tz or timezone.get_current_timezone()
    own = operable_account(user)
    if own is None:
        raise OpsRefused('No tienes una Cuenta inteligente activa.')
    if action == 'delete':
        allocation = current_allocation(own)
        if allocation is None:
            return {'steps': [], 'texto': 'No tenías un objetivo guardado.'}
        allocation.soft_delete()
        return {'steps': [], 'texto': 'Listo, ya no sigo un objetivo de reparto. Tus reglas de compra siguen como '
                                      'están; si quieres detener alguna, dímelo.'}
    if not chain.enabled():
        raise OpsRefused('Ahora no puedo preparar reglas nuevas. Inténtalo más tarde.')
    viewer = _viewer(user, meta)

    if action == 'set':
        weights = _parse_weights(viewer, assets, said)
        if frequency not in FREQUENCIES:
            raise OpsRefused('¿Cada cuánto quieres comprar? Cada día, semana, dos semanas o mes.')
        if probe:
            first_run(frequency, tz=tz, weekday=weekday, day_of_month=day_of_month, start_date=start_date, now=now)
            return {'probe': True, 'frequency': FREQUENCY_ES[frequency],
                    'split': ', '.join(f'{Decimal(w) / 100}% {_asset_label(k)}' for k, w in weights.items())}
        total = _amount(total_usd, required=True, given=amount_given)
        split = split_amounts(total, weights)
        for key, amount in split.items():
            _check_buy_amount(key, amount, _asset_label(key))
        when = first_run(frequency, tz=tz, weekday=weekday, day_of_month=day_of_month, start_date=start_date, now=now)
        with transaction.atomic():
            for old in SmartAccountTargetAllocation.objects.select_for_update().filter(smart_account=own):
                old.soft_delete()
            SmartAccountTargetAllocation.objects.create(
                smart_account=own, weights=[{'asset_key': k, 'weight_bps': w} for k, w in weights.items()],
                total_usd=total, frequency=frequency)
        steps = _allocation_steps(own, weights, split, frequency, when, tz, why='Tu objetivo')
        split = ', '.join(f'{Decimal(w) / 100}% {_asset_label(k)}' for k, w in weights.items())
        return {'steps': steps, 'split': split, 'total_text': _usd(total), 'frequency': frequency,
                'texto': (f'Guardé tu objetivo: {split}, con {_usd(total)} '
                                          f'{FREQUENCY_ES[frequency]} en total. Se mantiene solo con compras nuevas: '
                                          'nunca vendo nada. Cada regla se activa cuando la firmas.')}

    if action != 'next_split':
        raise OpsRefused('Puedo guardar tu objetivo, repartir las próximas compras hacia él u olvidarlo.')
    allocation = current_allocation(own)
    if allocation is None:
        raise OpsRefused('No tienes un objetivo de reparto guardado. Dime qué porcentaje quieres en cada inversión.')
    return rebalance_proposal(own, allocation, tz=tz)


def rebalance_proposal(own, allocation, *, tz) -> dict:
    """The drift proposal: re-split the next buys toward the target, same
    total, new money only. Never a sale."""
    weights = _weights(allocation)
    total, frequency = allocation.total_usd, allocation.frequency
    held = _holdings_usd(own, set(weights))
    threshold = drift_threshold_pp()
    drift = drift_pp(weights, held)
    base = {'desvio_maximo_puntos': float(drift.quantize(Decimal('0.1'))), 'umbral_puntos': float(threshold),
            'nunca_vende': True}
    if drift < threshold:
        return {**base, 'steps': [], 'texto': 'Tu inversión está dentro de tu objetivo: no hace falta cambiar nada.'}
    minimums = {k: _asset_minimum(k) for k in weights}
    split = drift_split(total, weights, held, minimums)
    if split is None:
        return {**base, 'steps': [], 'texto': (
            f'Con {_usd(total)} {FREQUENCY_ES[frequency]} no alcanza para comprar el mínimo de cada inversión y '
            'acercarte a tu objetivo. Solo se puede corregir con compras nuevas, nunca vendiendo.')}
    periods = periods_to_target(total, weights, held, lambda h: drift_split(total, weights, h, minimums), threshold)
    steps = _allocation_steps(own, weights, split, frequency, None, tz, why='Para acercarte a tu objetivo')
    lines = ', '.join(f'{_usd(v)} en {_asset_label(k)}' for k, v in split.items())
    if periods is None:
        text = (f'Con {_usd(total)} {FREQUENCY_ES[frequency]}, las compras nuevas mueven muy poco la proporción: '
                'volver al objetivo tomaría más de 5 años. Se puede repartir así igual, o subir el monto total. '
                'Nunca vendo nada.')
    else:
        text = (f'Propuesta para las próximas compras, mismo total: {lines}. Volverías a tu objetivo en unos '
                f'{periods} {"período" if periods == 1 else "períodos"}; después conviene volver al reparto normal. '
                'Nunca vendo nada.')
    return {**base, 'steps': steps, 'texto': text, 'periodos_estimados': periods}


# ── review ─────────────────────────────────────────────────────────────

def _month_bounds(months_back: int, tz, now=None):
    now = (now or timezone.now()).astimezone(tz)
    year, month = now.year, now.month - months_back
    while month < 1:
        year, month = year - 1, month + 12
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=tz)
    return start, end


MONTHS_ES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
             'noviembre', 'diciembre']


def review(user, *, months_back: int = 0, tz=None, now=None) -> dict:
    """What happened in the account in one calendar month, from the mirrors:
    plan charges, signed moves in and out, what each rule executed or
    skipped (with the reason), current balances and the target split."""
    tz = tz or timezone.get_current_timezone()
    own = context.own_account(user)
    if own is None or own.status == 'none':
        return {'disponible': False, 'motivo': 'No tienes una Cuenta inteligente.'}
    start, end = _month_bounds(max(0, min(int(months_back or 0), 11)), tz, now)
    charges = SmartAccountCharge.objects.filter(smart_account=own, charged_at__gte=start, charged_at__lt=end)
    moves = SmartAccountPreparedAction.objects.filter(
        smart_account=own, consumed=True, consumed_at__gte=start, consumed_at__lt=end,
        kind__in=('smart_deposit', 'smart_subscribe', 'smart_withdraw')).order_by('consumed_at')
    out = {
        'disponible': True, 'periodo': f'{MONTHS_ES[start.month - 1]} de {start.year}',
        'cobros_del_plan': [{'fecha': _local(c.charged_at, tz), 'monto_usd': assets_mod.money(c.fee_usd),
                             'pagado_con': c.paid_with} for c in charges],
        'entradas_y_salidas_firmadas': [
            {'fecha': _local(m.consumed_at, tz),
             'tipo': 'salida a tu billetera' if m.kind == 'smart_withdraw' else 'entrada desde tu billetera',
             'detalle': [_clean(line, 80) for line in (m.payload or {}).get('summary', [])][:6]} for m in moves],
        'retiros_en_cadena': SmartAccountEvent.objects.filter(
            smart_account=own, name='Withdrawn', block_time__gte=start, block_time__lt=end).count(),
    }
    rules = []
    for rule in SmartAccountRule.all_objects.filter(smart_account=own, state__in=('onchain', 'cancelled')).select_related(
            'payee_user', 'payout_method', 'pagomovil_destination'):
        runs = list(SmartAccountRuleRun.objects.filter(rule=rule, scheduled_for__gte=start, scheduled_for__lt=end))
        if not runs and not (rule.state == 'onchain' and rule.active):
            continue
        rules.append({
            'tipo': rule.kind, 'monto_usd': format(rule.amount, 'f'), 'frecuencia': rule.frequency,
            **{k: v for k, v in _rule_target(rule).items() if k not in ('cuenta_id', 'asset_key')},
            'ejecutadas': sum(1 for r in runs if r.status == 'ok'),
            'omitidas': [{'fecha': _local(r.scheduled_for, tz), 'motivo': _clean(r.message, 160) or 'sin detalle'}
                         for r in runs if r.status == 'skipped'],
            'fallidas': [{'fecha': _local(r.scheduled_for, tz), 'motivo': _clean(r.message, 160) or 'sin detalle'}
                         for r in runs if r.status == 'failed'],
            'en_curso': sum(1 for r in runs if r.status in ('pending', 'sent')),
        })
    out['reglas'] = rules
    pulls = list(SmartAccountCardPull.objects.filter(
        smart_account=own, pulled_at__gte=start, pulled_at__lt=end).order_by('pulled_at'))
    if pulls:
        from . import cards
        out['pagos_con_tarjeta'] = {
            'cantidad': len(pulls),
            'total_usd': cards.money(sum((p.usd_spent for p in pulls), Decimal(0))),
            'detalle': [{'fecha': _local(p.pulled_at, tz), 'monto_usd': cards.money(p.usd_spent),
                         'tarjeta': _clean(cards.spender_label(p.spender), 60)} for p in pulls[-20:]],
        }
    try:
        held = assets_mod.assets_of(own.contract_address)
        out['saldos_actuales'] = [{'activo': a.name if a.kind == 'dollar' else a.symbol,
                                   'valor_usd': assets_mod.money(a.value_usd)} for a in held]
        out['total_actual_usd'] = assets_mod.money(assets_mod.total_usd(held))
    except Exception:  # noqa: BLE001 — unknown, never "empty"
        logger.warning('smart account ops: balances unavailable for review', exc_info=True)
        out['saldos_actuales'] = 'desconocido'
    allocation = current_allocation(own)
    if allocation is not None and own.status in OPERABLE:
        out['objetivo_de_inversion'] = allocation_view(own, allocation)
    return out


def monthly_note_text(user, *, tz=None, now=None) -> str | None:
    """The monthly assistant-thread note: last month, short, no advice."""
    data = review(user, months_back=1, tz=tz, now=now)
    if not data.get('disponible'):
        return None
    lines = [f'Resumen de tu Cuenta inteligente, {data["periodo"]}:']
    if data['cobros_del_plan']:
        total = sum(Decimal(c['monto_usd'] or 0) for c in data['cobros_del_plan'])
        lines.append(f'• Plan: {_usd(total)} cobrado desde la cuenta.')
    if data['entradas_y_salidas_firmadas']:
        ins = sum(1 for m in data['entradas_y_salidas_firmadas'] if m['tipo'].startswith('entrada'))
        outs = len(data['entradas_y_salidas_firmadas']) - ins
        lines.append(f'• Movimientos que firmaste: {ins} de entrada y {outs} de salida.')
    done = sum(r['ejecutadas'] for r in data['reglas'])
    skipped = sum(len(r['omitidas']) + len(r['fallidas']) for r in data['reglas'])
    if data['reglas']:
        lines.append(f'• Reglas: {done} ejecutadas' + (f', {skipped} no se ejecutaron (pregúntame por qué).'
                                                        if skipped else '.'))
    card = data.get('pagos_con_tarjeta')
    if card:
        lines.append(f'• Tarjeta: {card["cantidad"]} pago{"s" if card["cantidad"] != 1 else ""} por '
                     f'{_usd(card["total_usd"])} desde la cuenta.')
    if isinstance(data.get('total_actual_usd'), str):
        lines.append(f'• Hoy hay {_usd(data["total_actual_usd"])} en la cuenta.')
    target = data.get('objetivo_de_inversion')
    if isinstance(target, dict) and target.get('fuera_de_objetivo'):
        lines.append('• Tus inversiones se alejaron de tu objetivo. Si quieres, te propongo repartir las próximas '
                     'compras para volver a él, sin vender nada.')
    lines.append('Pídeme el detalle cuando quieras, o un cambio en tus reglas: tú lo revisas y lo firmas.')
    return '\n'.join(lines)


def post_monthly_notes(now=None) -> dict:
    """One note per subscriber per month, idempotent on (account, month)."""
    from assistant.billing import has_plus
    from assistant.service import post_system_note
    now = now or timezone.now()
    out = {'posted': 0, 'skipped': 0, 'errors': 0}
    for own in SmartAccount.objects.filter(status__in=OPERABLE).select_related('owner_user'):
        user = own.owner_user
        try:
            if not has_plus(user):
                out['skipped'] += 1
                continue
            from assistant.service import _resolve_tz
            from security.geo import country_of
            tz = _resolve_tz(None, country_of(user))
            month = (now.astimezone(tz).replace(day=1) - timedelta(days=1))
            tag = f'smart_account_monthly_review:{own.pk}:{month:%Y-%m}'
            text = monthly_note_text(user, tz=tz, now=now)
            if not text:
                out['skipped'] += 1
                continue
            _message, created = post_system_note(user, text, tag)
            out['posted' if created else 'skipped'] += 1
        except Exception:  # noqa: BLE001 — one account never blocks the rest; counted, not hidden
            logger.exception('smart account monthly review note failed for %s', own.pk)
            out['errors'] += 1
    return out
