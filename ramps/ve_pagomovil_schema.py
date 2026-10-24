"""GraphQL for Venezuelan Pago Móvil: top up with bolívares and send bolívares.

Provider-neutral (ramps.ve_pagomovil): the app never learns which provider
does the work; new orders go to the configured adapter and existing ones to
the adapter that made them. Personal accounts, owner only, identity-verified.
"""
from __future__ import annotations

import logging
from decimal import ROUND_DOWN, Decimal, InvalidOperation

import graphene
from django.conf import settings

from ramps import ve_pagomovil, ve_send
from ramps.ve_pagomovil import SEND, TOPUP, VePagoMovilError

logger = logging.getLogger(__name__)

TOPUP_UNAVAILABLE = 'Las recargas en bolívares no están disponibles por ahora.'
SEND_UNAVAILABLE = 'Los envíos en bolívares no están disponibles por ahora.'
GENERIC_ERROR = 'No pudimos procesar la operación. Intenta de nuevo en unos minutos.'


class VePagoMovilBankType(graphene.ObjectType):
    code = graphene.String()
    name = graphene.String()


class VePagoMovilReceivingAccountType(graphene.ObjectType):
    bank_code = graphene.String()
    bank_name = graphene.String()
    phone = graphene.String()
    identification = graphene.String()


class VePagoMovilTopUpOrderType(graphene.ObjectType):
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
    receiving_account = graphene.Field(VePagoMovilReceivingAccountType)
    tx_hash = graphene.String()
    # True only while the order waits for the key / reference and nothing has
    # been submitted: the app shows the payment form only then.
    can_confirm = graphene.Boolean()
    can_cancel = graphene.Boolean()


class VePagoMovilTopUpQuoteType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    usd_amount = graphene.String()
    ves_amount = graphene.String()
    rate = graphene.String()
    estimated_usdt = graphene.String()
    min_usd = graphene.String()
    max_usd = graphene.String()
    # "Comisión del procesador de pagos" / "Comisión de Confío".
    processor_fee_usd = graphene.String()
    confio_fee_usd = graphene.String()


class VePagoMovilBeneficiaryType(graphene.ObjectType):
    cedula = graphene.String()
    phone = graphene.String()
    bank_code = graphene.String()
    bank_name = graphene.String()


class VePagoMovilFundingType(graphene.ObjectType):
    """The vouched funding target; the app pays it with the Retiro batch."""
    deposit_address = graphene.String()
    network = graphene.String()
    deposit_amount_wei = graphene.String()
    gross_debit_amount_wei = graphene.String()


class VePagoMovilSendOrderType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    next_step = graphene.String()
    order_id = graphene.String()
    status = graphene.String()
    status_detail = graphene.String()
    phase = graphene.String()
    usd_amount = graphene.String()
    usdt_amount = graphene.String()
    estimated_ves = graphene.String()
    ves_amount = graphene.String()
    rate = graphene.String()
    beneficiary = graphene.Field(VePagoMovilBeneficiaryType)
    funding = graphene.Field(VePagoMovilFundingType)
    funding_tx_hash = graphene.String()
    bank_reference = graphene.String()
    can_cancel = graphene.Boolean()
    can_fund = graphene.Boolean()
    # The wallet the funding must come from: the app signs with it only.
    wallet = graphene.String()


class VePagoMovilSendQuoteType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    usd_amount = graphene.String()
    usdt_amount = graphene.String()
    confio_fee_usd = graphene.String()
    processor_fee_usd = graphene.String()
    estimated_ves = graphene.String()
    rate = graphene.String()
    min_usd = graphene.String()
    max_usd = graphene.String()


# ------------------------------------------------------------------ payloads

def _topup_payload(ramp) -> VePagoMovilTopUpOrderType:
    view = ve_pagomovil.adapter_for(ramp).view(ramp)
    receiving = view.pop('receiving_account', None)
    return VePagoMovilTopUpOrderType(
        success=True, order_id=str(ramp.internal_id), status=ramp.status, status_detail=ramp.status_detail,
        receiving_account=VePagoMovilReceivingAccountType(**receiving) if receiving else None, **view)


def _send_payload(ramp, *, with_funding: bool = False) -> VePagoMovilSendOrderType:
    view = ve_send.view(ramp, with_funding=with_funding)
    beneficiary = view.pop('beneficiary', None)
    funding = view.pop('funding', None)
    return VePagoMovilSendOrderType(
        success=True, order_id=str(ramp.internal_id), status=ramp.status, status_detail=ramp.status_detail,
        beneficiary=VePagoMovilBeneficiaryType(**beneficiary) if beneficiary else None,
        funding=VePagoMovilFundingType(**funding) if funding else None, **view)


def _parse_usd(value) -> Decimal | None:
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() and amount > 0 else None


