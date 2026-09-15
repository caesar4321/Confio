"""Bre-B location gate: usable from anywhere except Venezuela. No VPN lookup or Didit IP dependency."""
import base64
import hashlib
import json
import math
import logging
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from security.geo import country_for_request

logger = logging.getLogger(__name__)
UNAVAILABLE = 'La verificación del dispositivo no está disponible temporalmente. Intenta más tarde.'


class LocationError(ValueError):
    pass


class _Refused(ValueError):
    """A named check refused the reading. Its fixed code (never data) is the
    compliance record's reason, so refusals stay distinguishable."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def ip_allowed(meta):
    # Same trusted Cloudflare/origin boundary as the existing geo checks.
    # Unknown geography is not evidence of an allowed location.
    country = country_for_request(meta) or _dev_country(meta)
    return country is not None and country != 'VE'


def _dev_country(meta):
    """Local development only: a phone on the LAN has a private IP with no
    country. Never applies with DEBUG off or to a public IP."""
    country = str(getattr(settings, 'BREB_DEV_IP_COUNTRY', '') or '').strip().upper()
    if not (getattr(settings, 'DEBUG', False) and len(country) == 2):
        return None
    from security.geo import _is_public_ip
    from security.request_utils import extract_client_ip_from_meta
    ip = extract_client_ip_from_meta(meta)
    return country if ip and not _is_public_ip(ip) else None


def configured(platform=None):
    from . import apple_attest
    ios = apple_attest.configured()
    android = bool(getattr(settings, 'BREB_PLAY_CERTIFICATE_DIGESTS', [])
                and str(getattr(settings, 'BREB_PLAY_CLOUD_PROJECT_NUMBER', '')).isdigit()
                and 0 < int(settings.BREB_PLAY_CLOUD_PROJECT_NUMBER) < 2**63)
    # The rail's rule, not a provider's: Infinia's Bre-B needs it as much as Cobre's.
    return bool(getattr(settings, 'BREB_LOCATION_ENABLED', False)
                and (ios if platform == 'ios' else android if platform == 'android' else ios or android)
                and settings.CACHES['default']['BACKEND'] in {
                    'django_redis.cache.RedisCache', 'django.core.cache.backends.redis.RedisCache'})


def challenge(owner, meta, platform='android'):
    if platform not in ('android', 'ios') or not configured(platform):
        raise LocationError('La verificación de ubicación aún no está disponible.')
    if not ip_allowed(meta):
        raise LocationError('No podemos habilitar Bre-B desde tu ubicación actual.')
    if not cache.add(f'breb-location-rate:{owner.pk}', True, timeout=15):
        raise LocationError('Espera unos segundos antes de volver a intentarlo.')
    return signing.dumps({'owner': owner.pk, 'platform': platform, 'random': secrets.token_urlsafe(32)}, salt='breb-application')


@lru_cache(maxsize=1)
def _timezones():
    from timezonefinder import TimezoneFinder
    return TimezoneFinder()


def _venezuelan(zone):
    # All of Venezuela is America/Caracas, and no other country uses it.
    return zone == 'America/Caracas'


def outside_venezuela(lat, lon, accuracy):
    # Bre-B works from anywhere except Venezuela. The reading and its
    # uncertainty perimeter (+50 m policy buffer) must all resolve outside
    # Venezuela's zone in the pinned timezonefinder dataset, so a reading that
    # straddles the border asks for another attempt. Sampling the perimeter
    # is not proof that every point of the disk is outside Venezuela.
    finder = _timezones()
    if _venezuelan(finder.timezone_at(lat=lat, lng=lon)):
        return False
    radius = (accuracy + 50) / 111320
    for angle in range(0, 360, 30):
        # Wrap across the antimeridian and clamp at the poles: a sample outside
        # the lookup's range must not refuse a valid reading (e.g. Fiji).
        y = max(-90.0, min(90.0, lat + radius * math.sin(math.radians(angle))))
        x = lon + radius * math.cos(math.radians(angle)) / max(math.cos(math.radians(lat)), 1e-6)
        x = ((x + 180.0) % 360.0) - 180.0
        if _venezuelan(finder.timezone_at(lat=y, lng=x)):
            return False
    return True


def decode_token(token):
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    try:
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/playintegrity'])
        package = getattr(settings, 'BREB_PLAY_PACKAGE_NAME', 'com.Confio.Confio')
        # Feature-local UTC usage, not Google's authoritative shared quota.
        day = time.strftime('%Y-%m-%d', time.gmtime())
        key = f'breb-integrity-decodes:{day}'
        cache.add(key, 0, timeout=172800)
        count = cache.incr(key)
        logger.info('breb_integrity_decode_attempt day=%s count=%s', day, count)
        if count in (8000, 9500, 10000):
            logger.warning('breb_integrity_quota_threshold day=%s count=%s', day, count)
        with AuthorizedSession(credentials) as session:
            response = session.post(
                f'https://playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken',
                json={'integrity_token': token}, timeout=15)
            if response.status_code == 429:
                logger.error('breb_integrity_quota_exhausted')
            response.raise_for_status()
            return response.json()['tokenPayloadExternal']
    except Exception as exc:
        # Never log tokens, coordinates, HTTP bodies or credential exceptions.
        logger.warning('breb_integrity_decode_unavailable')
        raise LocationError(UNAVAILABLE) from exc


@dataclass(frozen=True)
class ApplicationPermit:
    owner_id: int
    expires: float


PASS_SECONDS = 15 * 60


def grant_pass(owner):
    """A verified reading lets this person use Bre-B for a short while; every
    Bre-B screen verifies again once it lapses."""
    expires = time.time() + PASS_SECONDS
    cache.set(f'breb-location-pass:{owner.pk}', expires, timeout=PASS_SECONDS)
    return expires


def require_location_pass(owner, meta=None):
    if meta is not None and not ip_allowed(meta):
        from .services import PaymentAccountError
        raise PaymentAccountError('No podemos habilitar Bre-B desde tu ubicación actual.')
    expires = cache.get(f'breb-location-pass:{owner.pk}') if configured() else None
    if not expires or expires < time.time():
        from .services import PaymentAccountError
        raise PaymentAccountError('Verifica tu ubicación para usar Bre-B.')


def require_for_country(owner, country, meta=None):
    """Every Bre-B operation (Colombia's rail, either provider) needs a
    current location pass; other countries' rails are not location-gated."""
    if str(country or '').strip().upper() in {'CO', 'COL'}:
        require_location_pass(owner, meta)


def require_permit(permit, owner):
    if not isinstance(permit, ApplicationPermit) or permit.owner_id != owner.pk or permit.expires < time.time():
        from .services import PaymentAccountError
        raise PaymentAccountError('Verifica tu ubicación para solicitar tu llave Bre-B.')


def _record(owner, meta, evidence, passed, reason='', strict=False):
    """Compliance record of one verification (BrebLocationCheck). A pass is
    granted only once its record is stored (strict); a refusal's record is
    best-effort so a storage error never changes the refusal."""
    try:
        import ipaddress
        from datetime import datetime, timezone
        from security.request_utils import extract_client_ip_from_meta
        from .models import BrebLocationCheck
        ip = extract_client_ip_from_meta(meta) or None
        try:
            ip = str(ipaddress.ip_address(ip)) if ip else None
        except ValueError:
            ip = None
        stamp = evidence.get('timestamp')
        BrebLocationCheck.objects.create(
            confio_account_id=owner.pk, platform=evidence.get('platform', ''), passed=passed, reason=reason[:160],
            ip_address=ip, ip_country=(country_for_request(meta) or _dev_country(meta) or '')[:2],
            latitude=evidence.get('latitude'), longitude=evidence.get('longitude'), accuracy_m=evidence.get('accuracy'),
            reading_at=datetime.fromtimestamp(stamp / 1000, tz=timezone.utc) if stamp else None)
    except Exception as exc:
        if strict:
            raise
        # The class only: a database error's text can quote the row (coordinates, IP).
        logger.warning('breb_location_record_failed error=%s', type(exc).__name__)


def _submitted(challenge_token, location_json):
    """What the device sent, kept on a refusal's record even when a check fails
    before validation (bounded; never trusted for a decision)."""
    evidence = {}
    try:
        if isinstance(challenge_token, str) and len(challenge_token) <= 2048:
            platform = signing.loads(challenge_token, salt='breb-application', max_age=180).get('platform', 'android')
            if platform in ('android', 'ios'):
                evidence['platform'] = platform
    except Exception:
        pass
    try:
        location = json.loads(location_json) if isinstance(location_json, str) and len(location_json) <= 2048 else {}
        bounds = {'latitude': (-90, 90), 'longitude': (-180, 180), 'accuracy': (0, 1e7), 'timestamp': (0, 1e14)}
        for key, (low, high) in bounds.items():
            value = location.get(key) if isinstance(location, dict) else None
            if type(value) in (int, float) and math.isfinite(value) and low <= value <= high:
                evidence[key] = value
    except Exception:
        pass
    return evidence


def verify(owner, meta, challenge_token, location_json, integrity_token):
    evidence = _submitted(challenge_token, location_json)
    if not configured() or not ip_allowed(meta):
        _record(owner, meta, evidence, False, 'not_configured' if not configured() else 'ip_not_allowed')
        raise LocationError('No podemos habilitar Bre-B desde tu ubicación actual.')
    try:
        if len(challenge_token) > 2048:
            raise _Refused('challenge_too_long')
        claim = signing.loads(challenge_token, salt='breb-application', max_age=180)
        platform = claim.get('platform', 'android')
        if platform not in ('android', 'ios') or not configured(platform):
            raise _Refused('platform_unavailable')
        if claim['owner'] != owner.pk or len(location_json) > 2048 or len(integrity_token) > 30000:
            raise _Refused('challenge_owner_or_size')
        location = json.loads(location_json)
        lat, lon, accuracy = (location[k] for k in ('latitude', 'longitude', 'accuracy'))
        timestamp = location['timestamp']
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lon, accuracy, timestamp)):
            raise _Refused('reading_invalid')
        # _submitted already retained the bounded reading. Never overwrite it
        # with unvalidated values: an overflowing timestamp can lose the whole
        # refusal record when converted to a database datetime.
        if not (-90 < lat < 90 and -180 <= lon <= 180 and 0 < accuracy <= 100):
            raise _Refused('reading_out_of_range')
        if location.get('mocked') is not False or not -5000 <= time.time()*1000-timestamp <= 120000:
            raise _Refused('reading_mocked_or_stale')
        if not outside_venezuela(lat, lon, accuracy):
            raise _Refused('in_venezuela')
        key = hashlib.sha256(challenge_token.encode()).hexdigest()
        # Reserve before Google, including failed decodes. A signed challenge
        # must not be an unlimited quota-spending credential. Redis add is
        # atomic across workers; failure requires a fresh challenge.
        if not cache.add(f'breb-location-used:{key}', True, timeout=240):
            raise _Refused('challenge_reused')
        if platform == 'ios':
            from . import apple_attest
            apple_attest.verify(owner, integrity_token, hashlib.sha256((challenge_token+'.'+location_json).encode()).digest())
            _record(owner, meta, evidence, True, strict=True)
            return ApplicationPermit(owner.pk, time.time()+120)
        verdict = decode_token(integrity_token)
        request = verdict['requestDetails']
        package = getattr(settings, 'BREB_PLAY_PACKAGE_NAME', 'com.Confio.Confio')
        request_hash = base64.urlsafe_b64encode(hashlib.sha256((challenge_token+'.'+location_json).encode()).digest()).decode().rstrip('=')
        app = verdict['appIntegrity']
        # The authenticated account owner, never a submitted username, selects
        # this explicit test exception. UNEVALUATED is still refused.
        sideload_exception = (
            app.get('appRecognitionVerdict') == 'UNRECOGNIZED_VERSION'
            and str(getattr(owner, 'user_id', None)) in
            getattr(settings, 'BREB_ANDROID_SIDELOAD_TEST_USER_IDS', [])
        )
        checks = {
            'request_hash': request.get('requestHash') == request_hash,
            'request_package': request['requestPackageName'] == package,
            'request_freshness': -5000 <= time.time()*1000-int(request['timestampMillis']) <= 120000,
            'app_recognition': app.get('appRecognitionVerdict') == 'PLAY_RECOGNIZED' or sideload_exception,
            'app_package': app.get('packageName') == package,
            'certificate': bool(set(app.get('certificateSha256Digest', [])) & set(settings.BREB_PLAY_CERTIFICATE_DIGESTS)),
            'device_integrity': 'MEETS_DEVICE_INTEGRITY' in verdict.get('deviceIntegrity', {}).get('deviceRecognitionVerdict', []),
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            # Fixed check names only, never tokens, fingerprints or location.
            logger.warning('breb_android_integrity_refused checks=%s', ','.join(failed))
            raise _Refused('android:' + ','.join(failed))
        _record(owner, meta, evidence, True, strict=True,
                reason='android_sideload_test_exception' if sideload_exception else '')
        return ApplicationPermit(owner.pk, time.time()+120)
    except LocationError:
        _record(owner, meta, evidence, False, 'integrity_unavailable')
        raise
    except Exception as exc:
        # Which check refused, never its data: the error type and the line
        # that raised it (App Attest's own messages are fixed strings).
        frame = exc.__traceback__
        while frame.tb_next:
            frame = frame.tb_next
        where = f"{frame.tb_frame.f_code.co_filename.rsplit('/', 1)[-1]}:{frame.tb_lineno}"
        detail = str(exc)[:80] if where.startswith('apple_attest.py') else ''
        logger.warning('breb_location_verify_failed error=%s at=%s %s', type(exc).__name__, where, detail)
        # A named check keeps its code; anything else, its type and line.
        reason = exc.code if isinstance(exc, _Refused) else f'{type(exc).__name__} at {where} {detail}'.strip()
        _record(owner, meta, evidence, False, reason)
        raise LocationError('No pudimos verificar tu ubicación y dispositivo. Activa la ubicación precisa y vuelve a intentarlo.') from exc
