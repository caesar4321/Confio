"""Face step-up: prove the KYC'd person is present before money moves.

A recruited-identity ring gets the holder in front of the camera once, for
KYC, and then runs the account alone. Re-proving the face at the moments
money moves (every deposit order, each outgoing operation, the
emergency exit) forces the ring to bring the holder back each time.

Flow: start → the app streams a Rekognition Face Liveness video with
short-lived, single-action credentials → complete → we fetch the liveness
result and compare its reference frame with the stored KYC selfie.

Region: Face Liveness is available in eu-west-1 (Ireland), not Frankfurt.
Liveness and comparison run there using bytes, without an S3 output location
(no OutputConfig). The reference frame and up to AUDIT_IMAGES_LIMIT audit
frames come back as bytes and are kept, with the KYC selfie, in the
eu-central-2 verification bucket (see _store_evidence). The video itself
never reaches Confío's servers.

Server enforcement covers the server-mediated money paths (ramp orders,
sponsored BSC sends). The emergency exit is signed and broadcast by the app
itself, by design without Confío's servers; there the app enforces the
check, and no server can.
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
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import FaceCheck, FaceReference
from .s3_utils import _build_s3_client_params, _resolve_bucket

logger = logging.getLogger(__name__)

REKOGNITION_REGION = 'eu-west-1'
LIVENESS_MIN_CONFIDENCE = Decimal('85')
FACE_MIN_SIMILARITY = Decimal('90')
SESSION_MAX_AGE = timedelta(minutes=10)
ON_RAMP_CHECK_MAX_AGE = timedelta(minutes=10)
WITHDRAWAL_WINDOW = timedelta(minutes=15)
MAX_OPEN_SESSIONS = 3
FAILURE_WINDOW = timedelta(hours=1)
MAX_FAILURES_PER_WINDOW = 5
REFERENCE_PREFIX = 'face-references'
# Evidence for abuse investigations: the frames AWS returns for each check
# (never the video, which AWS does not return), in the verification bucket.
EVIDENCE_PREFIX = 'face-checks'
AUDIT_IMAGES_LIMIT = 4
EVIDENCE_RETENTION = timedelta(days=180)
MAX_REFERENCE_BYTES = 5 * 1024 * 1024
LIVENESS_TERMINAL_STATUSES = {'SUCCEEDED', 'FAILED', 'EXPIRED'}

FACE_STEP_UP_NEXT_STEP = 'face_check'
FACE_STEP_UP_MESSAGE = 'Confirma que eres tú con tu rostro para continuar.'
NO_REFERENCE_MESSAGE = 'Necesitamos actualizar tu verificación de identidad antes de continuar.'
UNAVAILABLE_MESSAGE = 'La verificación con tu rostro no está disponible por ahora.'
TOO_MANY_MESSAGE = 'Demasiados intentos. Intenta de nuevo más tarde.'
PENDING_MESSAGE = 'Todavía estamos procesando tu verificación. Intenta de nuevo en unos segundos.'


class FaceStepUpError(Exception):
    """A step-up could not start or finish; the message is safe to show."""


class FaceStepUpPending(FaceStepUpError):
    """The liveness session is not finished yet; the same call can be retried."""


def _setting(name, default, cast=None):
    """A Django setting when defined, else the environment (settings.py is
    git-crypted, so these are read here, like other operational toggles)."""
    if hasattr(settings, name):
        return getattr(settings, name)
    from decouple import config
    return config(name, default=default, cast=cast) if cast else config(name, default=default)


def step_up_enabled() -> bool:
    return bool(_setting('FACE_STEP_UP_ENABLED', False, bool))


def face_enforced() -> bool:
    from .face_context import face_client_supported
    return step_up_enabled() or face_client_supported.get()


def step_up_applies(user) -> bool:
    """Confío Face is asked only of people who went through KYC.

    A recruited identity exists to pass KYC (it is what opens the fiat
    ramps and bank payouts), so the face gate sits on the KYC'd account the
    money enters through; its first send out needs the holder. Users who
    never verified keep sending as before. "Went through KYC" is an approved
    personal verification, not a stored selfie: a KYC'd user whose selfie
    copy is missing is asked to verify again, never waved through.
    Any verified personal document counts, primary or additional: a passport
    verified for a local-money rail opens that rail on its own.
    """
    return face_enforced() and bool(getattr(user, 'has_verified_identity_document', False))


def checks_available() -> bool:
    """Sessions may be opened while enforcement is still off (app rollout)."""
    return face_enforced() or bool(_setting('FACE_STEP_UP_AVAILABLE', False, bool))


def _rekognition():
    return boto3.client('rekognition', region_name=_setting('FACE_REKOGNITION_REGION', REKOGNITION_REGION))


def _s3():
    return boto3.client('s3', **_build_s3_client_params(_setting('AWS_S3_REGION', 'eu-central-2') or 'eu-central-2'))


def _lock_user(user_id):
    get_user_model().objects.select_for_update().filter(pk=user_id).first()


# ── Reference selfie ────────────────────────────────────────────────────────

def _didit_selfie_url(response_payload: dict) -> str:
    for key, field in (('liveness_checks', 'reference_image'), ('face_matches', 'target_image')):
        items = response_payload.get(key)
        first = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        url = first.get(field)
        if isinstance(url, str) and url.startswith('https://'):
            return url
    return ''


def _download_selfie(url: str) -> tuple[bytes, str]:
    """Fetch a signed Didit media URL. Errors never carry the URL: it is a
    live credential for a biometric image."""
    try:
        response = requests.get(url, timeout=20)
    except requests.RequestException as exc:
        raise FaceStepUpError(f'Selfie download failed ({type(exc).__name__})') from None
    if response.status_code != 200:
        raise FaceStepUpError(f'Selfie download failed (HTTP {response.status_code})')
    body = response.content
    content_type = response.headers.get('Content-Type', '')
    if not body or len(body) > MAX_REFERENCE_BYTES or not content_type.startswith('image/'):
        raise FaceStepUpError('Unexpected Didit selfie payload')
    return body, content_type


def _newer_reference_exists(verification) -> bool:
    active = FaceReference.objects.filter(
        user_id=verification.user_id, is_active=True).select_related('identity_verification').first()
    if not active:
        return False
    if active.identity_verification_id == verification.pk:
        return True
    other = active.identity_verification
    mine, theirs = verification.verified_at, getattr(other, 'verified_at', None)
    # A replayed, older approval must not displace the current reference.
    return bool(theirs and mine and theirs >= mine)


def store_face_reference_from_didit(verification, response_payload: dict) -> FaceReference | None:
    """Copy the approved KYC selfie into our bucket. Idempotent and replay-safe."""
    if _newer_reference_exists(verification):
        return FaceReference.objects.filter(user_id=verification.user_id, is_active=True).first()
    url = _didit_selfie_url(response_payload)
    if not url:
        logger.error('Face reference missing from Didit decision: verification=%s', verification.pk)
        return None
    body, content_type = _download_selfie(url)
    extension = 'png' if 'png' in content_type else 'jpg'
    key = f'{REFERENCE_PREFIX}/{verification.user_id}/{uuid.uuid4().hex}.{extension}'
    bucket = _resolve_bucket(None)
    s3 = _s3()
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type, ServerSideEncryption='AES256')
    with transaction.atomic():
        _lock_user(verification.user_id)
        if _newer_reference_exists(verification):
            stored = None
        else:
            FaceReference.objects.filter(user_id=verification.user_id, is_active=True).update(is_active=False)
            stored = FaceReference.objects.create(
                user_id=verification.user_id, identity_verification=verification, s3_key=key,
                sha256=hashlib.sha256(body).hexdigest(), source='didit_liveness',
            )
    if stored is None:
        # Lost the race to a concurrent or newer approval: drop our copy.
        s3.delete_object(Bucket=bucket, Key=key)
        return FaceReference.objects.filter(user_id=verification.user_id, is_active=True).first()
    return stored


def _active_reference(user) -> FaceReference | None:
    return FaceReference.objects.filter(user=user, is_active=True).first()


def _reference_bytes(reference: FaceReference) -> bytes:
    obj = _s3().get_object(Bucket=_resolve_bucket(None), Key=reference.s3_key)
    return obj['Body'].read()


# ── Liveness session ────────────────────────────────────────────────────────

def _client_credentials(user_id: int) -> dict:
    """Credentials that can do exactly one thing: stream a liveness video.

    StartFaceLivenessSession has no resource-level scoping, so '*' is the
    narrowest resource AWS allows.
    """
    role_arn = _setting('FACE_LIVENESS_CLIENT_ROLE_ARN', '')
    if not role_arn:
        logger.error('FACE_LIVENESS_CLIENT_ROLE_ARN is not configured')
        raise FaceStepUpError(UNAVAILABLE_MESSAGE)
    region = _setting('FACE_REKOGNITION_REGION', REKOGNITION_REGION)
    policy = {
        'Version': '2012-10-17',
        'Statement': [{'Effect': 'Allow', 'Action': 'rekognition:StartFaceLivenessSession', 'Resource': '*'}],
    }
    creds = boto3.client('sts', region_name=region).assume_role(
        RoleArn=role_arn,
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


# ── Device attestation (recorded, never enforced) ───────────────────────
#
# A liveness check is beaten by injecting video past the camera (root,
# emulator, virtual camera), not by a better deepfake in front of it, so the
# device matters as much as the video. Every Rekognition call records the
# request's Firebase App Check verdict (Play Integrity / App Attest) on the
# FaceCheck. Pass-through by decision: Play Integrity fails on some genuine
# phones (Motorola, uncertified LATAM devices), so a failed verdict never
# blocks a face check; it is evidence for review and later risk tiers.

APP_CHECK_ACTIONS = {'start': 'face_check_start', 'complete': 'face_check_complete'}


def record_app_check(user, app_check_token, stage: str):
    """The IntegrityVerdict id for this Rekognition call, or None. Never raises."""
    if app_check_token is None:
        return None  # caller has no request to read a token from
    try:
        from .integrity_service import app_check_service
        # A savepoint: a database error here must not break the caller's
        # transaction (ATOMIC_REQUESTS) along with the face check.
        with transaction.atomic():
            result = app_check_service.verify_and_record(
                user=user, token=app_check_token, action=APP_CHECK_ACTIONS[stage], should_enforce=False)
        return result.get('verdict_id')
    except Exception:  # noqa: BLE001 — attestation trouble never changes a face check
        logger.exception('Face check App Check could not be recorded: user=%s stage=%s', user.id, stage)
        return None


def start_face_check(user, purpose: str, app_check_token=None) -> dict:
    """Open a liveness session. `app_check_token` is the request's
    X-Firebase-AppCheck value ('' when absent), recorded, never enforced."""
    if purpose not in dict(FaceCheck.PURPOSE_CHOICES):
        raise FaceStepUpError('Propósito no válido.')
    if not checks_available():
        raise FaceStepUpError(UNAVAILABLE_MESSAGE)
    if not _active_reference(user):
        raise FaceStepUpError(NO_REFERENCE_MESSAGE)
    now = timezone.now()
    with transaction.atomic():
        _lock_user(user.id)
        checks = FaceCheck.objects.filter(user=user)
        if checks.filter(status='failed', completed_at__gte=now - FAILURE_WINDOW).count() >= MAX_FAILURES_PER_WINDOW:
            raise FaceStepUpError(TOO_MANY_MESSAGE)
        if checks.filter(status='created', created_at__gte=now - SESSION_MAX_AGE).count() >= MAX_OPEN_SESSIONS:
            raise FaceStepUpError(TOO_MANY_MESSAGE)
        credentials = _client_credentials(user.id)
        session = _rekognition().create_face_liveness_session(
            ClientRequestToken=uuid.uuid4().hex,
            # Frames come back as bytes (no S3 output in Ireland); we keep them
            # in our own bucket in Zurich, see _store_evidence.
            Settings={'AuditImagesLimit': AUDIT_IMAGES_LIMIT},
        )
        check = FaceCheck.objects.create(user=user, purpose=purpose, liveness_session_id=session['SessionId'])
    # After the lock (verifying the token is a network call) and only for a
    # session actually opened: a rate-limited start records nothing.
    start_verdict_id = record_app_check(user, app_check_token, 'start')
    if start_verdict_id:
        FaceCheck.objects.filter(pk=check.pk).update(start_integrity_id=start_verdict_id)
    return {'session_id': check.liveness_session_id, **credentials}


def complete_face_check(user, session_id: str, app_check_token=None) -> bool:
    """Grade the liveness session against the KYC selfie. Returns pass/fail only.

    Raises FaceStepUpPending while AWS is still processing the video. The
    request's App Check verdict is recorded once per check (the app polls
    while AWS processes), never enforced.
    """
    if app_check_token is not None:
        ungraded = FaceCheck.objects.filter(
            user=user, liveness_session_id=session_id, status='created', complete_integrity__isnull=True)
        if ungraded.exists():
            verdict_id = record_app_check(user, app_check_token, 'complete')
            if verdict_id:
                ungraded.update(complete_integrity_id=verdict_id)
    graded = {}
    try:
        return _grade(user, session_id, graded)
    except Exception:
        # Frames already in the bucket must stay reachable (admin) and purgeable
        # even when grading fails after storing them and the row rolls back.
        check = graded.get('check')
        if check is not None and check.evidence_keys:
            with transaction.atomic():
                stored = FaceCheck.objects.select_for_update().filter(pk=check.pk).first()
                if stored:
                    known = list(stored.evidence_keys or [])
                    merged = known + [key for key in check.evidence_keys if key not in known]
                    if merged != known:
                        FaceCheck.objects.filter(pk=check.pk).update(evidence_keys=merged)
        raise


def _grade(user, session_id: str, graded: dict) -> bool:
    with transaction.atomic():
        check = FaceCheck.objects.select_for_update().filter(
            user=user, liveness_session_id=session_id).first()
        graded['check'] = check
        if not check:
            raise FaceStepUpError('Sesión no encontrada.')
        if check.status != 'created':
            return check.status == 'passed'
        expired = timezone.now() - check.created_at > SESSION_MAX_AGE
        reference = _active_reference(user)
        if not reference:
            return _finish(check, False, 'no_reference')
        result = _rekognition().get_face_liveness_session_results(SessionId=session_id)
        status = str(result.get('Status') or '').upper()
        if status not in LIVENESS_TERMINAL_STATUSES:
            if expired:
                return _finish(check, False, 'session_expired')
            raise FaceStepUpPending(PENDING_MESSAGE)
        _store_evidence(check, result)
        if status != 'SUCCEEDED':
            return _finish(check, False, f'liveness_{status.lower()}')
        if expired:
            return _finish(check, False, 'session_expired')
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


def _store_evidence(check: FaceCheck, result: dict) -> None:
    """Keep the frames of a finished check for abuse investigations.

    Best effort: storage trouble never changes the outcome of a check.
    """
    frames = [('reference', (result.get('ReferenceImage') or {}).get('Bytes'))]
    frames += [(f'audit-{i}', (image or {}).get('Bytes'))
               for i, image in enumerate(result.get('AuditImages') or [])]
    frames = [(name, body) for name, body in frames if body][:1 + AUDIT_IMAGES_LIMIT]
    if not frames:
        return
    keys = []
    try:
        s3, bucket = _s3(), _resolve_bucket(None)
        for name, body in frames:
            key = f'{EVIDENCE_PREFIX}/{check.user_id}/{check.pk}/{name}.jpg'
            s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType='image/jpeg',
                          ServerSideEncryption='AES256')
            keys.append(key)
    except Exception:
        logger.exception('Face check evidence partly stored: check=%s stored=%s', check.pk, len(keys))
    # Whatever reached the bucket is recorded, so it can be viewed and purged.
    # Merged: a retry never drops frames an earlier attempt stored (keys are
    # fixed per check, so the same frame is never listed twice).
    existing = list(check.evidence_keys or [])
    check.evidence_keys = existing + [key for key in keys if key not in existing]


def purge_expired_evidence(batch=500) -> int:
    """Delete the frames of passed checks older than EVIDENCE_RETENTION.

    Kept instead: failed checks (retained with the KYC record) and every check
    of a user with a ban on record (active or lifted), for the fraud case.
    Pages by row id, so checks whose deletion failed never block later ones;
    they are retried on the next run.
    """
    from .models import UserBan
    cutoff = timezone.now() - EVIDENCE_RETENTION
    eligible = FaceCheck.objects.filter(
        status='passed', completed_at__lt=cutoff, evidence_purged_at__isnull=True,
    ).exclude(evidence_keys=[]).exclude(user_id__in=UserBan.all_objects.values('user_id')).order_by('pk')
    purged, after = 0, 0
    while True:
        rows = list(eligible.filter(pk__gt=after)[:batch])
        if not rows:
            return purged
        purged += _purge_rows(rows)
        after = rows[-1].pk


def _purge_rows(rows) -> int:
    s3, bucket = _s3(), _resolve_bucket(None)
    purged = 0
    for check in rows:
        try:
            response = s3.delete_objects(Bucket=bucket, Delete={
                'Objects': [{'Key': key} for key in check.evidence_keys], 'Quiet': True})
        except Exception:
            logger.exception('Face check evidence purge failed: check=%s', check.pk)
            continue
        # A 200 can still list per-object failures: keep those keys to retry.
        errors = response.get('Errors') if isinstance(response, dict) else None
        failed = {error.get('Key') for error in errors or []}
        remaining = [key for key in check.evidence_keys if key in failed]
        if remaining:
            logger.error('Face check evidence purge incomplete: check=%s failed=%s', check.pk, len(remaining))
            FaceCheck.objects.filter(pk=check.pk).update(evidence_keys=remaining)
            continue
        FaceCheck.objects.filter(pk=check.pk).update(evidence_keys=[], evidence_purged_at=timezone.now())
        purged += 1
    return purged


def _finish(check: FaceCheck, passed: bool, reason: str) -> bool:
    check.status = 'passed' if passed else 'failed'
    check.failure_reason = reason
    check.completed_at = timezone.now()
    check.save()
    if not passed:
        logger.warning('Face step-up failed: user=%s purpose=%s reason=%s', check.user_id, check.purpose, reason)
    return passed


# ── Enforcement ─────────────────────────────────────────────────────────────
#
# A deposit order spends its own fresh check (one face, one order). A
# withdrawal spends its own approval, bound to one immutable operation.

def _usable_on_ramp_checks(user, now):
    return FaceCheck.objects.filter(
        user=user, status='passed', purpose='on_ramp', consumed_at__isnull=True,
        completed_at__gte=now - ON_RAMP_CHECK_MAX_AGE,
    )


def missing_face_step_up(user, purpose: str) -> str:
    """'' when a usable check exists (nothing is spent), else the message."""
    if purpose == 'withdrawal':
        from .identity_reuse import outgoing_identity_restriction
        restriction = outgoing_identity_restriction(user)
        if restriction:
            return restriction
    if not step_up_applies(user):
        return ''
    now = timezone.now()
    if purpose == 'on_ramp':
        return '' if _usable_on_ramp_checks(user, now).exists() else FACE_STEP_UP_MESSAGE
    if purpose == 'withdrawal':
        recent = _usable_withdrawal_checks(user, now)
        return '' if recent.exists() else FACE_STEP_UP_MESSAGE
    raise ValueError(f'Unknown step-up purpose {purpose}')


def claim_on_ramp_check(user, consumed_by: str):
    """Spend one fresh deposit check right before the provider order.

    Returns (ok, check_id). ok is True with check_id None when no face is
    asked of this user. Release the claim only when the provider definitely
    made no order.
    """
    if not step_up_applies(user):
        return True, None
    now = timezone.now()
    with transaction.atomic():
        check = _usable_on_ramp_checks(user, now).select_for_update().order_by('-completed_at').first()
        if not check:
            return False, None
        check.consumed_at = now
        check.consumed_by = consumed_by[:80]
        check.save(update_fields=['consumed_at', 'consumed_by'])
        return True, check.pk


def release_on_ramp_check(check_id) -> None:
    if check_id:
        FaceCheck.objects.filter(pk=check_id).update(consumed_at=None, consumed_by='')


def withdrawal_action_key(namespace, identifier, payload) -> str:
    """Bind an approval to server-validated economic terms, never just a row ID."""
    encoded = json.dumps([namespace, str(identifier), payload], sort_keys=True,
                         separators=(',', ':'), default=str).encode()
    return 'out:' + hashlib.sha256(encoded).hexdigest()


def _usable_withdrawal_checks(user, now):
    return FaceCheck.objects.filter(
        user=user, status='passed', purpose='withdrawal', consumed_at__isnull=True,
        completed_at__gte=now - WITHDRAWAL_WINDOW)


def require_face_step_up(user, purpose: str, *, action_key=None, consume=False) -> str:
    """Peek during preparation; claim after validation and before side effects.

    An exact operation can retry after consumption. Callers MUST bind all
    economic terms and enforce durable operation idempotency, or include the
    exact signed nonce/deadline. Never release after an ambiguous broadcast.
    """
    if purpose != 'withdrawal':
        raise ValueError('Deposit orders must claim a check with claim_on_ramp_check')
    from .identity_reuse import outgoing_identity_restriction
    restriction = outgoing_identity_restriction(user)
    if restriction:
        return restriction
    if consume and not action_key:
        raise ValueError('An immutable action key is required to consume a check')
    if action_key is not None and (not action_key.startswith('out:') or len(action_key) != 68):
        raise ValueError('Use withdrawal_action_key for outgoing operations')
    if not step_up_applies(user):
        return ''
    with transaction.atomic():
        # Serialize claims even when there are several fresh approvals. Row
        # locks on the selected check alone cannot serialize exact retries.
        _lock_user(user.pk)
        if action_key and FaceCheck.objects.filter(
                user=user, purpose='withdrawal', status='passed',
                consumed_by=action_key, consumed_at__isnull=False).exists():
            return ''
        check = _usable_withdrawal_checks(user, timezone.now()).order_by('-completed_at', '-pk').first()
        if not check:
            return FACE_STEP_UP_MESSAGE
        if consume:
            check.consumed_at = timezone.now()
            check.consumed_by = action_key
            check.save(update_fields=['consumed_at', 'consumed_by'])
        return ''
