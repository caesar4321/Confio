"""Device location, in one place: every reading the app sends, whatever asked
for it, goes through record_reading into LocationReading (coordinates kept:
they are the evidence for geo eligibility). Features keep their own outcome
records (BrebLocationCheck, MarketplaceLocationCheck); residence reads the
readings (gps_residence_country_for)."""
import logging
import math
import os
from datetime import datetime, timedelta, timezone as dt_timezone
from functools import lru_cache

logger = logging.getLogger(__name__)

# A reading fixes a country only this precisely (metres).
MAX_ACCURACY_M = 5000
# Device time may lag or lead the server this much.
MAX_AGE_MS = 10 * 60 * 1000
MAX_FUTURE_MS = 2 * 60 * 1000


@lru_cache(maxsize=1)
def _zone_countries() -> dict:
    """IANA zone → ISO-2, from the tz database's own table (zone.tab)."""
    import tzdata
    path = os.path.join(os.path.dirname(tzdata.__file__), 'zoneinfo', 'zone.tab')
    mapping = {}
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) >= 3:
                mapping[parts[2].strip()] = parts[0].strip().upper()
    return mapping


@lru_cache(maxsize=1)
def _finder():
    from timezonefinder import TimezoneFinder
    return TimezoneFinder()


def country_at(latitude: float, longitude: float) -> str:
    """ISO-2 country a point falls in, '' at sea or unknown. Time zones follow
    national borders, and each zone belongs to exactly one country."""
    try:
        zone = _finder().timezone_at(lat=latitude, lng=longitude)
    except Exception:  # noqa: BLE001 — an unknown point is "no country", never a guess
        return ''
    return _zone_countries().get(zone or '', '')


def _valid_point(latitude, longitude, accuracy) -> bool:
    numbers = [latitude, longitude] + ([] if accuracy is None else [accuracy])
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in numbers):
        return False
    return -90 <= latitude <= 90 and -180 <= longitude <= 180 and (accuracy is None or 0 <= accuracy <= 1e7)


def record_reading(user, *, purpose, latitude, longitude, accuracy_m=None, mocked=None, verified=False,
                   platform='', provider='', reading_at_ms=None, meta=None):
    """Store one reading; returns it, or None when the values are unusable.
    Never raises: recording must not change any feature's answer."""
    from security.models import LocationReading
    try:
        if not _valid_point(latitude, longitude, accuracy_m):
            return None
        reading_at = None
        if type(reading_at_ms) in (int, float) and math.isfinite(reading_at_ms) and 0 < reading_at_ms < 1e14:
            reading_at = datetime.fromtimestamp(reading_at_ms / 1000, tz=dt_timezone.utc)
        ip, ip_country = None, ''
        if meta:
            import ipaddress
            from security.request_utils import extract_client_ip_from_meta
            from users.residence import _request_ip_country
            raw = extract_client_ip_from_meta(meta) or None
            try:
                ip = str(ipaddress.ip_address(raw)) if raw else None
            except ValueError:
                ip = None
            # CF-IPCountry only on a request that really came through
            # Cloudflare: this country corroborates residence.
            ip_country = (_request_ip_country(meta) or '')[:2].upper()
        return LocationReading.objects.create(
            user=user, purpose=purpose, latitude=float(latitude), longitude=float(longitude),
            accuracy_m=None if accuracy_m is None else float(accuracy_m),
            country=country_at(float(latitude), float(longitude)),
            mocked=mocked if isinstance(mocked, bool) else None, verified=bool(verified),
            platform=(platform or '')[:8], provider=(provider or '')[:16], reading_at=reading_at,
            ip_address=ip, ip_country=ip_country)
    except Exception as exc:  # noqa: BLE001
        # The class only: the text could quote the coordinates.
        logger.warning('location_reading_record_failed error=%s', type(exc).__name__)
        return None


def gps_residence_country_for(user, *, days: int = 90, min_days: int = 2):
    """Where the device says the user lives (ISO-2), or None.

    Never weaker evidence than IP (residence gates regulated products, e.g.
    the US-person exclusion): a reading counts when device integrity proved
    it, or when the request it came in on had an IP in the same country that
    is not a VPN, Tor or datacenter exit. Mock and imprecise readings and
    refused Bre-B attempts never count. Each day votes once, for the country
    most of that day's readings were in (a tied day does not vote); the
    country holding a strict majority of voting days wins."""
    if not getattr(user, 'pk', None):
        return None
    from collections import Counter
    from django.db.models import Q
    from django.utils import timezone
    from security.models import IPAddress, LocationReading
    since = timezone.now() - timedelta(days=days)
    rows = list(LocationReading.objects
                .filter(user=user, created_at__gte=since, accuracy_m__lte=MAX_ACCURACY_M)
                .exclude(mocked=True).exclude(country='')
                .exclude(purpose=LocationReading.PURPOSE_BREB, verified=False)
                .values_list('country', 'created_at', 'verified', 'ip_address', 'ip_country'))
    ips = {ip for _c, _t, verified, ip, _ic in rows if not verified and ip}
    flagged = set(IPAddress.objects.filter(ip_address__in=ips).filter(
        Q(is_vpn=True) | Q(is_tor=True) | Q(is_datacenter=True)).values_list('ip_address', flat=True)) if ips else set()
    per_day: dict = {}
    for country, created_at, verified, ip, ip_country in rows:
        if not verified and (not ip or ip in flagged or (ip_country or '').upper() != country):
            continue
        per_day.setdefault(created_at.date(), Counter())[country] += 1
    votes = Counter()
    for counts in per_day.values():
        ranked = counts.most_common(2)
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            votes[ranked[0][0]] += 1
    total = sum(votes.values())
    if total < min_days:
        return None
    country, seen = votes.most_common(1)[0]
    return country if seen * 2 > total else None
