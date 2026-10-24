"""GraphQL for the Venezuelan bolívar top-up through VEXPay (see ramps/vexpay.py).

Personal accounts only, owner only. Each top-up is a dynamic order, so it
carries the same Confío Face step-up as the Koywe top-up; the payer may be a
third party (recorded on the order).
"""
from __future__ import annotations

import logging
import math
from decimal import ROUND_DOWN, Decimal, InvalidOperation

import graphene
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError

from ramps import vexpay
from ramps.models import RampTransaction
from ramps.vexpay_client import VexPayClient, VexPayError

logger = logging.getLogger(__name__)

UNAVAILABLE = 'Las recargas en bolívares no están disponibles por ahora.'
GENERIC_ERROR = 'No pudimos procesar la recarga. Intenta de nuevo en unos minutos.'
# The Pago Móvil amount is priced in USD at confirmation time. Ask for a
# little more than today's quote so a small rate move cannot turn an exact
# transfer into an amount mismatch; VEXPay credits what actually arrived.
PAGO_MOVIL_CUSHION = Decimal('1.005')


class VexpayReceivingAccountType(graphene.ObjectType):
    bank_code = graphene.String()
    bank_name = graphene.String()
    phone = graphene.String()
    identification = graphene.String()


class VexpayBankType(graphene.ObjectType):
    code = graphene.String()
    name = graphene.String()


class VexpayOnRampOrderType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    next_step = graphene.String()
    order_id = graphene.String()
    status = graphene.String()
    status_detail = graphene.String()
    method = graphene.String()
    usd_amount = graphene.String()
    ves_amount = graphene.String()
    estimated_usdt = graphene.String()
    delivered_usdt = graphene.String()
    otp_requested = graphene.Boolean()
    receiving_account = graphene.Field(VexpayReceivingAccountType)
    tx_hash = graphene.String()
    # True only while the order waits for the key / reference and nothing
    # has been submitted: the app shows the payment form only then.
    can_confirm = graphene.Boolean()
    can_cancel = graphene.Boolean()


class VexpayOnRampQuoteType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    usd_amount = graphene.String()
    ves_amount = graphene.String()
    rate = graphene.String()
    estimated_usdt = graphene.String()
    min_usd = graphene.String()
    max_usd = graphene.String()
    # Everything VEXPay keeps (pay-in fee, conversion spread, BEP20 payout
    # fee), from the account's live terms: "Comisión del procesador de pagos".
    processor_fee_usd = graphene.String()
    confio_fee_usd = graphene.String()


def _order_payload(ramp: RampTransaction) -> VexpayOnRampOrderType:
    section = (ramp.metadata or {}).get('vexpay', {})
    onward = section.get('onward') or {}
    receiving = section.get('receiving_account') or {}
    return VexpayOnRampOrderType(
        success=True,
        order_id=str(ramp.internal_id),
        status=ramp.status,
        status_detail=ramp.status_detail,
        method=section.get('method'),
        usd_amount=section.get('usd_amount'),
        ves_amount=section.get('expected_ves') or (format(ramp.fiat_amount, 'f') if ramp.fiat_amount is not None else None),
        # Dollars after Confío's conversion fee; the settled net once the
        # auto-conversion has linked (final_amount), never the gross USDT.
        estimated_usdt=section.get('estimated_net') or (
            format(ramp.crypto_amount_estimated, 'f') if ramp.crypto_amount_estimated is not None else None),
        delivered_usdt=format(ramp.final_amount, 'f') if ramp.final_amount is not None else None,
        otp_requested=section.get('otp_requested'),
        receiving_account=VexpayReceivingAccountType(**receiving) if receiving else None,
        tx_hash=onward.get('txHash'),
        can_confirm=vexpay.can_confirm(ramp),
        can_cancel=vexpay.can_confirm(ramp),
    )


def _error(message: str, next_step: str | None = None) -> VexpayOnRampOrderType:
    return VexpayOnRampOrderType(success=False, error=message, next_step=next_step)


def _parse_usd(value) -> Decimal | None:
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() and amount > 0 else None


