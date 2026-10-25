"""Venezuelan on-ramp through VEXPay: bolívares in, USDT-BSC to the wallet.

One `RampTransaction(provider='vexpay', direction='on_ramp',
destination='cusd_plus')` per top-up. The pay-in (C2P or Pago Móvil) carries an
`onwardPayout` to the account's BSC address, so VEXPay itself converts the net
VES to USDT and pays it out. The existing BSC arrival scanner attributes the
delivery (VEXPay reports its `txHash`) and auto-converts it into the user's
balance; this module only tracks the provider lifecycle.

Submission phases (metadata.vexpay.phase), each move made under the row lock:

  created     waiting for the user's key (C2P) or bank reference (Pago Móvil)
  submitting  one confirmation is at VEXPay right now; no second one may start
  submitted   VEXPay accepted (or may have accepted) the charge; never again

VEXPay webhooks are delivered once, never retried, so `sync_vexpay_ramp` is
the source of truth and runs from both the webhook and the poller.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone

from ramps import ve_pagomovil
from ramps.models import RampTransaction
from ramps.ve_pagomovil import VePagoMovilError
from ramps.vexpay_client import (
    OnwardPayout,
    VexPayAmbiguousError,
    VexPayClient,
    VexPayError,
)

logger = logging.getLogger(__name__)

PROVIDER = 'vexpay'
NETWORK = 'BEP20'
CENT = Decimal('0.01')
MICRO = Decimal('0.000001')
OPEN_STATUSES = ('PENDING', 'PROCESSING')
# A C2P intent expires at VEXPay after 15 minutes. A Pago Móvil order waits
# for its reference much longer (the user may pay, then come back), but closes
# inside the 14-day window that matches a BSC arrival to its order; a later
# payment is a support case.
C2P_UNPAID_EXPIRY = timedelta(minutes=30)
PAGO_MOVIL_UNPAID_EXPIRY = timedelta(days=10)
# Settled orders are re-read for reversals this long, at most once per hour.
REVERSAL_WATCH = timedelta(days=7)
REVERSAL_CHECK_EVERY = timedelta(hours=1)
# A confirmation that never came back (worker died mid-call) is treated as
# submitted after this long, and reconciled by reference from then on.
STALE_SUBMISSION = timedelta(minutes=5)
ONWARD_IN_FLIGHT = {'pending', 'converting', 'waiting_release', 'sending'}
PAYMENT_DEAD = {'FAILED', 'CANCELED'}
FEE_TERMS_CACHE_KEY = 'vexpay:fee_terms'
RESERVE_LOCK = 'vexpay:onramp:reserve'


class VexPayRampError(VePagoMovilError):
    """User-facing refusal; the message is Spanish copy for the app."""


def enabled() -> bool:
    """New VE top-ups may be made (the product switch, ramps.ve_pagomovil)."""
    return ve_pagomovil.enabled(ve_pagomovil.TOPUP)


def _setting_decimal(name: str, default: str) -> Decimal:
    return ve_pagomovil.setting_decimal(name, default)


def _neutral(fn, value):
    try:
        return fn(value)
    except VePagoMovilError as exc:
        raise VexPayRampError(str(exc)) from exc


def normalize_cedula(value: str) -> str:
    return _neutral(ve_pagomovil.normalize_cedula, value)


def normalize_phone(value: str) -> str:
    """Venezuelan mobile → 58 + 10 digits (VEXPay's C2P format)."""
    return _neutral(ve_pagomovil.normalize_phone, value)


def normalize_bank_code(value) -> int:
    return int(_neutral(ve_pagomovil.normalize_bank, value))


# ------------------------------------------------------------------ pricing

def fee_terms(client: VexPayClient) -> dict:
    """Pay-in fee, conversion spread, minimums and BEP20 payout fee.

    Cached briefly. VEXPay computes the real amounts; nothing here is charged.
    """
    cached = cache.get(FEE_TERMS_CACHE_KEY)
    if cached:
        return cached
    settings_payload = client.conversion_settings()
    networks = client.crypto_networks('USDT')
    balance = client.balance()
    bep20 = next((n for n in networks if n.get('network') == NETWORK), None) or {}
    # The estimate and the minimums assume the pay-in is priced at the same
    # market rate the conversion uses. A BCV-priced account collects fewer
    # bolívares per dollar than it converts, so fail closed on it.
    rate_source = str((client.quote_usd(Decimal('1')) or {}).get('rateSource') or '').upper()
    terms = {
        'payin_fee_percent': str(balance.get('feePercent') or '0'),
        'payin_fee_fixed_usd': str(balance.get('feeFixedUsd') or '0'),
        'spread_percent': str((settings_payload.get('spreadPercent') or {}).get('VES') or '0'),
        'minimum_conversion_usdt': str(settings_payload.get('minimumUsdt') or '0'),
        'payout_fee_usdt': str(bep20.get('payoutFee') or '0'),
        'minimum_payout_usdt': str(bep20.get('minPayout') or '0'),
        # Instructions are shown only when VEXPay can finish the job: VES
        # conversions on, BEP20 payouts on, market-priced pay-ins.
        'payout_available': bool(bep20.get('available') and bep20.get('payoutEnabled', True)
                                 and rate_source == 'MARKET'
                                 and settings_payload.get('enabled') is True
                                 and (settings_payload.get('sourceCurrencies') or {}).get('VES') is True),
        'rate_source': rate_source,
    }
    cache.set(FEE_TERMS_CACHE_KEY, terms, 600)
    return terms


def _fixed_fee(terms: dict) -> Decimal:
    return Decimal(str(terms.get('payin_fee_fixed_usd') or '0'))


def _converted_usdt(usd_amount: Decimal, terms: dict) -> Decimal:
    payin = Decimal(terms['payin_fee_percent']) / 100
    spread = Decimal(terms['spread_percent']) / 100
    return (usd_amount * (1 - payin) - _fixed_fee(terms)) / (1 + spread)


def estimate_usdt(usd_amount: Decimal, terms: dict) -> Decimal:
    """USDT the wallet should receive for a top-up of `usd_amount`."""
    net = _converted_usdt(usd_amount, terms) - Decimal(terms['payout_fee_usdt'])
    return max(net, Decimal('0')).quantize(CENT, rounding=ROUND_DOWN)


def confio_net(usdt: Decimal) -> Decimal:
    """Dollars credited after Confío's mint fee, which the auto-conversion
    charges when the USDT lands. Same preview the Koywe top-up shows."""
    if not getattr(settings, 'CUSD_CONVERSION_FEE_ENABLED', False) or usdt <= 0:
        return usdt
    try:
        from cusd_plus.cusd_vault import WAD, preview_mint_wei
        preview = preview_mint_wei(int((usdt * WAD).to_integral_value(rounding=ROUND_DOWN)))
        return Decimal(preview.net).quantize(CENT, rounding=ROUND_DOWN)
    except Exception as exc:  # noqa: BLE001 — RPC / vault read
        logger.warning('cUSD fee preview failed for a VEXPay estimate', exc_info=True)
        raise VexPayRampError('No pudimos calcular la comisión de Confío.') from exc


def provider_minimum_usd(terms: dict) -> Decimal:
    """Smallest top-up that clears VEXPay's conversion AND payout minimums.
    Below it VEXPay would collect the bolívares and then hold them."""
    payin = Decimal(terms['payin_fee_percent']) / 100
    spread = Decimal(terms['spread_percent']) / 100
    needed = max(Decimal(terms['minimum_conversion_usdt']),
                 Decimal(terms['minimum_payout_usdt']) + Decimal(terms['payout_fee_usdt']))
    if payin >= 1:
        return Decimal('Infinity')
    usd = (needed * (1 + spread) + _fixed_fee(terms)) / (1 - payin)
    return Decimal(math.ceil(usd * 100)) / 100


def check_provider_minimums(usd_amount: Decimal, terms: dict) -> None:
    minimum = provider_minimum_usd(terms)
    if usd_amount < minimum:
        raise VexPayRampError(f'El monto mínimo para esta recarga es ${minimum}.')


# ------------------------------------------------------------------ limits

def counted_usd(ramp: RampTransaction) -> Decimal:
    """What an order uses of the limits: the larger of what was requested and
    what was actually paid (Pago Móvil credits overpayments in full)."""
    section = (ramp.metadata or {}).get('vexpay', {})
    values = []
    for key in ('usd_amount', 'paid_usd'):
        try:
            values.append(Decimal(str(section.get(key) or '0')))
        except (InvalidOperation, TypeError, ValueError):
            pass
    return max(values or [Decimal('0')])


def check_limits(user, usd_amount: Decimal) -> None:
    # No caps by default: the quote shows what a small top-up nets, VEXPay's
    # own minimums are checked separately, and the payer's bank enforces its
    # Pago Móvil limit. The settings stay as an emergency lever.
    minimum = ve_pagomovil.optional_limit('VE_PAGOMOVIL_TOPUP_MIN_USD')
    maximum = ve_pagomovil.optional_limit('VE_PAGOMOVIL_TOPUP_MAX_USD')
    if minimum is not None and usd_amount < minimum:
        raise VexPayRampError(f'El monto mínimo es ${minimum}.')
    if maximum is not None and usd_amount > maximum:
        raise VexPayRampError(f'El monto máximo por recarga es ${maximum}.')
    user_cap = ve_pagomovil.optional_limit('VE_PAGOMOVIL_TOPUP_USER_DAILY_USD')
    global_cap = ve_pagomovil.optional_limit('VE_PAGOMOVIL_TOPUP_GLOBAL_DAILY_USD')
    if user_cap is None and global_cap is None:
        return
    from django.db.models import Q
    since = timezone.now() - timedelta(hours=24)
    # By when money can move, not when the order was made: an open order
    # (payable for days) is an outstanding reservation, and an older order
    # paid today counts today.
    recent = list(RampTransaction.objects.filter(provider=PROVIDER, direction='on_ramp').filter(
        Q(created_at__gte=since) | Q(status__in=OPEN_STATUSES) | Q(completed_at__gte=since),
    ).exclude(status='FAILED'))
    user_total = sum((counted_usd(r) for r in recent if r.actor_user_id == user.pk), Decimal('0'))
    if user_cap is not None and user_total + usd_amount > user_cap:
        raise VexPayRampError('Alcanzaste el límite diario de recargas en bolívares. Intenta mañana.')
    global_total = sum((counted_usd(r) for r in recent), Decimal('0'))
    if global_cap is not None and global_total + usd_amount > global_cap:
        raise VexPayRampError('Las recargas en bolívares alcanzaron su cupo de hoy. Intenta más tarde.')


def _lock_reservations() -> None:
    """Serialize every reservation (Postgres advisory lock, released at
    transaction end) so concurrent orders cannot all pass the same remaining
    daily allowance."""
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [RESERVE_LOCK])


