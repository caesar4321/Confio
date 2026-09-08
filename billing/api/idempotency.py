import hashlib
import json
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.http import Http404
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from billing.models import IdempotencyRecord
from users.encryption import encrypt_data, decrypt_data

from .errors import BillingApiError, exception_handler


def _request_hash(request):
    canonical = json.dumps(
        request.data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _stored_body(body):
    if isinstance(body, dict) and 'signing_secret' in body:
        return {'_billing_encrypted_response_v1': encrypt_data(json.dumps(body))}
    return body


def _replayed_body(body):
    if isinstance(body, dict) and set(body) == {'_billing_encrypted_response_v1'}:
        return json.loads(decrypt_data(body['_billing_encrypted_response_v1']))
    return body


def execute_idempotent(request, operation):
    key = request.headers.get('Idempotency-Key', '')
    if not key:
        raise BillingApiError(
            code='idempotency_key_required',
            message='Idempotency-Key is required.', status_code=400,
            param='Idempotency-Key')
    if len(key.encode('utf-8')) > 255:
        raise BillingApiError(
            code='idempotency_key_too_long',
            message='Idempotency-Key must be at most 255 bytes.',
            param='Idempotency-Key')
    principal = request.user
    fingerprint = _request_hash(request)
    namespace = {
        'api_key_id': principal.api_key_id,
        'mode': principal.mode,
        'method': request.method,
        'route': request.path,
        'key': key,
    }
    now = timezone.now()
    with transaction.atomic():
        try:
            # Isolate the uniqueness race in a savepoint so the outer
            # transaction remains usable when another request wins.
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    business_id=principal.business_id,
                    request_hash=fingerprint,
                    lease_expires_at=now + timedelta(minutes=2),
                    expires_at=now + timedelta(days=7),
                    **namespace)
        except IntegrityError:
            record = IdempotencyRecord.objects.select_for_update().get(**namespace)
            if record.request_hash != fingerprint:
                raise BillingApiError(
                    code='idempotency_key_reused',
                    message='The idempotency key was already used with another request.',
                    status_code=409, param='Idempotency-Key')
            if record.status == 'completed':
                response = Response(_replayed_body(record.response_body), status=record.response_status)
                response['Idempotent-Replayed'] = 'true'
                return response
            if record.lease_expires_at > now:
                raise BillingApiError(
                    code='idempotency_in_progress',
                    message='A request with this idempotency key is still processing.',
                    status_code=409, retryable=True)
            record.lease_expires_at = now + timedelta(minutes=2)
            record.save(update_fields=('lease_expires_at', 'updated_at'))

        try:
            # Preserve a terminal domain error without committing partial writes.
            with transaction.atomic():
                response = operation()
        except (APIException, Http404) as exc:
            if getattr(exc, 'status_code', 404) >= 500:
                raise
            response = exception_handler(exc, {'request': request})
        if response.status_code >= 500:
            raise RuntimeError('cannot persist a server error as an idempotent result')
        record.status = 'completed'
        record.response_status = response.status_code
        record.response_body = _stored_body(response.data)
        record.save(update_fields=(
            'status', 'response_status', 'response_body', 'updated_at'))
        return response
