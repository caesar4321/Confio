"""Mobile access to the operator-only QR sandbox; never customer wallet settlement."""
from datetime import date
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from .models import StereumTestOperation
from .stereum_client import StereumClient, StereumError
from .stereum_customers import current_identity
from .stereum_service import execute, refresh


def available(user, *, personal=True):
    return bool(personal and user and user.is_authenticated and user.is_active and user.is_superuser
        and getattr(settings, 'STEREUM_TEST_ENABLED', False)
        and getattr(settings, 'STEREUM_MOBILE_QR_TEST_ENABLED', False)
        and getattr(settings, 'STEREUM_ENV', '') == 'sandbox'
        and getattr(settings, 'STEREUM_API_KEY', ''))


def require_operator(info):
    from users.jwt_context import get_jwt_business_context_with_validation
    user = info.context.user
    if not available(user):
        raise StereumError('QR Bolivia no está habilitado para esta cuenta.')
    context = get_jwt_business_context_with_validation(info)
    if not context or context.get('account_type') != 'personal':
        raise StereumError('Abre tu cuenta personal para usar QR Bolivia.')
    return user


def can_pay(user, client):
    if not getattr(settings, 'STEREUM_TEST_WRITES_ENABLED', False) or not client.account_id or not client.secret:
        return False
    try:
        current_identity(user)
    except StereumError:
        return False
    return True


def preview(operation):
    if operation.status != 'received':
        raise StereumError('No pudimos leer el QR. Revisa que sea un QR bancario de Bolivia.')
    data = operation.response_data
    try:
        value = Decimal(str(data['amount']))
        expiry = date.fromisoformat(data['expiration_date'])
        valid = (data['currency'] == 'BOB' and value.is_finite() and (value == 0 or 1 <= value <= 69000)
                 and value == value.quantize(Decimal('.01')) and type(data['single_use']) is bool
                 and isinstance(data['destination_name'], str) and bool(data['destination_name'].strip())
                 and isinstance(data['account_number'], str) and bool(data['account_number'].strip())
                 and expiry >= timezone.localdate(timezone=ZoneInfo('America/La_Paz')))
    except (KeyError, TypeError, ValueError, InvalidOperation):
        valid = False
    if not valid:
        raise StereumError('El QR está vencido o no contiene datos de pago válidos en bolivianos.')
    return dict(request_id=operation.request_id, recipient_name=data['destination_name'],
        bank_name=data.get('bank_name') or '', account_last4=data['account_number'][-4:],
        amount=format(value, '.2f'), fixed_amount=value > 0, currency='BOB', expires_on=expiry.isoformat())


def decode(user, request_id, payload):
    return preview(execute(user, 'decode_qr', {'qrs': payload}, request_id))


def pay(user, request_id, decode_request_id, amount):
    client = StereumClient()
    if not can_pay(user, client):
        raise StereumError('El pago de prueba no está habilitado. Revisa la configuración y tu identidad.')
    identity = current_identity(user)
    return execute(user, 'pay_qr', {'decode_request_id': str(decode_request_id), 'amount': amount,
        'comment': 'Pago QR de prueba', 'sender_name': f'{identity.verified_first_name} {identity.verified_last_name}',
        'sender_document': identity.document_number}, request_id, client=client)


def payment(user, request_id, *, poll=False):
    client = StereumClient()
    row = StereumTestOperation.objects.filter(request_id=request_id, actor=user,
        credential_scope=client.scope, action='pay_qr').first()
    if not row:
        return None
    if poll and row.provider_id and row.status not in {'failed', 'succeeded'}:
        row = refresh(user, row.request_id, client=client)
    return row


def pending(user, client):
    return StereumTestOperation.objects.filter(actor=user, credential_scope=client.scope,
        action='pay_qr', status__in=['submitting', 'pending', 'unknown']).order_by('created_at').first()