# ------------------------------------------------------------------ state

def _onward(ramp: RampTransaction) -> OnwardPayout:
    return OnwardPayout(network=NETWORK, address=ramp.actor_address)


def _section(ramp: RampTransaction) -> dict:
    return dict((ramp.metadata or {}).get('vexpay') or {})


def _phase(ramp: RampTransaction) -> str:
    return _section(ramp).get('phase') or 'created'


def can_confirm(ramp: RampTransaction) -> bool:
    return ramp.status == 'PENDING' and _phase(ramp) == 'created'


def _update(ramp_pk: int, *, require=None, status=None, detail=None, **values) -> RampTransaction | None:
    """Merge into metadata.vexpay under the row lock, never from a stale copy.
    `require(current) -> bool` gates the write; None when it refuses."""
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp_pk)
        if require is not None and not require(current):
            return None
        metadata = dict(current.metadata or {})
        section = dict(metadata.get('vexpay') or {})
        section.update(values)
        metadata['vexpay'] = section
        current.metadata = metadata
        fields = ['metadata', 'updated_at']
        if status is not None:
            current.status = status
            fields.append('status')
        if detail is not None:
            current.status_detail = detail[:500]
            fields.append('status_detail')
        current.save(update_fields=fields)
        return current


@transaction.atomic
def reserve_on_ramp(*, user, account, usd_amount: Decimal, method: str, payer: dict,
                    terms: dict) -> RampTransaction:
    """Persist the order before any provider call, under the Account lock the
    wallet re-enrollment gate uses (an in-flight top-up blocks replacing the
    BSC address it pays) and the reservation lock the limits need."""
    from users.models import Account

    _lock_reservations()
    locked = Account.objects.select_for_update().filter(pk=account.pk, deleted_at__isnull=True).first()
    address = (getattr(locked, 'bsc_address', '') or '').strip()
    if not locked or not address or address.lower() != (account.bsc_address or '').lower():
        raise VexPayRampError('Tu billetera cambió. Vuelve a intentarlo.')
    if RampTransaction.objects.filter(
        provider=PROVIDER, direction='on_ramp', actor_user=user, status='PENDING',
    ).exists():
        raise VexPayRampError('Ya tienes una recarga en bolívares pendiente. Termínala o cancélala.')
    check_limits(user, usd_amount)
    ramp = RampTransaction(
        provider=PROVIDER,
        direction='on_ramp',
        status='PENDING',
        country_code='VE',
        actor_user=user,
        actor_type='user',
        actor_display_name=account.display_name or user.get_full_name() or user.username or '',
        actor_address=address,
        destination='cusd_plus',
        fiat_currency='VES',
        crypto_currency='USDT',
        # Gross USDT VEXPay sends: what the BSC arrival is matched against.
        crypto_amount_estimated=estimate_usdt(usd_amount, terms),
        final_currency='USDT BSC',
        status_detail='awaiting_payment',
    )
    ramp.external_id = str(ramp.internal_id)
    ramp.metadata = {'vexpay': {
        'method': method,
        # Not confirmable until the Face claim and the provider preparation
        # succeed (mark_prepared); a failed preparation can then never race
        # an in-flight confirmation.
        'phase': 'preparing',
        'attempt': 0,
        'usd_amount': format(usd_amount, 'f'),
        'payer': payer,
        'fee_terms': terms,
        'network': NETWORK,
        # What the user is shown: after Confío's conversion fee.
        'estimated_net': format(confio_net(estimate_usdt(usd_amount, terms)), 'f'),
    }}
    ramp.save()
    return ramp


