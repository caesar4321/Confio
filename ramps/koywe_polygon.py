"""Koywe's Dollar+ rail through USDC on Polygon while its BSC network is off.

Koywe disabled USDT BSC on 2026-11-04 ("depends on an update our provider is
making on that network"). Every other network kept its currencies, so while
`KOYWE_SAVINGS_NETWORK=POLYGON` the cUSD+ rail settles in USDC on Polygon and
Relay (payment_accounts.relay, the audited bridge client) crosses to BSC:

  on-ramp   Koywe pays the order's USDC to a Relay deposit address on Polygon
            whose recipient is the person's BSC wallet, the QR Bolivia receive
            pattern. Koywe calls that delivered; the order stays PROCESSING
            until finalized BSC receipts prove the USDT arrived.
  off-ramp  the person pays the order's exact USDT to a Relay deposit address
            on BSC whose recipient is Koywe's Polygon deposit address, the Pago
            ASAP send pattern. The app funds `confioDepositAddress` as before;
            Koywe settles whatever USDC the bridge delivers.

Relay's cost (about $0.05 per crossing) comes out of the person's dollars; the
quote shows it. Orders created while the switch is on keep their route after
it is turned off (metadata[SECTION]).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

SECTION = 'koywe_polygon'
CRYPTO_SYMBOL = 'USDC Polygon'
ON_SOURCE, ON_DESTINATION = 'POL:USDC', 'BSC:USDT'
OFF_SOURCE, OFF_DESTINATION = 'BSC:USDT', 'POL:USDC'
MICRO = Decimal('0.000001')
USDC_UNITS = Decimal(10 ** 6)
USDT_UNITS = Decimal(10 ** 18)
LOG_CHUNK = 2000
# After Koywe reports the USDC delivered, how long its transfer may take to
# show on finalized Polygon logs before ops looks.
DELIVERY_REVIEW_AFTER = timedelta(hours=6)
SETTLEMENT_WINDOW_SECONDS = 2 * 3600
ROUTE_UNAVAILABLE = 'Las recargas no están disponibles temporalmente. Inténtalo más tarde.'


class KoywePolygonError(Exception):
    """User-safe Spanish message."""


def enabled() -> bool:
    return str(getattr(settings, 'KOYWE_SAVINGS_NETWORK', 'BSC') or 'BSC').strip().upper() == 'POLYGON'


def crypto_symbol(default: str = 'USDT BSC') -> str:
    return CRYPTO_SYMBOL if enabled() else default


def section(ramp) -> dict:
    return dict(((getattr(ramp, 'metadata', None) or {}).get(SECTION)) or {})


def polygon(ramp) -> bool:
    """Created on the Polygon route (marked before Koywe saw the order), so
    it must never be funded, completed or refunded as a direct BSC order,
    whatever the switch says now."""
    return bool(section(ramp))


def routed(ramp) -> bool:
    return bool(section(ramp).get('deposit_address'))


# ------------------------------------------------------------------ quotes

def bridge_ratio(direction: str, amount: Decimal) -> Decimal:
    """What one dollar entering Relay delivers on the other side, for this
    size, so a quote can show the dollars that actually arrive. Quotes may be
    anonymous, so it is priced with Confío's sponsor address on both ends;
    the order's real route is built at creation."""
    from payment_accounts.allbridge_next import NextError
    from payment_accounts.relay import RelayClient
    source, destination = ((ON_SOURCE, ON_DESTINATION) if direction == 'ON_RAMP'
                           else (OFF_SOURCE, OFF_DESTINATION))
    units_in = _units(amount, source)
    address = str(getattr(settings, 'BSC_SPONSOR_ADDRESS', '') or '')
    try:
        route = RelayClient().routes(source, destination, str(units_in), address, address)[0]
    except NextError as exc:
        logger.warning('Relay pricing failed for a Koywe %s quote: %s', direction, exc)
        raise KoywePolygonError(ROUTE_UNAVAILABLE) from exc
    out = Decimal(int(route['amountOut'])) / _scale(destination)
    return (out / amount) if amount > 0 else Decimal('0')


