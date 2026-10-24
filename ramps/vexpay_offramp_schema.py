"""GraphQL for the Venezuelan bolívar send through VEXPay (ramps/vexpay_offramp.py).

Personal accounts, owner only, identity-verified. The beneficiary may be the
user or a third party (recorded on the order). Each send spends a withdrawal
Confío Face approval bound to its exact terms; the app then funds the
server-vouched deposit address with the same audited batch as Retiro.
"""
from __future__ import annotations

import logging
from decimal import ROUND_DOWN, Decimal, InvalidOperation

import graphene
from django.core.exceptions import ValidationError as DjangoValidationError

from ramps import vexpay, vexpay_offramp
from ramps.models import RampTransaction
from ramps.vexpay_client import VexPayClient, VexPayError

logger = logging.getLogger(__name__)

UNAVAILABLE = 'Los envíos en bolívares no están disponibles por ahora.'
GENERIC_ERROR = 'No pudimos procesar el envío. Intenta de nuevo en unos minutos.'


class VexpayBeneficiaryType(graphene.ObjectType):
    cedula = graphene.String()
    phone = graphene.String()
    bank_code = graphene.String()
    bank_name = graphene.String()


class VexpayFundingType(graphene.ObjectType):
    """The vouched funding target; the app passes these to its funding path
    as confioDepositAddress / confioDepositNetwork / confioDepositAmountWei /
    confioGrossDebitAmountWei."""
    deposit_address = graphene.String()
    network = graphene.String()
    deposit_amount_wei = graphene.String()
    gross_debit_amount_wei = graphene.String()


class VexpayOffRampOrderType(graphene.ObjectType):
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
    beneficiary = graphene.Field(VexpayBeneficiaryType)
    funding = graphene.Field(VexpayFundingType)
    funding_tx_hash = graphene.String()
    bank_reference = graphene.String()
    can_cancel = graphene.Boolean()
    # The wallet the funding must come from: the app signs with it only.
    wallet = graphene.String()
    # The order is ready to be funded (once, through startVexpayOffRampFunding).
    can_fund = graphene.Boolean()


class VexpayOffRampQuoteType(graphene.ObjectType):
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


def _order_payload(ramp: RampTransaction, *, with_funding: bool = False) -> VexpayOffRampOrderType:
    section = vexpay._section(ramp)
    beneficiary = section.get('beneficiary') or {}
    # Only the start-funding claim's own answer carries the address.
    funding = vexpay_offramp.funding_details(ramp) if with_funding else None
    return VexpayOffRampOrderType(
        success=True,
        order_id=str(ramp.internal_id),
        status=ramp.status,
        status_detail=ramp.status_detail,
        phase=vexpay_offramp._phase(ramp),
        usd_amount=section.get('gross_usd'),
        usdt_amount=format(ramp.crypto_amount_estimated, 'f') if ramp.crypto_amount_estimated is not None else None,
        estimated_ves=section.get('estimated_ves'),
        ves_amount=section.get('ves_amount'),
        rate=section.get('quoted_rate'),
        beneficiary=VexpayBeneficiaryType(
            cedula=beneficiary.get('cedula'), phone=beneficiary.get('phone'),
            bank_code=beneficiary.get('bank_code'), bank_name=beneficiary.get('bank_name'),
        ) if beneficiary else None,
        funding=VexpayFundingType(
            deposit_address=funding['confioDepositAddress'],
            network=funding['confioDepositNetwork'],
            deposit_amount_wei=funding['confioDepositAmountWei'],
            gross_debit_amount_wei=funding.get('confioGrossDebitAmountWei'),
        ) if funding else None,
        funding_tx_hash=section.get('funding_tx_hash'),
        bank_reference=section.get('bank_reference'),
        can_cancel=vexpay_offramp.can_cancel(ramp),
        can_fund=vexpay_offramp.can_fund(ramp),
        wallet=ramp.actor_address,
    )


def _error(message: str, next_step: str | None = None) -> VexpayOffRampOrderType:
    return VexpayOffRampOrderType(success=False, error=message, next_step=next_step)


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
            provider=vexpay.PROVIDER, direction=vexpay_offramp.DIRECTION, actor_user=user, internal_id=order_id,
        ).first()
    except (ValueError, TypeError, DjangoValidationError):
        return None