SUBMISSION_CLOCK_SKEW = timedelta(seconds=5)


def _predates_submission(payment: dict, section: dict) -> bool:
    """True when VEXPay created this payment before our current submission
    started (so it belongs to an earlier attempt). Unknown times are not
    treated as stale."""
    # The latest outbound request, not the claim: a submission can send
    # several (inline retries, replays) and only the last one is unresolved.
    started = section.get('last_request_at') or section.get('submitting_since')
    created = payment.get('createdAt')
    if not started or not created:
        return False
    try:
        started_at = datetime.fromisoformat(str(started))
        created_at = datetime.fromisoformat(str(created).replace('Z', '+00:00'))
    except ValueError:
        return False
    return created_at < started_at - SUBMISSION_CLOCK_SKEW


def mark_prepared(ramp: RampTransaction) -> RampTransaction | None:
    return _update(ramp.pk, require=lambda c: c.status == 'PENDING' and _phase(c) == 'preparing',
                   phase='created')


def fail_preparation(ramp: RampTransaction, detail: str) -> RampTransaction:
    return _record_failure(ramp, detail, require=lambda c: _phase(c) == 'preparing')


def apply_payment(ramp: RampTransaction, payment: dict, *, direct: bool = False) -> RampTransaction:
    """Fold a VEXPay payment object (GET /v1/payments/:id or a confirmation
    response) into the order. Monotonic: a final order never reopens.
    `direct`: the payment is the answer to our own request just sent."""
    alerts = []
    ramp = RampTransaction.objects.get(pk=ramp.pk)
    if ramp.status == 'COMPLETED':
        return _apply_to_completed(ramp, payment)
    if ramp.status == 'FAILED':
        return ramp
    with transaction.atomic():
        ramp = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        if ramp.status in ('COMPLETED', 'FAILED'):
            return ramp
        status = str(payment.get('status') or '').upper()
        onward = payment.get('onwardPayout') or {}
        onward_status = str(onward.get('status') or '').lower()
        metadata = dict(ramp.metadata or {})
        section = dict(metadata.get('vexpay') or {})
        section.update(
            payment_id=section.get('accepted_payment_id') or payment.get('paymentId') or section.get('payment_id') or '',
            payment_status=status,
            onward=onward,
            bank_reference=payment.get('bankReference') or section.get('bank_reference') or '',
        )
        if section.get('method') == 'c2p' and not section.get('intent_id') and payment.get('paymentId'):
            # A lost c2p/request response: VEXPay's intent id is the payment id.
            section['intent_id'] = payment.get('intentId') or payment['paymentId']
            if section.get('phase') == 'preparing':
                # Only start_c2p (after the Face claim) creates an intent, so a
                # recovered one is ready for the user's key.
                section['phase'] = 'created'
        metadata['provider_payload_latest'] = payment
        if section.get('method') != 'pago_movil':
            # A C2P intent is one payment from the start. A Pago Móvil order
            # pins only its accepted attempt (below), never a failed try.
            ramp.provider_order_id = ramp.provider_order_id or str(payment.get('paymentId') or '')
        if payment.get('vesAmount') is not None:
            ramp.fiat_amount = Decimal(str(payment['vesAmount']))
        previous_detail = ramp.status_detail

        if status == 'COMPLETED' and payment.get('usdAmount') is not None:
            section['paid_usd'] = str(payment['usdAmount'])
            maximum = ve_pagomovil.optional_limit('VE_PAGOMOVIL_TOPUP_MAX_USD')
            if maximum is not None and Decimal(str(payment['usdAmount'])) > maximum \
                    and not section.get('over_limit_alerted'):
                # Pago Móvil credits an overpayment in full and its onward
                # payout follows automatically; flag it, it still counts in limits.
                section['over_limit_alerted'] = True
                alerts.append(f"pagó ${payment['usdAmount']} (máximo ${maximum})")

        retryable = (section.get('method') == 'pago_movil' and status == 'FAILED'
                     and str(payment.get('failureCode') or '').upper() in RETRYABLE_VERIFY_CODES)
        pid = str(payment.get('paymentId') or '')
        accepted = section.get('accepted_payment_id')
        pago_movil = section.get('method') == 'pago_movil'
        # Any failed Pago Móvil try (bank rejections too, not only the
        # claimable codes) is one attempt among several: it never closes an
        # order another attempt superseded.
        failed_try = pago_movil and status in PAYMENT_DEAD
        if failed_try and accepted and pid != accepted:
            # A superseded failed try: a later verification was accepted.
            return ramp
        if failed_try and (_predates_submission(payment, section)
                           or pid in (section.get('known_failed_ids') or [])):
            # A failure of an earlier attempt, read while (or before) the
            # current one was submitted: it says nothing about this attempt.
            return ramp
        if retryable and accepted and pid == accepted:
            # The pinned attempt itself turned out unmatched: follow the
            # latest try by reference again.
            section.pop('accepted_payment_id', None)
            ramp.provider_order_id = ''
        accept_states = ('COMPLETED', 'REVERSED') if pago_movil else ('PENDING', 'COMPLETED', 'REVERSED')
        if pid and status in accept_states:
            # The accepted attempt is the one every later read must follow.
            section['accepted_payment_id'] = pid
            section['payment_id'] = pid
            ramp.provider_order_id = pid
        elif pid and not section.get('accepted_payment_id'):
            section['last_try_payment_id'] = pid
        in_doubt = section.get('phase') in ('submitting', 'submitted')
        if (failed_try and in_doubt and not direct
                and not (section.get('accepted_payment_id') and pid == section.get('accepted_payment_id'))):
            # A looked-up failed try while a submission's outcome is unknown:
            # no lookup proves which request it answers (times are close and
            # rejections may carry no id). Never close or reopen from it; the
            # bounded replay's own answer decides, else ops review.
            if pid:
                section['known_failed_ids'] = (list(section.get('known_failed_ids') or []) + [pid])[-20:]
        elif retryable:
            # VEXPay records an unmatched verification as FAILED, but the
            # transfer stays claimable. A looked-up failure reopens only an
            # order whose submission outcome is NOT in doubt; a submitted
            # (ambiguous) one is resolved by a replay's own direct answer.
            if pid:
                section['known_failed_ids'] = (list(section.get('known_failed_ids') or []) + [pid])[-20:]
            if section.get('phase') not in ('submitting', 'submitted'):
                section['phase'] = 'created'
                ramp.status = 'PENDING'
                ramp.status_detail = f"verify_{str(payment.get('failureCode')).lower()}"
        elif status in PAYMENT_DEAD:
            ramp.status = 'FAILED'
            ramp.status_detail = f"payment_{status.lower()}:{payment.get('failureCode') or payment.get('cancelReason') or ''}"
        elif status == 'REVERSED':
            if onward_status == 'completed':
                # USDT already left; the bolívares came back to the payer.
                # Keep the delivery, surface it for manual recovery.
                ramp.status_detail = 'needs_review:reversed_after_payout'
            else:
                ramp.status = 'FAILED'
                ramp.status_detail = 'payment_reversed'
        elif status == 'PENDING':
            if section.get('phase') == 'submitting':
                # The confirmation call itself decides; a poll racing it must
                # neither close nor reopen the order.
                pass
            elif section.get('phase') == 'submitted':
                # The charge was sent; the bank confirms it later. Never offer
                # another confirmation for it.
                section['phase'] = 'submitted'
                ramp.status = 'PROCESSING'
                ramp.status_detail = 'bank_confirming'
            else:
                ramp.status_detail = 'awaiting_payment'
        elif status == 'COMPLETED':
            section['phase'] = 'submitted'
            if onward_status == 'completed':
                ramp.status = 'COMPLETED'
                ramp.status_detail = 'delivered'
                ramp.completed_at = ramp.completed_at or timezone.now()
                try:
                    ramp.crypto_amount_actual = Decimal(str(onward.get('amountUsdt'))).quantize(MICRO)
                except (InvalidOperation, TypeError, ValueError):
                    pass
            elif onward_status in ONWARD_IN_FLIGHT or not onward_status:
                ramp.status = 'PROCESSING'
                ramp.status_detail = f'onward_{onward_status or "pending"}'
            else:
                # held / failed / canceled: the user paid, the USDT (or VES)
                # is parked in Confío's VEXPay balance. Never show the user a
                # failure for money that exists; ops resolve it.
                ramp.status = 'PROCESSING'
                ramp.status_detail = f"needs_review:onward_{onward_status}:{onward.get('reason') or ''}"
        metadata['vexpay'] = section
        ramp.metadata = metadata
        ramp.save()

    if ramp.status_detail.startswith('needs_review') and ramp.status_detail != previous_detail:
        alerts.append(ramp.status_detail)
    for reason in alerts:
        _alert(ramp, reason)
    if ramp.status == 'COMPLETED':
        _attach_arrival(ramp)
    return ramp


