"""Conditional alerts ("watches") a Cuenta inteligente owner sets through
Confío IA+ (spec decision 34): "avísame si TSLA baja 5% y prepárame una
compra de 100".

- The owner names the asset or currency, the threshold and any attached
  action. The assistant never suggests any of them (no advice): every value
  must be in the owner's own words, and the watch is saved only on the
  owner's explicit "sí" to a question written by code (the categorizing
  pattern in assistant/service.py).
- Prices come from the sources the app already shows: Ondo GM market data
  for stocks, the crypto snapshot prices for bitcoin and gold, and the
  reference exchange rate Home shows for local currencies.
- A trigger only tells the owner (push + assistant-thread note). An
  attached buy is a chip that opens the rule screen prefilled; nothing runs
  without the owner's review and signature.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import assets as assets_mod, chain
from .assistant_ops import (
    OpsRefused, _asset_label, _check_buy_amount, _resolve_asset, _usd, _viewer, operable_account, rule_chip,
    said_number,
    said_usd,
)
from .models import SmartAccountWatch

logger = logging.getLogger(__name__)

MAX_ACTIVE = 10
DEFAULT_COOLDOWN_HOURS = 24
FX_MAX_AGE = timedelta(days=2)
PRICE_KINDS = ('asset_price_drop_pct', 'asset_price_rise_pct', 'asset_price_below', 'asset_price_above')
FX_KINDS = ('fx_rate_below', 'fx_rate_above')
KINDS = PRICE_KINDS + FX_KINDS


# ── prices from existing sources ───────────────────────────────────────

def asset_price(asset_key: str, *, cache: dict | None = None) -> Decimal | None:
    """USD price of one unit, or None when unknown (never a guess)."""
    cache = {} if cache is None else cache
    if asset_key.startswith('stock:'):
        if 'stocks' not in cache:
            cache['stocks'] = assets_mod._stock_market()
        price = ((cache['stocks'].get(asset_key[6:]) or {}).get('primaryMarket') or {}).get('price')
        return Decimal(str(price)) if price is not None else None
    if asset_key.startswith('crypto:'):
        if 'crypto' not in cache:
            from cusd_plus import crypto_prices
            # Only snapshots inside the freshness bound: a stalled snapshot
            # job must never trigger (or seed) a watch on an old price.
            oldest = timezone.now() - crypto_max_age()
            cache['crypto'] = {
                row['token'].symbol: row['price_usd'] for row in crypto_prices.market_rows()
                if row.get('price_usd') is not None and row.get('priced_at') is not None
                and row['priced_at'] >= oldest}
        price = cache['crypto'].get(asset_key[7:])
        return Decimal(str(price)) if price is not None else None
    return None


def crypto_max_age() -> timedelta:
    """How old a crypto/gold snapshot price may be (the snapshot runs every
    few minutes); SMART_ACCOUNT_WATCH_CRYPTO_MAX_AGE_MINUTES, default 30."""
    try:
        minutes = int(getattr(settings, 'SMART_ACCOUNT_WATCH_CRYPTO_MAX_AGE_MINUTES', 30))
    except (TypeError, ValueError):
        minutes = 30
    return timedelta(minutes=max(minutes, 1))


def fx_rate(currency: str) -> Decimal | None:
    """Local currency per 1 USD: the reference rate Home shows (parallel,
    then average, then official); None when missing or older than two days."""
    from exchange_rates.services import exchange_rate_service
    for kind in ('parallel', 'average', 'official'):
        row = exchange_rate_service.get_current_rate_row(currency, 'USD', kind)
        if row and row.rate and row.rate > 0:
            if not row.fetched_at or row.fetched_at < timezone.now() - FX_MAX_AGE:
                return None
            return Decimal(str(row.rate))
    return None


def current_value(watch, *, cache=None) -> Decimal | None:
    return fx_rate(watch.currency) if watch.kind in FX_KINDS else asset_price(watch.asset_key, cache=cache)


def triggered(watch, value: Decimal) -> bool:
    t = watch.threshold
    if watch.kind == 'asset_price_below' or watch.kind == 'fx_rate_below':
        return value <= t
    if watch.kind == 'asset_price_above' or watch.kind == 'fx_rate_above':
        return value >= t
    ref = watch.reference_price
    if not ref or ref <= 0:
        return False
    change = (value - ref) * 100 / ref
    return change <= -t if watch.kind == 'asset_price_drop_pct' else change >= t


# ── describing ─────────────────────────────────────────────────────────

def _num(value: Decimal) -> str:
    return format(Decimal(value).normalize(), 'f')


def describe(kind, *, asset_key='', currency='', threshold: Decimal, action=None) -> str:
    target = _asset_label(asset_key) if asset_key else f'el dólar en {currency}'
    text = {
        'asset_price_drop_pct': f'si {target} baja {_num(threshold)}% desde hoy',
        'asset_price_rise_pct': f'si {target} sube {_num(threshold)}% desde hoy',
        'asset_price_below': f'si {target} baja a {_usd(threshold)} o menos',
        'asset_price_above': f'si {target} sube a {_usd(threshold)} o más',
        'fx_rate_below': f'si {target} baja a {_num(threshold)} {currency} o menos',
        'fx_rate_above': f'si {target} sube a {_num(threshold)} {currency} o más',
    }[kind]
    out = f'Te aviso {text}'
    if action:
        out += f', y te dejo lista una compra de {_usd(action["amount_usd"])} en {_asset_label(action["asset_key"])} ' \
               'para que la revises y la firmes'
    return out + '.'


# ── proposing (no write) and saving (on the owner's "sí") ──────────────

def _decimal(value, what):
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OpsRefused(f'No entendí {what}.') from exc
    if not out.is_finite() or out <= 0:
        raise OpsRefused(f'No entendí {what}.')
    return out


def propose(user, *, said: str, kind: str, asset=None, currency=None, threshold=None, action_asset=None,
            action_amount_usd=None, meta=None) -> dict:
    """Validate a watch the owner asked for; returns the draft to confirm."""
    own = operable_account(user)
    if own is None:
        raise OpsRefused('No tienes una Cuenta inteligente activa.')
    if kind not in KINDS:
        raise OpsRefused('Puedo avisarte cuando un precio o el tipo de cambio sube o baja.')
    if SmartAccountWatch.objects.filter(smart_account=own, active=True).count() >= MAX_ACTIVE:
        raise OpsRefused(f'Ya tienes {MAX_ACTIVE} alertas activas. Borra alguna para crear otra.')
    if threshold is None or not said_number(said, threshold):
        # The level is always the owner's: the assistant never suggests one.
        raise OpsRefused('Dime tú el nivel exacto del aviso: yo no elijo cuándo avisarte.', 'not_said')
    threshold = _decimal(threshold, 'el nivel del aviso')
    if kind.endswith('_pct') and threshold >= 100:
        raise OpsRefused('El porcentaje tiene que ser menor que 100.')
    viewer = _viewer(user, meta)
    draft = {'kind': kind, 'threshold': format(threshold, 'f'), 'asset_key': '', 'currency': '', 'action': {}}
    if kind in FX_KINDS:
        code = (currency or '').strip().upper()
        if not re.fullmatch(r'[A-Z]{3}', code) or code == 'USD':
            raise OpsRefused('Dime de qué moneda quieres el aviso (por ejemplo VES o BOB).')
        if fx_rate(code) is None:
            raise OpsRefused(f'No tengo un tipo de cambio al día para {code}.')
        draft['currency'] = code
    else:
        picked = _resolve_asset(viewer, asset, said)
        price = asset_price(picked['asset_key'])
        if price is None:
            raise OpsRefused('No tengo el precio de esa inversión ahora. Inténtalo más tarde.')
        draft['asset_key'] = picked['asset_key']
        draft['reference_price'] = format(price, 'f')
    if action_asset or action_amount_usd:
        if not (action_asset and action_amount_usd):
            raise OpsRefused('Para dejarte una compra lista dime en qué y cuánto.')
        if not said_usd(said, action_amount_usd, level=threshold):
            raise OpsRefused('Dime tú el monto de la compra en dólares, en números: yo no elijo ni convierto cuánto '
                             'invertir.', 'not_said')
        buy = _resolve_asset(viewer, action_asset, said)
        amount = _decimal(action_amount_usd, 'el monto').quantize(Decimal('0.01'))
        _check_buy_amount(buy['asset_key'], amount, buy['name'])
        draft['action'] = {'kind': 'buy', 'asset_key': buy['asset_key'], 'amount_usd': format(amount, 'f')}
    draft['texto'] = describe(kind, asset_key=draft['asset_key'], currency=draft['currency'], threshold=threshold,
                              action=draft['action'] or None)
    return draft


def save(user, draft: dict) -> SmartAccountWatch:
    own = operable_account(user)
    if own is None:
        raise OpsRefused('No tienes una Cuenta inteligente activa.')
    with transaction.atomic():
        live = SmartAccountWatch.objects.select_for_update().filter(smart_account=own, active=True)
        if len(list(live)) >= MAX_ACTIVE:
            raise OpsRefused(f'Ya tienes {MAX_ACTIVE} alertas activas. Borra alguna para crear otra.')
        return SmartAccountWatch.objects.create(
            smart_account=own, user=user, kind=draft['kind'], asset_key=draft.get('asset_key') or '',
            currency=draft.get('currency') or '', threshold=Decimal(draft['threshold']),
            reference_price=Decimal(draft['reference_price']) if draft.get('reference_price') else None,
            action=draft.get('action') or {},
            cooldown_hours=int(getattr(settings, 'SMART_ACCOUNT_WATCH_COOLDOWN_HOURS', DEFAULT_COOLDOWN_HOURS)))


def list_for(user) -> list[dict]:
    own = operable_account(user)
    if own is None:
        return []
    return [{'alerta_id': str(w.internal_id), 'texto': describe(
                w.kind, asset_key=w.asset_key, currency=w.currency, threshold=w.threshold, action=w.action or None),
             'ultima_vez': w.last_triggered_at.date().isoformat() if w.last_triggered_at else None}
            for w in SmartAccountWatch.objects.filter(smart_account=own, active=True).order_by('-created_at')]


def delete(user, watch_id) -> bool:
    """Owner-only, by opaque id. Deleting an alert moves no money."""
    import uuid
    try:
        internal_id = uuid.UUID(str(watch_id))
    except (ValueError, TypeError):
        return False
    watch = SmartAccountWatch.objects.filter(internal_id=internal_id, user=user).first()
    if watch is None:
        return False
    watch.active = False
    watch.save(update_fields=['active', 'updated_at'])
    watch.soft_delete()
    return True


# ── evaluating ─────────────────────────────────────────────────────────

def _trigger_text(watch, value: Decimal) -> str:
    if watch.kind in FX_KINDS:
        what = f'El dólar está en {_num(value)} {watch.currency}'
    else:
        what = f'{_asset_label(watch.asset_key)} está en {_usd(value)}'
        if watch.kind.endswith('_pct') and watch.reference_price:
            change = (value - watch.reference_price) * 100 / watch.reference_price
            what += f' ({"+" if change > 0 else ""}{change.quantize(Decimal("0.1"))}% desde que creaste la alerta)'
    return what + '.'


def _notify(watch, value: Decimal, fired_at) -> None:
    from assistant.service import post_system_note
    from . import notifications
    text = _trigger_text(watch, value)
    notifications.safe(notifications._send, watch.user, 'Tu alerta se cumplió', text, kind='watch_triggered',
                       account=watch.smart_account, data={'watchId': str(watch.internal_id)})
    body = f'Tu alerta se cumplió: {text}'
    proposal, actions = None, []
    action = watch.action or {}
    if action.get('kind') == 'buy':
        name = _asset_label(action['asset_key'])
        body += (f' Te dejé lista la compra de {_usd(action["amount_usd"])} en {name} que pediste: ábrela, revísala '
                 'y fírmala si todavía la quieres. No se ejecuta sin tu firma.')
        from .assistant_ops import _step
        proposal = {'steps': [_step('create', 'buy', amount=Decimal(action['amount_usd']), frequency='monthly',
                                    asset_key=action['asset_key'], asset_name=name,
                                    sentence=(f'Comprar {_usd(action["amount_usd"])} de {name} desde tu Cuenta '
                                              'inteligente. Se guarda como regla mensual: si solo querías esta '
                                              'compra, detén la regla después de la primera ejecución.'))],
                    'created_at': fired_at.isoformat()}
        actions = [rule_chip()]
    post_system_note(watch.user, body, f'smart_account_watch:{watch.pk}:{fired_at:%Y%m%d%H%M}',
                     actions=actions, rule_proposal=proposal)


def evaluate(now=None) -> dict:
    """Every active watch of a current subscriber, once per cooldown."""
    from assistant.billing import has_plus
    now = now or timezone.now()
    out = {'checked': 0, 'triggered': 0, 'unknown': 0, 'errors': 0}
    prices: dict = {}
    watches = (SmartAccountWatch.objects.filter(active=True, smart_account__status__in=('active', 'cancel_pending'))
               .select_related('smart_account', 'user').order_by('id'))
    plus: dict = {}
    for watch in watches:
        try:
            if watch.user_id not in plus:
                plus[watch.user_id] = has_plus(watch.user)
            if not plus[watch.user_id]:
                continue
            if watch.last_triggered_at and watch.last_triggered_at > now - timedelta(hours=watch.cooldown_hours):
                continue
            out['checked'] += 1
            value = current_value(watch, cache=prices)
            if value is None:
                out['unknown'] += 1
                continue
            if not triggered(watch, value):
                continue
            # Compare-and-set on the last trigger: a second worker loses.
            updates = {'last_triggered_at': now, 'last_value': value, 'updated_at': now}
            if watch.kind.endswith('_pct'):
                updates['reference_price'] = value  # the next alert counts from here
            won = SmartAccountWatch.objects.filter(
                pk=watch.pk, last_triggered_at=watch.last_triggered_at).update(**updates)
            if not won:
                continue
            _notify(watch, value, now)
            out['triggered'] += 1
        except Exception:  # noqa: BLE001 — one watch never blocks the rest; counted
            logger.exception('smart account watch %s failed', watch.pk)
            out['errors'] += 1
    return out