def adjust_quote(quote: dict, direction: str) -> dict:
    """A Koywe quote in USDC on Polygon, restated as what the person gets:
    USDT on BSC after Relay (on-ramp), or the fiat Koywe pays for the USDC the
    bridge delivers (off-ramp). The asset the person holds never changes."""
    adjusted = dict(quote)
    network_fee = Decimal(str(quote.get('network_fee_amount') or 0))
    rate = Decimal(str(quote.get('exchange_rate') or 0))  # fiat per dollar
    # Relay's cost is a network cost: it joins the quote's network-fee line
    # (in that line's currency) so the lines still add up to what arrives.
    if direction == 'ON_RAMP':
        usdc = Decimal(str(quote['amount_out']))
        usdt = (usdc * bridge_ratio('ON_RAMP', usdc)).quantize(MICRO, rounding=ROUND_DOWN)
        adjusted['amount_out'] = usdt
        adjusted['network_fee_amount'] = (network_fee + (usdc - usdt) * rate).quantize(
            Decimal('0.01'), rounding=ROUND_DOWN)
    else:
        usdt = Decimal(str(quote['amount_in']))
        fiat = Decimal(str(quote['amount_out']))
        ratio = bridge_ratio('OFF_RAMP', usdt)
        adjusted['amount_out'] = (fiat * ratio).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        adjusted['network_fee_amount'] = (network_fee + usdt * (1 - ratio)).quantize(
            MICRO, rounding=ROUND_DOWN)
    adjusted.update(
        token_symbol='USDT BSC', network_symbol='USDT BSC',
        network_display='BNB Smart Chain (BEP-20)',
        asset_note='USDT por BNB Smart Chain (BEP-20), vía Polygon',
    )
    return adjusted


def _scale(token: str) -> Decimal:
    return USDC_UNITS if token == 'POL:USDC' else USDT_UNITS


def _units(amount: Decimal, token: str) -> int:
    return int((Decimal(str(amount)) * _scale(token)).to_integral_value(rounding=ROUND_DOWN))


# ------------------------------------------------------------------ routes

def _build(source: str, destination: str, units: int, sender: str, recipient: str) -> dict:
    from payment_accounts.allbridge_next import NextError
    from payment_accounts.bridge_binding import deposit_call
    from payment_accounts.relay import RelayClient
    client = RelayClient()
    try:
        route = client.routes(source, destination, str(units), sender, recipient)[0]
        build = client.build(route, source_address=sender, destination_address=recipient)
        deposit, _ = deposit_call(build, source, str(units))
    except NextError as exc:
        logger.warning('Relay route failed for a Koywe %s->%s order: %s', source, destination, exc)
        raise KoywePolygonError(
            'El monto es muy pequeño o la red no está disponible. Prueba con otro monto.') from exc
    return {
        'source': source, 'destination': destination,
        'deposit_address': deposit.lower(), 'request_id': build['relay']['request_id'],
        'response': build['relay']['response'], 'deadline': int(build['relay']['deadline']),
        'sender': sender.lower(), 'recipient': recipient.lower(),
        'amount_in': str(units), 'amount_out': str(build['amountOut']),
        'amount_out_min': str(build['amountOutMin']),
    }


def on_ramp_route(recipient_bsc: str, usdc: Decimal) -> dict:
    """A Polygon deposit address that bridges exactly `usdc` to the person's
    BSC wallet; refunds go to the same EVM address on Polygon."""
    route = _build(ON_SOURCE, ON_DESTINATION, _units(usdc, ON_SOURCE), recipient_bsc, recipient_bsc)
    route['polygon_from_block'] = _polygon_block()
    return route


def off_ramp_route(sender_bsc: str, koywe_polygon_address: str, usdt_wei: int) -> dict:
    """A BSC deposit address that bridges the person's exact USDT to Koywe's
    Polygon deposit address for this order; refunds go back to the person."""
    return _build(OFF_SOURCE, OFF_DESTINATION, int(usdt_wei), sender_bsc, koywe_polygon_address)


def _polygon_block() -> int | None:
    from payment_accounts import bridge_chain as chain
    try:
        return int(chain.rpc('POL', 'eth_blockNumber', []), 16)
    except Exception:  # noqa: BLE001
        return None


def mark(ramp, **values) -> None:
    """Merge into this order's Polygon section (creating it)."""
    from ramps.models import RampTransaction
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        metadata = dict(current.metadata or {})
        sec = dict(metadata.get(SECTION) or {})
        sec.setdefault('phase', 'created')
        sec.update(values)
        metadata[SECTION] = sec
        current.metadata = metadata
        current.save(update_fields=['metadata', 'updated_at'])
    ramp.metadata = current.metadata


