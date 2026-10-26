"""QR Bolivia adapter: Mesa de pagos (ramps/mesadepagos_client.py).

Recibir: `deposit/qr` in conversion mode. The QR's bolivianos are converted
and sent as USDC on Polygon to the address fixed at creation, a Relay deposit
address that bridges to the person's BSC wallet (ROUTE_AT_CREATION).

Pagar: `payouts/validate/qr` decodes; `payouts/qr` in conversion mode answers
with the Polygon address and the USDC amount that, once received, execute the
payment. Funding goes through the send core (ramps/ve_send.py): the person's
USDT on BSC -> Relay -> that address. The API takes QR images only, so the
scanned text is rendered back into a PNG.

Mesa de pagos has no GET by id: status comes from the history searched by
our reference (the order's external_id).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone

from ramps import ve_send
from ramps.bolivia_qr import BoliviaQrError
from ramps.mesadepagos_client import MesaDePagosClient, MesaDePagosError

logger = logging.getLogger(__name__)

PROVIDER = 'mesadepagos'
COUNTRY, FIAT, LIMIT_PREFIX = 'BO', 'BOB', 'BOLIVIA_QR_SEND'
ROUTE_AT_CREATION = True
# Each payment has its own Relay deposit address: no amount tags needed.
SHARED_DEPOSIT_TARGET = False
TARGET_AT_CLAIM = True
PENDING_STALE = timedelta(hours=2)
USDC_DECIMALS = 6
UNAVAILABLE = 'Pagar con QR Bolivia no está disponible por ahora.'
GENERIC_ERROR = 'No pudimos procesar el QR. Intenta de nuevo en unos minutos.'
PAID, FAILED_STATES = 'completed_transaction', ('reject_transaction', 'failed_transaction', 'cancelled_transaction')


def _client() -> MesaDePagosClient:
    client = MesaDePagosClient()
    if not client.is_configured:
        raise BoliviaQrError(UNAVAILABLE)
    return client


def _dec(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BoliviaQrError(GENERIC_ERROR) from exc
    if not result.is_finite() or result < 0:
        raise BoliviaQrError(GENERIC_ERROR)
    return result


def _units(usdc: Decimal) -> int:
    return int((usdc * Decimal(10 ** USDC_DECIMALS)).to_integral_value(rounding=ROUND_UP))


def replay_window() -> timedelta:
    return timedelta(minutes=30)


# ------------------------------------------------------------------ receive

def quote_receive(bob: Decimal) -> dict:
    """How many USDC a QR of `bob` bolivianos yields (indicative: their quotes
    cannot be locked; the QR itself fixes the amounts)."""
    try:
        row = _client().quote('USDC/BOB', 'deposit_express')
    except MesaDePagosError as exc:
        logger.warning('Mesa de pagos receive quote failed: %s', exc)
        raise BoliviaQrError('No pudimos cotizar tu QR. Intenta de nuevo en unos minutos.') from exc
    rate = _dec(row.get('partnerExchangeRate') or row.get('serviceExchangeRate'))
    if rate <= 0:
        raise BoliviaQrError(GENERIC_ERROR)
    usdc = (bob / rate).quantize(Decimal('0.000001'), rounding=ROUND_DOWN)
    if usdc <= 0:
        raise BoliviaQrError('El monto es muy bajo.')
    return {'usdc_units': _units(usdc), 'usd_estimate': format(usdc, 'f'), 'rate': format(rate, 'f'), 'fee_bob': '0'}


def create_receive(ramp, *, bob, usdc_units, deposit_address, pay_by=None) -> dict:
    usdc = Decimal(usdc_units) / Decimal(10 ** USDC_DECIMALS)
    # Never payable after the Relay address it pays stops accepting.
    seconds = 15 * 60
    if pay_by is not None:
        seconds = min(seconds, int((pay_by - timezone.now()).total_seconds()))
    if seconds < 60:
        raise BoliviaQrError(GENERIC_ERROR)
    lifetime = f'{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'
    try:
        body = _client().create_deposit_qr(reference=ramp.external_id, crypto_amount=usdc,
                                           deposit_address=deposit_address, expiration=lifetime,
                                           description='Confío')
    except MesaDePagosError as exc:
        if exc.ambiguous:
            raise
        raise BoliviaQrError('No pudimos crear tu QR. Intenta de nuevo en unos minutos.') from exc
    image = str(body.get('qrCodeBase64') or '')
    # The QR must send exactly what the Relay address was quoted for.
    if not image or abs(_dec(body.get('requestedCryptoAmount')) - usdc) > Decimal('0.000001'):
        raise BoliviaQrError(GENERIC_ERROR)
    expires = timezone.now() + timedelta(seconds=seconds)
    return {'qr_image': image, 'qr_text': '', 'provider_id': str(body.get('transactionId') or ''),
            'expires_at': expires.isoformat(), 'bob': str(body.get('calculatedFiatAmount') or '')}


def receive_status(ramp) -> str:
    row = _client().find(ramp.external_id, transaction_type='deposit_express')
    if row is None:
        return 'unknown'
    status = str(row.get('status') or '')
    if status == PAID:
        return 'paid'
    if status == 'expired_transaction':
        return 'expired'
    if status in FAILED_STATES:
        return 'failed'
    if status == 'pending_transaction':
        return 'unpaid'
    return 'processing'  # received / processing: paid, still converting


def deliver(ramp, *, usdc_units, deposit_address) -> dict:  # pragma: no cover - ROUTE_AT_CREATION
    raise BoliviaQrError(GENERIC_ERROR)


# ------------------------------------------------------------------ pay: decode + price

def decode(qr_text: str) -> dict:
    """Who and how much, from the provider (never from the app)."""
    try:
        body = _client().validate_qr(qr_text)
    except MesaDePagosError as exc:
        raise BoliviaQrError('No pudimos leer ese QR. Revisa que sea un QR de un banco boliviano.') from exc
    details = body.get('details') if isinstance(body, dict) else None
    if not body or body.get('code') is None or not isinstance(details, dict):
        raise BoliviaQrError('No pudimos leer ese QR. Revisa que sea un QR de un banco boliviano.')
    if str(details.get('moneda') or 'BOB').upper() not in ('BOB', 'BS', '068'):
        raise BoliviaQrError('Ese QR no es en bolivianos.')
    amount = _dec(details.get('monto') or 0)
    return {
        'holder_name': str(details.get('titularDestino') or '')[:120],
        'bank_name': str(details.get('nombreBancoDestino') or '')[:120],
        'bank_code': str(details.get('codigoBancoDestino') or '')[:20],
        'account_last4': str(details.get('cuentaDestino') or '')[-4:],
        'document': str(details.get('ciNitDestino') or '')[:30],
        'amount': format(amount, '.2f') if amount > 0 else '',
        'fixed_amount': amount > 0,
        'reference': str(details.get('numeroReferencia') or '')[:60],
        'expires_on': str(details.get('fechaVencimiento') or '')[:30],
    }


def quote_send(bob: Decimal) -> dict:
    """Indicative USDC the provider will ask for `bob` (the payment itself
    fixes it)."""
    try:
        row = _client().quote('USDC/BOB', 'withdrawal_express')
    except MesaDePagosError as exc:
        raise BoliviaQrError('No pudimos cotizar el pago. Intenta de nuevo en unos minutos.') from exc
    rate = _dec(row.get('partnerExchangeRate') or row.get('serviceExchangeRate'))
    if rate <= 0:
        raise BoliviaQrError(GENERIC_ERROR)
    usdc = (bob / rate).quantize(Decimal('0.000001'), rounding=ROUND_UP)
    return {'usdc_units': _units(usdc), 'rate': format(rate, 'f')}


def create_payment(ramp, *, qr_text: str, bob: Decimal, fixed_amount: bool) -> dict:
    """The provider's payment, pending its funding: where and how much USDC."""
    try:
        body = _client().create_payout_qr(payload=qr_text, reference=ramp.external_id[:32], amount=bob)
    except MesaDePagosError as exc:
        if exc.ambiguous:
            raise
        if exc.status == 410:
            raise BoliviaQrError('Ese QR ya venció.') from exc
        raise BoliviaQrError('No pudimos preparar el pago de ese QR.') from exc
    address = str(body.get('deposit_address') or '')
    amount = body.get('amount_deposit')
    if not address.startswith('0x') or len(address) != 42 or amount in (None, ''):
        raise BoliviaQrError(GENERIC_ERROR)
    tx = (body.get('transactions') or {}) if isinstance(body.get('transactions'), dict) else {}
    return {'deposit_address': address.lower(), 'usdc_units': _units(_dec(amount)),
            'provider_id': str(tx.get('transaction_id') or ''), 'status': str(tx.get('status') or ''),
            # No provider-backed window: no expiry, so relay_target never funds it.
            'expires_at': int((timezone.now() + window).timestamp()) if (window := _funding_window()) else 0}


