"""Recibir con QR Bolivia: the provider-neutral receive core.

One `RampTransaction(direction='on_ramp', destination='cusd_plus',
country_code='BO')` per QR; `provider` names the adapter
(ramps.bolivia_qr.RECEIVE_ADAPTERS). The person never signs anything on
Polygon: the provider pays the converted dollars (USDC on Polygon) to a
Relay deposit address whose recipient is the person's BSC wallet, the Infinia
receive pattern. Phases (metadata.bo_receive.phase):

  qr_ready    the QR exists; waiting for the payer (until it expires)
  paid        the provider confirmed the payment; waiting for its dollars
  delivering  the provider's deposit into the Relay address is found on
              Polygon; Relay is bridging to BSC
  completed   finalized BSC receipts prove USDT reached the person's wallet
  expired     nobody paid before the QR expired
  failed      the provider definitely refused or cancelled it
  review      the outcome cannot be decided automatically (ops checks)

Money that may have moved is never failed: once paid, an order ends
completed or in review.

Adapter contract (module attributes/functions):
  PROVIDER
  ROUTE_AT_CREATION: the Relay deposit address is the QR's destination
    (Mesa de pagos); else it is made once the payment is confirmed (Stereum)
  quote_receive(bob) -> dict (usdc_units, usd_estimate, rate, fee_bob, ...)
  create_receive(ramp, *, bob, usdc_units, deposit_address|None, pay_by) -> dict
    (qr_text and/or qr_image, expires_at ISO, provider_id). `pay_by` is when
    the Relay address stops accepting the deposit (minus the provider's
    settlement time): a QR must not be payable after it.
  receive_status(ramp) -> 'paid' | 'unpaid' (definitively not paid yet) |
    'processing' (paid, provider still working) | 'unknown' (no record) |
    'expired' | 'failed'. Only 'expired', or 'unpaid' well past the QR's
    expiry, ends an order: missing or unfinished records never do.
  deliver(ramp, *, usdc_units, deposit_address) -> dict  (ROUTE_AT_CREATION
    False only: e.g. a per-order BUY paying the Relay address)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from ramps import bolivia_qr
from ramps.bolivia_qr import RECEIVE, BoliviaQrError
from ramps.models import RampTransaction

logger = logging.getLogger(__name__)

SECTION = 'bo_receive'
DIRECTION = RECEIVE
SOURCE, DESTINATION = 'POL:USDC', 'BSC:USDT'
OPEN_STATUSES = ('PENDING', 'PROCESSING')
MICRO = Decimal('0.000001')
# After a payment is confirmed, how long the provider may take to send the
# dollars before ops looks.
DELIVERY_REVIEW_AFTER = timedelta(hours=6)
# Time between a payer's payment and the provider's deposit into Relay.
PROVIDER_SETTLEMENT_SECONDS = 120
MIN_QR_LIFETIME_SECONDS = 180
SETTLEMENT_WINDOW_SECONDS = 2 * 3600
LOG_CHUNK = 2000
GENERIC = 'No pudimos crear tu QR. Intenta de nuevo en unos minutos.'


def adapter(ramp_or_provider):
    provider = getattr(ramp_or_provider, 'provider', ramp_or_provider)
    return bolivia_qr.adapter(RECEIVE, provider)


def _section(ramp: RampTransaction) -> dict:
    return dict((ramp.metadata or {}).get(SECTION) or {})


def _phase(ramp: RampTransaction) -> str:
    return _section(ramp).get('phase') or 'qr_ready'


def _now_iso() -> str:
    return timezone.now().isoformat()


def _parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


def _update(ramp_pk: int, *, require=None, status=None, detail=None, **values) -> RampTransaction | None:
    """Move an order under its row lock; None when `require` rejects it."""
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp_pk)
        if require is not None and not require(current):
            return None
        metadata = dict(current.metadata or {})
        section = dict(metadata.get(SECTION) or {})
        section.update(values)
        metadata[SECTION] = section
        current.metadata = metadata
        fields = ['metadata', 'updated_at']
        if status:
            current.status = status
            fields.append('status')
        if detail is not None:
            current.status_detail = detail
            fields.append('status_detail')
        current.save(update_fields=fields)
        return current


def _receives():
    return RampTransaction.objects.filter(
        provider__in=bolivia_qr.providers(RECEIVE), direction=DIRECTION, country_code=bolivia_qr.COUNTRY)


def active_order(user) -> RampTransaction | None:
    return _receives().filter(actor_user=user, status__in=OPEN_STATUSES).order_by('-created_at').first()


def owned_order(user, order_id) -> RampTransaction | None:
    from django.core.exceptions import ValidationError
    try:
        return _receives().filter(actor_user=user, internal_id=order_id).first()
    except (ValueError, TypeError, ValidationError):
        return None


# ------------------------------------------------------------------ bridge

def _route(recipient: str, usdc_units: int) -> dict:
    """A Relay deposit address on Polygon that bridges exactly `usdc_units`
    USDC to the person's BSC wallet (refunds to the same EVM address)."""
    from payment_accounts.allbridge_next import NextError
    from payment_accounts.bridge_binding import deposit_call
    from payment_accounts.relay import RelayClient
    client = RelayClient()
    try:
        route = client.routes(SOURCE, DESTINATION, str(usdc_units), recipient, recipient)[0]
        build = client.build(route, source_address=recipient, destination_address=recipient)
        deposit, _ = deposit_call(build, SOURCE, str(usdc_units))
    except NextError as exc:
        logger.warning('Relay route failed for a QR Bolivia receive: %s', exc)
        raise BoliviaQrError('El monto es muy pequeño o la red no está disponible. Prueba con otro monto.') from exc
    return {
        'deposit_address': deposit.lower(), 'request_id': build['relay']['request_id'],
        'response': build['relay']['response'], 'deadline': int(build['relay']['deadline']),
        'amount_in': str(usdc_units), 'amount_out': str(build['amountOut']),
        'amount_out_min': str(build['amountOutMin']),
    }