def save_route(ramp, route: dict) -> None:
    mark(ramp, route=route, deposit_address=route['deposit_address'])


def vouch_off_ramp_deposit(annotated: dict, ramp, deposit_key: str) -> dict:
    """Swap Koywe's Polygon address for this order's Relay deposit on BSC.
    Only when the address the server resolved from Koywe's payload is the one
    the route bridges to: anything else withholds funding."""
    sec = section(ramp)
    route = sec.get('route') or {}
    koywe_address = str(annotated.get(deposit_key) or '').strip().lower()
    if not koywe_address:
        return annotated
    if not route:
        # Polygon order without a route: Koywe's address is on Polygon and
        # must never be paid from BSC.
        annotated.pop(deposit_key, None)
        return annotated
    if int(route.get('deadline') or 0) <= int(timezone.now().timestamp()):
        # The Relay quote behind this address expired unfunded: a new order
        # gets a fresh one.
        annotated.pop(deposit_key, None)
        return annotated
    if koywe_address != route.get('recipient'):
        logger.error('Koywe off-ramp %s deposit address no longer matches its Relay route; refusing',
                     getattr(ramp, 'pk', None))
        annotated.pop(deposit_key, None)
        return annotated
    annotated[deposit_key] = route['deposit_address']
    annotated['confioBridge'] = 'relay:BSC:USDT->POL:USDC'
    return annotated


# ------------------------------------------------------------------ on-ramp settlement

def hold_completion(ramp) -> bool:
    """Koywe's DELIVERED means USDC reached the Relay address, not that the
    person has dollars. True for Polygon on-ramps the bridge has not proven."""
    return (getattr(ramp, 'direction', '') == 'on_ramp' and polygon(ramp)
            and section(ramp).get('phase') != 'completed')


def needs_settlement(ramp) -> bool:
    return (getattr(ramp, 'direction', '') == 'on_ramp' and routed(ramp)
            and section(ramp).get('phase') in ('provider_delivered', 'delivering'))


def _update(ramp_pk: int, *, require=None, status=None, detail=None, **values):
    from ramps.models import RampTransaction
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp_pk)
        if require is not None and not require(current):
            return None
        metadata = dict(current.metadata or {})
        sec = dict(metadata.get(SECTION) or {})
        sec.update(values)
        metadata[SECTION] = sec
        current.metadata = metadata
        fields = ['metadata', 'updated_at']
        if status:
            current.status = status
            fields.append('status')
        if detail:
            current.status_detail = detail
            fields.append('status_detail')
        current.save(update_fields=fields)
        return current


def mark_provider_delivered(ramp) -> None:
    if section(ramp).get('phase') in (None, '', 'created'):
        _update(ramp.pk, phase='provider_delivered', provider_delivered_at=timezone.now().isoformat())


def _review(ramp, reason: str):
    """Money may have moved: never failed, ops decides."""
    # Under the row lock: a settled order never goes back to review.
    updated = _update(ramp.pk, require=lambda r: section(r).get('phase') not in ('completed', 'review'),
                      phase='review', review_reason=reason, status='PROCESSING',
                      detail=f'needs_review:{reason}')
    if updated is None:
        from ramps.models import RampTransaction
        return RampTransaction.objects.get(pk=ramp.pk)
    return _alert_review(updated)


def _alert_review(ramp):
    reason = section(ramp).get('review_reason') or 'unknown'
    return _alert(ramp, f'review_{reason}',
                  f'⚠️ Koywe por Polygon (recarga) {ramp.internal_id} requiere revisión: {reason}.')


def settle(ramp):
    """Advance one routed on-ramp: find Koywe's USDC in the Relay address on
    Polygon, then prove Relay's USDT delivery on BSC. Never raises."""
    phase = section(ramp).get('phase')
    try:
        if phase == 'review':
            return _alert_review(ramp)  # retries an undelivered alert
        if phase == 'provider_delivered':
            ramp = _find_deposit(ramp)
            phase = section(ramp).get('phase')
        if phase == 'delivering':
            ramp = _settle(ramp)
    except Exception:  # noqa: BLE001 — next poll retries
        logger.exception('Koywe Polygon settlement failed for %s', getattr(ramp, 'pk', None))
    return ramp


