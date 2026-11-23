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
from decimal import ROUND_DOWN, ROUND_UP, Decimal, InvalidOperation

from django.conf import settings

from ramps import ve_pagomovil, ve_send
from ramps.pagoasap_client import (
    PagoAsapAmbiguousError, PagoAsapAuthError, PagoAsapClient, PagoAsapError, idempotency_key,
)
from ramps.ve_pagomovil import VePagoMovilError
from ramps.ve_send import Outcome, Settlement

logger = logging.getLogger(__name__)

PROVIDER = 'pagoasap'
# Several sends of one person may share a Relay deposit route: tag amounts.
# A contract-funded send (ve_send.CONTRACT_FUNDING) is untagged: it asks for
# a one-time address (a used one is refused), and ve_send proves it only by
# the reported executeRule hash (never by a log scan) and refuses a second
# open one of the same account and amount.
SHARED_DEPOSIT_TARGET = True
TARGET_AT_CLAIM = True
SOURCE, DESTINATION = 'BSC:USDT', 'POL:USDC'
PENDING_STALE = timedelta(hours=2)
COUNTRY, FIAT, LIMIT_PREFIX = 'VE', 'VES', 'VE_PAGOMOVIL_SEND'
REFUSALS_403 = ('Partner Limit Exceeded', 'Beneficiary Limit Exceeded', 'Partner IP Not Allowed')
MIN_PAYOUT_VES = Decimal('10')
PAYABLE_MARGIN = Decimal('1.5')
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


TOO_SMALL = 'El monto es muy pequeño para enviarlo. Prueba con un monto mayor.'


def _require_payable(client, delivered_usd: Decimal) -> None:
    """Refuse a send whose bridged dollars could not pay Pago ASAP's smallest
    payout: once funded it would only reach ops review. There are no product
    caps, so this is the floor (kept with a margin for rate moves)."""
    try:
        smallest = _cost(client, MIN_PAYOUT_VES)
    except PagoAsapError as exc:
        logger.exception('Pago ASAP preview failed')
        raise VePagoMovilError(GENERIC_ERROR) from exc
    if smallest <= 0 or _fee_free_usd(delivered_usd) < smallest * PAYABLE_MARGIN:
        raise VePagoMovilError(TOO_SMALL)


def _polygon_address() -> str:
    return (getattr(settings, 'PAGOASAP_DEPOSIT_ADDRESS_POLYGON', '') or '').strip()


def deposit_target(ramp) -> str | None:
    return None  # made at claim time (funding_target)


