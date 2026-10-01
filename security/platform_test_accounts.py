"""Google Play pre-launch report robots (Firebase Test Lab).

Every build uploaded to the Play Console is installed on Google test devices
that crawl the app, signing up with Google test accounts. They connect from
Google networks and never obtain an App Check token (they are not Play
installs). Tagged accounts are excluded from analytics only: nothing is
blocked, so a mistaken tag can only affect metrics.
"""
import ipaddress
import logging

logger = logging.getLogger(__name__)

# Google ranges the pre-launch devices were seen on (66.249.x crawl, 74.125.x,
# 66.102.x and 192.178.x Google infrastructure).
GOOGLE_PRELAUNCH_NETWORKS = tuple(ipaddress.ip_network(net) for net in (
    '66.249.64.0/19',
    '74.125.0.0/16',
    '66.102.0.0/20',
    '192.178.0.0/15',
))


def is_google_network(ip: str) -> bool:
    try:
        address = ipaddress.ip_address((ip or '').strip())
    except ValueError:
        return False
    return any(address in net for net in GOOGLE_PRELAUNCH_NETWORKS)


def device_never_passed_app_check(fingerprint: str) -> bool:
    from .models import IntegrityVerdict
    return bool(fingerprint) and not IntegrityVerdict.objects.filter(
        device_fingerprint=fingerprint, passed=True).exists()


def device_seen_on_google_network(fingerprint: str) -> bool:
    """A Test Lab device profile is shared by many robot accounts, and some of
    their sessions egress outside Google's ranges. Requires Google-network
    sessions from at least two accounts, so one Google-proxied login from a
    real phone never marks that phone as a robot device."""
    from .models import IPDeviceUser
    rows = IPDeviceUser.objects.filter(device_fingerprint__fingerprint=fingerprint).values_list(
        'ip_address__ip_address', 'user_id').distinct()
    return len({user_id for ip, user_id in rows if is_google_network(ip)}) >= 2


def is_prelaunch_robot(ip: str, fingerprint: str) -> bool:
    """A device that never produced a valid App Check token, seen now or
    before on a Google network."""
    if not device_never_passed_app_check(fingerprint):
        return False
    return is_google_network(ip) or device_seen_on_google_network(fingerprint)


def tag_if_prelaunch_robot(user, ip: str, fingerprint: str) -> bool:
    """Tag the account when it is on a pre-launch robot device."""
    if getattr(user, 'is_platform_test_account', False):
        return True
    if not is_prelaunch_robot(ip, fingerprint):
        return False
    type(user).all_objects.filter(pk=user.pk).update(is_platform_test_account=True)
    user.is_platform_test_account = True
    logger.info('Tagged Google Play pre-launch robot: user=%s ip=%s device=%s', user.pk, ip, fingerprint[:10])
    return True
