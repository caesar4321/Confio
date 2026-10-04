"""Assistant+ subscriptions, verified with Apple and Google directly.

The app's word is never trusted: every purchase, restore and store
notification is re-read from the store (Apple: a JWS signed by Apple and
chained to the pinned Apple Root CA G3; Google: the Play Developer API) and
bound to the user through the opaque billing_token the app passed to the
store at purchase time.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from . import conf
from .models import AssistantProfile, AssistantSubscription, StoreNotification, SubscriptionStatus

logger = logging.getLogger(__name__)

CERT_DIR = Path(__file__).resolve().parent / 'certs'


class BillingError(Exception):
    """Shown to the user (Spanish)."""


class BillingTransient(BillingError):
    """The store couldn't be reached: retry later (webhooks answer 503)."""


# --------------------------------------------------------------------------- #
# Entitlement
# --------------------------------------------------------------------------- #

def active_subscription(user):
    now = timezone.now()
    for sub in AssistantSubscription.objects.filter(user=user).order_by('-expires_at'):
        if sub.is_entitled(now):
            return sub
    return None


def has_plus(user):
    return active_subscription(user) is not None


def billing_token_for(user):
    profile, _ = AssistantProfile.objects.get_or_create(user=user)
    if profile.billing_token is None:
        # Compare-and-set: concurrent first requests must agree on ONE token,
        # or a purchase bound to the losing token could never be verified.
        AssistantProfile.objects.filter(pk=profile.pk, billing_token__isnull=True).update(billing_token=uuid.uuid4())
        profile.refresh_from_db(fields=['billing_token'])
    return profile.billing_token


def user_for_token(token):
    if not token:
        return None
    try:
        token = uuid.UUID(str(token))
    except ValueError:
        return None
    profile = AssistantProfile.objects.select_related('user').filter(billing_token=token).first()
    return profile.user if profile else None


def _ms(value):
    if not value:
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=dt_timezone.utc)