def funding_target(ramp) -> dict:
    """A Relay deposit address on BSC for this order's exact USDT, bridging to
    Pago ASAP's Polygon address. Validated by the bridge client (assets,
    amounts, recipient, refund to the sender, single ERC20 deposit)."""
    from payment_accounts.allbridge_next import NextError, TOKENS
    from payment_accounts.bridge_binding import deposit_call
    from payment_accounts.relay import RelayClient
    section = ve_send._section(ramp)
    amount = str(section['deposit_wei'])
    recipient = _polygon_address()
    if not recipient:
        raise VePagoMovilError(UNAVAILABLE)
    if section.get('funding_sender'):
        # As an Infinia run: a one-time address, and (refundTo is the account
        # contract, which cannot sign a withdrawal) who may recover a refund.
        from payment_accounts.contract_funding import OneTimeDepositRelay
        client = OneTimeDepositRelay((section.get('funding_terms') or {}).get('recovery') or '')
    else:
        client = RelayClient()
    try:
        route = client.routes(SOURCE, DESTINATION, amount, ramp.actor_address, recipient)[0]
        build = client.build(route, source_address=ramp.actor_address, destination_address=recipient)
        deposit, _ = deposit_call(build, SOURCE, amount)
    except NextError as exc:
        logger.warning('Relay quote failed for VE send %s: %s', ramp.pk, exc)
        raise VePagoMovilError('No pudimos preparar el envío. Intenta de nuevo en unos minutos.') from exc
    # The least this bridge may deliver must still pay a payout, checked
    # again here because the claim is the last step before money moves.
    _require_payable(_client(), Decimal(str(build['amountOutMin'])) / Decimal(10 ** TOKENS[DESTINATION][1]))
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
    binding = {'request_id': bridge['request_id'], 'response': bridge['response']}
    sender = section.get('funding_sender')
    if sender:
        # As an Infinia run: the request Relay bound to the deposit address
        # and our funding hash, never the quote's id; a sweep may carry more.
        binding['contract_funding'] = {
            **(section.get('relay_follow') or {}),      # the request found for this deposit
            'sender': str(sender).lower(), 'funded_units': str(section.get('funded_wei') or ''),
            'recovery': str((section.get('funding_terms') or {}).get('recovery') or '').lower()}
    transfer = SimpleNamespace(
        pk=f've{ramp.pk}', internal_id=ramp.internal_id, provider_name='Pago Móvil',
        quote=SimpleNamespace(source_token_id=SOURCE, destination_token_id=DESTINATION,
                              amount_units=str(section['deposit_wei']),
                              source_address=(ramp.actor_address or '').lower(),
                              destination_address=bridge['recipient']),
        binding=binding,
        deadline=int(bridge['deadline']), source_tx_hash=section['funding_tx_hash'],
        deposit_address=section['deposit_address'],
        # A contract-funded send (ve_send.CONTRACT_FUNDING): the vault, not
        # source_address, sent the deposit; ve_send already proved that
        # Transfer from funding_sender. Any mode other than 'wallet' makes
        # relay_settlement match the funding by that vault (binding); refunds
        # still go to source_address (the account contract).
        funding_mode='contract' if section.get('funding_sender') else 'wallet',
        # A contract-funded order may be funded above deposit_wei (a vault
        # exit, ve_send._check_receipt; recorded as funding_excess_wei): the
        # proven funded amount is what Relay's sweep collects, so the
        # reconciler matches that instead of failing on the exact quote.
        funded_units=(str(section.get('funded_wei') or '') or None) if section.get('funding_sender') else None,
        amount_out_min=bridge['amount_out_min'], status='bridging', failure_code='',
        actual_out_units=None, destination_tx_hash='')
    if sender:
        follow = dict(section.get('relay_follow') or {})

        def remember(values):
            follow.update(values)
            ve_send._update(ramp.pk, relay_follow=dict(follow))
        transfer.remember = remember
    try:
        reconcile_relay(transfer)
    except NextError:
        return Settlement('pending')  # not resolvable yet; escalates after the deadline
    if transfer.status == 'delivered':
        received = int(transfer.actual_out_units)
        expected = int(bridge.get('amount_out') or 0)
        # The receipt check sums every USDC transfer to Pago ASAP in the
        # delivery transaction: credit at most this order's own quoted output,
        # and let ops look when the transaction plainly carries more than
        # what was swept for it explains.
        explained = expected
        if sender:
            quoted = int(section['deposit_wei'])
            swept = int((transfer.binding.get('settlement_evidence') or {}).get('collected_units') or 0)
            explained = expected * max(swept, quoted) // quoted
        if expected <= 0 or received > explained + max(explained // 50, 50_000):
            return Settlement('review', reason='delivery_amount_unattributable')
        units = min(received, expected)
        usd = Decimal(units) / Decimal(10 ** TOKENS[DESTINATION][1])
        return Settlement('delivered', credited_usd=format(usd, 'f'), evidence=transfer.destination_tx_hash)
    if transfer.status == 'refunded':
        return Settlement('refunded')
    if transfer.status == 'needs_review':
        return Settlement('review', reason=transfer.failure_code or 'bridge')
    return Settlement('pending')


def route_cost_bps(deposit_wei, amount_out) -> int:
    """What a deposit route and the deposit fee keep of the USDT it is
    funded with. Raises when the route does not say what it delivers."""
    from payment_accounts.allbridge_next import TOKENS
    usdt = Decimal(int(deposit_wei)) / Decimal(10 ** TOKENS[SOURCE][1])
    out = Decimal(int(str(amount_out))) / Decimal(10 ** TOKENS[DESTINATION][1])
    if usdt <= 0 or out <= 0:
        raise ValueError('The route names no amount')
    kept = max(usdt - _fee_free_usd(out), Decimal('0'))
    return int((kept / usdt * 10_000).to_integral_value(rounding=ROUND_UP))


def quote(amount: Decimal) -> dict:
    return _priced(amount)[0]


def _rates(client) -> tuple[Decimal, Decimal]:
    """(Pago ASAP's USD→VES rate, the market reference or 0)."""
    try:
        rate = client.rate('USD', 'VES')
    except PagoAsapError as exc:
        logger.exception('Pago ASAP quote failed')
        raise VePagoMovilError(GENERIC_ERROR) from exc
    # The market reference only splits the cost into a fee line; the payout is
    # priced from `rate` alone, so a send never waits on it.
    try:
        reference = client.reference_rate()
    except PagoAsapError:
        logger.warning('Pago ASAP reference rate unavailable; quoting without the processor fee line', exc_info=True)
        reference = Decimal('0')
    if rate <= 0:
        raise VePagoMovilError(GENERIC_ERROR)
    return rate, reference


def _priced(amount: Decimal, client=None, rates=None) -> tuple[dict, Decimal]:
    """(the quote for `amount` gross dollars, the dollars Relay delivers)."""
    client = client or _client()
    _, deposit_wei = ve_send.confio_amounts(amount)
    usdt = Decimal(deposit_wei) / Decimal(10 ** 18)
    recipient = _polygon_address()
    if not recipient:
        raise VePagoMovilError(UNAVAILABLE)
    rate, reference = rates or _rates(client)
    # The bridge's own estimate (no deposit address is made for a quote).
    from payment_accounts.allbridge_next import NextError, TOKENS
    from payment_accounts.relay import RelayClient
    try:
        estimate = RelayClient().quote(SOURCE, DESTINATION, str(deposit_wei), source_address=recipient,
                                       destination_address=recipient)
        delivered = Decimal(str(estimate['details']['currencyOut']['amount'])) / Decimal(10 ** TOKENS[DESTINATION][1])
    except (NextError, KeyError, TypeError) as exc:
        raise VePagoMovilError(str(exc) if 'muy pequeño' in str(exc) else GENERIC_ERROR) from exc
    _require_payable(client, delivered)
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
    }, delivered


