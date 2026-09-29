"""Face step-up: prove the KYC'd person is present before money moves.

A recruited-identity ring gets the holder in front of the camera once, for
KYC, and then runs the account alone. Re-proving the face at the moments
money moves (every deposit order, withdrawals within a short window, the
emergency exit) forces the ring to bring the holder back each time.

Flow: start → the app streams a Rekognition Face Liveness video with
short-lived, single-action credentials → complete → we fetch the liveness
result and compare its reference frame with the stored KYC selfie.

Region: Rekognition has no endpoint in eu-central-2, so the comparison runs in
eu-central-1 (Frankfurt) on bytes sent per call; nothing is stored there
(AuditImagesLimit=0, no OutputConfig). The selfie itself stays in the
eu-central-2 verification bucket.
"""
import hashlib
import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal

import boto3
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import FaceCheck, FaceReference
from .s3_utils import _build_s3_client_params, _resolve_bucket

logger = logging.getLogger(__name__)

REKOGNITION_REGION = 'eu-central-1'
LIVENESS_MIN_CONFIDENCE = Decimal('85')
FACE_MIN_SIMILARITY = Decimal('90')
SESSION_MAX_AGE = timedelta(minutes=10)
ON_RAMP_CHECK_MAX_AGE = timedelta(minutes=10)
WITHDRAWAL_WINDOW = timedelta(minutes=15)
REFERENCE_PREFIX = 'face-references'
MAX_REFERENCE_BYTES = 5 * 1024 * 1024

FACE_STEP_UP_NEXT_STEP = 'face_check'
FACE_STEP_UP_MESSAGE = 'Confirma que eres tú con tu rostro para continuar.'
NO_REFERENCE_MESSAGE = 'Necesitamos actualizar tu verificación de identidad antes de continuar.'


class FaceStepUpError(Exception):
    """A step-up could not start or finish; the message is safe to show."""


def _setting(name, default):
    return getattr(settings, name, default)


def step_up_enabled() -> bool:
    return bool(_setting('FACE_STEP_UP_ENABLED', False))


def _rekognition():
    return boto3.client('rekognition', region_name=_setting('FACE_REKOGNITION_REGION', REKOGNITION_REGION))


def _s3():
    return boto3.client('s3', **_build_s3_client_params(_setting('AWS_S3_REGION', None) or 'eu-central-2'))


# ── Reference selfie ────────────────────────────────────────────────────────

def _didit_selfie_url(response_payload: dict) -> str:
    for key, field in (('liveness_checks', 'reference_image'), ('face_matches', 'target_image')):
        items = response_payload.get(key)
        first = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        url = first.get(field)
        if isinstance(url, str) and url.startswith('https://'):
            return url
    return ''


def store_face_reference_from_didit(verification, response_payload: dict) -> FaceReference | None:
    """Copy the approved KYC selfie into our bucket. Idempotent per verification."""
    existing = FaceReference.objects.filter(identity_verification=verification, is_active=True).first()
    if existing:
        return existing
    url = _didit_selfie_url(response_payload)
    if not url:
        logger.error('Face reference missing from Didit decision: verification=%s', verification.pk)
        return None
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    body = response.content
    content_type = response.headers.get('Content-Type', '')
    if not body or len(body) > MAX_REFERENCE_BYTES or not content_type.startswith('image/'):
        raise FaceStepUpError('Unexpected Didit selfie payload')
    extension = 'png' if 'png' in content_type else 'jpg'
    key = f'{REFERENCE_PREFIX}/{verification.user_id}/{uuid.uuid4().hex}.{extension}'
    _s3().put_object(
        Bucket=_resolve_bucket(None), Key=key, Body=body, ContentType=content_type,
        ServerSideEncryption='AES256',
    )
    with transaction.atomic():
        FaceReference.objects.filter(user_id=verification.user_id, is_active=True).update(is_active=False)
        return FaceReference.objects.create(
            user_id=verification.user_id, identity_verification=verification, s3_key=key,
            sha256=hashlib.sha256(body).hexdigest(), source='didit_liveness',
        )


def _active_reference(user) -> FaceReference | None:
    return FaceReference.objects.filter(user=user, is_active=True).order_by('-created_at').first()


def _reference_bytes(reference: FaceReference) -> bytes:
    obj = _s3().get_object(Bucket=_resolve_bucket(None), Key=reference.s3_key)
    return obj['Body'].read()


# ── Liveness session ────────────────────────────────────────────────────────