def _owned_order(info, order_id) -> RampTransaction | None:
    user = getattr(info.context, 'user', None)
    if not (user and getattr(user, 'is_authenticated', False)):
        return None
    try:
        return RampTransaction.objects.filter(
            provider=vexpay.PROVIDER, direction='on_ramp', actor_user=user, internal_id=order_id,
        ).first()
    except (ValueError, TypeError, DjangoValidationError):
        return None


def _preflight(info):
    """Shared gates; returns (user, account) or an error payload."""
    from ramps.schema import (
        _employee_ramp_denial,
        _get_ramp_account_for_user,
        _get_wallet_upgrade_blocker,
    )

    user = getattr(info.context, 'user', None)
    if not (user and getattr(user, 'is_authenticated', False)):
        return _error('Authentication required')
    if not vexpay.enabled():
        return _error(UNAVAILABLE)
    denial = _employee_ramp_denial(info)
    if denial:
        return _error(denial)
    account = _get_ramp_account_for_user(info, user)
    if not account or getattr(account, 'account_type', None) != 'personal':
        return _error('Las recargas en bolívares solo están disponibles para cuentas personales.')
    from security.identity_status import is_identity_verified
    if not is_identity_verified(user):
        # The Face step-up exempts people who never passed KYC; this rail
        # requires KYC itself, whoever pays.
        return _error('Verifica tu identidad para recargar con bolívares.', 'verification')
    if not getattr(account, 'bsc_address', None):
        return _error('Tu cuenta aún no está activada en este dispositivo. Actualiza la app e inicia sesión de nuevo.')
    blocker = _get_wallet_upgrade_blocker(user=user, account=account)
    if blocker:
        return _error(blocker)
    if getattr(settings, 'CUSD_CONVERSION_FEE_ENABLED', False):
        meta = getattr(info.context, 'META', {})
        if str(meta.get('HTTP_X_CONFIO_FEE_CAPABLE', '')).strip() != '1':
            from cusd_plus.eligibility import CUSD_BSC_LEGACY_UPDATE_MESSAGE, check_savings_mint_eligibility
            if not check_savings_mint_eligibility(user, meta):
                return _error(CUSD_BSC_LEGACY_UPDATE_MESSAGE)
        try:
            from cusd_plus.cusd_vault import require_operational
            require_operational()
        except Exception:  # noqa: BLE001
            logger.exception('cUSD perimeter preflight failed before VEXPay order')
            return _error('Las conversiones de dólares están pausadas temporalmente.')
    return user, account


