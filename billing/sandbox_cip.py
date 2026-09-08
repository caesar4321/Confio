"""Durable CIP contract simulator for local/staging pilot exercises only."""

import hashlib
import hmac
import json
from urllib.parse import quote

from django.conf import settings
from django.db import transaction

from .identity_tokens import create_identity_session, issue_identity_token
from .models import (
    CipSandboxApplicationReceipt,
    CipSandboxMember,
    InstitutionConnection,
)


class CipSandboxDisabled(ValueError):
    pass


def require_cip_sandbox():
    if not getattr(settings, 'BILLING_CIP_SANDBOX_ENABLED', False):
        raise CipSandboxDisabled('cip_sandbox_disabled')


def authorize_sandbox_request(value):
    require_cip_sandbox()
    configured = str(getattr(settings, 'BILLING_CIP_SANDBOX_TOKEN', ''))
    supplied = str(value or '')
    return bool(configured) and hmac.compare_digest(
        configured.encode('utf-8'), supplied.encode('utf-8'))


def _canonical_sha256(payload):
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def sandbox_connection(provider='cip', public_id=None):
    try:
        queryset = InstitutionConnection.objects.filter(
            provider=provider, mode='test', status='sandbox')
        if public_id:
            queryset = queryset.filter(public_id=public_id)
        return queryset.get()
    except InstitutionConnection.DoesNotExist:
        raise ValueError('cip_sandbox_connection_not_found')
    except InstitutionConnection.MultipleObjectsReturned:
        raise ValueError('cip_sandbox_connection_is_ambiguous')


def verify_member_and_issue_link(*, member_number, provider='cip', connection=None):
    """Simulate CIP verification and return an OAuth-like one-use app link."""
    require_cip_sandbox()
    connection = connection or sandbox_connection(provider)
    if connection.provider != provider or connection.mode != 'test' or connection.status != 'sandbox':
        raise ValueError('not_a_cip_sandbox_connection')
    member = CipSandboxMember.objects.select_related('subject').filter(
        connection=connection, member_number=member_number,
        subject__business_id=connection.business_id, subject__mode='test',
        subject__status='active').first()
    if member is None:
        return {'matched': False, 'habilidad': 'unknown'}
    session = create_identity_session(
        connection=connection, subject=member.subject, requested_fields=[],
        obligation_references=list(
            member.subject.obligations.exclude(status__in=('paid', 'void'))
            .values_list('public_id', flat=True)[:50]),
    )
    token = issue_identity_token(session)
    return {
        'matched': True,
        'habilidad': member.habilidad,
        'paid_through': member.paid_through.isoformat() if member.paid_through else None,
        'member_reference': member.subject.masked_reference,
        'membership_link': f'confio://memberships?provider={provider}&token={quote(token)}',
        'expires_at': session.expires_at.isoformat(),
    }


@transaction.atomic
def apply_cip_sandbox_payload(*, connection, payload, idempotency_key):
    """Apply a future CIP-style payment callback with strict idempotency."""
    require_cip_sandbox()
    if connection.mode != 'test' or connection.status != 'sandbox':
        raise ValueError('not_a_sandbox_connection')
    # Serialize receipt keys and member status changes per fake connection.
    connection = InstitutionConnection.objects.select_for_update().get(pk=connection.pk)
    if connection.provider != 'cip' or connection.mode != 'test' or connection.status != 'sandbox':
        raise ValueError('not_a_cip_sandbox_connection')
    digest = _canonical_sha256(payload)
    prior = CipSandboxApplicationReceipt.objects.filter(
        connection=connection, idempotency_key=idempotency_key).first()
    if prior:
        if prior.request_sha256 != digest:
            return 'mismatch', {
                'status': 'mismatch', 'version': '',
                'reference': prior.public_id,
            }
        return prior.outcome, dict(prior.response_snapshot)

    subject_reference = str(payload.get('subject_reference', ''))
    member = CipSandboxMember.objects.select_for_update().filter(
        connection=connection, subject__external_id=subject_reference,
        subject__business_id=connection.business_id, subject__mode='test').first()
    try:
        from datetime import date
        period_end = date.fromisoformat(str(payload.get('period_end', '')))
    except ValueError:
        period_end = None

    if member is None or period_end is None:
        outcome = 'mismatch'
        response = {
            'status': 'mismatch', 'version': '',
            'reference': '',
        }
    else:
        if member.paid_through is None or period_end > member.paid_through:
            member.paid_through = period_end
        member.habilidad = 'active'
        member.version += 1
        member.save(update_fields=('paid_through', 'habilidad', 'version', 'updated_at'))
        outcome = 'acknowledged'
        response = {
            'status': member.habilidad,
            'version': str(member.version),
            'reference': '',
            'paid_through': member.paid_through.isoformat(),
        }

    receipt = CipSandboxApplicationReceipt.objects.create(
        connection=connection, member=member, idempotency_key=idempotency_key,
        request_sha256=digest, outcome=outcome, response_snapshot=response)
    response['reference'] = receipt.public_id
    receipt.response_snapshot = response
    receipt.save(update_fields=('response_snapshot', 'updated_at'))
    return outcome, response