def _rfc3339(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _upsert(*, user, platform, store_key, signed_ms=None, **fields):
    """Create or refresh a subscription; refuses to move it between users and
    ignores payloads older than the last one applied (signed_ms)."""
    with transaction.atomic():
        sub = AssistantSubscription.objects.select_for_update().filter(
            platform=platform, store_key=store_key).first()
        if sub is not None and user is not None and sub.user_id != user.id:
            raise BillingError('Esta suscripción ya está vinculada a otra cuenta de Confío.')
        if sub is not None and signed_ms is not None and sub.last_signed_ms and signed_ms <= sub.last_signed_ms:
            return sub
        if signed_ms is not None:
            fields['last_signed_ms'] = signed_ms
        if sub is None:
            if user is None:
                return None
            sub = AssistantSubscription(user=user, platform=platform, store_key=store_key)
        for name, value in fields.items():
            setattr(sub, name, value)
        sub.verified_at = timezone.now()
        sub.save()
        return sub


# --------------------------------------------------------------------------- #
# Apple (StoreKit 2 / App Store Server Notifications V2)
# --------------------------------------------------------------------------- #

def _apple_verifiers():
    from appstoreserverlibrary.models.Environment import Environment
    from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier

    roots = [p.read_bytes() for p in sorted(CERT_DIR.glob('*.cer'))]
    bundle_id = conf.get('CONFIO_ASSISTANT_IOS_BUNDLE_ID')
    app_id = conf.get('CONFIO_ASSISTANT_APPLE_APP_ID')
    verifiers = []
    if app_id:
        verifiers.append(SignedDataVerifier(roots, True, Environment.PRODUCTION, bundle_id, int(app_id)))
    if conf.get('CONFIO_ASSISTANT_ACCEPT_APPLE_SANDBOX'):
        verifiers.append(SignedDataVerifier(roots, True, Environment.SANDBOX, bundle_id))
    if not verifiers:
        raise BillingError('Las compras en iPhone aún no están disponibles.')
    return verifiers


def _apple_decode(method, signed):
    from appstoreserverlibrary.signed_data_verifier import VerificationException

    last = None
    for verifier in _apple_verifiers():
        try:
            return getattr(verifier, method)(signed)
        except VerificationException as exc:  # wrong environment, or forged
            last = exc
    raise BillingError('No pudimos verificar la compra con Apple.') from last


def _apple_status(tx, renewal=None, now=None):
    now = now or timezone.now()
    if tx.revocationDate:
        return SubscriptionStatus.REVOKED, None
    expires = _ms(tx.expiresDate)
    grace = _ms(getattr(renewal, 'gracePeriodExpiresDate', None)) if renewal else None
    if expires and expires > now:
        return SubscriptionStatus.ACTIVE, grace
    if grace and grace > now:
        return SubscriptionStatus.GRACE, grace
    if renewal is not None and getattr(renewal, 'isInBillingRetryPeriod', False):
        return SubscriptionStatus.ON_HOLD, grace
    return SubscriptionStatus.EXPIRED, grace


def _apple_apply(tx, *, renewal=None, expected_user=None):
    if tx.productId != conf.get('CONFIO_ASSISTANT_PLUS_PRODUCT_ID'):
        raise BillingError('Este producto no es Confio Assistant+.')
    owner = user_for_token(tx.appAccountToken)
    if expected_user is not None and owner is not None and owner.id != expected_user.id:
        raise BillingError('Esta suscripción ya está vinculada a otra cuenta de Confío.')
    if expected_user is not None and owner is None:
        # StoreKit always sends our appAccountToken; a purchase without it was
        # made outside this app's flow and can't be proven to be this user's.
        raise BillingError('No pudimos vincular esta compra a tu cuenta.')
    status, grace = _apple_status(tx, renewal)
    if renewal is None and status == SubscriptionStatus.EXPIRED:
        # A bare transaction knows nothing about billing retry: keep a grace
        # period a notification already granted.
        existing = AssistantSubscription.objects.filter(
            platform='ios', store_key=str(tx.originalTransactionId)).first()
        if existing is not None and existing.grace_until and existing.grace_until > timezone.now():
            status = SubscriptionStatus.GRACE
    # Renewal facts (grace, auto-renew) only come with notifications; a bare
    # purchase verification must not overwrite them.
    renewal_fields = {} if renewal is None else {
        'grace_until': grace,
        'auto_renew': bool(getattr(renewal, 'autoRenewStatus', 1)),
    }
    return _upsert(
        user=owner,
        platform='ios',
        store_key=str(tx.originalTransactionId),
        signed_ms=int(tx.signedDate) if tx.signedDate else None,
        product_id=tx.productId,
        status=status,
        expires_at=_ms(tx.expiresDate),
        **renewal_fields,
        environment=str(tx.rawEnvironment or ''),
        latest_transaction_id=str(tx.transactionId),
        last_payload={'transaction_id': str(tx.transactionId), 'type': str(tx.rawType or '')},
    )


def verify_apple_purchase(user, signed_transaction):
    tx = _apple_decode('verify_and_decode_signed_transaction', signed_transaction)
    return _apple_apply(tx, expected_user=user)


def handle_apple_notification(signed_payload):
    note = _apple_decode('verify_and_decode_notification', signed_payload)
    record, created = StoreNotification.objects.get_or_create(
        platform='ios', notification_id=str(note.notificationUUID),
        defaults={'notification_type': f'{note.rawNotificationType}/{note.rawSubtype or ""}'},
    )
    if not created and record.processed:
        return record
    data = note.data
    if data is None or not data.signedTransactionInfo:
        record.processed = True
        record.save(update_fields=['processed'])
        return record
    tx = _apple_decode('verify_and_decode_signed_transaction', data.signedTransactionInfo)
    renewal = (_apple_decode('verify_and_decode_renewal_info', data.signedRenewalInfo)
               if data.signedRenewalInfo else None)
    record.store_key = str(tx.originalTransactionId)
    try:
        _apple_apply(tx, renewal=renewal)
        record.processed = True
    except BillingError as exc:
        record.error = str(exc)[:280]
    record.payload = {'type': record.notification_type, 'transaction_id': str(tx.transactionId)}
    record.save()
    return record


# --------------------------------------------------------------------------- #
# Google Play (Billing 8 / Play Developer API / RTDN)
# --------------------------------------------------------------------------- #

GOOGLE_STATES = {
    'SUBSCRIPTION_STATE_ACTIVE': SubscriptionStatus.ACTIVE,
    'SUBSCRIPTION_STATE_CANCELED': SubscriptionStatus.ACTIVE,  # entitled until expiry, won't renew
    'SUBSCRIPTION_STATE_IN_GRACE_PERIOD': SubscriptionStatus.GRACE,
    'SUBSCRIPTION_STATE_ON_HOLD': SubscriptionStatus.ON_HOLD,
    'SUBSCRIPTION_STATE_PAUSED': SubscriptionStatus.ON_HOLD,
    'SUBSCRIPTION_STATE_PENDING': SubscriptionStatus.PENDING,
    'SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED': SubscriptionStatus.EXPIRED,
    'SUBSCRIPTION_STATE_EXPIRED': SubscriptionStatus.EXPIRED,
}


def _play_service():
    creds = conf.get('CONFIO_ASSISTANT_GOOGLE_PLAY_CREDENTIALS')
    if not creds:
        raise BillingError('Las compras en Android aún no están disponibles.')
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(creds) if isinstance(creds, str) else creds
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=['https://www.googleapis.com/auth/androidpublisher'])
    return build('androidpublisher', 'v3', credentials=credentials, cache_discovery=False)


