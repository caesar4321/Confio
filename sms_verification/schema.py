import graphene
from graphene_django import DjangoObjectType
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from django.db import IntegrityError
import hmac
import hashlib
import logging
import re

from .models import SMSVerification
from .twilio_verify import send_verification_sms, check_verification, TwilioVerifyError
from users.country_codes import COUNTRY_CODES
from users.phone_utils import normalize_phone
from users.models import Account
from blockchain.invite_send_mutations import ClaimInviteForPhone
from users.review_numbers import (
    is_review_test_phone_key,
    review_test_pairs,
    find_matching_review_number,
)

logger = logging.getLogger(__name__)


def _validate_country_iso(iso_code: str) -> bool:
    return any(row[2] == iso_code for row in COUNTRY_CODES)


def _numeric_code_for_iso(iso_code: str) -> str:
    for row in COUNTRY_CODES:
        if row[2] == iso_code:
            return row[1].replace('+', '')
    return ''


def _format_e164(local_phone: str, iso_code: str) -> str:
    """Format input into E.164.

    - If `local_phone` already starts with '+', treat it as E.164 and just strip
      non-digits after the '+' to avoid duplicating the calling code.
    - Otherwise, prepend the calling code derived from `iso_code`.
    """
    s = (local_phone or '').strip()
    if s.startswith('+'):
        # Already E.164-like; normalize by removing non-digits after '+'
        digits = re.sub(r"\D", "", s)
        return f"+{digits}"
    digits = re.sub(r"\D", "", s)
    cc = _numeric_code_for_iso(iso_code)
    return f"+{cc}{digits}"


def _hmac_code(phone_e164: str, code: str) -> str:
    key = (getattr(settings, 'OTP_HASH_KEY', None) or settings.SECRET_KEY).encode()
    return hmac.new(key, f"{phone_e164}:{code}".encode(), hashlib.sha256).hexdigest()


def _gen_code(n: int = 6) -> str:
    return f"{secrets.randbelow(10**n):0{n}d}"


"""
Twilio Verify migration: SNS client no longer used for OTP delivery.
Left here intentionally removed.
"""


def _should_use_sender_id(iso_code: str) -> bool:
    sid = getattr(settings, 'SMS_SENDER_ID', None)
    if not sid:
        return False
    mode = getattr(settings, 'SMS_SENDER_ID_MODE', 'default_on').lower()
    if mode == 'never':
        return False
    if mode == 'always':
        return True
    if mode == 'allowlist':
        allowed = set(getattr(settings, 'SMS_SENDER_ID_COUNTRIES', set()))
        return iso_code.upper() in allowed
    # default_on
    deny = set(getattr(settings, 'SMS_SENDER_ID_DENYLIST', set()))
    return iso_code.upper() not in deny


class SMSVerificationType(DjangoObjectType):
    class Meta:
        model = SMSVerification
        fields = ('id', 'phone_number', 'created_at', 'expires_at', 'is_verified')


