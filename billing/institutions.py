import hashlib
import hmac
import json
import secrets
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    BillingEvent, BillingOutboxMessage, InstitutionApplication,
    InstitutionConnection, InstitutionDataGrant, SubjectIdentityValue,
)
from .webhooks import (UnsafeWebhookUrl,
                       public_https_post, validate_delivery_url)


class InstitutionIntegrationError(ValueError):
    pass


def public_institution_status(value):
    """Only reviewed status codes may cross the public billing boundary.

    Connectors can retain additional provider-specific states internally; new
    public codes must be reviewed here rather than forwarding arbitrary text.
    """
    return value if value in ('active', 'inactive', 'habil', 'inhabil') else ''


def create_payment_applications(*, payment, effect):
    mode = payment.billing_invoice.subject.mode
    connection = None
    if mode == 'live':
        connection = InstitutionConnection.objects.filter(
            business_id=effect.business_id, mode=mode, status='active',
            live_approved=True,
        ).order_by('id').first()
    if connection is None and mode == 'test' and getattr(settings, 'BILLING_CIP_SANDBOX_ENABLED', False):
        connection = InstitutionConnection.objects.filter(
            business_id=effect.business_id, provider='cip', mode='test',
            status='sandbox').order_by('id').first()
    if connection is None:
        return []
    created = []
    for allocation in effect.allocations.select_related('obligation__subject'):
        obligation = allocation.obligation
        application, was_created = InstitutionApplication.objects.get_or_create(
            allocation=allocation,
            defaults={
                'connection': connection,
                'billing_payment': payment,
                'opaque_subject_reference': obligation.subject.external_id,
                'status': 'application_pending',
                'idempotency_key': f'application:{allocation.id}:v1',
                'payment_confirmed_at': payment.confirmed_at or timezone.now(),
                'payload_snapshot': {
                    'payment_id': payment.public_id,
                    'obligation_id': obligation.public_id,
                    'external_reference': obligation.external_reference,
                    'commercial_amount_minor': allocation.commercial_delta_minor,
                    'currency': obligation.currency,
                    'period_start': obligation.period_start.isoformat(),
                    'period_end': obligation.period_end.isoformat(),
                },
            })
        if was_created:
            created.append(application)
    return created


def _identity_payload(application):
    subject = application.allocation.obligation.subject
    now = timezone.now()
    required = set(application.connection.data_requirements.filter(
        required=True).values_list('field_name', flat=True))
    grant = InstitutionDataGrant.objects.filter(
        connection=application.connection, subject=subject, revoked_at__isnull=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).order_by('-granted_at', '-id').first()
    if grant is None:
        if required:
            raise InstitutionIntegrationError('identity grant is required')
        return {}
    # Consent does not authorize fields removed from the current manifest.
    manifest = set(application.connection.data_requirements.values_list('field_name', flat=True))
    allowed = set(grant.field_names) & manifest
    if not required.issubset(allowed):
        raise InstitutionIntegrationError('identity grant does not cover required fields')
    values = SubjectIdentityValue.objects.filter(
        subject=subject, field_name__in=allowed)
    payload = {value.field_name: value.encrypted_value for value in values}
    if not required.issubset(payload):
        raise InstitutionIntegrationError('required identity values are missing')
    return payload


def _append_application_event(application, event_type):
    body = {
        'object': 'event', 'type': event_type,
        'data': {'object': {
            'id': application.public_id, 'object': 'institution_application',
            'payment': application.billing_payment.public_id,
            'status': application.status,
            'acknowledgement_reference': application.acknowledgement_reference,
            'returned_status': public_institution_status(application.returned_status),
        }},
    }
    event, _ = BillingEvent.objects.get_or_create(
        business_id=application.billing_payment.billing_invoice.business_id,
        transition_key=f'application:{application.id}:{event_type}:{application.attempts}',
        defaults={
            'event_type': event_type, 'aggregate_type': 'institution_application',
            'mode': application.connection.mode,
            'aggregate_id': application.public_id,
            'aggregate_version': max(application.attempts, 1),
            'correlation_id': application.billing_payment.public_id,
            'causation_id': application.idempotency_key, 'payload': body,
        })
    BillingOutboxMessage.objects.get_or_create(event=event, defaults={'available_at': timezone.now()})


