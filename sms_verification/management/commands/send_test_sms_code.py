from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from sms_verification.models import SMSVerification
from sms_verification.schema import _should_use_sender_id
import boto3
import hmac
import hashlib
import secrets
import re


def _hmac_code(phone_e164: str, code: str) -> str:
    key = (getattr(settings, 'OTP_HASH_KEY', None) or settings.SECRET_KEY).encode()
    return hmac.new(key, f"{phone_e164}:{code}".encode(), hashlib.sha256).hexdigest()


def _numeric_code_for_iso(iso_code: str) -> str:
    from users.country_codes import COUNTRY_CODES
    for row in COUNTRY_CODES:
        if row[2] == iso_code:
            return row[1].replace('+', '')
    return ''


def _format_e164(local_phone: str, iso_code: str) -> str:
    digits = re.sub(r"\D", "", local_phone or "")
    cc = _numeric_code_for_iso(iso_code)
    if not cc:
        raise ValueError(f"Invalid ISO country code: {iso_code}")
    return f"+{cc}{digits}"


class Command(BaseCommand):
    help = "Send a test SMS OTP to a phone using SNS. Usage: manage.py send_test_sms_code --user <username or id> --iso CO --phone 3001234567"

    def add_arguments(self, parser):
        parser.add_argument('--user', required=True, help='Username or user id')
        parser.add_argument('--iso', required=True, help='ISO alpha-2 country code (e.g., CO)')
        parser.add_argument('--phone', required=True, help='Local phone number without country code (digits only)')
        parser.add_argument('--autocreate', action='store_true', help='Create the user if it does not exist (username only)')

    def handle(self, *args, **options):
        user_ref = options['user']
        iso = options['iso'].upper()
        local_phone = options['phone']

        User = get_user_model()
        try:
            if user_ref.isdigit():
                user = User.objects.get(id=int(user_ref))
            else:
                user = User.objects.get(username=user_ref)
        except User.DoesNotExist:
            if options.get('autocreate') and not user_ref.isdigit():
                user = User.objects.create(username=user_ref, firebase_uid=f"auto-{user_ref}")
                self.stdout.write(self.style.WARNING(f"Created user '{user_ref}' for test sending."))
            else:
                raise CommandError(f"User not found: {user_ref}")

        phone_e164 = _format_e164(local_phone, iso)
        ttl_sec = getattr(settings, 'SMS_CODE_TTL_SECONDS', 600)
        code = f"{secrets.randbelow(10**6):06d}"
        code_hash = _hmac_code(phone_e164, code)

        # Cleanup previous pending
        SMSVerification.objects.filter(user=user, phone_number=phone_e164, is_verified=False).delete()
        v = SMSVerification.objects.create(
            user=user,
            phone_number=phone_e164,
            code_hash=code_hash,
            expires_at=timezone.now() + timedelta(seconds=ttl_sec),
        )

        # SNS publish
        client = boto3.client('sns', region_name=getattr(settings, 'SMS_SNS_REGION', 'eu-central-2'))
        brand = getattr(settings, 'SMS_BRAND', 'CONFIO')
        msg = f"{brand}: Tu código es {code}. Caduca en 5 minutos."
        attrs = {'AWS.SNS.SMS.SMSType': {'DataType': 'String', 'StringValue': 'Transactional'}}
        sid = getattr(settings, 'SMS_SENDER_ID', None)
        ono = getattr(settings, 'SMS_ORIGINATION_NUMBER', None)
        if sid and _should_use_sender_id(iso):
            attrs['AWS.SNS.SMS.SenderID'] = {'DataType': 'String', 'StringValue': sid}
        if ono:
            attrs['AWS.SNS.SMS.OriginationNumber'] = {'DataType': 'String', 'StringValue': ono}

        try:
            resp = client.publish(PhoneNumber=phone_e164, Message=msg, MessageAttributes=attrs)
        except Exception as e:
            if 'INVALID_IDENTITY_FOR_DESTINATION_COUNTRY' in str(e):
                attrs.pop('AWS.SNS.SMS.SenderID', None)
                resp = client.publish(PhoneNumber=phone_e164, Message=msg, MessageAttributes=attrs)
            else:
                raise

        self.stdout.write(self.style.SUCCESS(f"Published SMS to {phone_e164}. MessageId={resp.get('MessageId')}"))
        if getattr(settings, 'DEBUG', False):
            self.stdout.write(self.style.WARNING(f"DEBUG: OTP code is {code}"))