def _user(info):
    user = getattr(info.context, 'user', None)
    return user if user and getattr(user, 'is_authenticated', False) else None


def _preflight(info, direction: str):
    """Product rules for a NEW order; returns (user, account) or raises."""
    from ramps.schema import _employee_ramp_denial, _get_ramp_account_for_user, _get_wallet_upgrade_blocker

    user = _user(info)
    if not user:
        raise VePagoMovilError('Authentication required')
    if not ve_pagomovil.enabled(direction):
        raise VePagoMovilError(TOPUP_UNAVAILABLE if direction == TOPUP else SEND_UNAVAILABLE)
    denial = _employee_ramp_denial(info)
    if denial:
        raise VePagoMovilError(denial)
    account = _get_ramp_account_for_user(info, user)
    if not account or getattr(account, 'account_type', None) != 'personal':
        raise VePagoMovilError('Pago Móvil solo está disponible para cuentas personales.')
    from security.identity_status import is_identity_verified
    if not is_identity_verified(user):
        raise VePagoMovilError('Verifica tu identidad para usar Pago Móvil.', 'verification')
    if not getattr(account, 'bsc_address', None):
        raise VePagoMovilError('Tu cuenta aún no está activada en este dispositivo. '
                               'Actualiza la app e inicia sesión de nuevo.')
    blocker = _get_wallet_upgrade_blocker(user=user, account=account)
    if blocker:
        raise VePagoMovilError(blocker)
    if getattr(settings, 'CUSD_CONVERSION_FEE_ENABLED', False):
        meta = getattr(info.context, 'META', {})
        if str(meta.get('HTTP_X_CONFIO_FEE_CAPABLE', '')).strip() != '1':
            from cusd_plus.eligibility import CUSD_BSC_LEGACY_UPDATE_MESSAGE, check_savings_mint_eligibility
            if not check_savings_mint_eligibility(user, meta):
                raise VePagoMovilError(CUSD_BSC_LEGACY_UPDATE_MESSAGE)
        try:
            from cusd_plus.cusd_vault import require_operational
            require_operational()
        except Exception as exc:  # noqa: BLE001
            logger.exception('cUSD perimeter preflight failed before a VE Pago Móvil order')
            raise VePagoMovilError('Las conversiones de dólares están pausadas temporalmente.') from exc
    return user, account


def _beneficiary(cedula, phone, bank_code) -> dict:
    return {
        'cedula': ve_pagomovil.normalize_cedula(cedula),
        'phone': ve_pagomovil.normalize_phone(phone),
        'bank_code': ve_pagomovil.normalize_bank(bank_code),
    }


def _guard(error_type, fn):
    """Run fn; turn refusals into the payload's error fields."""
    try:
        return fn()
    except VePagoMovilError as exc:
        extra = {'next_step': exc.next_step} if 'next_step' in error_type._meta.fields else {}
        return error_type(success=False, error=str(exc), **extra)
    except Exception:  # noqa: BLE001 — never leak provider internals
        logger.exception('VE Pago Móvil operation failed')
        return error_type(success=False, error=GENERIC_ERROR)


# ------------------------------------------------------------------ top-up

class CreateVePagoMovilTopUp(graphene.Mutation):
    class Arguments:
        usd_amount = graphene.String(required=True)
        method = graphene.String(required=True, description="'pago_movil' or 'c2p'")
        cedula = graphene.String(required=True)
        phone = graphene.String(required=True)
        bank_code = graphene.String(required=True)

    Output = VePagoMovilTopUpOrderType

    def mutate(self, info, usd_amount, method, cedula, phone, bank_code):
        def run():
            user, account = _preflight(info, TOPUP)
            amount = _parse_usd(usd_amount)
            if amount is None:
                raise VePagoMovilError('Monto no válido.')
            chosen = (method or '').strip().lower()
            if chosen not in ('c2p', 'pago_movil'):
                raise VePagoMovilError('Método de pago no válido.')
            payer = _beneficiary(cedula, phone, bank_code)
            ramp = ve_pagomovil.topup_adapter().create(user, account, amount, chosen, payer)
            return _topup_payload(ramp)
        return _guard(VePagoMovilTopUpOrderType, run)


def _topup_order_action(info, order_id, action):
    def run():
        ramp = ve_pagomovil.owned_order(_user(info), order_id, TOPUP)
        if not ramp:
            raise VePagoMovilError('Recarga no encontrada.')
        return _topup_payload(action(ve_pagomovil.adapter_for(ramp), ramp))
    return _guard(VePagoMovilTopUpOrderType, run)


class ConfirmVePagoMovilTopUpKey(graphene.Mutation):
    """C2P: the payer's bank payment key."""

    class Arguments:
        order_id = graphene.String(required=True)
        otp = graphene.String(required=True)

    Output = VePagoMovilTopUpOrderType

    def mutate(self, info, order_id, otp):
        return _topup_order_action(info, order_id, lambda a, r: a.confirm_c2p(r, otp))


