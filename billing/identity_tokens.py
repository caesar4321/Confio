import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import InstitutionIdentitySession


class InvalidInstitutionToken(ValueError):
    pass


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=')


def _decode(value):
    return base64.urlsafe_b64decode(value + b'=' * (-len(value) % 4))


def _key():
    value = getattr(settings, 'BILLING_INSTITUTION_TOKEN_KEY', '')
    if not value:
        raise RuntimeError('BILLING_INSTITUTION_TOKEN_KEY is not configured')
    return value.encode('utf-8')


def create_identity_session(*, connection, subject, requested_fields,
                            obligation_references=(), lifetime_seconds=300):
    if (connection.business_id != subject.business_id
            or connection.mode != subject.mode):
        raise ValueError('institution and subject context mismatch')
    if (connection.status not in ('active', 'sandbox') or subject.status != 'active'
            or (connection.mode == 'live' and not (
                connection.status == 'active' and connection.live_approved))):
        raise ValueError('institution or subject is disabled')
    if lifetime_seconds < 30 or lifetime_seconds > 600:
        raise ValueError('identity token lifetime must be between 30 and 600 seconds')
    allowed = set(connection.data_requirements.values_list('field_name', flat=True))
    requested = sorted(set(requested_fields))
    if not set(requested).issubset(allowed):
        raise ValueError('requested identity fields are not in the approved manifest')
    return InstitutionIdentitySession.objects.create(
        connection=connection, subject=subject, requested_fields=requested,
        obligation_references=list(obligation_references), nonce=secrets.token_hex(24),
        expires_at=timezone.now() + timedelta(seconds=lifetime_seconds))


def issue_identity_token(session):
    now = int(time.time())
    header = {'alg': 'HS256', 'typ': 'JWT', 'kid': 'institution-v1'}
    payload = {
        'iss': 'https://api.confio.lat',
        'aud': f'institution:{session.connection.provider}',
        'sub': session.subject.public_id,
        'sid': session.public_id,
        'jti': session.nonce,
        'env': session.connection.mode,
        'iat': now,
        'exp': int(session.expires_at.timestamp()),
        'obligations': session.obligation_references,
    }
    parts = [
        _encode(json.dumps(header, sort_keys=True, separators=(',', ':')).encode()),
        _encode(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()),
    ]
    signing_input = b'.'.join(parts)
    parts.append(_encode(hmac.new(_key(), signing_input, hashlib.sha256).digest()))
    return b'.'.join(parts).decode('ascii')


@transaction.atomic
def consume_identity_token(token, *, provider, clock_skew_seconds=30):
    if not isinstance(token, str) or len(token) > 16384:
        raise InvalidInstitutionToken('malformed token')
    try:
        encoded_header, encoded_payload, encoded_signature = token.encode().split(b'.')
        signing_input = encoded_header + b'.' + encoded_payload
        expected = hmac.new(_key(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(encoded_signature)):
            raise InvalidInstitutionToken('invalid signature')
        header = json.loads(_decode(encoded_header))
        payload = json.loads(_decode(encoded_payload))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        if isinstance(exc, InvalidInstitutionToken):
            raise
        raise InvalidInstitutionToken('malformed token') from exc
    if header != {'alg': 'HS256', 'kid': 'institution-v1', 'typ': 'JWT'}:
        raise InvalidInstitutionToken('unsupported token header')
    if (not isinstance(payload, dict)
            or type(payload.get('exp')) is not int
            or type(payload.get('iat')) is not int):
        raise InvalidInstitutionToken('malformed token claims')
    now = int(time.time())
    if payload.get('iss') != 'https://api.confio.lat' or payload.get('aud') != f'institution:{provider}':
        raise InvalidInstitutionToken('issuer or audience mismatch')
    if payload.get('exp', 0) < now - clock_skew_seconds or payload.get('iat', now) > now + clock_skew_seconds:
        raise InvalidInstitutionToken('expired or not-yet-valid token')
    if payload.get('exp', 0) - payload.get('iat', 0) > 600:
        raise InvalidInstitutionToken('token lifetime exceeds maximum')
    session = InstitutionIdentitySession.objects.select_for_update().select_related(
        'connection', 'subject').filter(public_id=payload.get('sid'), nonce=payload.get('jti')).first()
    if session is None or session.connection.provider != provider:
        raise InvalidInstitutionToken('unknown token session')
    if (session.connection.status not in ('active', 'sandbox')
            or (session.connection.mode == 'live' and not (
                session.connection.status == 'active' and session.connection.live_approved))
            or session.subject.status != 'active'
            or session.connection.business_id != session.subject.business_id
            or session.connection.mode != session.subject.mode):
        raise InvalidInstitutionToken('institution or subject context is no longer active')
    approved = set(session.connection.data_requirements.values_list('field_name', flat=True))
    if not set(session.requested_fields).issubset(approved):
        raise InvalidInstitutionToken('identity manifest changed')
    if session.token_used_at is not None:
        raise InvalidInstitutionToken('token was already used')
    if session.status != 'pending':
        raise InvalidInstitutionToken('token session is no longer pending')
    if session.expires_at < timezone.now() - timedelta(seconds=clock_skew_seconds):
        raise InvalidInstitutionToken('token session expired')
    if payload.get('sub') != session.subject.public_id or payload.get('env') != session.connection.mode:
        raise InvalidInstitutionToken('token context mismatch')
    session.token_used_at = timezone.now()
    session.save(update_fields=('token_used_at', 'updated_at'))
    return session, payload
