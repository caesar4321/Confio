"""VEXPay as the VE Pago Móvil top-up provider (adapter for ramps.ve_pagomovil).

The order lifecycle lives in ramps/vexpay.py; this module is the contract the
provider-neutral GraphQL layer calls:

  quote(amount) -> dict
  create(user, account, amount, method, payer) -> RampTransaction
  confirm_c2p(ramp, otp) / verify_reference(ramp, reference, date) / cancel(ramp)
  view(ramp) -> dict
  active_order(user) -> RampTransaction | None

Errors are ve_pagomovil.VePagoMovilError (Spanish, user-facing).
"""
from __future__ import annotations

import logging
import math
from decimal import Decimal

from ramps import ve_pagomovil, vexpay
from ramps.models import RampTransaction
from ramps.ve_pagomovil import VePagoMovilError
from ramps.vexpay_client import VexPayClient, VexPayError

logger = logging.getLogger(__name__)

PROVIDER = vexpay.PROVIDER
UNAVAILABLE = 'Las recargas en bolívares no están disponibles por ahora.'
GENERIC_ERROR = 'No pudimos procesar la recarga. Intenta de nuevo en unos minutos.'
# The Pago Móvil amount is priced in USD at confirmation time. Ask for a
# little more than today's quote so a small rate move cannot turn an exact
# transfer into an amount mismatch; VEXPay credits what actually arrived.
PAGO_MOVIL_CUSHION = Decimal('1.005')


def _client() -> VexPayClient:
    client = VexPayClient()
    if not client.is_configured:
        raise VePagoMovilError(UNAVAILABLE)
    return client


def quote(amount: Decimal) -> dict:
    client = _client()
    try:
        terms = vexpay.fee_terms(client)
        payload = client.quote_usd(amount)
        gross = vexpay.estimate_usdt(amount, terms)
        net = vexpay.confio_net(gross)
    except VexPayError as exc:
        logger.exception('VEXPay quote failed')
        raise VePagoMovilError(GENERIC_ERROR) from exc
    return {
        'usd_amount': format(amount, 'f'),
        'ves_amount': str(math.ceil(Decimal(str(payload['vesAmount'])) * PAGO_MOVIL_CUSHION)),
        'rate': str(payload.get('rate') or payload.get('bcvRate') or ''),
        'estimated_usdt': format(net, 'f'),
        # Everything VEXPay keeps (pay-in fee, conversion spread, BEP20
        # payout fee), from the account's live terms.
        'processor_fee_usd': format(max(amount - gross, Decimal('0')), 'f'),
        'confio_fee_usd': format(max(gross - net, Decimal('0')), 'f'),
        'min_usd': str(max(ve_pagomovil.optional_limit('VE_PAGOMOVIL_TOPUP_MIN_USD') or Decimal('0'),
                           vexpay.provider_minimum_usd(terms))),
    }


