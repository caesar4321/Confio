"""Automatic crypto refunds for Koywe invalid withdrawal details.

No balance credits are synthesized here. REFUND_DELIVERED is provider evidence;
normal on-chain wallet reconciliation remains responsible for spendable funds.
"""
import logging
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ramps.models import KoyweRefund, RampTransaction

logger = logging.getLogger(__name__)

REFUND_STATES = {
    'REFUND_STARTED': 'started',
    'REFUND_IN_PROGRESS': 'in_progress',
    'REFUND_DELIVERED': 'delivered',
    'REFUNDED': 'delivered',
}
RANK = {'pending': 0, 'requesting': 1, 'unknown': 1, 'requested': 2,
        'started': 3, 'in_progress': 4, 'delivered': 6, 'not_required': 5, 'rejected': 1}


def _valid_destination(ramp):
    symbol = str(ramp.crypto_currency or '').strip().lower()
    address = str(ramp.actor_address or '').strip()
    if symbol in {'usdt bsc', 'usdc polygon'}:
        return bool(re.fullmatch(r'0x[0-9a-fA-F]{40}', address)) and int(address[2:], 16) != 0
    if symbol in {'usdc algorand', 'usdc-a'}:
        from algosdk.encoding import is_valid_address
        return is_valid_address(address)
    return False


def reconcile_refund(*, ramp_id, client):
    """Claim before POST, re-read provider status, and recover after crashes.

    A ten-minute lease prevents concurrent requests. After an uncertain result
    the same order/address can be retried: provider codes 004/005 identify an
    already processing/requested refund. Accepted requests are never reposted.
    """
    with transaction.atomic():
        ramp = RampTransaction.objects.select_for_update().get(pk=ramp_id)
        if ramp.provider != 'koywe' or ramp.direction != 'off_ramp' or not ramp.provider_order_id or ramp.status == 'COMPLETED':
            return
        refund = KoyweRefund.objects.filter(provider_order_id=ramp.provider_order_id).first()
        if refund and refund.ramp_id != ramp.pk:
            return  # Another local row already owns this provider order.
        if refund and refund.state in {'delivered', 'not_required'}:
            return
        if not refund:
            if not _valid_destination(ramp):
                logger.error('Cannot refund Koywe order %s: missing or invalid original wallet/rail', ramp.provider_order_id)
                return
            refund = KoyweRefund.objects.create(
                ramp=ramp, provider_order_id=ramp.provider_order_id,
                destination_address=ramp.actor_address.strip(),
                auth_email=str((ramp.metadata or {}).get('auth_email') or '').strip(),
            )
        if refund.last_attempt_at and refund.last_attempt_at > timezone.now() - timedelta(minutes=10):
            return
        # Persist lease before network I/O, including GET failures.
        refund.last_attempt_at = timezone.now()
        refund.attempts += 1
        refund.save(update_fields=['last_attempt_at', 'attempts', 'updated_at'])

    result = client.get_ramp_order_status(order_id=refund.provider_order_id, email=refund.auth_email or None)
    payload = result.raw_response or {}
    returned_id = payload.get('orderId') or payload.get('_id') or payload.get('id')
    if returned_id and str(returned_id) != refund.provider_order_id:
        return
    status = str(payload.get('status') or '').strip().upper()
    if status in REFUND_STATES:
        _advance(refund.pk, REFUND_STATES[status])
        return
    if status in {'DELIVERED', 'FIAT_DELIVERED', 'CRYPTO_DELIVERED'} and refund.state in {'pending', 'requesting', 'unknown'}:
        _advance(refund.pk, 'not_required')
        return
    if status != 'INVALID_WITHDRAWALS_DETAILS' or refund.state in {'requested', 'started', 'in_progress', 'rejected'}:
        return
    # Require the persisted source rail to agree with provider data when given.
    if payload.get('symbolIn') and str(payload['symbolIn']).strip().lower() != str(ramp.crypto_currency).strip().lower():
        return
    if _advance(refund.pk, 'requesting') != 'requesting':
        return  # A webhook may have advanced the refund during the GET.
    try:
        response = client.request_offramp_refund(
            order_id=refund.provider_order_id,
            destination_address=refund.destination_address,
            email=refund.auth_email or None,
        )
    except Exception:
        _advance(refund.pk, 'unknown')
        raise
    code = response.get('code') if isinstance(response, dict) else None
    response_id = (response.get('data') or {}).get('orderId') if isinstance(response, dict) and isinstance(response.get('data'), dict) else None
    if response_id and str(response_id) != refund.provider_order_id:
        code = None
    if code in {'REFUND_000', 'REFUND_004', 'REFUND_005'}:
        _advance(refund.pk, 'requested', code)
    elif code == 'REFUND_003':
        _advance(refund.pk, 'unknown', code)  # Status may have changed after GET.
    elif code in {'REFUND_001', 'REFUND_002', 'REFUND_006', 'REFUND_007'}:
        _advance(refund.pk, 'rejected', code)
        logger.error('Koywe refund rejected for order %s: %s', refund.provider_order_id, code)
    else:
        _advance(refund.pk, 'unknown')


def _advance(refund_id, state, code=''):
    with transaction.atomic():
        ramp_id = KoyweRefund.objects.values_list('ramp_id', flat=True).get(pk=refund_id)
        # Match the claim's lock order to avoid deadlocks with concurrent polls.
        RampTransaction.objects.select_for_update().get(pk=ramp_id)
        refund = KoyweRefund.objects.select_for_update().get(pk=refund_id)
        if RANK[state] >= RANK[refund.state]:
            refund.state = state
            refund.result_code = code
            refund.save(update_fields=['state', 'result_code', 'updated_at'])
        state = refund.state
        detail = {'requested': 'refund_requested', 'started': 'refund_started',
                  'in_progress': 'refund_in_progress', 'delivered': 'refund_delivered'}.get(state)
        if detail:
            RampTransaction.objects.filter(pk=refund.ramp_id).update(
                status='FAILED', status_detail=detail, completed_at=None,
            )
        return state


def preserve_refund_progress(ramp, status_raw):
    refund = KoyweRefund.objects.filter(ramp_id=ramp.pk).first()
    if refund:
        state = REFUND_STATES.get(status_raw, refund.state)
        if status_raw in {'DELIVERED', 'FIAT_DELIVERED', 'CRYPTO_DELIVERED'} and refund.state in {'pending', 'requesting', 'unknown'}:
            state = 'not_required'
        current_state = _advance(refund.pk, state, refund.result_code)
        if current_state in {'requested', 'started', 'in_progress', 'delivered'}:
            ramp.refresh_from_db(fields=['status', 'status_detail', 'completed_at'])