class InitiateSMSVerification(graphene.Mutation):
    class Arguments:
        phone_number = graphene.String(required=True)
        country_code = graphene.String(required=True)  # ISO alpha-2

    success = graphene.Boolean()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, phone_number, country_code):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return InitiateSMSVerification(success=False, error="Authentication required")

        if not _validate_country_iso(country_code):
            return InitiateSMSVerification(success=False, error="Invalid country code")

        # Fuzzy match review number override (handles wrong country selection)
        review_override = find_matching_review_number(phone_number)
        if review_override:
            phone_e164 = review_override
        else:
            phone_e164 = _format_e164(phone_number, country_code)
        ttl_sec = getattr(settings, 'SMS_CODE_TTL_SECONDS', 600)

        try:
            # Store review test number bypass (no external SMS)
            try:
                for p, c in review_test_pairs():
                    if phone_e164 == p:
                        # Clean old unverified
                        SMSVerification.objects.filter(user=user, phone_number=phone_e164, is_verified=False).delete()
                        code_hash = _hmac_code(phone_e164, c)
                        SMSVerification.objects.create(
                            user=user,
                            phone_number=phone_e164,
                            code_hash=code_hash,
                            expires_at=timezone.now() + timedelta(seconds=ttl_sec),
                        )
                        logger.info("Review test phone used; created local verification without sending SMS")
                        return InitiateSMSVerification(success=True, error=None)
            except Exception:
                # Never fail the flow due to review bypass logic
                pass

            # Clean up previous unverified for this phone (housekeeping)
            SMSVerification.objects.filter(user=user, phone_number=phone_e164, is_verified=False).delete()

            # --- Rate Limiting Checks ---
            from django.core.cache import cache
            
            # Helper to get client IP
            def get_client_ip(info):
                req = info.context
                x_forwarded_for = req.META.get('HTTP_X_FORWARDED_FOR')
                if x_forwarded_for:
                    return x_forwarded_for.split(',')[0].strip()
                return req.META.get('REMOTE_ADDR')

            ip_addr = get_client_ip(info)
            
            # 1. Cooldown per phone number (60s)
            cache_key_cooldown = f"sms_limit:cooldown:{phone_e164}"
            if cache.get(cache_key_cooldown):
                return InitiateSMSVerification(success=False, error="Por favor espera un minuto antes de intentar nuevamente.")
            
            # 2. Limit per User (5 per hour)
            cache_key_user = f"sms_limit:user:{user.id}"
            user_count = cache.get(cache_key_user, 0)
            if user_count >= 5:
                return InitiateSMSVerification(success=False, error="Has excedido el límite de intentos por hora.")
            
            # 3. Limit per IP (20 per hour)
            if ip_addr:
                cache_key_ip = f"sms_limit:ip:{ip_addr}"
                ip_count = cache.get(cache_key_ip, 0)
                if ip_count >= 20:
                    logger.warning(f"SMS Rate limit exceeded for IP {ip_addr}")
                    return InitiateSMSVerification(success=False, error="Demasiados intentos desde esta dirección IP.")
            
            # 4. Limit per Phone Number (3 per hour)
            cache_key_phone = f"sms_limit:phone:{phone_e164}"
            phone_count = cache.get(cache_key_phone, 0)
            if phone_count >= 3:
                return InitiateSMSVerification(success=False, error="Demasiados intentos para este número. Intenta más tarde.")

            # --- Updates Counters ---
            # Set cooldown
            cache.set(cache_key_cooldown, True, 60)
            
            # Increment and set expiry if new (User)
            if user_count == 0:
                cache.set(cache_key_user, 1, 3600)
            else:
                try:
                    cache.incr(cache_key_user)
                except ValueError:
                     cache.set(cache_key_user, 1, 3600)

            # Increment and set expiry if new (IP)
            if ip_addr:
                if ip_count == 0:
                    cache.set(cache_key_ip, 1, 3600)
                else:
                    try:
                        cache.incr(cache_key_ip)
                    except ValueError:
                         cache.set(cache_key_ip, 1, 3600)

            # Increment and set expiry if new (Phone)
            if phone_count == 0:
                cache.set(cache_key_phone, 1, 3600)
            else:
                try:
                    cache.incr(cache_key_phone)
                except ValueError:
                     cache.set(cache_key_phone, 1, 3600)
                     
            # --- End Rate Limiting ---

            # Start Twilio Verify SMS
            verification_sid, status = send_verification_sms(phone_e164)
            logger.info("Twilio Verify started sid=%s status=%s", verification_sid, status)

            # Create a placeholder record to track expiry/state (code_hash not used with Twilio)
            # Use HMAC of phone+sid to satisfy non-null constraint and keep schema stable
            code_hash = _hmac_code(phone_e164, verification_sid or 'sid')
            SMSVerification.objects.create(
                user=user,
                phone_number=phone_e164,
                code_hash=code_hash,
                expires_at=timezone.now() + timedelta(seconds=ttl_sec),
            )

            return InitiateSMSVerification(success=True, error=None)
        except TwilioVerifyError as e:
            logger.exception("Twilio Verify error: %s", e)
            return InitiateSMSVerification(success=False, error="Failed to send SMS")
        except Exception as e:
            logger.exception("Failed to initiate SMS verification: %s", e)
            return InitiateSMSVerification(success=False, error="Failed to send SMS")