def _client_credentials(user_id: int) -> dict:
    """Credentials that can do exactly one thing: stream a liveness video."""
    region = _setting('FACE_REKOGNITION_REGION', REKOGNITION_REGION)
    policy = {
        'Version': '2012-10-17',
        'Statement': [{'Effect': 'Allow', 'Action': 'rekognition:StartFaceLivenessSession', 'Resource': '*'}],
    }
    creds = boto3.client('sts', region_name=region).assume_role(
        RoleArn=_setting('FACE_LIVENESS_CLIENT_ROLE_ARN', ''),
        RoleSessionName=f'face-liveness-{user_id}',
        DurationSeconds=900,
        Policy=json.dumps(policy),
    )['Credentials']
    return {
        'access_key_id': creds['AccessKeyId'],
        'secret_access_key': creds['SecretAccessKey'],
        'session_token': creds['SessionToken'],
        'expiration': creds['Expiration'].isoformat(),
        'region': region,
    }


def start_face_check(user, purpose: str) -> dict:
    if purpose not in dict(FaceCheck.PURPOSE_CHOICES):
        raise FaceStepUpError('Propósito no válido.')
    if not _active_reference(user):
        raise FaceStepUpError(NO_REFERENCE_MESSAGE)
    session = _rekognition().create_face_liveness_session(
        ClientRequestToken=uuid.uuid4().hex,
        Settings={'AuditImagesLimit': 0},
    )
    check = FaceCheck.objects.create(user=user, purpose=purpose, liveness_session_id=session['SessionId'])
    return {'session_id': check.liveness_session_id, **_client_credentials(user.id)}


def complete_face_check(user, session_id: str) -> bool:
    """Grade the liveness session against the KYC selfie. Returns pass/fail only."""
    with transaction.atomic():
        check = FaceCheck.objects.select_for_update().filter(
            user=user, liveness_session_id=session_id).first()
        if not check:
            raise FaceStepUpError('Sesión no encontrada.')
        if check.status != 'created':
            return check.status == 'passed'
        if timezone.now() - check.created_at > SESSION_MAX_AGE:
            return _finish(check, False, 'session_expired')
        reference = _active_reference(user)
        if not reference:
            return _finish(check, False, 'no_reference')
        result = _rekognition().get_face_liveness_session_results(SessionId=session_id)
        if result.get('Status') != 'SUCCEEDED':
            return _finish(check, False, f"liveness_{str(result.get('Status')).lower()}")
        confidence = Decimal(str(result.get('Confidence') or 0))
        live_bytes = ((result.get('ReferenceImage') or {}).get('Bytes')) or b''
        check.liveness_confidence = confidence
        check.face_reference = reference
        if confidence < Decimal(str(_setting('FACE_LIVENESS_MIN_CONFIDENCE', LIVENESS_MIN_CONFIDENCE))):
            return _finish(check, False, 'low_liveness')
        if not live_bytes:
            return _finish(check, False, 'no_liveness_frame')
        matches = _rekognition().compare_faces(
            SourceImage={'Bytes': live_bytes},
            TargetImage={'Bytes': _reference_bytes(reference)},
            SimilarityThreshold=0,
        ).get('FaceMatches') or []
        similarity = max((Decimal(str(m.get('Similarity') or 0)) for m in matches), default=Decimal('0'))
        check.similarity = similarity
        if similarity < Decimal(str(_setting('FACE_MIN_SIMILARITY', FACE_MIN_SIMILARITY))):
            return _finish(check, False, 'face_mismatch')
        return _finish(check, True, '')


def _finish(check: FaceCheck, passed: bool, reason: str) -> bool:
    check.status = 'passed' if passed else 'failed'
    check.failure_reason = reason
    check.completed_at = timezone.now()
    check.save()
    if not passed:
        logger.warning('Face step-up failed: user=%s purpose=%s reason=%s', check.user_id, check.purpose, reason)
    return passed


# ── Enforcement ─────────────────────────────────────────────────────────────

def require_face_step_up(user, purpose: str, consumed_by: str = '') -> str:
    """'' when the action may proceed, else the message to show.

    A deposit order spends its own fresh check (one face, one order). A
    withdrawal accepts any passed check from the last few minutes, so a
    deposit-then-withdraw sitting asks for the face once.
    """
    if not step_up_enabled():
        return ''
    now = timezone.now()
    passed = FaceCheck.objects.filter(user=user, status='passed')
    if purpose == 'on_ramp':
        with transaction.atomic():
            check = passed.select_for_update().filter(
                purpose='on_ramp', consumed_at__isnull=True,
                completed_at__gte=now - ON_RAMP_CHECK_MAX_AGE,
            ).order_by('-completed_at').first()
            if not check:
                return FACE_STEP_UP_MESSAGE
            check.consumed_at = now
            check.consumed_by = consumed_by[:80]
            check.save(update_fields=['consumed_at', 'consumed_by'])
            return ''
    if purpose == 'withdrawal':
        if passed.filter(completed_at__gte=now - WITHDRAWAL_WINDOW).exists():
            return ''
        return FACE_STEP_UP_MESSAGE
    raise ValueError(f'Unknown step-up purpose {purpose}')
