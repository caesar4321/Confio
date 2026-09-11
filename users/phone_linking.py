"""Commit a phone link only after a verification provider has accepted its code."""
import hashlib
import json
import logging

from django.core import signing
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import User
from .country_codes import COUNTRY_CODES
from .masking import mask_email
from .phone_utils import normalize_phone, phone_lookup_key
from .review_numbers import is_review_test_phone_key

logger = logging.getLogger(__name__)


class PhoneLinkError(ValueError):
    pass


CONFIRMATION_SALT = 'users.phone-relink.v1'
OWNERS_DIGEST_SALT = 'users.phone-relink.owners.v1'


class PhoneRelinkRequired(PhoneLinkError):
    def __init__(self, token, accounts):
        super().__init__('Este número está vinculado a otra cuenta. Confirma el cambio para continuar.')
        self.token = token
        self.accounts = accounts


def read_confirmation(token, user):
    try:
        payload = signing.loads(token, salt=CONFIRMATION_SALT, max_age=600)
        if payload['user_id'] != user.pk:
            raise ValueError('wrong user')
        return payload
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise PhoneLinkError('La confirmación expiró o no es válida. Verifica tu número de nuevo.')


def link_verified_phone(user, verification, country_code, confirmation_token=None):
    """Consume approved proof and transfer a phone only for phone-less onboarding.

    The caller must verify the code with the provider first, or provide the
    signed confirmation issued after that approval. Use the phone on that
    server-side request, never a separately supplied destination number.
    Existing accounts keep their identity, wallets, and history when unlinked.
    """
    confirmation = read_confirmation(confirmation_token, user) if confirmation_token else None
    phone_key = phone_lookup_key(verification.phone_number)
    if not phone_key:
        raise PhoneLinkError('El número verificado no es válido.')
    if normalize_phone(verification.phone_number, country_code) != phone_key:
        # The configured reviewer number deliberately tolerates a wrong country
        # selection. Persist its actual calling code, never the caller's guess.
        if not is_review_test_phone_key(phone_key):
            raise PhoneLinkError('El país no coincide con el número verificado.')
        calling_code = '+' + phone_key.split(':', 1)[0]
        country_code = next(row[2] for row in COUNTRY_CODES if row[1] == calling_code)
    with transaction.atomic():
        # Serialize ownership changes even when the phone has no current owner.
        # A row lock alone cannot lock an absent phone or a newly changed owner.
        if connection.vendor == 'postgresql':
            lock_id = int.from_bytes(hashlib.sha256(
                f'phone-link:{phone_key}'.encode()).digest()[:8], 'big', signed=True)
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_id])

        users = list(User.objects.select_for_update().filter(
            Q(pk=user.pk) | Q(phone_key=phone_key)).order_by('pk'))
        current = next((item for item in users if item.pk == user.pk), None)
        if current is None or not current.is_active:
            raise PhoneLinkError('Authentication required')
        proof = type(verification).objects.select_for_update().get(pk=verification.pk)
        context = {
            'user_id': current.pk, 'verification_id': proof.pk,
            'channel': proof._meta.app_label, 'phone_key': phone_key,
            'country_code': country_code,
        }
        if confirmation and any(confirmation.get(key) != value for key, value in context.items()):
            raise PhoneLinkError('La confirmación no corresponde a esta verificación.')
        if (proof.user_id != current.pk
                or proof.expires_at <= timezone.now()
                or proof.phone_number != verification.phone_number):
            raise PhoneLinkError('Solicita un nuevo código de verificación.')

        if proof.is_verified:
            # A response may be lost after committing. Retrying may acknowledge
            # that same link, but can never reclaim it after another transfer.
            if confirmation and current.phone_key == phone_key:
                user.refresh_from_db(fields=['phone_number', 'phone_country', 'phone_key'])
                return phone_key
            raise PhoneLinkError('Solicita un nuevo código de verificación.')

        owners = [item for item in users if item.pk != current.pk]
        if owners and not is_review_test_phone_key(phone_key):
            if current.phone_number:
                raise PhoneLinkError('Este número ya está registrado en Confío. Inicia sesión o recupera tu cuenta.')
            # Whoever holds the number now may not be the previous owner: show
            # enough to recognize one's own account, never the full address.
            accounts = [{'email': mask_email(owner.email), 'username': owner.username or ''}
                        for owner in owners]
            # Keyed: the signed token is readable by the client, and a plain hash
            # would let it confirm guesses of the masked email offline.
            owner_digest = salted_hmac(OWNERS_DIGEST_SALT, json.dumps(
                [(owner.pk, owner.email, owner.username) for owner in owners],
                ensure_ascii=True), algorithm='sha256').hexdigest()
            if not confirmation or confirmation.get('owners') != owner_digest:
                token = signing.dumps({**context, 'owners': owner_digest}, salt=CONFIRMATION_SALT)
                raise PhoneRelinkRequired(token, accounts)
            for owner in owners:
                owner.phone_number = None
                owner.phone_country = None
                owner.phone_key = None
                owner.save(update_fields=['phone_number', 'phone_country', 'phone_key', 'updated_at'])
                transaction.on_commit(
                    lambda previous_id=owner.pk, current_id=current.pk, channel=proof._meta.label:
                    logger.info('Verified phone relink: previous_user=%s new_user=%s channel=%s',
                                previous_id, current_id, channel), robust=True)

        current.phone_number = phone_key.split(':', 1)[-1]
        current.phone_country = country_code
        current.phone_key = phone_key
        current.save(update_fields=['phone_number', 'phone_country', 'phone_key', 'updated_at'])
        proof.is_verified = True
        proof.save(update_fields=['is_verified'])

    # Keep the request user consistent for downstream invitation handling.
    user.refresh_from_db(fields=['phone_number', 'phone_country', 'phone_key'])
    verification.is_verified = True
    return phone_key


def claim_verified_phone_invites(user, info, phone_key):
    """Best-effort claims only after the phone link has committed."""
    try:
        from send.invite_bsc_flow import claim_pending_bsc_invites
        from send.models import PhoneInvite
        from .models import Account
        from blockchain.invite_send_mutations import ClaimInviteForPhone

        claim_pending_bsc_invites(user, phone_key)
        account = Account.objects.filter(
            user=user, account_type='personal', account_index=0).first()
        if account and account.algorand_address:
            invite = PhoneInvite.objects.filter(
                rail='algorand', phone_key=phone_key, status='pending',
                token_type__in=('CUSD', 'CONFIO', 'USDC')).order_by('-created_at').first()
            if invite:
                ClaimInviteForPhone.mutate(None, info, recipient_address=account.algorand_address,
                                          invitation_id=invite.invitation_id)
    except Exception:
        logger.exception('Auto-claim after phone verification failed')