EXACT_PRICE_TRIES = 6
PRICE_MOVED = 'El precio cambió. Revisa el envío de nuevo.'


def quote_exact(ves) -> dict:
    """The dollars that pay exactly `ves` bolívares by Pago Móvil, all in.

    Priced from Pago ASAP's own cost for that payout plus a margin
    (VE_PAGOMOVIL_EXACT_MARGIN_BPS) against the rate moving before it runs;
    the payout is exactly `ves` and what the deposit buys above it stays in
    Confío's Pago ASAP balance (payout_terms). Same keys as quote()."""
    try:
        ves = Decimal(str(ves))
    except (InvalidOperation, TypeError, ValueError):
        raise VePagoMovilError('Monto no válido.')
    if not ves.is_finite() or ves != ves.quantize(ve_send.CENT) or ves < MIN_PAYOUT_VES or ves >= Decimal('1e10'):
        raise VePagoMovilError(f'Escribe un monto desde {MIN_PAYOUT_VES} bolívares, con hasta dos decimales.')
    client = _client()
    try:
        cost = _cost(client, ves)
    except PagoAsapError as exc:
        logger.exception('Pago ASAP exact preview failed')
        raise VePagoMovilError(GENERIC_ERROR) from exc
    if cost <= 0:
        raise VePagoMovilError(GENERIC_ERROR)
    margin = ve_pagomovil.setting_decimal('VE_PAGOMOVIL_EXACT_MARGIN_BPS', '100') / 10_000
    needed = (cost * (1 + margin)).quantize(ve_send.CENT, rounding=ROUND_UP)
    rates = _rates(client)   # once per quote: each try only asks Relay again
    amount = needed
    for _ in range(EXACT_PRICE_TRIES):
        priced, delivered = _priced(amount, client, rates)
        have = _fee_free_usd(delivered)
        if have <= 0:
            raise VePagoMovilError(GENERIC_ERROR)
        # Scaled both ways: never charged far above what the payout needs.
        target = (amount * needed / have).quantize(ve_send.CENT, rounding=ROUND_UP) + ve_send.CENT
        if have >= needed and amount <= target:
            # The lines add up to what the person pays for exactly these
            # bolívares: Confío's fee, then everything else (Pago ASAP's cost,
            # the bridge and the margin, which is not returned) as the
            # processor's share; the rate is bolívares per dollar sent.
            usdt = Decimal(priced['usdt_amount'])
            reference = rates[1]
            processor = max(usdt - ves / reference, Decimal('0')) if reference > 0 else max(usdt - cost, Decimal('0'))
            return {**priced, 'estimated_ves': format(ves, 'f'), 'exact_ves': format(ves, 'f'),
                    'processor_fee_usd': format(processor.quantize(ve_send.CENT, rounding=ROUND_UP), 'f'),
                    'rate': format((ves / amount).quantize(Decimal('0.0001'), rounding=ROUND_DOWN), 'f')}
        amount = target
    raise VePagoMovilError(GENERIC_ERROR)