class CreateVexpayOnRamp(graphene.Mutation):
    class Arguments:
        usd_amount = graphene.String(required=True)
        method = graphene.String(required=True, description="'c2p' or 'pago_movil'")
        cedula = graphene.String(required=True)
        phone = graphene.String(required=True)
        bank_code = graphene.String(required=True)

    Output = VexpayOnRampOrderType

    def mutate(self, info, usd_amount, method, cedula, phone, bank_code):
        gate = _preflight(info)
        if isinstance(gate, VexpayOnRampOrderType):
            return gate
        user, account = gate
        method = (method or '').strip().lower()
        if method not in ('c2p', 'pago_movil'):
            return _error('Método de pago no válido.')
        amount = _parse_usd(usd_amount)
        if amount is None:
            return _error('Monto no válido.')

        from security.face_step_up import (
            FACE_STEP_UP_MESSAGE, FACE_STEP_UP_NEXT_STEP, claim_on_ramp_check,
            missing_face_step_up, release_on_ramp_check,
        )
        step_up = missing_face_step_up(user, 'on_ramp')
        if step_up:
            return _error(step_up, FACE_STEP_UP_NEXT_STEP)

        client = VexPayClient()
        if not client.is_configured:
            return _error(UNAVAILABLE)
        try:
            payer = {
                'cedula': vexpay.normalize_cedula(cedula),
                'phone': vexpay.normalize_phone(phone),
                'bank_code': vexpay.normalize_bank_code(bank_code),
            }
            # Third parties (e.g. family) may pay: the order, its Face check
            # and limits belong to the Confío account holder; the payer is
            # recorded on the order. Limits are checked under the
            # reservation lock in reserve_on_ramp.
            terms = vexpay.fee_terms(client)
            if not terms.get('payout_available'):
                return _error(UNAVAILABLE)
            # Receiving details alone do not mean the method is on: never show
            # bank instructions VEXPay would then refuse to verify.
            methods = {m.get('method'): m for m in (client.payment_methods() or {}).get('methods', [])}
            if not (methods.get(method) or {}).get('available'):
                return _error('Este método de pago no está disponible por ahora. Prueba con el otro.')
            vexpay.check_provider_minimums(amount, terms)
            ramp = vexpay.reserve_on_ramp(
                user=user, account=account, usd_amount=amount, method=method, payer=payer, terms=terms)
        except vexpay.VexPayRampError as exc:
            return _error(str(exc))
        except VexPayError:
            logger.exception('VEXPay preflight failed')
            return _error(GENERIC_ERROR)

        claimed, face_claim_id = claim_on_ramp_check(user, consumed_by=f'ramp:on_ramp:{ramp.internal_id}')
        if not claimed:
            vexpay.fail_preparation(ramp, 'face_check_unavailable')
            return _error(FACE_STEP_UP_MESSAGE, FACE_STEP_UP_NEXT_STEP)

        try:
            if method == 'c2p':
                vexpay.start_c2p(ramp, client)
            else:
                receiving = client.receiving_account()
                if not receiving.get('configured'):
                    # A definite no-order outcome: free the order and the Face claim.
                    vexpay.fail_preparation(ramp, 'receiving_account_not_configured')
                    raise vexpay.VexPayRampError(UNAVAILABLE)
                quote = client.quote_usd(amount)
                expected = math.ceil(Decimal(str(quote['vesAmount'])) * PAGO_MOVIL_CUSHION)
                vexpay._update(
                    ramp.pk,
                    expected_ves=str(expected),
                    quoted_rate=str(quote.get('rate') or quote.get('bcvRate') or ''),
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
        except vexpay.VexPayRampError as exc:
            ramp.refresh_from_db()
            if ramp.status == 'FAILED':
                release_on_ramp_check(face_claim_id)
            return _error(str(exc))
        except VexPayError:
            logger.exception('VEXPay order start failed for ramp %s', ramp.pk)
            # Only the Pago Móvil instruction reads (GETs) reach here: nothing
            # was created at VEXPay, so the order and the Face claim are free.
            vexpay.fail_preparation(ramp, 'start_failed')
            release_on_ramp_check(face_claim_id)
            return _error(GENERIC_ERROR)
        ramp.refresh_from_db()
        return _order_payload(ramp)


class ConfirmVexpayC2p(graphene.Mutation):
    class Arguments:
        order_id = graphene.String(required=True)
        otp = graphene.String(required=True)

    Output = VexpayOnRampOrderType

    def mutate(self, info, order_id, otp):
        ramp = _owned_order(info, order_id)
        if not ramp:
            return _error('Recarga no encontrada.')
        if not vexpay.enabled():
            # Switching the rail off stops new charges; reconciliation of
            # existing orders continues in the poller.
            return _error(UNAVAILABLE)
        try:
            ramp = vexpay.execute_c2p(ramp, otp, VexPayClient())
        except vexpay.VexPayRampError as exc:
            return _error(str(exc))
        except VexPayError:
            logger.exception('VEXPay C2P execute failed for ramp %s', ramp.pk)
            return _error(GENERIC_ERROR)
        return _order_payload(ramp)


class VerifyVexpayPagoMovil(graphene.Mutation):
    class Arguments:
        order_id = graphene.String(required=True)
        reference = graphene.String(required=True)
        payment_date = graphene.String(description="YYYY-MM-DD when the transfer was not made today")

    Output = VexpayOnRampOrderType

    def mutate(self, info, order_id, reference, payment_date=None):
        ramp = _owned_order(info, order_id)
        if not ramp:
            return _error('Recarga no encontrada.')
        # Allowed with the rail switched off: the user already sent the
        # bolívares, and only their reference can find that transfer.
        try:
            ramp = vexpay.verify_pago_movil(ramp, reference, VexPayClient(), payment_date or '')
        except vexpay.VexPayRampError as exc:
            return _error(str(exc))
        except VexPayError:
            logger.exception('VEXPay Pago Móvil verify failed for ramp %s', ramp.pk)
            return _error(GENERIC_ERROR)
        return _order_payload(ramp)


class Query(graphene.ObjectType):
    vexpay_on_ramp_order = graphene.Field(VexpayOnRampOrderType, order_id=graphene.String(required=True))
    vexpay_on_ramp_quote = graphene.Field(VexpayOnRampQuoteType, usd_amount=graphene.String(required=True))
    vexpay_banks = graphene.List(VexpayBankType)
    # The open top-up to resume after the app closes, or null.
    vexpay_active_on_ramp_order = graphene.Field(VexpayOnRampOrderType)

    def resolve_vexpay_active_on_ramp_order(self, info):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return None
        ramp = vexpay.active_order(user)
        return _order_payload(ramp) if ramp else None

    def resolve_vexpay_on_ramp_order(self, info, order_id):
        ramp = _owned_order(info, order_id)
        if not ramp:
            return _error('Recarga no encontrada.')
        return _order_payload(ramp)

    def resolve_vexpay_on_ramp_quote(self, info, usd_amount):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return VexpayOnRampQuoteType(success=False, error='Authentication required')
        if not vexpay.enabled():
            return VexpayOnRampQuoteType(success=False, error=UNAVAILABLE)
        amount = _parse_usd(usd_amount)
        if amount is None:
            return VexpayOnRampQuoteType(success=False, error='Monto no válido.')
        client = VexPayClient()
        if not client.is_configured:
            return VexpayOnRampQuoteType(success=False, error=UNAVAILABLE)
        try:
            terms = vexpay.fee_terms(client)
            quote = client.quote_usd(amount)
            gross = vexpay.estimate_usdt(amount, terms)
            net = vexpay.confio_net(gross)
        except vexpay.VexPayRampError as exc:
            return VexpayOnRampQuoteType(success=False, error=str(exc))
        except VexPayError:
            logger.exception('VEXPay quote failed')
            return VexpayOnRampQuoteType(success=False, error=GENERIC_ERROR)
        return VexpayOnRampQuoteType(
            success=True,
            usd_amount=format(amount, 'f'),
            ves_amount=str(math.ceil(Decimal(str(quote['vesAmount'])) * PAGO_MOVIL_CUSHION)),
            rate=str(quote.get('rate') or quote.get('bcvRate') or ''),
            estimated_usdt=format(net, 'f'),
            processor_fee_usd=format(max(amount - gross, Decimal('0')), 'f'),
            confio_fee_usd=format(max(gross - net, Decimal('0')), 'f'),
            min_usd=str(max(vexpay._setting_decimal('VEXPAY_ONRAMP_MIN_USD', '5'),
                            vexpay.provider_minimum_usd(terms))),
            max_usd=str(getattr(settings, 'VEXPAY_ONRAMP_MAX_USD', '100')),
        )

    def resolve_vexpay_banks(self, info):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)) or not vexpay.enabled():
            return []
        try:
            banks = VexPayClient().banks()
        except VexPayError:
            logger.exception('VEXPay banks failed')
            return []
        return [VexpayBankType(code=b.get('code'), name=b.get('name')) for b in banks
                if 'P2P' in (b.get('services') or []) or not b.get('services')]


class CancelVexpayOnRamp(graphene.Mutation):
    class Arguments:
        order_id = graphene.String(required=True)

    Output = VexpayOnRampOrderType

    def mutate(self, info, order_id):
        ramp = _owned_order(info, order_id)
        if not ramp:
            return _error('Recarga no encontrada.')
        try:
            ramp = vexpay.cancel_on_ramp(ramp)
        except vexpay.VexPayRampError as exc:
            return _error(str(exc))
        return _order_payload(ramp)


class Mutation(graphene.ObjectType):
    cancel_vexpay_on_ramp = CancelVexpayOnRamp.Field()
    create_vexpay_on_ramp = CreateVexpayOnRamp.Field()
    confirm_vexpay_c2p = ConfirmVexpayC2p.Field()
    verify_vexpay_pago_movil = VerifyVexpayPagoMovil.Field()