def _apply_to_completed(ramp: RampTransaction, payment: dict) -> RampTransaction:
    """A completed order keeps its status but still takes new evidence (a
    late txHash) and surfaces a reversal of the bolívares after the USDT left."""
    reversed_now = False
    with transaction.atomic():
        ramp = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        metadata = dict(ramp.metadata or {})
        section = dict(metadata.get('vexpay') or {})
        status = str(payment.get('status') or '').upper()
        onward = payment.get('onwardPayout') or {}
        if onward:
            section['onward'] = onward
        section['payment_status'] = status or section.get('payment_status', '')
        section['reversal_checked_at'] = timezone.now().isoformat()
        metadata['vexpay'] = section
        metadata['provider_payload_latest'] = payment
        ramp.metadata = metadata
        fields = ['metadata', 'updated_at']
        if status == 'REVERSED' and not ramp.status_detail.startswith('needs_review'):
            ramp.status_detail = 'needs_review:reversed_after_payout'
            fields.append('status_detail')
            reversed_now = True
        ramp.save(update_fields=fields)
    if reversed_now:
        _alert(ramp, ramp.status_detail)
    _attach_arrival(ramp)
    return ramp


def _attach_arrival(ramp: RampTransaction) -> None:
    """VEXPay may report the delivery hash after the scanner saw the transfer:
    prove the arrival from the hash and link the conversion. Idempotent; the
    poller keeps calling it until the proof exists."""
    from ramps.bsc_provider_hash import attach_after_provider_sync
    attach_after_provider_sync(ramp)