# ------------------------------------------------------------------ send core contract

def _funding_window() -> timedelta | None:
    """The payout's funding window as Mesa de pagos confirmed it (their API
    returns none); None until configured, which refuses funding."""
    try:
        minutes = int(str(getattr(settings, 'MESADEPAGOS_FUNDING_WINDOW_MINUTES', '') or '0'))
    except ValueError:
        return None
    return timedelta(minutes=minutes) if minutes > 0 else None


def environment() -> str:
    """Which API and partner account a payment was made under."""
    import hashlib
    client = MesaDePagosClient()
    return f"{client.base_url.rstrip('/')}|{hashlib.sha256(client.email.encode()).hexdigest()[:16]}"


def live() -> bool:
    """Funding real dollars only into the production API's orders."""
    return (MesaDePagosClient().base_url.rstrip('/')
            == str(getattr(settings, 'MESADEPAGOS_PRODUCTION_URL', '')).rstrip('/'))


def funding_target(ramp) -> dict:
    from ramps import bolivia_qr_send
    return bolivia_qr_send.relay_target(ramp, live())


def settle(ramp):
    from ramps import bolivia_qr_send
    return bolivia_qr_send.settle(ramp)


def payout_terms(ramp, inflight) -> dict | None:
    """The payment runs on funding at the provider; nothing to send."""
    return {'auto': True}


def dispatch(ramp, claim) -> 've_send.Outcome':
    return poll(ramp)


def poll(ramp) -> 've_send.Outcome':
    try:
        row = _client().find(ramp.external_id[:32], transaction_type='withdrawal_express')
    except MesaDePagosError:
        return ve_send.Outcome('ambiguous')
    status = str((row or {}).get('status') or '')
    operation = str((row or {}).get('transactionId') or ve_send._section(ramp).get('provider_payment', {}).get(
        'provider_id') or '')
    if status == PAID:
        return ve_send.Outcome('paid', reference=operation, operation_id=operation,
                               ves_amount=str((row or {}).get('amountFiat') or ''))
    if status in FAILED_STATES or status == 'expired_transaction':
        return ve_send.Outcome('failed', operation_id=operation, reason=status)
    return ve_send.Outcome('pending', operation_id=operation or ramp.external_id)


def beneficiary_view(beneficiary: dict) -> dict:
    from ramps.bolivia_qr_send import beneficiary_view as view
    return view(beneficiary)


def active_order(user):
    return ve_send.active_order(user, PROVIDER)