def _polygon_block() -> int | None:
    from payment_accounts import bridge_chain as chain
    try:
        return int(chain.rpc('POL', 'eth_blockNumber', []), 16)
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ create

def quote(bob: Decimal) -> dict:
    if bob <= 0:
        raise BoliviaQrError('Monto no válido.')
    maximum = bolivia_qr.optional_limit('BOLIVIA_QR_RECEIVE_MAX_USD')
    terms = adapter(bolivia_qr.provider_name(RECEIVE)).quote_receive(bob)
    if maximum is not None and Decimal(str(terms.get('usd_estimate') or '0')) > maximum:
        raise BoliviaQrError(f'El monto máximo por QR es ${maximum}.')
    return terms


def create(user, account, bob: Decimal) -> RampTransaction:
    """Price, reserve, then ask the provider for the QR. A failed QR request
    leaves a FAILED order (nothing can be paid into it)."""
    address = (getattr(account, 'bsc_address', '') or '').strip().lower()
    if not address:
        raise BoliviaQrError('Tu billetera aún no está lista. Intenta de nuevo en unos minutos.')
    provider = bolivia_qr.provider_name(RECEIVE)
    impl = adapter(provider)
    terms = quote(bob)
    usdc_units = int(terms['usdc_units'])
    start_block = _polygon_block()
    if start_block is None:
        raise BoliviaQrError(GENERIC)
    with transaction.atomic():
        from users.models import Account
        locked = Account.objects.select_for_update().filter(pk=account.pk, deleted_at__isnull=True).first()
        if not locked or (locked.bsc_address or '').strip().lower() != address:
            raise BoliviaQrError('Tu billetera cambió. Vuelve a intentarlo.')
        if active_order(user):
            raise BoliviaQrError('Ya tienes un QR activo. Úsalo o cancélalo para crear otro.')
        usd = Decimal(str(terms.get('usd_estimate') or '0')).quantize(MICRO, rounding=ROUND_DOWN)
        ramp = RampTransaction(
            provider=provider, direction=DIRECTION, status='PENDING', country_code=bolivia_qr.COUNTRY,
            actor_user=user, actor_type='user',
            actor_display_name=account.display_name or user.get_full_name() or user.username or '',
            actor_address=address, destination='cusd_plus', fiat_currency='BOB', fiat_amount=bob,
            crypto_currency='USDT', crypto_amount_estimated=usd, status_detail='qr_ready')
        ramp.external_id = str(ramp.internal_id)
        ramp.metadata = {SECTION: {
            'phase': 'creating', 'bob': format(bob, 'f'), 'usdc_units': str(usdc_units),
            'terms': {k: str(v) for k, v in terms.items()}, 'polygon_from_block': start_block,
        }}
        ramp.save()
    # Each QR spends its own Confío Face check, like any top-up.
    from security.face_step_up import (
        FACE_STEP_UP_MESSAGE, FACE_STEP_UP_NEXT_STEP, claim_on_ramp_check, release_on_ramp_check,
    )
    claimed, face_claim_id = claim_on_ramp_check(user, consumed_by=f'ramp:on_ramp:{ramp.internal_id}')
    if not claimed:
        _update(ramp.pk, status='FAILED', detail='face_check_unavailable', phase='failed')
        raise BoliviaQrError(FACE_STEP_UP_MESSAGE, FACE_STEP_UP_NEXT_STEP)
    try:
        route = _route(address, usdc_units) if impl.ROUTE_AT_CREATION else None
        pay_by = None
        if route:
            pay_by = datetime.fromtimestamp(int(route['deadline']) - PROVIDER_SETTLEMENT_SECONDS,
                                            tz=timezone.get_current_timezone())
            if (pay_by - timezone.now()).total_seconds() < MIN_QR_LIFETIME_SECONDS:
                raise BoliviaQrError(GENERIC)
        qr = impl.create_receive(ramp, bob=bob, usdc_units=usdc_units,
                                 deposit_address=route['deposit_address'] if route else None, pay_by=pay_by)
        # The app shows (and we enforce) the earlier of the provider's expiry
        # and the bridge's.
        expires = _parse_time(qr.get('expires_at'))
        if pay_by is not None and (expires is None or expires > pay_by):
            qr = {**qr, 'expires_at': pay_by.isoformat()}
    except BoliviaQrError as exc:
        # A definite no: no QR exists, so the Face check is given back.
        _update(ramp.pk, status='FAILED', detail='qr_refused', phase='failed', error=str(exc))
        release_on_ramp_check(face_claim_id)
        raise
    except Exception as exc:  # noqa: BLE001 — a lost answer may still have made a QR nobody sees
        logger.exception('QR Bolivia receive creation failed for %s', ramp.pk)
        _update(ramp.pk, status='FAILED', detail='qr_request_failed', phase='failed')
        raise BoliviaQrError(GENERIC) from exc
    updated = _update(ramp.pk, status='PENDING', detail='qr_ready', phase='qr_ready', route=route,
                      qr_text=qr.get('qr_text') or '', qr_image=qr.get('qr_image') or '',
                      expires_at=qr.get('expires_at') or '', provider_id=qr.get('provider_id') or '')
    if qr.get('provider_id'):
        RampTransaction.objects.filter(pk=ramp.pk).update(provider_order_id=str(qr['provider_id'])[:100])
    return updated