def _alert(ramp: RampTransaction, reason: str) -> None:
    """Tell ops; remember a delivered alert so a failed one is retried by the
    next poll (ensure_alerted) instead of being lost with the transition."""
    try:
        from config.ops_alerts import send_ops_alert
        sent = send_ops_alert(
            f'⚠️ VEXPay recarga {ramp.internal_id} requiere revisión: {reason} '
            f'(pago {ramp.provider_order_id or "?"}).',
            dedupe_key=f'vexpay:{ramp.pk}:{reason}', dedupe_seconds=86400,
        )
    except Exception:  # noqa: BLE001 — alerting never breaks reconciliation
        logger.exception('VEXPay review alert failed for ramp %s', ramp.pk)
        sent = False
    if sent:
        alerted = dict(_section(RampTransaction.objects.get(pk=ramp.pk)).get('alerted') or {})
        alerted[reason] = timezone.now().isoformat()
        _update(ramp.pk, alerted=alerted)


def ensure_alerted(ramp: RampTransaction) -> None:
    """Re-send a needs_review alert that has not been delivered yet."""
    detail = ramp.status_detail or ''
    if detail.startswith('needs_review') and detail not in (_section(ramp).get('alerted') or {}):
        _alert(ramp, detail)


def _record_failure(ramp: RampTransaction, detail: str, *, require=None) -> RampTransaction:
    def allowed(current):
        return current.status == 'PENDING' and (require is None or require(current))
    updated = _update(ramp.pk, require=allowed, status='FAILED', detail=detail)
    return updated or RampTransaction.objects.get(pk=ramp.pk)


def _mark_ambiguous(ramp: RampTransaction, detail: str) -> RampTransaction:
    """The charge may have happened: stop accepting confirmations and let the
    reconciler find it by reference. Only from PENDING — a webhook may have
    already finished the order while the call was hanging."""
    updated = _update(ramp.pk, require=lambda c: c.status == 'PENDING',
                      status='PROCESSING', detail=detail, phase='submitted')
    return updated or RampTransaction.objects.get(pk=ramp.pk)


def _claim(ramp: RampTransaction, method: str, **values) -> RampTransaction:
    """Atomically take the single right to submit a confirmation, saving with
    it everything a later replay needs (e.g. the bank reference)."""
    def free(current):
        return (current.status == 'PENDING' and _section(current).get('method') == method
                and (_section(current).get('phase') or 'created') == 'created')
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        if not free(current):
            raise VexPayRampError('Esta recarga ya se está confirmando o ya no acepta datos.')
        # Read the counter under the lock: every attempt gets its own number
        # and so its own idempotency keys.
        attempt = int(_section(current).get('attempt') or 0) + 1
        metadata = dict(current.metadata or {})
        section = dict(metadata.get('vexpay') or {})
        section.update(phase='submitting', attempt=attempt,
                       submitting_since=timezone.now().isoformat(), **values)
        metadata['vexpay'] = section
        current.metadata = metadata
        current.save(update_fields=['metadata', 'updated_at'])
        return current


def _release(ramp: RampTransaction) -> None:
    """A definite rejection: the user may correct the data and try again."""
    _update(ramp.pk, require=lambda c: c.status == 'PENDING' and _phase(c) == 'submitting', phase='created')


def _submitted(ramp: RampTransaction) -> None:
    _update(ramp.pk, require=lambda c: c.status in OPEN_STATUSES, phase='submitted')


# ------------------------------------------------------------------ flows

def start_c2p(ramp: RampTransaction, client: VexPayClient) -> dict:
    payer = _section(ramp).get('payer') or {}
    try:
        payment = client.c2p_request(
            usd_amount=Decimal(_section(ramp)['usd_amount']), debtor_id=payer['cedula'],
            debtor_phone=payer['phone'], debtor_bank_code=payer['bank_code'],
            external_ref=ramp.external_id, onward=_onward(ramp),
            idempotency_key=f'{ramp.external_id}:c2p-request',
        )
    except VexPayAmbiguousError:
        # The intent may exist; keep the order (and the Face claim) and let
        # the reconciler find it by reference.
        _update(ramp.pk, require=lambda c: c.status == 'PENDING', detail='c2p_request_ambiguous')
        raise VexPayRampError('El banco no respondió a tiempo. Revisa si recibiste un SMS y vuelve a abrir esta recarga.')
    except VexPayError as exc:
        _record_failure(ramp, f'c2p_request_failed:{exc.code or exc.status}')
        raise VexPayRampError(bank_message(exc))
    _update(ramp.pk, intent_id=payment.get('intentId') or '', otp_requested=bool(payment.get('otpRequested')))
    apply_payment(ramp, payment, direct=True)
    return payment