def exact_ves_of(ramp):
    """The exact bolívares a send pays, or None for a dollar send."""
    value = ((ve_send._section(ramp).get('estimate') or {}).get('exact_ves'))
    try:
        return Decimal(str(value)) if value not in (None, '') else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def create(user, account, amount: Decimal, beneficiary: dict, exact_ves=None):
    if not _polygon_address():
        raise VePagoMovilError(UNAVAILABLE)
    if exact_ves is not None:
        estimate = quote_exact(exact_ves)
        # Priced again now: never more dollars than the person approved, and
        # never more than the fresh price either (a stale screen does not
        # overpay): the send is the fresh price, its lines as quoted.
        fresh = Decimal(estimate['usd_amount'])
        if fresh > amount:
            raise VePagoMovilError(PRICE_MOVED)
        amount = fresh
    else:
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


def pays_at_floor(usd: Decimal, rate: Decimal, floor: Decimal) -> bool:
    """Whether `usd` buys at least what the signed floor gives, the provider's
    own payout cost included. Asked before a contract funds a send, by the
    measure payout_terms pays by: money is never sent only to be held."""
    if rate < floor:
        return False
    priced = _affordable(_client(), usd, rate)
    return priced is not None and priced[0] >= _ves_for(usd, floor)


def payout_terms(ramp, inflight) -> dict | None:
    """Price the payout now and check the balance covers it after payouts
    in flight. None: not payable yet (deposit not credited, below minimum)."""
    section = ve_send._section(ramp)
    # What Relay actually delivered to Pago ASAP (proven on Polygon).
    credited = Decimal(str(section.get('credited_usd') or '0'))
    if section.get('funding_sender') and credited > Decimal(str(section.get('gross_usd') or '0')):
        # A contract-funded send never pays over what its owner signed.
        return {'review': ve_send.TERMS_CHANGED}
    client = _client()
    usd = _fee_free_usd(credited)
    rate = client.rate('USD', 'VES')
    if rate <= 0 or usd <= 0:
        return None
    exact = exact_ves_of(ramp)
    if exact is not None:
        # An exact bolívar send pays exactly that; what the deposit bought
        # above it stays in Confío's Pago ASAP balance. Dollars that no longer
        # cover it go to review, never a smaller payout.
        total = _cost(client, exact)
        if total <= 0:
            return None
        if total > usd:
            # The rate moved against it since funding: wait for it to come
            # back (ve_send's RATE_WAIT), then review. Never a smaller payout.
            return {'wait': 'exact_payout_short'}
        return _terms(client, section, exact, total, inflight)
    floor = None
    if section.get('funding_sender'):
        from smart_account.payouts import ramp_fx_floor
        floor = ramp_fx_floor(ramp)
        if floor is None:
            return {'review': ve_send.TERMS_CHANGED}
        if rate < floor:
            return {'wait': ve_send.RATE_OUTSIDE}
    priced = _affordable(client, usd, rate)
    if priced is None:
        # No amount at or above the minimum fits the funded dollars.
        return {'review': 'payout_unpriceable'}
    ves, total = priced
    if floor is not None and ves < _ves_for(usd, floor):
        # The rate alone is not it: the provider's own cost counts.
        return {'wait': ve_send.RATE_OUTSIDE}
    return _terms(client, section, ves, total, inflight)


def _terms(client, section, ves, total, inflight):
    symbol = str(getattr(settings, 'PAGOASAP_BALANCE_SYMBOL', 'USD')).upper()
    symbol = 'USD' if symbol == 'USDT' else symbol  # balances() names dollars "USD"
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
    except PagoAsapAuthError:
        return Outcome('retry', reason=ve_send.NOT_SENT)
    except PagoAsapError as exc:
        if exc.status == 429:
            # Too many requests, not a refusal of this payout: the same key
            # again, and nothing was taken (the replay window does not run).
            return Outcome('ambiguous', reason=ve_send.RATE_LIMITED)
        if exc.status in (400, 422) or (exc.status == 403 and exc.code in REFUSALS_403):
            # Validation refusal, or a partner/beneficiary limit or IP
            # allowlist refusal: checked before creation, no intent exists.
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
