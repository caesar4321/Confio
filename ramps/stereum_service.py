"""Durable sandbox exercises. No customer balances or on-chain funds are touched."""
import re
import json
import hashlib
import math
import time
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction, IntegrityError
from django.utils import timezone

from .models import StereumTestOperation
from .stereum_client import StereumClient, StereumError, amount, resource_id, validate_response


FIELDS = {
    'banks': set(), 'balance': set(), 'orders': set(),
    'quote': {'side', 'amount', 'currency'},
    'customer_quote': {'side', 'amount', 'currency'},
    'decode_qr': {'qrs'},
    'charge': {'amount', 'name', 'lastname', 'document_number', 'reason'},
    'order': {'quote_request_id', 'address', 'name', 'document_number', 'bank'},
    'pay_qr': {'decode_request_id', 'amount', 'comment', 'sender_name', 'sender_document'},
    'confirm_charge': {'charge_request_id'},
}


def permitted(user):
    if not getattr(settings, 'STEREUM_TEST_ENABLED', False):
        raise StereumError('Stereum test integration is disabled.')
    if not user or not user.is_active or not user.is_superuser:
        raise StereumError('Only administrators can operate the Stereum test integration.')


def text(data, key, *, limit=100):
    if not isinstance(data, dict):
        raise StereumError('Expected an object from Stereum.')
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise StereumError(f'{key} is required (maximum {limit} characters).')
    return value.strip()


def reference(user, client, value, action):
    try:
        identifier = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise StereumError('Invalid test operation reference.')
    result = StereumTestOperation.objects.filter(
        request_id=identifier, actor=user, credential_scope=client.scope, action__in=[action] if isinstance(action, str) else action,
        status__in=['received', 'succeeded', 'pending'],
    ).first()
    if not result:
        raise StereumError('Test operation not found for this administrator and credential.')
    return result


def consumption_key(user, client, action, data):
    """Reserve single-use provider resources across actors and request UUIDs."""
    if action == 'order':
        previous = reference(user, client, data.get('quote_request_id'), ('quote', 'customer_quote'))
        value = previous.provider_id
    elif action == 'confirm_charge':
        previous = reference(user, client, data.get('charge_request_id'), 'charge')
        value = previous.provider_id
    elif action == 'pay_qr':
        previous = reference(user, client, data.get('decode_request_id'), 'decode_qr')
        if previous.response_data.get('single_use') is not True:
            return None
        # The same scanned QR can be decoded into different provider resources.
        value = text(previous.request_data, 'qrs', limit=32768)
    else:
        return None
    return hashlib.sha256(json.dumps([client.scope, action, value]).encode()).hexdigest()


