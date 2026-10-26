"""QR Bolivia adapter: Stereum (ramps/stereum_client.StereumLiveClient).

Recibir: an OTC BUY order is itself the QR. Its `paymentInstructions` carry a
bolivianos QR for the payer; once paid, Stereum sends the quoted USDC on
Polygon to the order's `outputAccountAddress`, a Relay deposit address that
bridges to the person's BSC wallet (ROUTE_AT_CREATION). The quote fixes the
amount, so the Relay address is made for exactly that.

Pagar (just in time, per order): `decode-qr` reads the QR; at the funding
claim an OTC SELL for this order tells where to send its USDC on Polygon and
sells it for bolivianos into our corporate account; once that SELL is done,
`send-qr` pays the decoded QR from the account. Nothing is pre-funded.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import ROUND_DOWN, ROUND_UP, Decimal, InvalidOperation

from django.conf import settings

from ramps import ve_send
from ramps.bolivia_qr import BoliviaQrError
from ramps.stereum_client import StereumError, StereumLiveClient

logger = logging.getLogger(__name__)

PROVIDER = 'stereum'
COUNTRY, FIAT, LIMIT_PREFIX = 'BO', 'BOB', 'BOLIVIA_QR_SEND'
ROUTE_AT_CREATION = True
PAYMENT_AT_CREATION = False  # the SELL quote lives ~5 minutes: made at the claim
SHARED_DEPOSIT_TARGET = False
TARGET_AT_CLAIM = True
PENDING_STALE = timedelta(hours=2)
USDC_DECIMALS = 6
NAMESPACE = uuid.UUID('6f2b8f6e-3c1a-4f53-9d2a-6b0b9a8f6a11')
UNAVAILABLE = 'QR Bolivia no está disponible por ahora.'
GENERIC_ERROR = 'No pudimos procesar el QR. Intenta de nuevo en unos minutos.'
PAID_TRANSFER = {'VERIFICADO', 'PAGADO', 'ENVIADO', 'COMPLETADO'}
FAILED = {'CANCELADO', 'CANCELADA', 'ERROR', 'RECHAZADO', 'FALLIDO'}
EXPIRED = {'EXPIRADO', 'EXPIRADA'}


def _client() -> StereumLiveClient:
    try:
        client = StereumLiveClient()
    except StereumError as exc:
        raise BoliviaQrError(UNAVAILABLE) from exc
    if not client.api_key:
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


def _units(usdc: Decimal, rounding=ROUND_UP) -> int:
    return int((usdc * Decimal(10 ** USDC_DECIMALS)).to_integral_value(rounding=rounding))


def _key(*parts) -> str:
    return str(uuid.uuid5(NAMESPACE, ':'.join(str(p) for p in parts)))


def _expiry(value) -> str:
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(int(value) / 1000, tz=dt_timezone.utc).isoformat()
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).isoformat()
    except (TypeError, ValueError, OSError):
        return ''


def _order(client, order_id: str) -> dict | None:
    body = client.list_orders()
    items = body.get('items') if isinstance(body, dict) else body
    for row in items or []:
        if isinstance(row, dict) and str(row.get('id')) == str(order_id):
            return row
    return None


def replay_window() -> timedelta:
    return timedelta(minutes=30)


# ------------------------------------------------------------------ receive

def quote_receive(bob: Decimal) -> dict:
    try:
        body = _client().otc_quote(side='BUY', input_amount=bob, input_currency='BOB', output_currency='USDC',
                                   customer=getattr(settings, 'STEREUM_OTC_CUSTOMER', 'SELF') or 'SELF')
    except StereumError as exc:
        logger.warning('Stereum receive quote failed: %s', exc)
        raise BoliviaQrError('No pudimos cotizar tu QR. Intenta de nuevo en unos minutos.') from exc
    usdc = _dec(body.get('outputAmount')).quantize(Decimal('0.000001'), rounding=ROUND_DOWN)
    if usdc <= 0 or not body.get('id'):
        raise BoliviaQrError('El monto es muy bajo.')
    return {'usdc_units': _units(usdc, ROUND_DOWN), 'usd_estimate': format(usdc, 'f'),
            'rate': str(body.get('exchangeRate') or ''), 'fee_bob': str(body.get('serviceFee') or '0'),
            'quote_id': str(body['id'])}


def create_receive(ramp, *, bob, usdc_units, deposit_address, pay_by=None) -> dict:
    """The BUY order paying the Relay address; its instructions are the QR."""
    from ramps.bolivia_qr_receive import _section as receive_section
    quote_id = (receive_section(ramp).get('terms') or {}).get('quote_id')
    if not quote_id:
        raise BoliviaQrError(GENERIC_ERROR)
    try:
        body = _client().create_order({'idempotencyKey': _key(ramp.external_id, 'buy'), 'quoteId': quote_id,
                                       'outputAccountAddress': deposit_address, 'outputNetwork': 'POLYGON'})
    except StereumError as exc:
        if exc.ambiguous:
            raise
        raise BoliviaQrError('No pudimos crear tu QR. Intenta de nuevo en unos minutos.') from exc
    instructions = body.get('paymentInstructions') if isinstance(body, dict) else None
    if not isinstance(instructions, dict) or not instructions.get('qrBase64'):
        raise BoliviaQrError(GENERIC_ERROR)
    if _units(_dec(body.get('outputAmount')), ROUND_DOWN) != int(usdc_units):
        # The Relay address was quoted for exactly this amount.
        raise BoliviaQrError(GENERIC_ERROR)
    expires = _expiry(instructions.get('expiresAt'))
    # The QR itself must stop being payable before the Relay address does (a
    # shared or saved image can be paid late); its lifetime cannot be set here,
    # so a missing or later expiry is refused. The unpaid order just lapses.
    if pay_by is not None and (not expires or datetime.fromisoformat(expires) > pay_by):
        raise BoliviaQrError('No pudimos crear tu QR. Intenta de nuevo en unos minutos.')
    return {'qr_image': str(instructions['qrBase64']), 'qr_text': '', 'provider_id': str(body.get('id') or ''),
            'expires_at': expires}


def receive_status(ramp) -> str:
    from ramps.bolivia_qr_receive import _section as receive_section
    order_id = receive_section(ramp).get('provider_id') or ramp.provider_order_id
    row = _order(_client(), order_id) if order_id else None
    if row is None:
        return 'unknown'
    status = str(row.get('status') or '').upper()
    if status in PAID_TRANSFER:
        return 'paid'
    if status in EXPIRED:
        return 'expired'
    if status in FAILED:
        return 'failed'
    if status == 'PENDIENTE':
        return 'unpaid'
    return 'processing'


def deliver(ramp, *, usdc_units, deposit_address) -> dict:  # pragma: no cover - ROUTE_AT_CREATION
    raise BoliviaQrError(GENERIC_ERROR)


# ------------------------------------------------------------------ pay: decode + price

def decode(qr_text: str) -> dict:
    try:
        body = _client().decode_qr(qr_text)
    except StereumError as exc:
        raise BoliviaQrError('No pudimos leer ese QR. Revisa que sea un QR de un banco boliviano.') from exc
    if not isinstance(body, dict) or not body.get('id'):
        raise BoliviaQrError('No pudimos leer ese QR. Revisa que sea un QR de un banco boliviano.')
    if str(body.get('currency') or '').upper() != 'BOB':
        raise BoliviaQrError('Ese QR no es en bolivianos.')
    try:
        if date.fromisoformat(str(body.get('expiration_date'))) < date.today():
            raise BoliviaQrError('Ese QR ya venció.')
    except ValueError:
        pass
    amount = _dec(body.get('amount') or 0)
    account = str(body.get('account_number') or '')
    return {
        'holder_name': str(body.get('destination_name') or '')[:120],
        'bank_name': str(body.get('bank_name') or '')[:120], 'bank_code': str(body.get('bank_code') or '')[:20],
        'account_last4': account[-4:], 'amount': format(amount, '.2f') if amount > 0 else '',
        'fixed_amount': amount > 0, 'expires_on': str(body.get('expiration_date') or '')[:30],
        # Kept on the order for send-qr; never returned to the app.
        'raw': {'id': str(body['id']), 'account_number': account,
                'document_number': str(body.get('document_number') or ''),
                'destination_name': str(body.get('destination_name') or ''),
                'bank_code': str(body.get('bank_code') or ''), 'single_use': body.get('single_use')},
    }


def _sell_quote(client, usdc: Decimal) -> dict:
    return client.otc_quote(side='SELL', input_amount=usdc, input_currency='USDC', output_currency='BOB',
                            customer=getattr(settings, 'STEREUM_OTC_CUSTOMER', 'SELF') or 'SELF')


def _sell_for(client, bob: Decimal) -> dict:
    """A SELL quote whose bolivianos cover `bob` (fees are taken in the quote)."""
    probe = _sell_quote(client, Decimal('10'))
    rate = _dec(probe.get('outputAmount')) / Decimal('10')
    if rate <= 0:
        raise BoliviaQrError(GENERIC_ERROR)
    usdc = (bob / rate * Decimal('1.002')).quantize(Decimal('0.01'), rounding=ROUND_UP)
    for _ in range(3):
        quote = _sell_quote(client, usdc)
        out = _dec(quote.get('outputAmount'))
        if out >= bob:
            return quote
        usdc = (usdc * bob / out * Decimal('1.001')).quantize(Decimal('0.01'), rounding=ROUND_UP)
    raise BoliviaQrError(GENERIC_ERROR)


def quote_send(bob: Decimal) -> dict:
    try:
        quote = _sell_for(_client(), bob)
    except StereumError as exc:
        raise BoliviaQrError('No pudimos cotizar el pago. Intenta de nuevo en unos minutos.') from exc
    usdc = _dec(quote.get('inputAmount'))
    return {'usdc_units': _units(usdc), 'rate': str(quote.get('exchangeRate') or '')}


def create_payment(ramp, *, qr_text: str, bob: Decimal, fixed_amount: bool) -> dict:
    """At the funding claim: this order's SELL into the corporate account; its
    instructions are where the bridged USDC must arrive."""
    account = getattr(settings, 'STEREUM_BOB_ACCOUNT_NUMBER', '')
    bank_type = getattr(settings, 'STEREUM_BOB_ACCOUNT_BANK_TYPE', '')
    holder = getattr(settings, 'STEREUM_BOB_ACCOUNT_HOLDER', '')
    document = getattr(settings, 'STEREUM_BOB_ACCOUNT_DOCUMENT', '')
    if not (account and bank_type and holder and document):
        raise BoliviaQrError(UNAVAILABLE)
    client = _client()
    section = ve_send._section(ramp)
    try:
        quote = _sell_for(client, bob)
        body = client.create_order({
            'idempotencyKey': _key(ramp.external_id, 'sell', section.get('payout_attempt') or 0),
            'quoteId': quote['id'], 'outputAccountAddress': account, 'outputNetwork': bank_type,
            'outputAccountOwnerName': holder, 'outputAccountDocNumber': document})
    except StereumError as exc:
        if exc.ambiguous:
            raise
        raise BoliviaQrError('No pudimos preparar el pago de ese QR.') from exc
    instructions = body.get('paymentInstructions') if isinstance(body, dict) else None
    address = str((instructions or {}).get('depositAddress') or '')
    if (not isinstance(instructions, dict) or not address.startswith('0x') or len(address) != 42
            or str(instructions.get('currency') or '').upper() != 'USDC'
            or str(instructions.get('network') or '').upper() != 'POLYGON'):
        raise BoliviaQrError(GENERIC_ERROR)
    expires = _expiry(instructions.get('expiresAt'))
    if not expires:
        # Without a known deadline the order could be funded after it lapsed.
        raise BoliviaQrError(GENERIC_ERROR)
    return {'deposit_address': address.lower(), 'usdc_units': _units(_dec(instructions.get('amount'))),
            'provider_id': str(body.get('id') or ''), 'bob_out': str(body.get('outputAmount') or ''),
            'expires_at': int(datetime.fromisoformat(expires).timestamp())}


# ------------------------------------------------------------------ send core contract

def environment() -> str:
    """Which environment and credential a payment was made under."""
    return f"{getattr(settings, 'STEREUM_ENV', 'sandbox')}|{_client().scope[:16]}"


def live() -> bool:
    """Funding real dollars only into production orders (a sandbox key's
    instructions must never receive them)."""
    return getattr(settings, 'STEREUM_ENV', 'sandbox') == 'production'


def funding_target(ramp) -> dict:
    from ramps import bolivia_qr_send
    return bolivia_qr_send.relay_target(ramp, live())


def _network(client, bank_code: str) -> str:
    banks = client.banks()
    networks = {b.get('type') for b in banks if isinstance(b, dict) and str(b.get('code')) in
                {str(bank_code), 'MLD' + str(bank_code)} and isinstance(b.get('type'), str)}
    if len(networks) != 1:
        raise BoliviaQrError('No podemos pagar a ese banco por ahora.')
    return networks.pop()


def preflight_send(user, preview: dict) -> dict:
    """Before any money moves: the sender identity Stereum accepts, the
    recipient's bank, and our account. Snapshotted for the payout."""
    from ramps.stereum_customers import current_identity
    if not all(getattr(settings, name, '') for name in (
            'STEREUM_BOB_ACCOUNT_NUMBER', 'STEREUM_BOB_ACCOUNT_BANK_TYPE', 'STEREUM_BOB_ACCOUNT_HOLDER',
            'STEREUM_BOB_ACCOUNT_DOCUMENT', 'STEREUM_BOB_ACCOUNT_ID', 'STEREUM_SECRET_KEY', 'STEREUM_COMPANY_ID')):
        raise BoliviaQrError(UNAVAILABLE)
    client = _client()
    try:
        identity = current_identity(user, scope=client.scope)
        network = _network(client, (preview.get('raw') or {}).get('bank_code') or '')
    except StereumError as exc:
        raise BoliviaQrError('Para pagar QR en Bolivia necesitamos tu carnet boliviano o tu pasaporte '
                             'verificado.', 'verification') from exc
    return {'name': f'{identity.verified_first_name} {identity.verified_last_name}'.strip()[:100],
            'document': identity.document_number, 'identity_id': identity.pk, 'network': network}


