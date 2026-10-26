"""Pagar con QR Bolivia: what both adapters share on top of the send core.

The send core (ramps/ve_send.py) owns the order, the single-use funding
claim, the BSC proof, the payout lease and the ops console. This module adds
the Bolivian steps around it:

  decode   the provider reads the QR (who, bank, amount); the app never
           supplies the recipient
  quote    bolivianos -> the USDC the provider asks for -> the USDT the
           person's BSC wallet must send through Relay so that even its
           guaranteed minimum covers it -> the Confío-dollar debit
  funding  at the claim: the provider's funding address and amount (made at
           creation or at the claim, per adapter, and remade or refused once
           expired) and a Relay route for the order's exact USDT to it,
           refused if its minimum no longer covers the amount. Only a
           production provider is ever funded.
  surplus  the bridge usually delivers a little more than its minimum; the
           surplus stays in our balance at the provider (decided 2026-10-26)
           and is recorded on the order (provider_surplus_units)
  settle   Relay's delivery to the provider, proven from finalized receipts

The person signs only on BSC; Polygon is between Relay and the provider.
"""
from __future__ import annotations

import logging
from decimal import ROUND_UP, Decimal

from ramps import bolivia_qr, ve_send
from ramps.bolivia_qr import SEND, BoliviaQrError

logger = logging.getLogger(__name__)

SOURCE, DESTINATION = 'BSC:USDT', 'POL:USDC'
USDT_WEI = Decimal(10 ** 18)
USDC_UNITS = Decimal(10 ** 6)
GENERIC = 'No pudimos preparar el pago. Intenta de nuevo en unos minutos.'
PRICE_MOVED = 'El precio cambió. Vuelve a escanear el QR para cotizar de nuevo.'
NOT_LIVE = 'Pagar con QR Bolivia está en modo de prueba: no se envió nada.'
EXPIRED = 'Este pago venció. Vuelve a escanear el QR.'
# Never sign a funding the provider order would not survive (bridge time).
PROVIDER_MARGIN_SECONDS = 600
# Room between what the provider asks and the bridge's guaranteed minimum,
# so a small move between the quote and the claim does not refuse the send.
CUSHION = Decimal('1.004')
SIZING_ROUNDS = 4


def adapter(provider: str | None = None):
    return bolivia_qr.adapter(SEND, provider)


# ------------------------------------------------------------------ decode

def decode(qr_text: str) -> dict:
    text = str(qr_text or '').strip()
    if not text or len(text) > 2000:
        raise BoliviaQrError('Ese no parece un QR boliviano.')
    preview = adapter().decode(text)
    if not preview.get('holder_name'):
        raise BoliviaQrError('No pudimos leer el destinatario de ese QR.')
    return preview


def _bob(preview: dict, amount) -> Decimal:
    """A fixed-amount QR pays its amount; an open one what the person typed."""
    if preview.get('fixed_amount'):
        return Decimal(str(preview['amount']))
    try:
        bob = Decimal(str(amount)).quantize(Decimal('0.01'))
    except Exception as exc:  # noqa: BLE001
        raise BoliviaQrError('Escribe el monto en bolivianos.') from exc
    if not bob.is_finite() or bob <= 0:
        raise BoliviaQrError('Escribe el monto en bolivianos.')
    return bob


# ------------------------------------------------------------------ sizing

def _relay_min_out(usdt_wei: int, recipient: str) -> tuple[int, int]:
    """(expected, guaranteed minimum) USDC units Relay delivers for this
    exact input (an estimate: no deposit address is made)."""
    from payment_accounts.allbridge_next import NextError
    from payment_accounts.relay import RelayClient
    try:
        quote = RelayClient().quote(SOURCE, DESTINATION, str(usdt_wei), source_address=recipient,
                                    destination_address=recipient)
        out = quote['details']['currencyOut']
        return int(out['amount']), int(out['minimumAmount'])
    except (NextError, KeyError, TypeError, ValueError) as exc:
        message = str(exc) if 'muy pequeño' in str(exc) else GENERIC
        raise BoliviaQrError(message) from exc