def build_call(user, client, action, data, request_id):
    if action == 'banks':
        return client.banks
    if action == 'balance':
        return client.balance
    if action == 'orders':
        return client.list_orders
    if action in {'quote', 'customer_quote'}:
        customer = 'SELF'
        if action == 'customer_quote':
            from .stereum_customers import quote_customer
            customer = quote_customer(user, client=client)
        return lambda: client.create_quote(side=text(data, 'side'), value=amount(data.get('amount')), currency=data.get('currency', 'USDT'), customer=customer)
    if action == 'decode_qr':
        return lambda: client.decode_qr(text(data, 'qrs', limit=32768))
    if action == 'charge':
        payload = {
            'country': 'BO', 'currency': 'BOB', 'network': 'CSL',
            'amount': amount(data.get('amount')), 'idempotency_key': str(request_id),
            'charge_reason': text(data, 'reason', limit=60), 'reservation_validity_time': 10,
            'customer': {key: text(data, key) for key in ['name', 'lastname', 'document_number']},
        }
        return lambda: client.create_charge(payload)
    if action == 'order':
        previous = reference(user, client, data.get('quote_request_id'), ('quote', 'customer_quote'))
        q = previous.response_data
        expiry = q.get('expireAt') if isinstance(q, dict) else None
        if not isinstance(q, dict) or not q.get('id') or type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= time.time() * 1000:
            raise StereumError('Quote expired; obtain a new quote and review its output.')
        # One persisted quote can back only one local order. A submitting or unknown
        # operation continues to consume it until manually reconciled.
        if StereumTestOperation.objects.filter(
            action='order', credential_scope=client.scope,
            request_data__quote_request_id=str(previous.request_id),
        ).exclude(request_id=request_id).exists():
            raise StereumError('This quote already has an order attempt.')
        payload = {'quoteId': q['id'], 'idempotencyKey': str(request_id), 'outputAccountAddress': text(data, 'address')}
        if previous.request_data['side'] == 'BUY':
            if not re.fullmatch(r'0x[0-9a-fA-F]{40}', payload['outputAccountAddress']):
                raise StereumError('A Polygon wallet address is required.')
            payload['outputNetwork'] = 'POLYGON'
        else:
            payload.update(outputNetwork=text(data, 'bank'), outputAccountOwnerName=text(data, 'name'), outputAccountDocNumber=text(data, 'document_number'))
        return lambda: client.create_order(payload)
    if action == 'pay_qr':
        previous = reference(user, client, data.get('decode_request_id'), 'decode_qr')
        decoded = previous.response_data
        if not isinstance(decoded, dict) or decoded.get('currency') != 'BOB':
            raise StereumError('Only BOB QR payments are supported.')
        if type(decoded.get('single_use')) is not bool:
            raise StereumError('The QR single-use restriction could not be verified.')
        try:
            if date.fromisoformat(decoded['expiration_date']) < timezone.localdate(timezone=ZoneInfo('America/La_Paz')):
                raise StereumError('The QR has expired.')
        except (KeyError, TypeError, ValueError):
            raise StereumError('The QR expiration could not be verified.')
        value = amount(data.get('amount'))
        if not 1 <= Decimal(value) <= 69000:
            raise StereumError('QR payout must be between 1 and 69,000 BOB.')
        try:
            qr_amount = Decimal(str(decoded['amount']))
        except (InvalidOperation, KeyError):
            raise StereumError('The QR amount could not be verified.') from None
        if not qr_amount.is_finite() or qr_amount < 0 or (qr_amount > 0 and Decimal(value) != qr_amount):
            raise StereumError('Payment amount must match the closed QR.')
        comment = text(data, 'comment', limit=30)
        if len(comment) < 5:
            raise StereumError('Payment description must contain 5–30 characters.')
        # Never accept caller overrides of the recipient returned by decode-qr.
        banks = client.banks()
        if not isinstance(banks, list) or not all(isinstance(b, dict) for b in banks) or not decoded.get('bank_code'):
            raise StereumError('Bank mapping could not be verified.')
        networks = {b.get('type') for b in banks if str(b.get('code')) in {str(decoded['bank_code']), 'MLD' + str(decoded['bank_code'])} and isinstance(b.get('type'), str)}
        network = next(iter(networks)) if len(networks) == 1 else None
        if not network or not client.account_id:
            raise StereumError('Bank mapping or test corporate BOB account is missing.')
        payload = {
            'account_id': client.account_id, 'amount': value, 'comment': comment,
            'originating_name': text(data, 'sender_name'), 'originating_document_number': text(data, 'sender_document'),
            'destination_account_address': text(decoded, 'account_number'),
            'destination_name': text(decoded, 'destination_name'),
            'destination_document_number': text(decoded, 'document_number'),
            'destination_network': network, 'id_qr': text(decoded, 'id'), 'idempotency_key': str(request_id),
        }
        return lambda: client.send_transfer(payload, qr=True)
    if action == 'confirm_charge':
        charge = reference(user, client, data.get('charge_request_id'), 'charge')
        flag = charge.response_data.get('on_main_net') if isinstance(charge.response_data, dict) else None
        if flag is not False and flag != 'false':
            raise StereumError('Charge has not been confirmed as a testnet resource.')
        if not client.company_id:
            raise StereumError('Test company ID is required.')
        return lambda: client.confirm_test_charge(identifier=charge.provider_id, value=charge.request_data['amount'])
    raise StereumError('Unsupported action.')


