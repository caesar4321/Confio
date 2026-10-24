"""Pago ASAP as the VE Pago Móvil send provider (adapter for ramps.ve_send).

Pago ASAP takes stablecoins on Polygon only. Funding: when the user claims
the funding, a Relay quote (payment_accounts.relay, the audited bridge
client) gives a deposit address on BSC that bridges the user's exact USDT to
native USDC at Confío's Pago ASAP Polygon address. The user pays that
address in the usual sponsored batch; ve_send proves it on BSC, and settle()
proves Relay's delivery on Polygon from finalized canonical receipts
(payment_accounts.relay_settlement). Pago ASAP credits our USD balance.
Payout: a Pago Móvil intent for `amountVES`, converted from that balance at
Pago ASAP's rate, sized from the USDC actually delivered; polled to
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
from ramps.ve_send import Outcome, Settlement

logger = logging.getLogger(__name__)

PROVIDER = 'pagoasap'
# Several sends of one person may share a Relay deposit route: tag amounts.
SHARED_DEPOSIT_TARGET = True
TARGET_AT_CLAIM = True
SOURCE, DESTINATION = 'BSC:USDT', 'POL:USDC'
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


def _polygon_address() -> str:
    return (getattr(settings, 'PAGOASAP_DEPOSIT_ADDRESS_POLYGON', '') or '').strip()


def deposit_target(ramp) -> str | None:
    return None  # made at claim time (funding_target)


def funding_target(ramp) -> dict:
    """A Relay deposit address on BSC for this order's exact USDT, bridging to
    Pago ASAP's Polygon address. Validated by the bridge client (assets,
    amounts, recipient, refund to the sender, single ERC20 deposit)."""
    from payment_accounts.allbridge_next import NextError
    from payment_accounts.bridge_binding import deposit_call
    from payment_accounts.relay import RelayClient
    section = ve_send._section(ramp)
    amount = str(section['deposit_wei'])
    recipient = _polygon_address()
    if not recipient:
        raise VePagoMovilError(UNAVAILABLE)
    client = RelayClient()
    try:
        route = client.routes(SOURCE, DESTINATION, amount, ramp.actor_address, recipient)[0]
        build = client.build(route, source_address=ramp.actor_address, destination_address=recipient)
        deposit, _ = deposit_call(build, SOURCE, amount)
    except NextError as exc:
        logger.warning('Relay quote failed for VE send %s: %s', ramp.pk, exc)
        raise VePagoMovilError('No pudimos preparar el envío. Intenta de nuevo en unos minutos.') from exc
    return {
        'deposit_address': deposit,
        'binding': {
            'provider': 'relay', 'request_id': build['relay']['request_id'],
            'response': build['relay']['response'], 'deadline': build['relay']['deadline'],
            'recipient': recipient.lower(), 'amount_out': build['amountOut'],
            'amount_out_min': build['amountOutMin'],
        },
    }


def settle(ramp) -> Settlement:
    """Relay's delivery to Pago ASAP on Polygon, proven from finalized
    canonical receipts by the audited bridge reconciler."""
    from types import SimpleNamespace
    from payment_accounts.allbridge_next import NextError, TOKENS
    from payment_accounts.relay_settlement import reconcile_relay
    section = ve_send._section(ramp)
    bridge = section.get('bridge') or {}
    if not bridge.get('request_id') or not section.get('funding_tx_hash'):
        return Settlement('review', reason='bridge_binding_missing')
    transfer = SimpleNamespace(
        quote=SimpleNamespace(source_token_id=SOURCE, destination_token_id=DESTINATION,
                              amount_units=str(section['deposit_wei']),
                              source_address=(ramp.actor_address or '').lower(),
                              destination_address=bridge['recipient']),
        binding={'request_id': bridge['request_id'], 'response': bridge['response']},
        deadline=int(bridge['deadline']), source_tx_hash=section['funding_tx_hash'],
        deposit_address=section['deposit_address'], funding_mode='wallet',
        amount_out_min=bridge['amount_out_min'], status='bridging', failure_code='',
        actual_out_units=None, destination_tx_hash='')
    try:
        reconcile_relay(transfer)
    except NextError:
        return Settlement('pending')  # not resolvable yet; escalates after the deadline
    if transfer.status == 'delivered':
        received = int(transfer.actual_out_units)
        expected = int(bridge.get('amount_out') or 0)
        # The receipt check sums every USDC transfer to Pago ASAP in the
        # delivery transaction: credit at most this order's own quoted output,
        # and let ops look when the transaction plainly carries more.
        if expected <= 0 or received > expected + max(expected // 50, 50_000):
            return Settlement('review', reason='delivery_amount_unattributable')
        units = min(received, expected)
        usd = Decimal(units) / Decimal(10 ** TOKENS[DESTINATION][1])
        return Settlement('delivered', credited_usd=format(usd, 'f'), evidence=transfer.destination_tx_hash)
    if transfer.status == 'refunded':
        return Settlement('refunded')
    if transfer.status == 'needs_review':
        return Settlement('review', reason=transfer.failure_code or 'bridge')
    return Settlement('pending')


def quote(amount: Decimal) -> dict:
    client = _client()
    _, deposit_wei = ve_send.confio_amounts(amount)
    usdt = Decimal(deposit_wei) / Decimal(10 ** 18)
    recipient = _polygon_address()
    if not recipient:
        raise VePagoMovilError(UNAVAILABLE)
    try:
        rate = client.rate('USD', 'VES')
        reference = client.reference_rate()
    except PagoAsapError as exc:
        logger.exception('Pago ASAP quote failed')
        raise VePagoMovilError(GENERIC_ERROR) from exc
    if rate <= 0:
        raise VePagoMovilError(GENERIC_ERROR)
    # The bridge's own estimate (no deposit address is made for a quote).
    from payment_accounts.allbridge_next import NextError, TOKENS
    from payment_accounts.relay import RelayClient
    try:
        estimate = RelayClient().quote(SOURCE, DESTINATION, str(deposit_wei), source_address=recipient,
                                       destination_address=recipient)
        delivered = Decimal(str(estimate['details']['currencyOut']['amount'])) / Decimal(10 ** TOKENS[DESTINATION][1])
    except (NextError, KeyError, TypeError) as exc:
        raise VePagoMovilError(str(exc) if 'muy pequeño' in str(exc) else GENERIC_ERROR) from exc
    ves = _ves_for(_fee_free_usd(delivered), rate)
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
    if not _polygon_address():
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
    # What Relay actually delivered to Pago ASAP (proven on Polygon).
    usd = _fee_free_usd(Decimal(str(section.get('credited_usd') or '0')))
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