def create(user, account, amount: Decimal, method: str, payer: dict) -> RampTransaction:
    """Reserve, spend the deposit Face check, then prepare the payment."""
    from security.face_step_up import (
        FACE_STEP_UP_MESSAGE, FACE_STEP_UP_NEXT_STEP, claim_on_ramp_check,
        missing_face_step_up, release_on_ramp_check,
    )
    step_up = missing_face_step_up(user, 'on_ramp')
    if step_up:
        raise VePagoMovilError(step_up, FACE_STEP_UP_NEXT_STEP)
    client = _client()
    try:
        provider_payer = {
            'cedula': payer['cedula'],
            'phone': payer['phone'],
            'bank_code': int(payer['bank_code']),
        }
        # Third parties (e.g. family) may pay: the order, its Face check
        # and limits belong to the Confío account holder; the payer is
        # recorded on the order. Limits are checked under the reservation
        # lock in reserve_on_ramp.
        terms = vexpay.fee_terms(client)
        if not terms.get('payout_available'):
            raise VePagoMovilError(UNAVAILABLE)
        # Receiving details alone do not mean the method is on: never show
        # bank instructions VEXPay would then refuse to verify.
        methods = {m.get('method'): m for m in (client.payment_methods() or {}).get('methods', [])}
        if not (methods.get(method) or {}).get('available'):
            raise VePagoMovilError('Este método de pago no está disponible por ahora. Prueba con el otro.')
        vexpay.check_provider_minimums(amount, terms)
        ramp = vexpay.reserve_on_ramp(
            user=user, account=account, usd_amount=amount, method=method, payer=provider_payer, terms=terms)
    except VexPayError as exc:
        logger.exception('VEXPay preflight failed')
        raise VePagoMovilError(GENERIC_ERROR) from exc

    claimed, face_claim_id = claim_on_ramp_check(user, consumed_by=f'ramp:on_ramp:{ramp.internal_id}')
    if not claimed:
        vexpay.fail_preparation(ramp, 'face_check_unavailable')
        raise VePagoMovilError(FACE_STEP_UP_MESSAGE, FACE_STEP_UP_NEXT_STEP)

    try:
        if method == 'c2p':
            vexpay.start_c2p(ramp, client)
        else:
            receiving = client.receiving_account()
            if not receiving.get('configured'):
                # A definite no-order outcome: free the order and the Face claim.
                vexpay.fail_preparation(ramp, 'receiving_account_not_configured')
                raise VePagoMovilError(UNAVAILABLE)
            payload = client.quote_usd(amount)
            expected = math.ceil(Decimal(str(payload['vesAmount'])) * PAGO_MOVIL_CUSHION)
            vexpay._update(
                ramp.pk,
                expected_ves=str(expected),
                quoted_rate=str(payload.get('rate') or payload.get('bcvRate') or ''),
                receiving_account={
                    'bank_code': receiving.get('bankCode') or '',
                    'bank_name': receiving.get('bankName') or '',
                    'phone': receiving.get('phone') or '',
                    'identification': receiving.get('identification') or '',
                },
            )
        # Confirmable only now: Face claimed and instructions (or the C2P
        # intent) in place.
        vexpay.mark_prepared(ramp)
    except VePagoMovilError:
        ramp.refresh_from_db()
        if ramp.status == 'FAILED':
            release_on_ramp_check(face_claim_id)
        raise
    except VexPayError as exc:
        logger.exception('VEXPay order start failed for ramp %s', ramp.pk)
        # Only the Pago Móvil instruction reads (GETs) reach here: nothing
        # was created at VEXPay, so the order and the Face claim are free.
        vexpay.fail_preparation(ramp, 'start_failed')
        release_on_ramp_check(face_claim_id)
        raise VePagoMovilError(GENERIC_ERROR) from exc
    ramp.refresh_from_db()
    return ramp


def confirm_c2p(ramp: RampTransaction, otp: str) -> RampTransaction:
    if not vexpay.enabled():
        # Switching the rail off stops new charges; reconciliation of
        # existing orders continues in the poller.
        raise VePagoMovilError(UNAVAILABLE)
    try:
        return vexpay.execute_c2p(ramp, otp, VexPayClient())
    except VexPayError as exc:
        logger.exception('VEXPay C2P execute failed for ramp %s', ramp.pk)
        raise VePagoMovilError(GENERIC_ERROR) from exc


def verify_reference(ramp: RampTransaction, reference: str, payment_date: str) -> RampTransaction:
    # Allowed with the rail switched off: the user already sent the
    # bolívares, and only their reference can find that transfer.
    try:
        return vexpay.verify_pago_movil(ramp, reference, VexPayClient(), payment_date or '')
    except VexPayError as exc:
        logger.exception('VEXPay Pago Móvil verify failed for ramp %s', ramp.pk)
        raise VePagoMovilError(GENERIC_ERROR) from exc


def cancel(ramp: RampTransaction) -> RampTransaction:
    return vexpay.cancel_on_ramp(ramp)


def active_order(user) -> RampTransaction | None:
    return vexpay.active_order(user)


def view(ramp: RampTransaction) -> dict:
    section = vexpay._section(ramp)
    onward = section.get('onward') or {}
    return {
        'method': section.get('method'),
        'usd_amount': section.get('usd_amount'),
        'ves_amount': section.get('expected_ves') or (
            format(ramp.fiat_amount, 'f') if ramp.fiat_amount is not None else None),
        # Dollars after Confío's conversion fee; the settled net once the
        # auto-conversion has linked (final_amount), never the gross USDT.
        'estimated_usdt': section.get('estimated_net') or (
            format(ramp.crypto_amount_estimated, 'f') if ramp.crypto_amount_estimated is not None else None),
        'delivered_usdt': format(ramp.final_amount, 'f') if ramp.final_amount is not None else None,
        'otp_requested': section.get('otp_requested'),
        'receiving_account': section.get('receiving_account') or None,
        'tx_hash': onward.get('txHash'),
        'can_confirm': vexpay.can_confirm(ramp),
        'can_cancel': vexpay.can_confirm(ramp),
    }