def _preflight(info):
    """Shared gates; returns (user, account) or an error payload."""
    from ramps.schema import _employee_ramp_denial, _get_ramp_account_for_user, _get_wallet_upgrade_blocker

    user = getattr(info.context, 'user', None)
    if not (user and getattr(user, 'is_authenticated', False)):
        return _error('Authentication required')
    if not vexpay_offramp.enabled():
        return _error(UNAVAILABLE)
    denial = _employee_ramp_denial(info)
    if denial:
        return _error(denial)
    account = _get_ramp_account_for_user(info, user)
    if not account or getattr(account, 'account_type', None) != 'personal':
        return _error('Los envíos en bolívares solo están disponibles para cuentas personales.')
    from security.identity_status import is_identity_verified
    if not is_identity_verified(user):
        return _error('Verifica tu identidad para enviar bolívares.', 'verification')
    if not getattr(account, 'bsc_address', None):
        return _error('Tu cuenta aún no está activada en este dispositivo. Actualiza la app e inicia sesión de nuevo.')
    blocker = _get_wallet_upgrade_blocker(user=user, account=account)
    if blocker:
        return _error(blocker)
    return user, account


def _beneficiary(cedula, phone, bank_code, client: VexPayClient) -> dict:
    bank = vexpay.normalize_bank_code(bank_code)
    code = f'{bank:04d}'
    names = {str(b.get('code')): b.get('name') for b in (client.banks() or [])}
    if code not in names and str(bank) not in names:
        raise vexpay_offramp.VexPayOffRampError('Elige un banco de la lista.')
    return {
        'cedula': vexpay.normalize_cedula(cedula),
        'phone': vexpay.normalize_phone(phone),
        'bank_code': code,
        'bank_name': names.get(code) or names.get(str(bank)) or '',
    }


class CreateVexpayOffRamp(graphene.Mutation):
    class Arguments:
        usd_amount = graphene.String(required=True)
        cedula = graphene.String(required=True)
        phone = graphene.String(required=True)
        bank_code = graphene.String(required=True)

    Output = VexpayOffRampOrderType

    def mutate(self, info, usd_amount, cedula, phone, bank_code):
        gate = _preflight(info)
        if isinstance(gate, VexpayOffRampOrderType):
            return gate
        user, account = gate
        amount = _parse_usd(usd_amount)
        if amount is None:
            return _error('Monto no válido.')

        # Peek only, like the Koywe Retiro: the sponsored funding batch spends
        # the approval, bound to that exact transfer. One face per send.
        from security.face_step_up import FACE_STEP_UP_NEXT_STEP, missing_face_step_up
        step_up = missing_face_step_up(user, 'withdrawal', amount_usd=amount, cash_out=True)
        if step_up:
            return _error(step_up, FACE_STEP_UP_NEXT_STEP)

        client = VexPayClient()
        if not client.is_configured:
            return _error(UNAVAILABLE)
        try:
            beneficiary = _beneficiary(cedula, phone, bank_code, client)
            rate = vexpay_offramp.market_rate(client)
            gross_wei, deposit_wei = vexpay_offramp.confio_amounts(amount)
            # Where the chain scan starts: without it a lost funding hash
            # could never be found, so no order is made.
            created_block = vexpay_offramp.current_block()
            if created_block is None:
                return _error(GENERIC_ERROR)
            ramp = vexpay_offramp.reserve_off_ramp(
                user=user, account=account, gross_usd=amount, beneficiary=beneficiary, rate=rate,
                gross_wei=gross_wei, deposit_wei=deposit_wei, created_block=created_block)
        except vexpay.VexPayRampError as exc:
            return _error(str(exc))
        except VexPayError:
            logger.exception('VEXPay send preflight failed')
            return _error(GENERIC_ERROR)

        try:
            ramp = vexpay_offramp.prepare_deposit(ramp, client)
        except vexpay.VexPayRampError as exc:
            return _error(str(exc))
        return _order_payload(ramp)


class StartVexpayOffRampFunding(graphene.Mutation):
    """Claim the single funding of an order; answers the vouched address."""

    class Arguments:
        order_id = graphene.String(required=True)

    Output = VexpayOffRampOrderType

    def mutate(self, info, order_id):
        ramp = _owned_order(info, order_id)
        if not ramp:
            return _error('Envío no encontrado.')
        if not vexpay_offramp.enabled():
            return _error(UNAVAILABLE)
        # Only the personal account whose wallet the order was made for may
        # fund it (the app signs with the ACTIVE account's wallet, and the
        # funding proof requires the transfer to come from that wallet).
        from ramps.schema import _get_ramp_account_for_user
        account = _get_ramp_account_for_user(info, info.context.user)
        if (not account or getattr(account, 'account_type', None) != 'personal'
                or (getattr(account, 'bsc_address', '') or '').strip().lower() != (ramp.actor_address or '').lower()):
            return _error('Cambia a tu cuenta personal para continuar este envío.')
        try:
            ramp = vexpay_offramp.start_funding(ramp)
        except vexpay.VexPayRampError as exc:
            return _error(str(exc))
        return _order_payload(ramp, with_funding=True)