def size_funding(usdc_units: int, recipient: str) -> dict:
    """The USDT on BSC whose bridged minimum covers `usdc_units` with a small
    cushion, then the Confío-dollar debit that leaves exactly that USDT."""
    target = int((Decimal(usdc_units) * CUSHION).to_integral_value(rounding=ROUND_UP))
    usdt_wei = int(Decimal(target) * USDT_WEI / USDC_UNITS)
    for _ in range(SIZING_ROUNDS):
        expected, minimum = _relay_min_out(usdt_wei, recipient)
        if minimum >= target:
            break
        # Relay's cost is roughly fixed per crossing: add the gap and retry.
        usdt_wei += int(Decimal(target - minimum) * USDT_WEI / USDC_UNITS * Decimal('1.05')) + 10 ** 12
    else:
        raise BoliviaQrError('El monto es muy pequeño para pagarlo. Prueba con un monto mayor.')
    usdt_wei = (usdt_wei // ve_send.WEI_PER_MICRO + 1) * ve_send.WEI_PER_MICRO
    gross = (Decimal(usdt_wei) / USDT_WEI).quantize(ve_send.CENT, rounding=ROUND_UP)
    for _ in range(SIZING_ROUNDS + 2):
        gross_wei, deposit_wei = ve_send.confio_amounts(gross)
        if deposit_wei >= usdt_wei:
            break
        gross += max(((Decimal(usdt_wei - deposit_wei) / USDT_WEI) * Decimal('1.02')).quantize(
            ve_send.CENT, rounding=ROUND_UP), ve_send.CENT)
    else:
        raise BoliviaQrError(GENERIC)
    return {'usdc_units': usdc_units, 'usdt_wei': deposit_wei, 'gross_usd': gross, 'gross_wei': gross_wei,
            'bridge_expected_units': expected, 'bridge_minimum_units': minimum}


# ------------------------------------------------------------------ quote + create

def quote(qr_text: str, amount=None) -> dict:
    preview = decode(qr_text)
    bob = _bob(preview, amount)
    impl = adapter()
    priced = impl.quote_send(bob)
    # Sized against a neutral recipient: the provider's address only exists
    # once the payment is made, and a route's cost does not depend on it.
    sizing = size_funding(int(priced['usdc_units']), '0x' + '1' * 40)
    usdt = Decimal(sizing['usdt_wei']) / USDT_WEI
    return {
        'preview': preview, 'bob_amount': format(bob, '.2f'), 'usd_amount': format(sizing['gross_usd'], 'f'),
        'usdt_amount': format(usdt.quantize(ve_send.MICRO), 'f'),
        'confio_fee_usd': format(max(sizing['gross_usd'] - usdt, Decimal('0')).quantize(ve_send.CENT), 'f'),
        'rate': priced.get('rate') or '', 'usdc_units': str(priced['usdc_units']),
    }


def create(user, account, qr_text: str, amount=None, *, max_usd=None):
    """Price on the server again (never above what the person approved),
    check the provider can pay for this person, reserve, then (per adapter)
    make the provider's payment. Nothing leaves the wallet before the claim."""
    provider = bolivia_qr.provider_name(SEND)
    impl = adapter(provider)
    terms = quote(qr_text, amount)
    preview, bob = terms['preview'], Decimal(terms['bob_amount'])
    gross_usd = Decimal(terms['usd_amount'])
    try:
        approved = Decimal(str(max_usd)) if max_usd not in (None, '') else None
    except Exception:  # noqa: BLE001
        approved = None
    if approved is None or gross_usd > approved:
        raise BoliviaQrError(PRICE_MOVED)
    # Everything the payout needs about this person is checked now, before any
    # money can move (e.g. a document the provider accepts).
    snapshot = impl.preflight_send(user, preview) if hasattr(impl, 'preflight_send') else {}
    gross_wei, deposit_wei = ve_send.confio_amounts(gross_usd)
    created_block = ve_send.current_block()
    if created_block is None:
        raise BoliviaQrError(GENERIC)
    beneficiary = {**preview, 'qr_text': str(qr_text).strip(), 'bob': format(bob, '.2f'), 'sender': snapshot}
    estimate = {'estimated_fiat': format(bob, '.2f'), 'rate': terms['rate'], 'usdc_units': terms['usdc_units']}
    ramp = ve_send.reserve(provider=provider, user=user, account=account, gross_usd=gross_usd,
                           beneficiary=beneficiary, gross_wei=gross_wei, deposit_wei=deposit_wei,
                           created_block=created_block, estimate=estimate)
    if getattr(impl, 'PAYMENT_AT_CREATION', True):
        try:
            payment = impl.create_payment(ramp, qr_text=str(qr_text).strip(), bob=bob,
                                          fixed_amount=bool(preview.get('fixed_amount')))
        except BoliviaQrError as exc:
            ve_send.fail_unfunded(ramp, 'payment_refused')
            raise exc
        except Exception as exc:  # noqa: BLE001 — unfunded: safe to fail, the provider waits for funding
            logger.exception('QR Bolivia payment creation failed for %s', ramp.pk)
            ve_send.fail_unfunded(ramp, 'payment_request_failed')
            raise BoliviaQrError(GENERIC) from exc
        ve_send._update(ramp.pk, provider_payment={**payment, 'environment': impl.environment()})
    return ve_send.prepare(ramp)


# ------------------------------------------------------------------ funding claim

def _payment_expired(payment: dict) -> bool:
    import time
    expires = int(payment.get('expires_at') or 0)
    return bool(expires) and expires - PROVIDER_MARGIN_SECONDS <= int(time.time())


def relay_target(ramp, live: bool) -> dict:
    """The Relay deposit address on BSC for the order's exact USDT, bridging
    to the provider's funding address, checked again at the last moment."""
    from payment_accounts.allbridge_next import NextError
    from payment_accounts.bridge_binding import deposit_call
    from payment_accounts.relay import RelayClient
    if not live:
        # Real dollars only ever fund a production provider order.
        raise BoliviaQrError(NOT_LIVE)
    section = ve_send._section(ramp)
    beneficiary = section.get('beneficiary') or {}
    impl = adapter(ramp.provider)
    payment = section.get('provider_payment')
    # A payment made under other credentials or another environment (e.g.
    # sandbox, before a switch to production) never receives real dollars.
    if payment and payment.get('environment') != impl.environment():
        ve_send.fail_unfunded(ramp, 'provider_environment_changed')
        raise BoliviaQrError(EXPIRED)
    if payment and _payment_expired(payment):
        if getattr(impl, 'PAYMENT_AT_CREATION', True):
            # Made with the order and not remade (it would need a new
            # reference): the person rescans.
            ve_send.fail_unfunded(ramp, 'provider_payment_expired')
            raise BoliviaQrError(EXPIRED)
        payment = None
    if not payment:
        payment = impl.create_payment(ramp, qr_text=beneficiary.get('qr_text', ''),
                                      bob=Decimal(beneficiary.get('bob') or '0'),
                                      fixed_amount=bool(beneficiary.get('fixed_amount')))
        payment = {**payment, 'environment': impl.environment()}
        ve_send._update(ramp.pk, provider_payment=payment)
    if not int(payment.get('expires_at') or 0):
        # Every provider payment carries a deadline; one without is never funded.
        raise BoliviaQrError(EXPIRED)
    recipient = payment['deposit_address']
    needed = int(payment['usdc_units'])
    amount = str(section['deposit_wei'])
    client = RelayClient()
    try:
        route = client.routes(SOURCE, DESTINATION, amount, ramp.actor_address, recipient)[0]
        build = client.build(route, source_address=ramp.actor_address, destination_address=recipient)
        deposit, _ = deposit_call(build, SOURCE, amount)
    except NextError as exc:
        logger.warning('Relay quote failed for QR Bolivia send %s: %s', ramp.pk, exc)
        raise BoliviaQrError(GENERIC) from exc
    if int(build['amountOutMin']) < needed:
        raise BoliviaQrError(PRICE_MOVED)
    # The signing window never outlives the provider's order (with room for
    # the bridge to deliver), nor Relay's deposit address.
    deadline = int(build['relay']['deadline'])
    if payment.get('expires_at'):
        deadline = min(deadline, int(payment['expires_at']) - PROVIDER_MARGIN_SECONDS)
    import time
    if deadline <= int(time.time()) + 60:
        raise BoliviaQrError(EXPIRED)
    return {
        'deposit_address': deposit,
        'binding': {
            'provider': 'relay', 'request_id': build['relay']['request_id'],
            'response': build['relay']['response'], 'deadline': deadline,
            'recipient': recipient.lower(), 'amount_out': build['amountOut'],
            'amount_out_min': build['amountOutMin'], 'needed_units': str(needed),
        },
    }


def settle(ramp) -> 've_send.Settlement':
    """Relay's delivery to the provider's funding address, proven from
    finalized canonical receipts by the audited bridge reconciler."""
    from types import SimpleNamespace
    from payment_accounts.allbridge_next import NextError
    from payment_accounts.relay_settlement import reconcile_relay
    section = ve_send._section(ramp)
    bridge = section.get('bridge') or {}
    if not bridge.get('request_id') or not section.get('funding_tx_hash'):
        return ve_send.Settlement('review', reason='bridge_binding_missing')
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
        return ve_send.Settlement('pending')
    if transfer.status == 'delivered':
        received = int(transfer.actual_out_units)
        needed = int(bridge.get('needed_units') or 0)
        if received < needed:
            return ve_send.Settlement('review', reason='provider_underfunded')
        # What the bridge delivered beyond the payment stays in our balance at
        # the provider; recorded per order so it is always accountable.
        ve_send._update(ramp.pk, provider_surplus_units=str(received - needed))
        usd = Decimal(received) / USDC_UNITS
        return ve_send.Settlement('delivered', credited_usd=format(usd, 'f'), evidence=transfer.destination_tx_hash)
    if transfer.status == 'refunded':
        return ve_send.Settlement('refunded')
    if transfer.status == 'needs_review':
        return ve_send.Settlement('review', reason=transfer.failure_code or 'bridge')
    return ve_send.Settlement('pending')


# ------------------------------------------------------------------ display

def beneficiary_view(beneficiary: dict) -> dict:
    return {
        'holder_name': beneficiary.get('holder_name'), 'bank_name': beneficiary.get('bank_name'),
        'account_last4': beneficiary.get('account_last4'), 'bob': beneficiary.get('bob'),
    }


def active_order(user):
    for provider in bolivia_qr.providers(SEND):
        ramp = ve_send.active_order(user, provider)
        if ramp is not None:
            return ramp
    return None


def owned_order(user, order_id):
    from django.core.exceptions import ValidationError
    from ramps.models import RampTransaction
    try:
        return RampTransaction.objects.filter(
            provider__in=bolivia_qr.providers(SEND), direction=ve_send.DIRECTION, country_code=bolivia_qr.COUNTRY,
            actor_user=user, internal_id=order_id).first()
    except (ValueError, TypeError, ValidationError):
        return None