def execute_c2p(ramp: RampTransaction, token: str, client: VexPayClient) -> RampTransaction:
    token = re.sub(r'\D', '', str(token or ''))
    if not 6 <= len(token) <= 8:
        raise VexPayRampError('La clave debe tener entre 6 y 8 dígitos.')
    if not _section(ramp).get('intent_id'):
        raise VexPayRampError('Esta recarga ya no acepta una clave.')
    ramp = _claim(ramp, 'c2p')
    section = _section(ramp)
    payer = section.get('payer') or {}
    try:
        payment = client.c2p_execute(
            intent_id=section['intent_id'], token=token, debtor_id=payer['cedula'],
            debtor_phone=payer['phone'], debtor_bank_code=payer['bank_code'],
            external_ref=ramp.external_id, onward=_onward(ramp),
            idempotency_key=f"{ramp.external_id}:c2p-execute:{section['attempt']}",
        )
    except VexPayAmbiguousError:
        # The bank may have debited. Never ask for a second key; the poller
        # resolves the payment by reference.
        return _mark_ambiguous(ramp, 'c2p_execute_ambiguous')
    except VexPayError as exc:
        if exc.status and 400 <= exc.status < 500:
            _release(ramp)
            # A failed charge usually closes the intent; re-read it so the
            # order shows the real outcome instead of waiting for another key.
            try:
                sync_vexpay_ramp(ramp, client)
            except VexPayError:
                pass
            raise VexPayRampError(bank_message(exc))
        return _mark_ambiguous(ramp, 'c2p_execute_ambiguous')
    _submitted(ramp)
    return apply_payment(ramp, payment, direct=True)


def bank_message(exc: VexPayError) -> str:
    """The bank's own Spanish reason without VEXPay's code prefix
    ('ECBG14Es posible…' → 'Es posible…', 'ECBG56000000Tarjeta…' → 'Tarjeta…')."""
    text = re.sub(r'^[A-Z]{2,8}\d+', '', str(exc or '').strip()).strip()
    # Only the bank's own words: our client's transport/HTTP texts name the
    # provider, which users must never see.
    if not text or len(text) > 200 or 'vexpay' in text.lower() or 'http' in text.lower():
        return 'El banco no pudo procesar el pago. Verifica tus datos e intenta de nuevo.'
    return f'El banco respondió: {text}'


# Pago Móvil verification outcomes VEXPay documents as claimable: the bank's
# notification can lag a genuine transfer, and an amount can be corrected.
RETRYABLE_VERIFY_CODES = {'MOVEMENT_NOT_FOUND', 'AMOUNT_MISMATCH'}
VERIFY_INLINE_TRIES = 3
VERIFY_INLINE_WAIT_S = 4


def _verify_code(exc: VexPayError) -> str:
    payload = exc.payload if isinstance(exc.payload, dict) else {}
    for value in (payload.get('failureCode'), payload.get('error'), payload.get('code'), exc.code):
        if value and str(value).upper() in RETRYABLE_VERIFY_CODES:
            return str(value).upper()
    text = str(exc).upper()
    return next((code for code in RETRYABLE_VERIFY_CODES if code in text), '')


def _bank_today():
    """Today in Venezuela, the date the bank stamps on a Pago Móvil."""
    from zoneinfo import ZoneInfo
    return timezone.now().astimezone(ZoneInfo('America/Caracas')).date()


def parse_payment_date(value) -> str:
    """The absolute YYYY-MM-DD of the transfer (empty = today in Venezuela),
    stored with the claim so a replay the next day still searches the right
    day. Never in the future, never before the order window."""
    value = str(value or '').strip()
    today = _bank_today()
    if not value:
        return today.isoformat()
    try:
        day = datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        raise VexPayRampError('La fecha del pago no es válida.')
    # One day of slack for a device ahead of Caracas time.
    if day > today + timedelta(days=1) or day < today - PAGO_MOVIL_UNPAID_EXPIRY:
        raise VexPayRampError('La fecha del pago no es válida.')
    return min(day, today).isoformat()


def _call_verify(ramp: RampTransaction, section: dict, usd_amount: Decimal, client: VexPayClient,
                 key: str) -> dict:
    # Stamp every outbound request before it leaves: a failure VEXPay created
    # before this moment belongs to an earlier request.
    _update(ramp.pk, last_request_at=timezone.now().isoformat())
    payer = section.get('payer') or {}
    phone = payer.get('phone', '')
    return client.pago_movil_verify(
        usd_amount=usd_amount, reference=section['reference'], external_ref=ramp.external_id,
        onward=_onward(ramp), debtor_bank_code=str(payer.get('bank_code') or '').zfill(4),
        debtor_phone=f'0{phone[2:]}' if phone.startswith('58') else phone,
        date_movement=section.get('date_movement') or '', idempotency_key=key,
    )


