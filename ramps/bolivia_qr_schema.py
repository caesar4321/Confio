"""GraphQL for QR Bolivia: receive with a QR and pay any Bolivian QR.

Provider-neutral (ramps.bolivia_qr): the app never learns which provider does
the work. Its own operations, so an older server fails only these screens.
Personal accounts, owner only, identity-verified; each direction behind its
explicit switch and app floor. Sends run on the shared send core
(ramps/ve_send.py): the funding claim and report reuse its rules.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

import graphene

from ramps import bolivia_qr, bolivia_qr_receive, bolivia_qr_send, ve_send
from ramps.bolivia_qr import RECEIVE, SEND, BoliviaQrError
from ramps.ve_pagomovil import VePagoMovilError

logger = logging.getLogger(__name__)

GENERIC_ERROR = 'No pudimos procesar la operación. Intenta de nuevo en unos minutos.'
NOT_FOUND = 'Operación no encontrada.'


# ------------------------------------------------------------------ types

class KoyweReplacedType(graphene.ObjectType):
    """Koywe rows QR Bolivia takes over for this person right now."""
    top_up = graphene.Boolean(required=True)
    withdraw = graphene.Boolean(required=True)


class BoliviaQrAvailabilityType(graphene.ObjectType):
    receive = graphene.Boolean(required=True)
    send = graphene.Boolean(required=True)


class BoliviaQrReceiveQuoteType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    bob_amount = graphene.String()
    usd_estimate = graphene.String()
    rate = graphene.String()
    fee_bob = graphene.String()


class BoliviaQrReceiveOrderType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    next_step = graphene.String()
    order_id = graphene.String()
    status = graphene.String()
    phase = graphene.String()
    bob_amount = graphene.String()
    usd_estimate = graphene.String()
    usd_received = graphene.String()
    rate = graphene.String()
    fee_bob = graphene.String()
    qr_text = graphene.String()
    qr_image = graphene.String()
    expires_at = graphene.String()
    cancelled = graphene.Boolean()
    created_at = graphene.String()


class BoliviaQrRecipientType(graphene.ObjectType):
    holder_name = graphene.String()
    bank_name = graphene.String()
    account_last4 = graphene.String()
    amount = graphene.String()
    fixed_amount = graphene.Boolean()
    expires_on = graphene.String()


class BoliviaQrSendQuoteType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    recipient = graphene.Field(BoliviaQrRecipientType)
    bob_amount = graphene.String()
    usd_amount = graphene.String()
    usdt_amount = graphene.String()
    confio_fee_usd = graphene.String()
    rate = graphene.String()


class BoliviaQrFundingType(graphene.ObjectType):
    deposit_address = graphene.String()
    network = graphene.String()
    deposit_amount_wei = graphene.String()
    gross_debit_amount_wei = graphene.String()
    expires_at = graphene.Int()


class BoliviaQrSendOrderType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    next_step = graphene.String()
    order_id = graphene.String()
    status = graphene.String()
    status_detail = graphene.String()
    phase = graphene.String()
    usd_amount = graphene.String()
    usdt_amount = graphene.String()
    bob_amount = graphene.String()
    holder_name = graphene.String()
    bank_name = graphene.String()
    account_last4 = graphene.String()
    funding_tx_hash = graphene.String()
    bank_reference = graphene.String()
    can_cancel = graphene.Boolean()
    can_fund = graphene.Boolean()
    wallet = graphene.String()
    funding = graphene.Field(BoliviaQrFundingType)


# ------------------------------------------------------------------ helpers

def _user(info):
    user = getattr(info.context, 'user', None)
    return user if user and getattr(user, 'is_authenticated', False) else None


def _guard(error_type, fn):
    try:
        return fn()
    except VePagoMovilError as exc:  # BoliviaQrError and the send core's refusals
        extra = {'next_step': exc.next_step} if 'next_step' in error_type._meta.fields else {}
        return error_type(success=False, error=str(exc), **extra)
    except Exception:  # noqa: BLE001 — never leak provider internals
        logger.exception('QR Bolivia operation failed')
        return error_type(success=False, error=GENERIC_ERROR)


def _bob(value) -> Decimal | None:
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() and amount > 0 else None


def _personal_owner(info, user):
    from ramps.schema import _get_ramp_account_for_user
    account = _get_ramp_account_for_user(info, user)
    if not account or getattr(account, 'account_type', None) != 'personal':
        raise BoliviaQrError('QR Bolivia solo está disponible para cuentas personales.')
    return account


def _preflight(info, direction: str):
    """Product rules for a NEW order; (user, account) or raises."""
    from ramps.schema import _employee_ramp_denial, _get_wallet_upgrade_blocker
    user = _user(info)
    if not user:
        raise BoliviaQrError('Authentication required')
    if not bolivia_qr.offered(direction, getattr(info.context, 'META', {}), user):
        raise BoliviaQrError(bolivia_qr.UNAVAILABLE[direction])
    denial = _employee_ramp_denial(info)
    if denial:
        raise BoliviaQrError(denial)
    account = _personal_owner(info, user)
    from security.identity_status import is_identity_verified
    if not is_identity_verified(user):
        raise BoliviaQrError('Verifica tu identidad para usar QR Bolivia.', 'verification')
    if not getattr(account, 'bsc_address', None):
        raise BoliviaQrError('Tu cuenta aún no está activada en este dispositivo. '
                             'Actualiza la app e inicia sesión de nuevo.')
    blocker = _get_wallet_upgrade_blocker(user=user, account=account)
    if blocker:
        raise BoliviaQrError(blocker)
    if direction == SEND:
        from django.conf import settings
        if getattr(settings, 'CUSD_CONVERSION_FEE_ENABLED', False):
            try:
                from cusd_plus.cusd_vault import require_operational
                require_operational()
            except Exception as exc:  # noqa: BLE001
                logger.exception('cUSD perimeter preflight failed before a QR Bolivia send')
                raise BoliviaQrError('Las conversiones de dólares están pausadas temporalmente.') from exc
    return user, account


def _receive_payload(ramp) -> BoliviaQrReceiveOrderType:
    return BoliviaQrReceiveOrderType(success=True, **bolivia_qr_receive.view(ramp))


def _send_payload(ramp, *, with_funding: bool = False) -> BoliviaQrSendOrderType:
    view = ve_send.view(ramp, with_funding=with_funding)
    beneficiary = view.get('beneficiary') or {}
    funding = view.get('funding')
    return BoliviaQrSendOrderType(
        success=True, order_id=str(ramp.internal_id), status=ramp.status, status_detail=ramp.status_detail,
        phase=view.get('phase'), usd_amount=view.get('usd_amount'), usdt_amount=view.get('usdt_amount'),
        bob_amount=beneficiary.get('bob') or view.get('estimated_fiat'),
        holder_name=beneficiary.get('holder_name'), bank_name=beneficiary.get('bank_name'),
        account_last4=beneficiary.get('account_last4'), funding_tx_hash=view.get('funding_tx_hash'),
        bank_reference=view.get('bank_reference'), can_cancel=view.get('can_cancel'),
        can_fund=view.get('can_fund'), wallet=view.get('wallet'),
        funding=BoliviaQrFundingType(**funding) if funding else None)


def _recipient(preview: dict) -> BoliviaQrRecipientType:
    return BoliviaQrRecipientType(
        holder_name=preview.get('holder_name'), bank_name=preview.get('bank_name'),
        account_last4=preview.get('account_last4'), amount=preview.get('amount') or None,
        fixed_amount=bool(preview.get('fixed_amount')), expires_on=preview.get('expires_on') or None)


# ------------------------------------------------------------------ receive

class CreateBoliviaQrReceive(graphene.Mutation):
    class Arguments:
        bob_amount = graphene.String(required=True)

    Output = BoliviaQrReceiveOrderType

    def mutate(self, info, bob_amount):
        def run():
            user, account = _preflight(info, RECEIVE)
            bob = _bob(bob_amount)
            if bob is None:
                raise BoliviaQrError('Escribe el monto en bolivianos.')
            return _receive_payload(bolivia_qr_receive.create(user, account, bob))
        return _guard(BoliviaQrReceiveOrderType, run)


class CancelBoliviaQrReceive(graphene.Mutation):
    class Arguments:
        order_id = graphene.String(required=True)

    Output = BoliviaQrReceiveOrderType

    def mutate(self, info, order_id):
        def run():
            ramp = bolivia_qr_receive.owned_order(_user(info), order_id)
            if not ramp:
                raise BoliviaQrError(NOT_FOUND)
            return _receive_payload(bolivia_qr_receive.cancel(ramp))
        return _guard(BoliviaQrReceiveOrderType, run)


# ------------------------------------------------------------------ send

class CreateBoliviaQrSend(graphene.Mutation):
    class Arguments:
        qr_text = graphene.String(required=True)
        bob_amount = graphene.String()
        # The debit the person approved on screen: never charged more.
        max_usd_amount = graphene.String(required=True)

    Output = BoliviaQrSendOrderType

    def mutate(self, info, qr_text, max_usd_amount, bob_amount=None):
        def run():
            user, account = _preflight(info, SEND)
            terms = bolivia_qr_send.quote(qr_text, bob_amount)
            # Peek only (like the Koywe Retiro): the sponsored funding batch
            # spends the approval, bound to that exact transfer.
            from security.face_step_up import FACE_STEP_UP_NEXT_STEP, missing_face_step_up
            step_up = missing_face_step_up(user, 'withdrawal', amount_usd=Decimal(terms['usd_amount']),
                                           cash_out=True)
            if step_up:
                raise BoliviaQrError(step_up, FACE_STEP_UP_NEXT_STEP)
            return _send_payload(bolivia_qr_send.create(user, account, qr_text, bob_amount, max_usd=max_usd_amount))
        return _guard(BoliviaQrSendOrderType, run)


class StartBoliviaQrSendFunding(graphene.Mutation):
    """Claim the single funding of a send; answers the vouched target."""

    class Arguments:
        order_id = graphene.String(required=True)

    Output = BoliviaQrSendOrderType

    def mutate(self, info, order_id):
        def run():
            from ramps.schema import _get_ramp_account_for_user
            user = _user(info)
            ramp = bolivia_qr_send.owned_order(user, order_id)
            if not ramp:
                raise BoliviaQrError(NOT_FOUND)
            if not (bolivia_qr.enabled(SEND) or bolivia_qr.is_tester(user)):
                raise BoliviaQrError(bolivia_qr.UNAVAILABLE[SEND])
            account = _get_ramp_account_for_user(info, user)
            wallet = (getattr(account, 'bsc_address', '') or '').strip().lower()
            if (not account or getattr(account, 'account_type', None) != 'personal'
                    or wallet != (ramp.actor_address or '').lower()):
                raise BoliviaQrError('Cambia a tu cuenta personal para continuar este pago.')
            return _send_payload(ve_send.start_funding(ramp), with_funding=True)
        return _guard(BoliviaQrSendOrderType, run)


class ReportBoliviaQrSendFunding(graphene.Mutation):
    class Arguments:
        order_id = graphene.String(required=True)
        tx_hash = graphene.String()

    Output = BoliviaQrSendOrderType

    def mutate(self, info, order_id, tx_hash=None):
        def run():
            ramp = bolivia_qr_send.owned_order(_user(info), order_id)
            if not ramp:
                raise BoliviaQrError(NOT_FOUND)
            # Allowed with the switch off: the money may already be out.
            ramp = ve_send.report_funding(ramp, tx_hash)
            try:
                ramp = ve_send.sync(ramp)
            except Exception:  # noqa: BLE001 — the poller proves it within a minute
                logger.warning('Immediate funding check failed for QR Bolivia send %s', ramp.pk, exc_info=True)
                ramp.refresh_from_db()
            return _send_payload(ramp)
        return _guard(BoliviaQrSendOrderType, run)


class CancelBoliviaQrSend(graphene.Mutation):
    class Arguments:
        order_id = graphene.String(required=True)

    Output = BoliviaQrSendOrderType

    def mutate(self, info, order_id):
        def run():
            ramp = bolivia_qr_send.owned_order(_user(info), order_id)
            if not ramp:
                raise BoliviaQrError(NOT_FOUND)
            return _send_payload(ve_send.cancel(ramp))
        return _guard(BoliviaQrSendOrderType, run)


# ------------------------------------------------------------------ queries

class Query(graphene.ObjectType):
    bolivia_qr_koywe_replaced = graphene.Field(KoyweReplacedType, required=True)
    bolivia_qr_availability = graphene.Field(BoliviaQrAvailabilityType, required=True)
    bolivia_qr_receive_quote = graphene.Field(BoliviaQrReceiveQuoteType, bob_amount=graphene.String(required=True))
    bolivia_qr_active_receive = graphene.Field(BoliviaQrReceiveOrderType)
    bolivia_qr_receive_order = graphene.Field(BoliviaQrReceiveOrderType, order_id=graphene.String(required=True))
    bolivia_qr_send_quote = graphene.Field(BoliviaQrSendQuoteType, qr_text=graphene.String(required=True),
                                           bob_amount=graphene.String())
    bolivia_qr_active_send = graphene.Field(BoliviaQrSendOrderType)
    bolivia_qr_send_order = graphene.Field(BoliviaQrSendOrderType, order_id=graphene.String(required=True))

    def resolve_bolivia_qr_koywe_replaced(self, info):
        replaced = bolivia_qr.koywe_replaced(_user(info), getattr(info.context, 'META', {}))
        return KoyweReplacedType(top_up=replaced['top_up'], withdraw=replaced['withdraw'])

    def resolve_bolivia_qr_availability(self, info):
        meta, user = getattr(info.context, 'META', {}), _user(info)
        return BoliviaQrAvailabilityType(receive=bolivia_qr.offered(RECEIVE, meta, user),
                                         send=bolivia_qr.offered(SEND, meta, user))

    def resolve_bolivia_qr_receive_quote(self, info, bob_amount):
        def run():
            if not _user(info):
                raise BoliviaQrError('Authentication required')
            if not bolivia_qr.offered(RECEIVE, getattr(info.context, 'META', {}), _user(info)):
                raise BoliviaQrError(bolivia_qr.UNAVAILABLE[RECEIVE])
            bob = _bob(bob_amount)
            if bob is None:
                raise BoliviaQrError('Escribe el monto en bolivianos.')
            terms = bolivia_qr_receive.quote(bob)
            return BoliviaQrReceiveQuoteType(success=True, bob_amount=format(bob, '.2f'),
                                             usd_estimate=terms.get('usd_estimate'), rate=terms.get('rate'),
                                             fee_bob=terms.get('fee_bob'))
        return _guard(BoliviaQrReceiveQuoteType, run)

    def resolve_bolivia_qr_active_receive(self, info):
        user = _user(info)
        ramp = bolivia_qr_receive.active_order(user) if user else None
        return _guard(BoliviaQrReceiveOrderType, lambda: _receive_payload(ramp)) if ramp else None

    def resolve_bolivia_qr_receive_order(self, info, order_id):
        ramp = bolivia_qr_receive.owned_order(_user(info), order_id)
        if not ramp:
            return BoliviaQrReceiveOrderType(success=False, error=NOT_FOUND)
        return _guard(BoliviaQrReceiveOrderType, lambda: _receive_payload(ramp))

    def resolve_bolivia_qr_send_quote(self, info, qr_text, bob_amount=None):
        def run():
            if not _user(info):
                raise BoliviaQrError('Authentication required')
            if not bolivia_qr.offered(SEND, getattr(info.context, 'META', {}), _user(info)):
                raise BoliviaQrError(bolivia_qr.UNAVAILABLE[SEND])
            preview = bolivia_qr_send.decode(qr_text)
            if not preview.get('fixed_amount') and _bob(bob_amount) is None:
                # An open-amount QR: show who receives; the person types the amount.
                return BoliviaQrSendQuoteType(success=True, recipient=_recipient(preview))
            terms = bolivia_qr_send.quote(qr_text, bob_amount)
            return BoliviaQrSendQuoteType(
                success=True, recipient=_recipient(terms['preview']), bob_amount=terms['bob_amount'],
                usd_amount=terms['usd_amount'], usdt_amount=terms['usdt_amount'],
                confio_fee_usd=terms['confio_fee_usd'], rate=terms['rate'])
        return _guard(BoliviaQrSendQuoteType, run)

    def resolve_bolivia_qr_active_send(self, info):
        user = _user(info)
        ramp = bolivia_qr_send.active_order(user) if user else None
        return _guard(BoliviaQrSendOrderType, lambda: _send_payload(ramp)) if ramp else None

    def resolve_bolivia_qr_send_order(self, info, order_id):
        ramp = bolivia_qr_send.owned_order(_user(info), order_id)
        if not ramp:
            return BoliviaQrSendOrderType(success=False, error=NOT_FOUND)
        return _guard(BoliviaQrSendOrderType, lambda: _send_payload(ramp))


class Mutation(graphene.ObjectType):
    create_bolivia_qr_receive = CreateBoliviaQrReceive.Field()
    cancel_bolivia_qr_receive = CancelBoliviaQrReceive.Field()
    create_bolivia_qr_send = CreateBoliviaQrSend.Field()
    start_bolivia_qr_send_funding = StartBoliviaQrSendFunding.Field()
    report_bolivia_qr_send_funding = ReportBoliviaQrSendFunding.Field()
    cancel_bolivia_qr_send = CancelBoliviaQrSend.Field()