class VerifyVePagoMovilTopUp(graphene.Mutation):
    """Pago Móvil: the reference of the transfer the payer made."""

    class Arguments:
        order_id = graphene.String(required=True)
        reference = graphene.String(required=True)
        payment_date = graphene.String(description='YYYY-MM-DD when the transfer was not made today')

    Output = VePagoMovilTopUpOrderType

    def mutate(self, info, order_id, reference, payment_date=None):
        return _topup_order_action(info, order_id, lambda a, r: a.verify_reference(r, reference, payment_date or ''))


class CancelVePagoMovilTopUp(graphene.Mutation):
    class Arguments:
        order_id = graphene.String(required=True)

    Output = VePagoMovilTopUpOrderType

    def mutate(self, info, order_id):
        return _topup_order_action(info, order_id, lambda a, r: a.cancel(r))


# ------------------------------------------------------------------ send

class CreateVePagoMovilSend(graphene.Mutation):
    class Arguments:
        usd_amount = graphene.String(required=True)
        cedula = graphene.String(required=True)
        phone = graphene.String(required=True)
        bank_code = graphene.String(required=True)

    Output = VePagoMovilSendOrderType

    def mutate(self, info, usd_amount, cedula, phone, bank_code):
        def run():
            user, account = _preflight(info, SEND)
            amount = _parse_usd(usd_amount)
            if amount is None:
                raise VePagoMovilError('Monto no válido.')
            # Peek only, like the Koywe Retiro: the sponsored funding batch
            # spends the approval, bound to that exact transfer.
            from security.face_step_up import FACE_STEP_UP_NEXT_STEP, missing_face_step_up
            step_up = missing_face_step_up(user, 'withdrawal', amount_usd=amount, cash_out=True)
            if step_up:
                raise VePagoMovilError(step_up, FACE_STEP_UP_NEXT_STEP)
            beneficiary = _beneficiary(cedula, phone, bank_code)
            ramp = ve_pagomovil.send_adapter().create(user, account, amount, beneficiary)
            return _send_payload(ramp)
        return _guard(VePagoMovilSendOrderType, run)


class StartVePagoMovilSendFunding(graphene.Mutation):
    """Claim the single funding of a send; answers the vouched target."""

    class Arguments:
        order_id = graphene.String(required=True)

    Output = VePagoMovilSendOrderType

    def mutate(self, info, order_id):
        def run():
            from ramps.schema import _get_ramp_account_for_user
            user = _user(info)
            ramp = ve_pagomovil.owned_order(user, order_id, SEND)
            if not ramp:
                raise VePagoMovilError('Envío no encontrado.')
            if not ve_pagomovil.enabled(SEND):
                raise VePagoMovilError(SEND_UNAVAILABLE)
            # Only the personal account whose wallet the order was made for
            # may fund it (the app signs with the ACTIVE account's wallet, and
            # the funding proof requires the transfer to come from it).
            account = _get_ramp_account_for_user(info, user)
            wallet = (getattr(account, 'bsc_address', '') or '').strip().lower()
            if (not account or getattr(account, 'account_type', None) != 'personal'
                    or wallet != (ramp.actor_address or '').lower()):
                raise VePagoMovilError('Cambia a tu cuenta personal para continuar este envío.')
            return _send_payload(ve_send.start_funding(ramp), with_funding=True)
        return _guard(VePagoMovilSendOrderType, run)


class ReportVePagoMovilSendFunding(graphene.Mutation):
    """The app broadcast the funding batch (txHash), or may have (no hash)."""

    class Arguments:
        order_id = graphene.String(required=True)
        tx_hash = graphene.String()

    Output = VePagoMovilSendOrderType

    def mutate(self, info, order_id, tx_hash=None):
        def run():
            ramp = ve_pagomovil.owned_order(_user(info), order_id, SEND)
            if not ramp:
                raise VePagoMovilError('Envío no encontrado.')
            # Allowed with the rail switched off: the money may already be out.
            ramp = ve_send.report_funding(ramp, tx_hash)
            try:
                ramp = ve_send.sync(ramp)
            except Exception:  # noqa: BLE001 — the poller proves it within a minute
                logger.warning('Immediate funding check failed for send %s', ramp.pk, exc_info=True)
                ramp.refresh_from_db()
            return _send_payload(ramp)
        return _guard(VePagoMovilSendOrderType, run)


class CancelVePagoMovilSend(graphene.Mutation):
    class Arguments:
        order_id = graphene.String(required=True)

    Output = VePagoMovilSendOrderType

    def mutate(self, info, order_id):
        def run():
            ramp = ve_pagomovil.owned_order(_user(info), order_id, SEND)
            if not ramp:
                raise VePagoMovilError('Envío no encontrado.')
            return _send_payload(ve_send.cancel(ramp))
        return _guard(VePagoMovilSendOrderType, run)