def verify_pago_movil(ramp: RampTransaction, reference: str, client: VexPayClient,
                      payment_date: str = '', *, wait=None) -> RampTransaction:
    reference = re.sub(r'\D', '', str(reference or ''))
    if not 4 <= len(reference) <= 32:
        raise VexPayRampError('Escribe la referencia del Pago Móvil (al menos los últimos 6 dígitos).')
    date_movement = parse_payment_date(payment_date)
    ramp = _claim(ramp, 'pago_movil', reference=reference, date_movement=date_movement)
    section = _section(ramp)
    try:
        usd_amount = verify_usd_amount(section, client)
    except VexPayError:
        # Nothing was sent yet: the user can simply try again.
        _release(ramp)
        raise VexPayRampError('No pudimos consultar la tasa. Intenta de nuevo en unos segundos.')
    _update(ramp.pk, verify_usd_amount=format(usd_amount, 'f'))
    if wait is None:
        import time
        wait = time.sleep
    for inline in range(1, VERIFY_INLINE_TRIES + 1):
        try:
            # A fresh key per try: VEXPay replays a cached answer for a key.
            payment = _call_verify(ramp, section, usd_amount, client,
                                   f"{ramp.external_id}:verify:{section['attempt']}:{inline}")
            break
        except VexPayAmbiguousError:
            _mark_ambiguous(ramp, 'pago_movil_verify_ambiguous')
            raise VexPayRampError('Estamos confirmando tu pago. No pagues de nuevo; revisa el estado en unos segundos.')
        except VexPayError as exc:
            if not (exc.status and 400 <= exc.status < 500):
                _mark_ambiguous(ramp, 'pago_movil_verify_ambiguous')
                raise VexPayRampError('Estamos confirmando tu pago. No pagues de nuevo; revisa el estado en unos segundos.')
            code = _verify_code(exc)
            failed_id = str((exc.payload or {}).get('paymentId') or '') if isinstance(exc.payload, dict) else ''
            if failed_id:
                known = list(_section(RampTransaction.objects.get(pk=ramp.pk)).get('known_failed_ids') or [])
                _update(ramp.pk, known_failed_ids=(known + [failed_id])[-20:])
            if code == 'MOVEMENT_NOT_FOUND' and inline < VERIFY_INLINE_TRIES:
                wait(VERIFY_INLINE_WAIT_S)  # the bank's notice can lag a real transfer
                continue
            _release(ramp)
            if code == 'AMOUNT_MISMATCH':
                raise VexPayRampError('El monto recibido no coincide con el que te indicamos. Revisa el monto que enviaste.')
            if code == 'MOVEMENT_NOT_FOUND' or exc.status == 404:
                raise VexPayRampError('Todavía no vemos tu pago. Revisa la referencia y la fecha, y vuelve a intentarlo en un minuto.')
            raise VexPayRampError('No pudimos confirmar el pago con esos datos. Revisa la referencia.')
    _submitted(ramp)
    return apply_payment(ramp, payment, direct=True)


def verify_usd_amount(section: dict, client: VexPayClient) -> Decimal:
    """VEXPay verifies a dollar amount at today's rate, but the user paid the
    bolívares we showed them, possibly days ago. Ask for exactly those
    bolívares at the current rate (rounded down, so an exact transfer always
    matches; VEXPay credits any excess)."""
    expected_ves = section.get('expected_ves')
    if not expected_ves:
        return Decimal(section['usd_amount'])
    rate = Decimal(str((client.quote_usd(Decimal('1')) or {}).get('rate') or '0'))
    if rate <= 0:
        raise VexPayError('VEXPay returned no rate', status=503)
    return (Decimal(str(expected_ves)) / rate).quantize(CENT, rounding=ROUND_DOWN)


VERIFY_RETRY_AFTER = timedelta(minutes=10)
VERIFY_MAX_RETRIES = 5


def _retry_lost_verification(ramp: RampTransaction, client: VexPayClient) -> RampTransaction:
    """A verification whose response was lost may never have reached
    VEXPay (a by-reference lookup finds nothing). Replay it, a bounded number
    of times, then hand it to ops without ever releasing the order."""
    section = _section(ramp)
    retries = int(section.get('verify_retries') or 0)
    if retries >= VERIFY_MAX_RETRIES:
        if not ramp.status_detail.startswith('needs_review'):
            ramp = _update(ramp.pk, require=lambda c: c.status == 'PROCESSING',
                           detail='needs_review:verification_lost') or ramp
            _alert(ramp, ramp.status_detail)
        return ramp
    if ramp.updated_at > timezone.now() - VERIFY_RETRY_AFTER:
        return ramp
    try:
        # Today's rate for the bolívares shown: a replay of an old dollar
        # amount would ask for more Bs than the user sent once the rate moved.
        usd_amount = verify_usd_amount(section, client)
    except VexPayError:
        return ramp  # try again next poll; nothing was sent
    attempt = section.get('attempt')

    def still_lost(current):
        now = _section(current)
        # Only the same unresolved attempt, unaccepted, at the same retry
        # count: anything else means another worker or the user moved on.
        return (current.status == 'PROCESSING' and _phase(current) == 'submitted'
                and not now.get('accepted_payment_id') and now.get('attempt') == attempt
                and int(now.get('verify_retries') or 0) == retries)
    if _update(ramp.pk, require=still_lost, verify_retries=retries + 1,
               verify_usd_amount=format(usd_amount, 'f')) is None:
        return RampTransaction.objects.get(pk=ramp.pk)
    try:
        # A fresh key per replay: the same key would only replay a cached
        # answer. Safe because the by-reference lookup just proved no payment
        # with our externalRef exists at VEXPay.
        payment = _call_verify(ramp, section, usd_amount, client,
                               f"{ramp.external_id}:verify:{section.get('attempt')}:replay{retries + 1}")
    except VexPayAmbiguousError:
        return RampTransaction.objects.get(pk=ramp.pk)
    except VexPayError as exc:
        code = _verify_code(exc)
        if exc.status and 400 <= exc.status < 500 and code:
            # This replay's own, direct answer: the transfer is not matched
            # (yet) or the amount differs. Safe to hand back to the user.
            reopened = _update(
                ramp.pk, require=lambda c: c.status == 'PROCESSING' and _phase(c) == 'submitted'
                and not _section(c).get('accepted_payment_id'),
                status='PENDING', detail=f'verify_{code.lower()}', phase='created')
            return reopened or RampTransaction.objects.get(pk=ramp.pk)
        return RampTransaction.objects.get(pk=ramp.pk)
    return apply_payment(ramp, payment, direct=True)