def apply_payment(application_id, *, sender=None):
    sender = sender or public_https_post
    with transaction.atomic():
        application = InstitutionApplication.objects.select_for_update(of=('self',)).select_related(
            'connection', 'billing_payment__billing_invoice',
            'allocation__obligation__subject').get(id=application_id)
        if application.status in ('acknowledged', 'rejected', 'mismatch'):
            return application.status
        if application.leased_at and application.leased_at > timezone.now() - timedelta(minutes=2):
            return 'leased'
        application.leased_at = timezone.now()
        application.lease_token = secrets.token_hex(16)
        application.attempts += 1
        application.save(update_fields=('leased_at', 'lease_token', 'attempts', 'updated_at'))
        token = application.lease_token
        payload = dict(application.payload_snapshot)
        payload['subject_reference'] = application.opaque_subject_reference
        identity_error = ''
        try:
            subject = application.allocation.obligation.subject
            if (application.connection.business_id != subject.business_id
                    or application.connection.mode != subject.mode
                    or application.billing_payment.billing_invoice.subject_id != subject.id
                    or application.billing_payment.status != 'confirmed'):
                raise InstitutionIntegrationError('institution application context mismatch')
            payload['identity'] = _identity_payload(application)
        except InstitutionIntegrationError as exc:
            payload['identity'] = {}
            identity_error = str(exc)
        connection = application.connection

    outcome = 'acknowledged'
    returned = {}
    error = ''
    try:
        if identity_error:
            raise InstitutionIntegrationError(identity_error)
        if connection.status not in ('active', 'sandbox'):
            raise InstitutionIntegrationError('institution connection is disabled')
        if connection.status == 'sandbox':
            if connection.mode != 'test':
                raise InstitutionIntegrationError('sandbox requires test mode')
            if connection.provider == 'cip' and getattr(
                    settings, 'BILLING_CIP_SANDBOX_ENABLED', False):
                from .sandbox_cip import apply_cip_sandbox_payload
                outcome, returned = apply_cip_sandbox_payload(
                    connection=connection, payload=payload,
                    idempotency_key=application.idempotency_key)
            else:
                # Preserve the generic in-process sandbox used by connector
                # contract tests; it has no externally reachable endpoint.
                returned = {'status': 'active', 'version': payload.get('period_end'),
                            'reference': f'sandbox-{application.public_id}'}
        else:
            if not (connection.mode == 'live' and connection.live_approved and connection.application_url
                    and connection.settlement_authority and connection.refund_authority):
                raise InstitutionIntegrationError('live institution authority is incomplete')
            validate_delivery_url(connection.application_url)
            response = sender(
                connection.application_url, json=payload,
                headers={'Authorization': f'Bearer {connection.bearer_token}',
                         'Idempotency-Key': application.idempotency_key},
                timeout=10, allow_redirects=False)
            if response.status_code == 409:
                outcome = 'mismatch'
            elif 400 <= response.status_code < 500:
                outcome = 'rejected'
            elif not 200 <= response.status_code < 300:
                raise InstitutionIntegrationError(f'http_{response.status_code}')
            returned = response.json()
            if not isinstance(returned, dict):
                raise InstitutionIntegrationError('institution response must be an object')
    except (requests.RequestException, UnsafeWebhookUrl, InstitutionIntegrationError,
            ValueError) as exc:
        error = str(exc)[:500]
        outcome = 'application_pending'
        returned = {}

    with transaction.atomic():
        current = InstitutionApplication.objects.select_for_update().select_related(
            'billing_payment__billing_invoice').get(id=application_id)
        if current.lease_token != token:
            return current.status
        current.status = outcome
        current.last_error = error
        current.lease_token = ''
        current.leased_at = None
        current.acknowledgement_reference = str(returned.get('reference', ''))[:255]
        current.returned_status = str(returned.get('status', ''))[:80]
        current.returned_version = str(returned.get('version', ''))[:80]
        if outcome != 'application_pending':
            current.institution_applied_at = timezone.now()
        else:
            current.available_at = timezone.now() + timedelta(
                seconds=min(6 * 60 * 60, 30 * (2 ** (current.attempts - 1))))
        current.save(update_fields=(
            'status', 'last_error', 'lease_token', 'leased_at',
            'acknowledgement_reference', 'returned_status', 'returned_version',
            'institution_applied_at', 'available_at', 'updated_at'))
        _append_application_event(current, f'application.{outcome}')
    return outcome