def cancel(ramp: RampTransaction) -> RampTransaction:
    """Hide an unpaid QR. The payer may still pay it until it expires, so the
    order keeps being watched; only an expired, unpaid QR ends."""
    if _phase(ramp) != 'qr_ready':
        raise BoliviaQrError('Este QR ya fue pagado: estamos acreditando tus dólares.')
    return _update(ramp.pk, require=lambda r: _phase(r) == 'qr_ready', cancelled_at=_now_iso()) or ramp


# ------------------------------------------------------------------ sync

def sync(ramp: RampTransaction) -> RampTransaction:
    ramp = RampTransaction.objects.get(pk=ramp.pk)
    if ramp.status not in OPEN_STATUSES:
        return ramp
    phase = _phase(ramp)
    if phase == 'qr_ready':
        ramp = _check_payment(ramp)
        phase = _phase(ramp)
    if phase == 'paid':
        ramp = _find_deposit(ramp)
        phase = _phase(ramp)
    if phase == 'delivering':
        ramp = _settle(ramp)
    return ramp


def _check_payment(ramp: RampTransaction) -> RampTransaction:
    section = _section(ramp)
    try:
        state = adapter(ramp).receive_status(ramp)
    except Exception:  # noqa: BLE001 — a read failure decides nothing
        logger.warning('QR Bolivia receive status failed for %s', ramp.pk, exc_info=True)
        return ramp
    expires = _parse_time(section.get('expires_at'))
    if state == 'paid':
        route = section.get('route')
        if not route:
            # Paid first, routed now (Stereum): the provider sends to a
            # Relay address made for this exact amount.
            try:
                route = _route(ramp.actor_address, int(section['usdc_units']))
                adapter(ramp).deliver(ramp, usdc_units=int(section['usdc_units']),
                                      deposit_address=route['deposit_address'])
            except Exception:  # noqa: BLE001 — paid money: never failed, ops decides
                logger.exception('QR Bolivia delivery request failed for %s', ramp.pk)
                return _review(ramp, 'delivery_request_failed')
        return _update(ramp.pk, require=lambda r: _phase(r) == 'qr_ready', status='PROCESSING',
                       detail='paid', phase='paid', route=route, paid_at=_now_iso()) or ramp
    if state == 'failed':
        return _update(ramp.pk, require=lambda r: _phase(r) == 'qr_ready', status='FAILED',
                       detail='qr_failed', phase='failed') or ramp
    if state == 'expired' or (state == 'unpaid' and expires is not None
                              and timezone.now() > expires + timedelta(minutes=30)):
        # The provider's own expiry, or ours well past it with no payment.
        return _update(ramp.pk, require=lambda r: _phase(r) == 'qr_ready', status='FAILED',
                       detail='qr_expired', phase='expired') or ramp
    return ramp