def cancel_on_ramp(ramp: RampTransaction) -> RampTransaction:
    """The user says they did not pay: close an order nothing was submitted for."""
    updated = _update(ramp.pk, require=can_confirm, status='FAILED', detail='cancelled_by_user')
    if updated is None:
        raise VexPayRampError('Esta recarga ya se está confirmando y no se puede cancelar.')
    return updated


def sync_vexpay_ramp(ramp: RampTransaction, client: VexPayClient | None = None) -> RampTransaction:
    """Re-read the payment at VEXPay and fold it in. Idempotent."""
    client = client or VexPayClient()
    ramp = RampTransaction.objects.get(pk=ramp.pk)
    section = _section(ramp)
    phase = section.get('phase') or 'created'
    if phase == 'submitting':
        since = section.get('submitting_since') or ''
        try:
            started = datetime.fromisoformat(since)
        except ValueError:
            started = None
        if started is None or started < timezone.now() - STALE_SUBMISSION:
            ramp = _mark_ambiguous(ramp, 'submission_unconfirmed')
    if section.get('method') == 'pago_movil':
        # Until an attempt is accepted, follow the LATEST payment for our
        # reference: an earlier unmatched try must not stand in for a later
        # verification whose response was lost.
        payment_id = section.get('accepted_payment_id') or ''
    else:
        payment_id = ramp.provider_order_id or section.get('payment_id')
    if (section.get('method') == 'pago_movil' and can_confirm(ramp)
            and ramp.created_at < timezone.now() - PAGO_MOVIL_UNPAID_EXPIRY):
        return _record_failure(ramp, 'expired_unpaid', require=can_confirm)
    if (not payment_id and section.get('method') == 'pago_movil' and phase == 'preparing'
            and ramp.created_at < timezone.now() - STALE_SUBMISSION):
        # Preparation (Face claim + reading the receiving account) never
        # finished: no instructions reached the user and nothing exists at
        # VEXPay, so free the slot.
        return fail_preparation(ramp, 'preparation_interrupted')
    if not payment_id and section.get('method') == 'pago_movil' and phase in ('preparing', 'created'):
        # Nothing exists at VEXPay until the reference is verified: no lookup.
        if ramp.created_at < timezone.now() - PAGO_MOVIL_UNPAID_EXPIRY:
            return _record_failure(ramp, 'expired_unpaid', require=can_confirm)
        return ramp
    try:
        payment = (client.get_payment(payment_id) if payment_id
                   else client.get_payment_by_ref(ramp.external_id))
    except VexPayError as exc:
        if exc.status == 404 and not payment_id:
            if section.get('method') == 'c2p' and ramp.created_at < timezone.now() - C2P_UNPAID_EXPIRY:
                # No C2P intent was ever created (its request failed
                # ambiguously and VEXPay has no record): nothing can be
                # debited. Never an order a key was submitted for.
                return _record_failure(ramp, 'expired_unpaid',
                                       require=lambda c: _phase(c) in ('preparing', 'created'))
            if (section.get('method') == 'pago_movil' and _phase(ramp) == 'submitted'
                    and section.get('reference')):
                return _retry_lost_verification(ramp, client)
            # Not found yet: keep it open.
            return ramp
        raise
    if (section.get('method') == 'pago_movil' and not section.get('accepted_payment_id')
            and _phase(ramp) == 'submitted' and section.get('reference')
            and str(payment.get('status') or '').upper() in PAYMENT_DEAD):
        # The submission's outcome is unknown and the only record is a failed
        # try, which never settles it (apply_payment keeps it open): replay
        # (bounded), act on the replay's own answer, then escalate.
        ramp = apply_payment(ramp, payment)
        if (ramp.status == 'PROCESSING' and _phase(ramp) == 'submitted'
                and not _section(ramp).get('accepted_payment_id')):
            return _retry_lost_verification(ramp, client)
        return ramp
    return apply_payment(ramp, payment)


def open_ramps():
    """What the poller reconciles: every open order however old (an
    unverified Pago Móvil one costs no API call), and orders completed in the
    last 30 days whose conversion is not linked yet."""
    from django.db.models import Q
    now = timezone.now()
    return RampTransaction.objects.filter(provider=PROVIDER, direction='on_ramp').filter(
        Q(status__in=OPEN_STATUSES)
        # Proven or not: a missing conversion link is retried by the sync hook.
        | Q(status='COMPLETED', conversion__isnull=True, completed_at__gte=now - timedelta(days=30))
        # A settled payment can still be reversed (the bolívares returned to
        # the payer after the USDT left); webhooks are single-attempt.
        | Q(status='COMPLETED', completed_at__gte=now - REVERSAL_WATCH)
    ).order_by('created_at')


def due_for_sync(ramp: RampTransaction) -> bool:
    """Open orders every poll; settled ones (proof in hand) once an hour."""
    if ramp.status != 'COMPLETED':
        return True
    metadata = ramp.metadata or {}
    if not metadata.get('bsc_arrival_tx_hash') and ramp.conversion_id is None:
        return True
    checked = (metadata.get('vexpay') or {}).get('reversal_checked_at') or ''
    try:
        last = datetime.fromisoformat(checked)
    except ValueError:
        return True
    return last < timezone.now() - REVERSAL_CHECK_EVERY


def awaiting_credit(ramp: RampTransaction) -> bool:
    return ramp.status == 'COMPLETED' and ramp.final_amount is None


def active_order(user) -> RampTransaction | None:
    """The order the app resumes: open, or delivered but not yet credited."""
    from django.db.models import Q
    return RampTransaction.objects.filter(provider=PROVIDER, direction='on_ramp', actor_user=user).filter(
        Q(status__in=OPEN_STATUSES)
        | Q(status='COMPLETED', final_amount__isnull=True, completed_at__gte=timezone.now() - timedelta(days=3))
    ).order_by('-created_at').first()