def _play_apply(token, *, expected_user=None, strict_ack=False):
    service = _play_service()
    package = conf.get('CONFIO_ASSISTANT_ANDROID_PACKAGE')
    try:
        purchase = service.purchases().subscriptionsv2().get(packageName=package, token=token).execute()
    except Exception as exc:  # noqa: BLE001 - HttpError / transport
        logger.warning('Play subscriptionsv2.get failed: %s', exc)
        raise BillingTransient('No pudimos verificar la compra con Google Play.') from exc

    items = purchase.get('lineItems') or []
    item = next((i for i in items if i.get('productId') == conf.get('CONFIO_ASSISTANT_PLUS_PRODUCT_ID')), None)
    if item is None:
        raise BillingError('Este producto no es Confio Assistant+.')
    owner = user_for_token((purchase.get('externalAccountIdentifiers') or {}).get('obfuscatedExternalAccountId'))
    if expected_user is not None and owner is not None and owner.id != expected_user.id:
        raise BillingError('Esta suscripción ya está vinculada a otra cuenta de Confío.')
    if expected_user is not None and owner is None:
        raise BillingError('No pudimos vincular esta compra a tu cuenta.')

    state = purchase.get('subscriptionState', '')
    status = GOOGLE_STATES.get(state, SubscriptionStatus.EXPIRED)
    expires = _rfc3339(item.get('expiryTime'))
    if status == SubscriptionStatus.ACTIVE and expires and expires <= timezone.now():
        status = SubscriptionStatus.EXPIRED
    auto_renew = bool((item.get('autoRenewingPlan') or {}).get('autoRenewEnabled'))

    # A resubscribe/upgrade points at the token it replaces: retire that one.
    linked = purchase.get('linkedPurchaseToken')
    if linked:
        AssistantSubscription.objects.filter(platform='android', store_key=linked).update(superseded_by=token)

    acknowledged = purchase.get('acknowledgementState') == 'ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED'
    sub = _upsert(
        user=owner,
        platform='android',
        store_key=token,
        product_id=item['productId'],
        status=status,
        expires_at=expires,
        grace_until=expires if status == SubscriptionStatus.GRACE else None,
        auto_renew=auto_renew,
        environment='Test' if purchase.get('testPurchase') is not None else 'Production',
        latest_transaction_id=str(purchase.get('latestOrderId') or ''),
        acknowledged=acknowledged,
        last_payload={'state': state, 'order': purchase.get('latestOrderId')},
    )
    # Unacknowledged purchases are refunded by Google after 3 days: the server
    # acknowledges once it has recorded the entitlement.
    if sub is not None and not acknowledged and status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE):
        try:
            service.purchases().subscriptions().acknowledge(
                packageName=package, subscriptionId=item['productId'], token=token, body={}).execute()
            sub.acknowledged = True
            sub.save(update_fields=['acknowledged', 'updated_at'])
        except Exception as exc:  # noqa: BLE001
            logger.exception('Play acknowledge failed for subscription %s', sub.id)
            if strict_ack:
                # From RTDN: answer non-2xx so Pub/Sub redelivers and we retry
                # the ack (Google refunds purchases unacknowledged for 3 days).
                raise BillingTransient('No pudimos confirmar la compra con Google Play.') from exc
    return sub


def _token_lock(token):
    """Serialize everything about one Play token (fetch + apply): a slower,
    older snapshot can never land after a newer one."""
    import hashlib

    from django.db import connection
    key = int.from_bytes(hashlib.sha256(f'play:{token}'.encode()).digest()[:8], 'big', signed=True)
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [key])


def verify_google_purchase(user, purchase_token):
    with transaction.atomic():
        _token_lock(purchase_token)
        return _play_apply(purchase_token, expected_user=user)


def verify_rtdn_push(authorization_header):
    """Pub/Sub push carries a Google-signed OIDC token; check it is ours."""
    audience = conf.get('CONFIO_ASSISTANT_RTDN_AUDIENCE')
    email = conf.get('CONFIO_ASSISTANT_RTDN_SERVICE_ACCOUNT')
    if not (audience and email):
        return False
    if not (authorization_header or '').startswith('Bearer '):
        return False
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        claims = id_token.verify_oauth2_token(authorization_header[7:], google_requests.Request(), audience=audience)
    except ValueError:
        return False
    return claims.get('email') == email and claims.get('email_verified') is True


def handle_google_rtdn(envelope):
    import base64

    message = (envelope or {}).get('message') or {}
    message_id = str(message.get('messageId') or message.get('message_id') or '')
    data = json.loads(base64.b64decode(message.get('data') or b'e30=') or b'{}')
    note = data.get('subscriptionNotification') or {}
    token = note.get('purchaseToken', '')
    record, created = StoreNotification.objects.get_or_create(
        platform='android', notification_id=message_id or f'nomsg:{token}:{note.get("notificationType")}',
        defaults={'notification_type': str(note.get('notificationType', data.get('testNotification') and 'TEST')),
                  'store_key': token},
    )
    if not created and record.processed:
        return record
    if data.get('packageName') and data['packageName'] != conf.get('CONFIO_ASSISTANT_ANDROID_PACKAGE'):
        record.error = 'other package'
    elif token:
        try:
            with transaction.atomic():
                _token_lock(token)
                _play_apply(token, strict_ack=True)
            record.processed = True
        except BillingTransient as exc:
            # Not acknowledged: Pub/Sub redelivers until Play answers.
            record.error = str(exc)[:280]
            record.save()
            raise
        except BillingError as exc:
            record.error = str(exc)[:280]
    else:
        record.processed = True  # test or one-time-product notification
    record.save()
    return record