def execute(user, action, data, request_id, *, client=None):
    permission = permitted
    if action == 'customer_quote':
        from .stereum_customers import access
        permission = access
    permission(user)
    client = client or StereumClient()
    try:
        request_id = uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError):
        raise StereumError('A valid request UUID is required.')
    if action not in FIELDS or not isinstance(data, dict) or set(data) - FIELDS[action]:
        raise StereumError('Unknown action or unexpected request fields.')
    try:
        json.dumps(data, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise StereumError('Request payload must contain valid JSON data.') from None
    data = dict(data)
    if action in {'quote', 'customer_quote'}:
        data['side'] = text(data, 'side')
        data['currency'] = text({'currency': data.get('currency', 'USDT')}, 'currency')
        if data['side'] not in {'BUY', 'SELL'} or data['currency'] not in {'USDT', 'USDC'}:
            raise StereumError('Unsupported Bolivia quote direction or asset.')
    for key in ('quote_request_id', 'decode_request_id', 'charge_request_id'):
        if key in data:
            try:
                data[key] = str(uuid.UUID(str(data[key])))
            except (ValueError, TypeError, AttributeError):
                raise StereumError('Invalid test operation reference.') from None
    # Serialize attempts by actor, including different UUIDs consuming one quote.
    with transaction.atomic(durable=True):
        locked_user = type(user).objects.select_for_update().get(pk=user.pk)
        permission(locked_user)
        existing = StereumTestOperation.objects.filter(request_id=request_id).first()
        if existing:
            if existing.actor_id != user.pk or existing.credential_scope != client.scope or existing.action != action or existing.request_data != data:
                raise StereumError('Request ID is already bound to different data.')
            return existing  # Never re-submit even after timeout or worker crash.
        call = build_call(user, client, action, data, request_id)
        reservation = consumption_key(user, client, action, data)
        try:
            with transaction.atomic():
                operation = StereumTestOperation.objects.create(
                    request_id=request_id, actor=user, credential_scope=client.scope,
                    action=action, request_data=data, status='submitting', consumption_key=reservation,
                )
        except IntegrityError:
            # Another administrator may concurrently reserve this global UUID.
            raise StereumError('Request or single-use resource is already reserved; reconcile the existing attempt.') from None
    try:
        result = validate_response(call(), writes=action in {'charge', 'order', 'pay_qr', 'confirm_charge'})
        if not isinstance(result, (dict, list)) or (action not in {'banks', 'orders'} and not isinstance(result, dict)):
            raise StereumError('Unexpected Stereum response.', ambiguous=action in {'charge', 'order', 'pay_qr', 'confirm_charge'})
        if action == 'banks' and (not isinstance(result, list) or not all(isinstance(bank, dict) for bank in result)):
            raise StereumError('Stereum returned an invalid bank catalog.')
        identifier = str(result.get('id') or '') if isinstance(result, dict) else ''
        if action in {'quote', 'customer_quote', 'decode_qr', 'charge', 'order', 'pay_qr'} and not identifier:
            raise StereumError('Stereum response is missing its resource ID.', ambiguous=action in {'charge', 'order', 'pay_qr'})
        if identifier:
            try:
                resource_id(identifier)
            except StereumError:
                raise StereumError('Stereum returned an invalid resource ID.', ambiguous=action in {'charge', 'order', 'pay_qr'}) from None
        operation.response_data = result
        operation.provider_id = identifier
        operation.provider_status = str(result.get('status') or result.get('transaction_status') or '')[:80] if isinstance(result, dict) else ''
        operation.status = 'pending' if action in {'charge', 'order', 'pay_qr'} else 'received'
    except StereumError as exc:
        operation.status = 'unknown' if exc.ambiguous else 'failed'
        operation.error = str(exc)[:300]
    operation.save()
    return operation


def refresh(user, request_id, *, client=None):
    # Serialize reads and writes so an older concurrent poll cannot overwrite a
    # newer terminal result. Network calls are bounded by the client timeout.
    with transaction.atomic():
        return _refresh_locked(user, request_id, client=client)


def _refresh_locked(user, request_id, *, client=None):
    permitted(user)
    client = client or StereumClient()
    try:
        identifier = uuid.UUID(str(request_id))
        operation = StereumTestOperation.objects.select_for_update().get(request_id=identifier, actor=user, credential_scope=client.scope)
    except (ValueError, TypeError, AttributeError, StereumTestOperation.DoesNotExist):
        raise StereumError('Test operation not found for this administrator and credential.') from None
    if not operation.provider_id:
        raise StereumError('No provider ID is available; reconcile the request UUID with Stereum before any retry.')
    if operation.action == 'charge':
        result = client.get_charge(operation.provider_id)
    elif operation.action == 'pay_qr':
        result = client.get_transfer(operation.provider_id)
    elif operation.action == 'order':
        response = client.list_orders()
        items = response if isinstance(response, list) else response.get('items', []) if isinstance(response, dict) else None
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise StereumError('Stereum returned invalid order history; status was not changed.')
        result = next((r for r in items if str(r.get('id')) == operation.provider_id), None)
        if result is None:
            raise StereumError('Order not found in returned history; status was not changed.')
    else:
        raise StereumError('This operation does not have a payment status.')
    validate_response(result)
    if not isinstance(result, dict) or str(result.get('id')) != operation.provider_id:
        raise StereumError('Provider returned a different resource.')
    status = result.get('status') or result.get('transaction_status')
    if not isinstance(status, str) or not status.strip():
        raise StereumError('Provider status is missing; status was not changed.')
    status = status.strip().upper()
    # These are provider test statuses only. No ledger or mint side effects.
    mapping = {'PAGADO': 'succeeded', 'ENVIADO': 'succeeded', 'VERIFICADO': 'succeeded',
               'CANCELADO': 'failed', 'CANCELADA': 'failed', 'ERROR': 'failed', 'EXPIRADO': 'failed'}
    next_status = mapping.get(status, 'pending')
    if operation.status in {'succeeded', 'failed'} and next_status != operation.status:
        raise StereumError('Provider status conflicts with a terminal result; reconcile manually.')
    operation.provider_status = status[:80]
    operation.status = next_status
    operation.error = ''
    operation.response_data = {**operation.response_data, **result}
    operation.save()
    return operation