# ------------------------------------------------------------------ queries

class Query(graphene.ObjectType):
    ve_pagomovil_banks = graphene.List(VePagoMovilBankType)
    ve_pagomovil_top_up_quote = graphene.Field(VePagoMovilTopUpQuoteType, usd_amount=graphene.String(required=True))
    ve_pagomovil_top_up_order = graphene.Field(VePagoMovilTopUpOrderType, order_id=graphene.String(required=True))
    ve_pagomovil_active_top_up = graphene.Field(VePagoMovilTopUpOrderType)
    ve_pagomovil_send_quote = graphene.Field(VePagoMovilSendQuoteType, usd_amount=graphene.String(required=True))
    ve_pagomovil_send_order = graphene.Field(VePagoMovilSendOrderType, order_id=graphene.String(required=True))
    ve_pagomovil_active_send = graphene.Field(VePagoMovilSendOrderType)

    def resolve_ve_pagomovil_banks(self, info):
        if not _user(info):
            return []
        return [VePagoMovilBankType(code=code, name=name) for code, name in ve_pagomovil.BANKS]

    def resolve_ve_pagomovil_top_up_quote(self, info, usd_amount):
        def run():
            if not _user(info):
                raise VePagoMovilError('Authentication required')
            if not ve_pagomovil.enabled(TOPUP):
                raise VePagoMovilError(TOPUP_UNAVAILABLE)
            amount = _parse_usd(usd_amount)
            if amount is None:
                raise VePagoMovilError('Monto no válido.')
            quote = ve_pagomovil.topup_adapter().quote(amount)
            quote.setdefault('max_usd', str(getattr(settings, 'VE_PAGOMOVIL_TOPUP_MAX_USD', '100')))
            return VePagoMovilTopUpQuoteType(success=True, **quote)
        return _guard(VePagoMovilTopUpQuoteType, run)

    def resolve_ve_pagomovil_top_up_order(self, info, order_id):
        ramp = ve_pagomovil.owned_order(_user(info), order_id, TOPUP)
        if not ramp:
            return VePagoMovilTopUpOrderType(success=False, error='Recarga no encontrada.')
        return _guard(VePagoMovilTopUpOrderType, lambda: _topup_payload(ramp))

    def resolve_ve_pagomovil_active_top_up(self, info):
        user = _user(info)
        ramp = ve_pagomovil.active_order(user, TOPUP) if user else None
        return _topup_payload(ramp) if ramp else None

    def resolve_ve_pagomovil_send_quote(self, info, usd_amount):
        def run():
            if not _user(info):
                raise VePagoMovilError('Authentication required')
            if not ve_pagomovil.enabled(SEND):
                raise VePagoMovilError(SEND_UNAVAILABLE)
            amount = _parse_usd(usd_amount)
            if amount is None:
                raise VePagoMovilError('Monto no válido.')
            quote = ve_pagomovil.send_adapter().quote(amount)
            quote.setdefault('min_usd', format(ve_pagomovil.setting_decimal('VE_PAGOMOVIL_SEND_MIN_USD', '5'), 'f'))
            quote.setdefault('max_usd', format(ve_pagomovil.setting_decimal('VE_PAGOMOVIL_SEND_MAX_USD', '100'), 'f'))
            return VePagoMovilSendQuoteType(success=True, **quote)
        return _guard(VePagoMovilSendQuoteType, run)

    def resolve_ve_pagomovil_send_order(self, info, order_id):
        ramp = ve_pagomovil.owned_order(_user(info), order_id, SEND)
        if not ramp:
            return VePagoMovilSendOrderType(success=False, error='Envío no encontrado.')
        return _send_payload(ramp)

    def resolve_ve_pagomovil_active_send(self, info):
        user = _user(info)
        ramp = ve_pagomovil.active_order(user, SEND) if user else None
        return _send_payload(ramp) if ramp else None


class Mutation(graphene.ObjectType):
    create_ve_pagomovil_top_up = CreateVePagoMovilTopUp.Field()
    confirm_ve_pagomovil_top_up_key = ConfirmVePagoMovilTopUpKey.Field()
    verify_ve_pagomovil_top_up = VerifyVePagoMovilTopUp.Field()
    cancel_ve_pagomovil_top_up = CancelVePagoMovilTopUp.Field()
    create_ve_pagomovil_send = CreateVePagoMovilSend.Field()
    start_ve_pagomovil_send_funding = StartVePagoMovilSendFunding.Field()
    report_ve_pagomovil_send_funding = ReportVePagoMovilSendFunding.Field()
    cancel_ve_pagomovil_send = CancelVePagoMovilSend.Field()