class ReportVexpayOffRampFunding(graphene.Mutation):
    """The app broadcast the funding batch (txHash), or may have (no hash)."""

    class Arguments:
        order_id = graphene.String(required=True)
        tx_hash = graphene.String()

    Output = VexpayOffRampOrderType

    def mutate(self, info, order_id, tx_hash=None):
        ramp = _owned_order(info, order_id)
        if not ramp:
            return _error('Envío no encontrado.')
        # Allowed with the rail switched off: the money may already be out.
        try:
            ramp = vexpay_offramp.report_funding(ramp, tx_hash)
        except vexpay.VexPayRampError as exc:
            return _error(str(exc))
        try:
            ramp = vexpay_offramp.sync_off_ramp(ramp)
        except Exception:  # noqa: BLE001 — the poller proves it within a minute
            logger.warning('Immediate funding check failed for send %s', ramp.pk, exc_info=True)
            ramp.refresh_from_db()
        return _order_payload(ramp)


class CancelVexpayOffRamp(graphene.Mutation):
    class Arguments:
        order_id = graphene.String(required=True)

    Output = VexpayOffRampOrderType

    def mutate(self, info, order_id):
        ramp = _owned_order(info, order_id)
        if not ramp:
            return _error('Envío no encontrado.')
        try:
            ramp = vexpay_offramp.cancel_off_ramp(ramp)
        except vexpay.VexPayRampError as exc:
            return _error(str(exc))
        return _order_payload(ramp)


class Query(graphene.ObjectType):
    vexpay_off_ramp_order = graphene.Field(VexpayOffRampOrderType, order_id=graphene.String(required=True))
    vexpay_active_off_ramp_order = graphene.Field(VexpayOffRampOrderType)
    vexpay_off_ramp_quote = graphene.Field(VexpayOffRampQuoteType, usd_amount=graphene.String(required=True))

    def resolve_vexpay_off_ramp_order(self, info, order_id):
        ramp = _owned_order(info, order_id)
        return _order_payload(ramp) if ramp else _error('Envío no encontrado.')

    def resolve_vexpay_active_off_ramp_order(self, info):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return None
        ramp = vexpay_offramp.active_order(user)
        return _order_payload(ramp) if ramp else None

    def resolve_vexpay_off_ramp_quote(self, info, usd_amount):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return VexpayOffRampQuoteType(success=False, error='Authentication required')
        if not vexpay_offramp.enabled():
            return VexpayOffRampQuoteType(success=False, error=UNAVAILABLE)
        amount = _parse_usd(usd_amount)
        if amount is None:
            return VexpayOffRampQuoteType(success=False, error='Monto no válido.')
        try:
            rate = vexpay_offramp.market_rate(VexPayClient())
            _, deposit_wei = vexpay_offramp.confio_amounts(amount)
        except vexpay.VexPayRampError as exc:
            return VexpayOffRampQuoteType(success=False, error=str(exc))
        except VexPayError:
            logger.exception('VEXPay send quote failed')
            return VexpayOffRampQuoteType(success=False, error=GENERIC_ERROR)
        usdt = Decimal(deposit_wei) / Decimal(10 ** 18)
        ves = vexpay_offramp.estimate_ves(usdt, rate)
        # The processor's share in dollars: what the bolívares would be worth
        # at the market rate without VEXPay's fee and spread.
        processor_fee = max(usdt - ves / rate, Decimal('0')) if rate > 0 else Decimal('0')
        return VexpayOffRampQuoteType(
            success=True,
            usd_amount=format(amount, 'f'),
            usdt_amount=format(usdt.quantize(vexpay_offramp.MICRO), 'f'),
            confio_fee_usd=format(max(amount - usdt, Decimal('0')).quantize(vexpay.CENT), 'f'),
            processor_fee_usd=format(processor_fee.quantize(vexpay.CENT), 'f'),
            estimated_ves=format(ves, 'f'),
            rate=format(rate, 'f'),
            min_usd=format(vexpay_offramp._setting('VEXPAY_OFFRAMP_MIN_USD', '5'), 'f'),
            max_usd=format(vexpay_offramp._setting('VEXPAY_OFFRAMP_MAX_USD', '100'), 'f'),
        )


class Mutation(graphene.ObjectType):
    create_vexpay_off_ramp = CreateVexpayOffRamp.Field()
    start_vexpay_off_ramp_funding = StartVexpayOffRampFunding.Field()
    report_vexpay_off_ramp_funding = ReportVexpayOffRampFunding.Field()
    cancel_vexpay_off_ramp = CancelVexpayOffRamp.Field()