class VerifySMSCode(graphene.Mutation):
    class Arguments:
        phone_number = graphene.String(required=True)
        country_code = graphene.String(required=True)
        code = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, phone_number, country_code, code):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return VerifySMSCode(success=False, error="Authentication required")

        if not _validate_country_iso(country_code):
            return VerifySMSCode(success=False, error="Invalid country code")

        # Fuzzy match review number override
        review_override = find_matching_review_number(phone_number)
        if review_override:
            phone_e164 = review_override
        else:
            phone_e164 = _format_e164(phone_number, country_code)
        ver = SMSVerification.objects.filter(
            user=user,
            phone_number=phone_e164,
            is_verified=False,
            expires_at__gt=timezone.now(),
        ).order_by('-created_at').first()

        if not ver:
            return VerifySMSCode(success=False, error="No active verification request found")

        # Store review test number bypass
        try:
            for p, c in review_test_pairs():
                if phone_e164 == p:
                    if code != c:
                        return VerifySMSCode(success=False, error="Invalid verification code")
                    # Mark verified and update user phone as in the normal success path
                    try:
                        phone_key = normalize_phone(phone_number, country_code)
                        allow_duplicates = is_review_test_phone_key(phone_key)
                        if not allow_duplicates:
                            from users.models import User as UserModel
                            duplicate_exists = UserModel.objects.filter(
                                phone_key=phone_key,
                                deleted_at__isnull=True
                            ).exclude(id=user.id).exists()
                            if duplicate_exists:
                                return VerifySMSCode(success=False, error="Este número ya está registrado en Confío. Inicia sesión o recupera tu cuenta.")

                        user.phone_number = phone_number
                        user.phone_country = country_code
                        user.save()

                        # Upsert local verification record
                        v = SMSVerification.objects.filter(
                            user=user, phone_number=phone_e164, is_verified=False
                        ).order_by('-created_at').first()
                        if v:
                            v.is_verified = True
                            v.save(update_fields=['is_verified'])
                        else:
                            SMSVerification.objects.create(
                                user=user,
                                phone_number=phone_e164,
                                code_hash=_hmac_code(phone_e164, c),
                                expires_at=timezone.now() + timedelta(seconds=getattr(settings, 'SMS_CODE_TTL_SECONDS', 600)),
                                is_verified=True,
                            )

                        # Best-effort auto-claim invite
                        try:
                            acct = Account.objects.filter(user=user, account_type='personal', account_index=0, deleted_at__isnull=True).first()
                            recipient_addr = getattr(acct, 'algorand_address', None)
                            if recipient_addr:
                                from send.models import PhoneInvite
                                pk = normalize_phone(phone_number, country_code)
                                inv = PhoneInvite.objects.filter(
                                    phone_key=pk,
                                    status='pending',
                                    deleted_at__isnull=True
                                ).order_by('-created_at').first()
                                if inv:
                                    ClaimInviteForPhone.mutate(None, info, recipient_address=recipient_addr, invitation_id=inv.invitation_id)
                        except Exception as ce:
                            logger.exception('Auto-claim invite failed (review bypass): %s', ce)

                        return VerifySMSCode(success=True, error=None)
                    except IntegrityError:
                        return VerifySMSCode(success=False, error="Este número ya está registrado en Confío. Inicia sesión o recupera tu cuenta.")
        except Exception:
            # Ignore bypass errors and continue with normal flow
            pass

        # Attempts control (retain local rate limit)
        max_attempts = 5
        if ver.attempts >= max_attempts:
            return VerifySMSCode(success=False, error="Maximum number of verification attempts exceeded")

        # Verify via Twilio Verify
        try:
            approved, status = check_verification(phone_e164, code)
        except TwilioVerifyError as e:
            logger.exception("Twilio Verify check error: %s", e)
            ver.attempts = ver.attempts + 1
            ver.save(update_fields=['attempts'])
            return VerifySMSCode(success=False, error="Invalid verification code")

        if not approved:
            ver.attempts = ver.attempts + 1
            ver.save(update_fields=['attempts'])
            return VerifySMSCode(success=False, error="Invalid verification code")

        # Valid code — update user phone (avoid duplicates)
        try:
            phone_key = normalize_phone(phone_number, country_code)
            allow_duplicates = is_review_test_phone_key(phone_key)
            if not allow_duplicates:
                from users.models import User as UserModel
                duplicate_exists = UserModel.objects.filter(
                    phone_key=phone_key,
                    deleted_at__isnull=True
                ).exclude(id=user.id).exists()
                if duplicate_exists:
                    return VerifySMSCode(success=False, error="Este número ya está registrado en Confío. Inicia sesión o recupera tu cuenta.")

            user.phone_number = phone_number  # store without calling code
            user.phone_country = country_code
            user.save()

            ver.is_verified = True
            ver.save(update_fields=['is_verified'])

            # Cleanup other pending records for this phone
            SMSVerification.objects.filter(
                user=user, phone_number=phone_e164, is_verified=False
            ).exclude(id=ver.id).delete()

            # Best-effort auto-claim invitation as in Telegram flow
            try:
                acct = Account.objects.filter(user=user, account_type='personal', account_index=0, deleted_at__isnull=True).first()
                recipient_addr = getattr(acct, 'algorand_address', None)
                if recipient_addr:
                    from send.models import PhoneInvite
                    pk = normalize_phone(phone_number, country_code)
                    inv = PhoneInvite.objects.filter(
                        phone_key=pk,
                        status='pending',
                        deleted_at__isnull=True
                    ).order_by('-created_at').first()
                    if inv:
                        ClaimInviteForPhone.mutate(None, info, recipient_address=recipient_addr, invitation_id=inv.invitation_id)
            except Exception as ce:
                logger.exception('Auto-claim invite failed: %s', ce)

            return VerifySMSCode(success=True, error=None)
        except IntegrityError:
            return VerifySMSCode(success=False, error="Este número ya está registrado en Confío. Inicia sesión o recupera tu cuenta.")
        except Exception as e:
            logger.exception("Verification failed: %s", e)
            return VerifySMSCode(success=False, error="Ocurrió un error al verificar el código")


class Mutation(graphene.ObjectType):
    initiate_sms_verification = InitiateSMSVerification.Field()
    verify_sms_code = VerifySMSCode.Field()
