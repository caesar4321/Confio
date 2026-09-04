"""Enforce recorded device and account restrictions before login side effects."""
import json
import ipaddress

from django.utils import timezone

from .models import RegistrationRestriction, UserBan
from .request_utils import extract_client_ip_from_meta
from .utils import calculate_device_fingerprint


def login_is_restricted(user, device_fingerprint, meta=None):
    if user is not None:
        if not user.is_active or user.deleted_at is not None:
            return True
        if UserBan.objects.filter(user=user, deleted_at__isnull=True).exclude(
            ban_type='temporary', expires_at__lt=timezone.now()
        ).exists():
            return True
        return False

    # Registration-only controls never lock unrelated existing users out of a
    # shared network. Store canonical exact IPs, not subnets or browser models.
    raw_ip = extract_client_ip_from_meta(meta or {})
    if raw_ip:
        ip = str(ipaddress.ip_address(raw_ip))
        if RegistrationRestriction.objects.filter(kind='ip', value=ip, is_active=True).exists():
            return True

    if device_fingerprint:
        if isinstance(device_fingerprint, str):
            device_fingerprint = json.loads(device_fingerprint)
        fingerprint = calculate_device_fingerprint(device_fingerprint)
        return RegistrationRestriction.objects.filter(
            kind='device', value=fingerprint, is_active=True
        ).exists()
    return False