def _find_deposit(ramp):
    from datetime import datetime
    from payment_accounts import bridge_chain as chain
    sec = section(ramp)
    route = sec.get('route') or {}
    deposit = route.get('deposit_address')
    try:
        finalized = int(chain.rpc('POL', 'eth_getBlockByNumber', ['finalized', False])['number'], 16)
        start = int(sec.get('polygon_scanned_to') or route.get('polygon_from_block') or 0)
        if not start:
            return _review(ramp, 'polygon_start_block_missing')
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
        logger.warning('Polygon deposit scan failed for Koywe ramp %s', ramp.pk, exc_info=True)
        return ramp
    if not found:
        delivered_at = sec.get('provider_delivered_at')
        if delivered_at and timezone.now() - datetime.fromisoformat(delivered_at) > DELIVERY_REVIEW_AFTER:
            return _review(ramp, 'provider_delivery_late')
        return ramp
    hashes = {log['transactionHash'].lower() for log in found}
    if len(hashes) != 1:
        return _review(ramp, 'several_deposits')
    received = sum(int(log['data'], 16) for log in found)
    if received != int(route.get('amount_in') or 0):
        return _review(ramp, 'deposit_amount_mismatch')
    deadline = max(int(route.get('deadline') or 0), int(timezone.now().timestamp())) + SETTLEMENT_WINDOW_SECONDS
    return _update(ramp.pk, require=lambda r: section(r).get('phase') == 'provider_delivered',
                   phase='delivering', deposit_tx_hash=hashes.pop(), settle_deadline=deadline) or ramp


def _settle(ramp):
    from types import SimpleNamespace
    from payment_accounts.allbridge_next import NextError
    from payment_accounts.relay import RelayClient
    from payment_accounts.relay_settlement import reconcile_relay
    sec = section(ramp)
    route = sec.get('route') or {}
    if not sec.get('bsc_provider_transfer_tx_hash'):
        # Recorded as soon as Relay reports it: the BSC arrival scanner then
        # files the transfer under this order, never as an outside deposit.
        try:
            status = RelayClient().status(route['request_id'])
            delivered = [h for h in status.get('txHashes') or [] if isinstance(h, str)]
            if status.get('status') == 'success' and len(delivered) == 1:
                ramp = _record_bsc_hash(ramp.pk, delivered[0].lower()) or ramp
        except Exception:  # noqa: BLE001
            pass
    view = SimpleNamespace(
        quote=SimpleNamespace(source_token_id=ON_SOURCE, destination_token_id=ON_DESTINATION,
                              amount_units=str(route['amount_in']), source_address=route['sender'],
                              destination_address=route['recipient']),
        binding={'request_id': route['request_id'], 'response': route['response']},
        deadline=int(sec.get('settle_deadline') or route['deadline']),
        source_tx_hash=sec['deposit_tx_hash'], deposit_address=route['deposit_address'],
        funding_mode='provider', amount_out_min=route['amount_out_min'], status='bridging', failure_code='',
        actual_out_units=None, destination_tx_hash='')
    try:
        reconcile_relay(view)
    except NextError:
        return ramp
    if view.status == 'delivered':
        usdt = (Decimal(int(view.actual_out_units)) / USDT_UNITS).quantize(MICRO, rounding=ROUND_DOWN)
        done = _complete(ramp, usdt, view.destination_tx_hash.lower())
        if done is not None:
            try:
                from ramps.bsc_provider_hash import attach_after_provider_sync
                attach_after_provider_sync(done)
            except Exception:  # noqa: BLE001
                logger.exception('Koywe Polygon arrival attach failed for %s', ramp.pk)
            return done
        return ramp
    if view.status in ('refunded', 'needs_review'):
        return _review(ramp, f'bridge_{view.failure_code or view.status}')
    return ramp


def _record_bsc_hash(ramp_pk: int, tx_hash: str):
    """Top level, where find_provider_tx_hash looks for Polygon orders."""
    from ramps.models import RampTransaction
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp_pk)
        metadata = dict(current.metadata or {})
        metadata['bsc_provider_transfer_tx_hash'] = tx_hash
        current.metadata = metadata
        current.save(update_fields=['metadata', 'updated_at'])
        return current