def _find_deposit(ramp: RampTransaction) -> RampTransaction:
    """The provider's USDC transfer into this order's Relay address (unique
    to the order), from canonical Polygon logs."""
    from payment_accounts import bridge_chain as chain
    section = _section(ramp)
    route = section.get('route') or {}
    deposit = route.get('deposit_address')
    if not deposit:
        return _review(ramp, 'route_missing')
    try:
        finalized = int(chain.rpc('POL', 'eth_getBlockByNumber', ['finalized', False])['number'], 16)
        start = int(section.get('polygon_scanned_to') or section.get('polygon_from_block') or 0)
        found = []
        while start <= finalized and not found:
            end = min(start + LOG_CHUNK - 1, finalized)
            logs = chain.rpc('POL', 'eth_getLogs', [{
                'address': chain.USDC, 'fromBlock': hex(start), 'toBlock': hex(end),
                'topics': [chain.TRANSFER_TOPIC, None, '0x' + deposit[2:].rjust(64, '0')]}])
            found = [log for log in logs or [] if not log.get('removed')]
            if not found:
                start = end + 1
                _update(ramp.pk, polygon_scanned_to=start)
    except Exception:  # noqa: BLE001 — RPC gap: retry next poll
        logger.warning('Polygon deposit scan failed for %s', ramp.pk, exc_info=True)
        return ramp
    if not found:
        paid_at = _parse_time(section.get('paid_at'))
        if paid_at and timezone.now() - paid_at > DELIVERY_REVIEW_AFTER:
            return _review(ramp, 'provider_delivery_late')
        return ramp
    hashes = {log['transactionHash'].lower() for log in found}
    if len(hashes) != 1:
        return _review(ramp, 'several_deposits')
    received = sum(int(log['data'], 16) for log in found)
    if received != int(route.get('amount_in') or 0):
        return _review(ramp, 'deposit_amount_mismatch')
    # A fixed settlement deadline: a stalled bridge escalates to ops instead
    # of waiting forever.
    deadline = max(int(route.get('deadline') or 0), int(timezone.now().timestamp())) + SETTLEMENT_WINDOW_SECONDS
    return _update(ramp.pk, require=lambda r: _phase(r) == 'paid', detail='delivering', phase='delivering',
                   deposit_tx_hash=hashes.pop(), settle_deadline=deadline) or ramp


