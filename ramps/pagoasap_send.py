"""Pago ASAP as the VE Pago Móvil send provider (adapter for ramps.ve_send).

Funding: the user's USDT goes to Confío's Pago ASAP deposit address on BSC
(one address for every send, so ve_send tags each sender's amounts). Pago
ASAP credits our USD balance. Payout: a Pago Móvil intent for `amountVES`,
which Pago ASAP converts from that balance at its rate; polled to
completed/failed. No manual step.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.conf import settings

from ramps import ve_pagomovil, ve_send
from ramps.pagoasap_client import PagoAsapAmbiguousError, PagoAsapClient, PagoAsapError, idempotency_key
from ramps.ve_pagomovil import VePagoMovilError
from ramps.ve_send import Outcome

logger = logging.getLogger(__name__)

PROVIDER = 'pagoasap'
SHARED_DEPOSIT_TARGET = True
PENDING_STALE = timedelta(hours=2)
MIN_PAYOUT_VES = Decimal('10')
UNAVAILABLE = 'Los envíos en bolívares no están disponibles por ahora.'
GENERIC_ERROR = 'No pudimos procesar el envío. Intenta de nuevo en unos minutos.'


def replay_window() -> timedelta:
    """How long a lost payout answer may be replayed under its own key.
    Pago ASAP has not documented how long an Idempotency-Key is honoured, so
    this is short and configurable; after it, ops checks."""
    return timedelta(minutes=int(getattr(settings, 'PAGOASAP_IDEMPOTENCY_REPLAY_MINUTES', 30)))


def _client() -> PagoAsapClient:
    client = PagoAsapClient()
    if not client.is_configured:
        raise VePagoMovilError(UNAVAILABLE)
    return client


def _fee_free_usd(usdt: Decimal) -> Decimal:
    """USD Pago ASAP credits for a USDT deposit (its deposit fee, if any)."""
    pct = ve_pagomovil.setting_decimal('PAGOASAP_DEPOSIT_FEE_PERCENT', '0') / 100
    fixed = ve_pagomovil.setting_decimal('PAGOASAP_DEPOSIT_FEE_FIXED', '0')
    return max(usdt * (1 - pct) - fixed, Decimal('0'))


def _ves_for(usd: Decimal, rate: Decimal) -> Decimal:
    return (usd * rate).quantize(ve_send.CENT, rounding=ROUND_DOWN)


def deposit_target(ramp) -> str | None:
    return getattr(settings, 'PAGOASAP_DEPOSIT_ADDRESS_BSC', '') or None


def quote(amount: Decimal) -> dict:
    client = _client()
    _, deposit_wei = ve_send.confio_amounts(amount)
    usdt = Decimal(deposit_wei) / Decimal(10 ** 18)
    try:
        rate = client.rate('USD', 'VES')
        reference = client.reference_rate()
    except PagoAsapError as exc:
        logger.exception('Pago ASAP quote failed')
        raise VePagoMovilError(GENERIC_ERROR) from exc
    if rate <= 0:
        raise VePagoMovilError(GENERIC_ERROR)
    ves = _ves_for(_fee_free_usd(usdt), rate)
    # The processor's share in dollars: what these bolívares would have cost
    # at the market reference, against the dollars that go in.
    processor_fee = max(usdt - (ves / reference), Decimal('0')) if reference > 0 else Decimal('0')
    return {
        'usd_amount': format(amount, 'f'),
        'usdt_amount': format(usdt.quantize(ve_send.MICRO), 'f'),
        'confio_fee_usd': format(max(amount - usdt, Decimal('0')).quantize(ve_send.CENT), 'f'),
        'processor_fee_usd': format(processor_fee.quantize(ve_send.CENT), 'f'),
        'estimated_ves': format(ves, 'f'),
        'rate': format(rate, 'f'),
    }


def create(user, account, amount: Decimal, beneficiary: dict):
    if not deposit_target(None):
        raise VePagoMovilError(UNAVAILABLE)
    estimate = quote(amount)
    gross_wei, deposit_wei = ve_send.confio_amounts(amount)
    # Where the chain scan starts: without it a lost funding hash could never
    # be found, so no order is made.
    created_block = ve_send.current_block()
    if created_block is None:
        raise VePagoMovilError(GENERIC_ERROR)
    ramp = ve_send.reserve(provider=PROVIDER, user=user, account=account, gross_usd=amount,
                           beneficiary=beneficiary, gross_wei=gross_wei, deposit_wei=deposit_wei,
                           created_block=created_block, estimate=estimate)
    return ve_send.prepare(ramp)


def _payout_cost(ramp) -> Decimal:
    claim = ve_send._section(ramp).get('payout_claim') or {}
    try:
        return Decimal(str(claim.get('cost') or '0'))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


PRICING_STEPS = 8


def _cost(client, ves: Decimal) -> Decimal:
    return Decimal(str((client.preview(ves) or {}).get('total') or '0'))


def _affordable(client, usd: Decimal, rate: Decimal):
    """(bolívares, USD cost): the largest payout whose previewed cost fits
    the funded dollars, by a bounded search (fees may be fixed or rounded)."""
    high = _ves_for(usd, rate)
    total = _cost(client, high)
    if 0 < total <= usd:
        return high, total
    low, best = MIN_PAYOUT_VES, None
    low_total = _cost(client, low)
    if not 0 < low_total <= usd:
        return None
    best = (low, low_total)
    for _ in range(PRICING_STEPS):
        if high - low <= ve_send.CENT:
            break
        middle = ((low + high) / 2).quantize(ve_send.CENT, rounding=ROUND_DOWN)
        cost = _cost(client, middle)
        if 0 < cost <= usd:
            low, best = middle, (middle, cost)
        else:
            high = middle
    return best


def payout_terms(ramp, inflight) -> dict | None:
    """Price the payout now and check the balance covers it after payouts
    in flight. None: not payable yet (deposit not credited, below minimum)."""
    client = _client()
    section = ve_send._section(ramp)
    usd = _fee_free_usd(Decimal(str(section.get('funded_wei') or '0')) / Decimal(10 ** 18))
    rate = client.rate('USD', 'VES')
    if rate <= 0 or usd <= 0:
        return None
    priced = _affordable(client, usd, rate)
    if priced is None:
        # No amount at or above the minimum fits the funded dollars.
        return {'review': 'payout_unpriceable'}
    ves, total = priced
    symbol = str(getattr(settings, 'PAGOASAP_BALANCE_SYMBOL', 'USD')).upper()
    balance = client.balances().get(symbol, Decimal('0'))
    cost = ves if symbol == 'VES' else total
    if balance - sum((_payout_cost(other) for other in inflight), Decimal('0')) < cost:
        return None
    beneficiary = section.get('beneficiary') or {}
    phone = str(beneficiary.get('phone') or '')
    return {
        'ves_amount': format(ves, 'f'),
        'cost': format(cost, 'f'),
        'phone': f'0{phone[2:]}' if phone.startswith('58') else phone,
        'cedula': str(beneficiary.get('cedula') or ''),
        'bank_code': str(beneficiary.get('bank_code') or ''),
    }


def dispatch(ramp, claim: dict) -> Outcome:
    try:
        intent_id = _client().create_payout(
            phone=claim['phone'], amount_ves=Decimal(claim['ves_amount']), cedula=claim['cedula'],
            bank_code=claim['bank_code'], order_ref=str(ramp.internal_id),
            idempotency_key=idempotency_key(claim['key']))
    except PagoAsapAmbiguousError:
        return Outcome('ambiguous')
    except PagoAsapError as exc:
        if exc.status in (400, 422):
            # Validation refusal: no intent was created.
            return Outcome('failed', reason=f'refused:{exc.code or exc.status}')
        return Outcome('unknown', reason=f'{exc.status}:{exc.code}')
    return Outcome('pending', operation_id=intent_id)


def poll(ramp) -> Outcome:
    section = ve_send._section(ramp)
    try:
        intent = _client().payout(section['operation_id'])
    except PagoAsapError as exc:
        if exc.status == 404:
            return Outcome('pending')  # not visible yet; stale -> review
        raise
    state = str(intent.get('state') or '').lower()
    if state == 'completed':
        return Outcome('paid', reference=str(intent.get('reference') or ''),
                       operation_id=section['operation_id'], ves_amount=str(intent.get('amountVES') or ''))
    if state == 'failed':
        reason = str(intent.get('reason') or 'failed')
        if reason == 'not_enough_funds':
            # Our balance did not cover it: nothing paid, try again later.
            return Outcome('retry', reason=reason)
        return Outcome('failed', reason=reason)
    if state in ('pending', 'processing', 'reserved'):
        return Outcome('pending', operation_id=section['operation_id'])
    return Outcome('unknown', reason=f'state:{state or "none"}')


def active_order(user):
    return ve_send.active_order(user, PROVIDER)