def settle(ramp):
    from ramps import bolivia_qr_send
    return bolivia_qr_send.settle(ramp)


def payout_terms(ramp, inflight) -> dict | None:
    """Payable once this order's SELL has put its bolivianos in the account."""
    section = ve_send._section(ramp)
    payment = section.get('provider_payment') or {}
    bob = Decimal(str((section.get('beneficiary') or {}).get('bob') or '0'))
    client = _client()
    row = _order(client, payment.get('provider_id') or '')
    status = str((row or {}).get('status') or '').upper()
    if status in FAILED | EXPIRED:
        return {'review': f'sell_{status.lower()}'}
    if status not in PAID_TRANSFER:
        return None
    balance = client.balance()
    available = _dec((balance or {}).get('availableBalance') or (balance or {}).get('balance') or 0)
    committed = sum((Decimal(str((ve_send._section(r).get('beneficiary') or {}).get('bob') or '0'))
                     for r in inflight), Decimal('0'))
    if available - committed < bob:
        return None
    return {'bob': format(bob, '.2f'), 'ves_amount': format(bob, '.2f')}


def dispatch(ramp, claim) -> 've_send.Outcome':
    client = _client()
    beneficiary = ve_send._section(ramp).get('beneficiary') or {}
    raw = beneficiary.get('raw') or {}
    # Checked and snapshotted before funding (preflight_send).
    sender = beneficiary.get('sender') or {}
    if not (sender.get('name') and sender.get('document') and sender.get('network')):
        return ve_send.Outcome('unknown', reason='sender_snapshot_missing')
    payload = {
        'account_id': client.account_id, 'amount': claim['bob'], 'comment': 'Pago Confio',
        'originating_name': sender['name'], 'originating_document_number': sender['document'],
        'destination_account_address': raw.get('account_number'), 'destination_name': raw.get('destination_name'),
        'destination_document_number': raw.get('document_number'), 'destination_network': sender['network'],
        'id_qr': raw.get('id'), 'idempotency_key': _key(claim['key']),
    }
    try:
        body = client.send_transfer(payload, qr=True)
    except StereumError as exc:
        return ve_send.Outcome('ambiguous' if exc.ambiguous else 'failed', reason=exc.code or 'refused')
    return _transfer_outcome(body)


def poll(ramp) -> 've_send.Outcome':
    operation = ve_send._section(ramp).get('operation_id')
    if not operation:
        return ve_send.Outcome('unknown', reason='no_operation_id')
    try:
        body = _client().get_transfer(operation)
    except StereumError:
        return ve_send.Outcome('ambiguous')
    return _transfer_outcome(body)


def _transfer_outcome(body) -> 've_send.Outcome':
    status = str((body or {}).get('status') or '').upper()
    operation = str((body or {}).get('id') or '')
    if status in PAID_TRANSFER:
        return ve_send.Outcome('paid', reference=operation, operation_id=operation,
                               ves_amount=str((body or {}).get('amount') or ''))
    if status in FAILED:
        return ve_send.Outcome('failed', operation_id=operation, reason=status.lower())
    if operation:
        return ve_send.Outcome('pending', operation_id=operation)
    return ve_send.Outcome('unknown', reason=status.lower() or 'no_status')


def beneficiary_view(beneficiary: dict) -> dict:
    from ramps.bolivia_qr_send import beneficiary_view as view
    return view(beneficiary)


def active_order(user):
    return ve_send.active_order(user, PROVIDER)