def _settle(ramp: RampTransaction) -> RampTransaction:
    """Relay's delivery to the person's BSC wallet, proven from finalized
    canonical receipts by the audited bridge reconciler."""
    from types import SimpleNamespace
    from payment_accounts.allbridge_next import NextError
    from payment_accounts.relay import RelayClient
    from payment_accounts.relay_settlement import reconcile_relay
    section = _section(ramp)
    route = section.get('route') or {}
    # The BSC delivery hash, as soon as Relay reports it: the arrival scanner
    # then files the transfer under this order, never as an outside deposit.
    if not section.get('bsc_provider_transfer_tx_hash'):
        try:
            status = RelayClient().status(route['request_id'])
            delivered = [h for h in status.get('txHashes') or [] if isinstance(h, str)]
            if status.get('status') == 'success' and len(delivered) == 1:
                ramp = _update(ramp.pk, bsc_provider_transfer_tx_hash=delivered[0].lower()) or ramp
        except Exception:  # noqa: BLE001
            pass
    view = SimpleNamespace(
        quote=SimpleNamespace(source_token_id=SOURCE, destination_token_id=DESTINATION,
                              amount_units=str(route['amount_in']), source_address=ramp.actor_address.lower(),
                              destination_address=ramp.actor_address.lower()),
        binding={'request_id': route['request_id'], 'response': route['response']},
        # Fixed when the deposit was found (reconcile_relay escalates an hour after).
        deadline=int(section.get('settle_deadline') or route['deadline']),
        source_tx_hash=section['deposit_tx_hash'], deposit_address=route['deposit_address'],
        funding_mode='provider', amount_out_min=route['amount_out_min'], status='bridging', failure_code='',
        actual_out_units=None, destination_tx_hash='')
    try:
        reconcile_relay(view)
    except NextError:
        return ramp
    if view.status == 'delivered':
        usdt = (Decimal(int(view.actual_out_units)) / Decimal(10 ** 18)).quantize(MICRO, rounding=ROUND_DOWN)
        done = _complete(ramp, usdt, view.destination_tx_hash.lower())
        if done is not None:
            try:
                from ramps.bsc_provider_hash import attach_after_provider_sync
                attach_after_provider_sync(RampTransaction.objects.get(pk=ramp.pk))
            except Exception:  # noqa: BLE001
                logger.exception('QR Bolivia arrival attach failed for %s', ramp.pk)
        return RampTransaction.objects.get(pk=ramp.pk)
    if view.status in ('refunded', 'needs_review'):
        return _review(ramp, f'bridge_{view.failure_code or view.status}')
    return ramp


def _complete(ramp: RampTransaction, usdt: Decimal, tx_hash: str) -> RampTransaction | None:
    """One save carries the status AND the proven amounts, so the history
    row written on save shows what arrived, never the estimate."""
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        if _phase(current) != 'delivering':
            return None
        metadata = dict(current.metadata or {})
        section = dict(metadata.get(SECTION) or {})
        section.update(phase='completed', delivered_usdt=format(usdt, 'f'), bsc_provider_transfer_tx_hash=tx_hash)
        metadata[SECTION] = section
        current.metadata = metadata
        current.status, current.status_detail = 'COMPLETED', 'completed'
        current.completed_at = timezone.now()
        current.crypto_amount_actual = usdt
        current.final_currency, current.final_amount = 'USDT', usdt
        current.save(update_fields=['metadata', 'status', 'status_detail', 'completed_at', 'crypto_amount_actual',
                                    'final_currency', 'final_amount', 'updated_at'])
        return current


def _review(ramp: RampTransaction, reason: str) -> RampTransaction:
    detail = f'needs_review:{reason}'
    updated = _update(ramp.pk, status='PROCESSING', detail=detail, phase='review') or ramp
    if reason not in (_section(updated).get('alerted') or {}):
        try:
            from config.ops_alerts import send_ops_alert
            if send_ops_alert(f'⚠️ QR Bolivia (recibir, {ramp.provider}) {ramp.internal_id} requiere revisión: '
                              f'{reason}.', dedupe_key=f'bo_receive:{ramp.pk}:{reason}', dedupe_seconds=86400):
                alerted = dict(_section(updated).get('alerted') or {})
                alerted[reason] = _now_iso()
                updated = _update(ramp.pk, alerted=alerted) or updated
        except Exception:  # noqa: BLE001
            logger.exception('QR Bolivia receive alert failed for %s', ramp.pk)
    return updated


def open_orders():
    return _receives().filter(status__in=OPEN_STATUSES).exclude(**{f'metadata__{SECTION}__phase': 'review'})


# ------------------------------------------------------------------ view

def view(ramp: RampTransaction) -> dict:
    section = _section(ramp)
    terms = section.get('terms') or {}
    phase = _phase(ramp)
    return {
        'order_id': str(ramp.internal_id), 'status': ramp.status, 'phase': phase,
        'bob_amount': section.get('bob'), 'usd_estimate': terms.get('usd_estimate'),
        'usd_received': section.get('delivered_usdt'), 'rate': terms.get('rate'),
        'fee_bob': terms.get('fee_bob'),
        'qr_text': section.get('qr_text') if phase == 'qr_ready' else '',
        'qr_image': section.get('qr_image') if phase == 'qr_ready' else '',
        'expires_at': section.get('expires_at'), 'cancelled': bool(section.get('cancelled_at')),
        'created_at': ramp.created_at.isoformat() if ramp.created_at else None,
    }


def counted_usd(ramp: RampTransaction) -> Decimal:
    try:
        return Decimal(str((_section(ramp).get('terms') or {}).get('usd_estimate') or '0'))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')