def expired_deposit_address(address: str) -> bool:
    """True when `address` is a routed off-ramp's Relay deposit whose quote
    has expired (the sponsor refuses to pay into it)."""
    from ramps.models import RampTransaction
    address = (address or '').lower()
    # Off the switch, the only routes left are in-flight ones whose quotes
    # expire within ten minutes; the sponsor skips the lookup.
    if not address or not enabled():
        return False
    for metadata in RampTransaction.objects.filter(
            provider='koywe', direction='off_ramp',
            metadata__koywe_polygon__deposit_address=address).values_list('metadata', flat=True):
        route = ((metadata or {}).get(SECTION) or {}).get('route') or {}
        if int(route.get('deadline') or 0) <= int(timezone.now().timestamp()):
            return True
    return False


def _alert(ramp, key: str, text: str):
    """Ops alert, recorded only once delivered so a failed send is retried
    on the next pass."""
    if key in (section(ramp).get('alerted') or {}):
        return ramp
    try:
        from config.ops_alerts import send_ops_alert
        sent = send_ops_alert(text, dedupe_key=f'koywe_polygon:{ramp.pk}:{key}', dedupe_seconds=86400)
    except Exception:  # noqa: BLE001
        logger.exception('Koywe Polygon alert failed for %s', ramp.pk)
        return ramp
    if not sent:
        return ramp
    alerted = dict(section(ramp).get('alerted') or {})
    alerted[key] = timezone.now().isoformat()
    return _update(ramp.pk, alerted=alerted) or ramp


def check_off_ramp(ramp):
    """An off-ramp's bridge to Koywe, from Relay's status: a refund or a
    failure means Koywe's order will never be funded, so ops looks (the
    person's USDT goes back to them on BSC). Never raises."""
    from payment_accounts.relay import RelayClient
    sec = section(ramp)
    route = sec.get('route') or {}
    status = sec.get('relay_status')
    if route.get('request_id') and status not in ('success', 'refund', 'failure'):
        try:
            status = str(RelayClient().status(route['request_id']).get('status') or '')
        except Exception:  # noqa: BLE001
            return ramp
        if status != sec.get('relay_status'):
            ramp = _update(ramp.pk, relay_status=status) or ramp
    if status in ('refund', 'failure'):
        ramp = _alert(ramp, f'relay_{status}',
                      f'⚠️ Koywe por Polygon (retiro) {ramp.internal_id}: el bridge de Relay terminó en '
                      f'{status}; Koywe no recibirá los fondos.')
    return ramp


def open_off_ramps():
    """Routed off-ramps whose bridge outcome is unknown or whose alert is
    undelivered, whatever Koywe says about the order. Filtered in Python: a
    missing JSON key is SQL NULL, which exclude() would silently drop."""
    from ramps.models import RampTransaction
    candidates = RampTransaction.objects.filter(
        provider='koywe', direction='off_ramp',
        metadata__koywe_polygon__deposit_address__isnull=False,
        created_at__gte=timezone.now() - timedelta(days=7),
    ).order_by('created_at')
    for ramp in candidates.iterator():
        sec = section(ramp)
        status = sec.get('relay_status')
        if status == 'success':
            continue
        if status in ('refund', 'failure') and f'relay_{status}' in (sec.get('alerted') or {}):
            continue
        yield ramp


def _complete(ramp, usdt: Decimal, tx_hash: str):
    """One save carries the status AND the proven amount, so the history row
    written on save shows what arrived, never Koywe's USDC figure."""
    from ramps.currencies import RAW_USDT_BSC
    from ramps.models import RampTransaction
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        if section(current).get('phase') != 'delivering':
            return None
        metadata = dict(current.metadata or {})
        sec = dict(metadata.get(SECTION) or {})
        sec.update(phase='completed', delivered_usdt=format(usdt, 'f'))
        metadata[SECTION] = sec
        # Top level: find_provider_tx_hash reads it before Koywe's Polygon
        # txHash nested in the provider payloads.
        metadata['bsc_provider_transfer_tx_hash'] = tx_hash
        current.metadata = metadata
        current.status, current.status_detail = 'COMPLETED', 'delivered'
        current.completed_at = current.completed_at or timezone.now()
        current.crypto_amount_actual = usdt
        fields = ['metadata', 'status', 'status_detail', 'completed_at', 'crypto_amount_actual', 'updated_at']
        if current.conversion_id is None:
            current.final_currency, current.final_amount = RAW_USDT_BSC, usdt
            fields += ['final_currency', 'final_amount']
        current.save(update_fields=fields)
        return current
