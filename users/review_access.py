"""The App Review deep link: confio://review?country=AR|US|GB&k=<token>.

Reviewers sign in with their own Apple/Google account; there is no phone
screen any more to type a reviewer number into. The link moves that account
to a country for 14 days so one account can show the Argentine experience
(every geo policy passes) and the US/UK ones (the blocks a real user there
gets).

The token is fixed and long (REVIEW_LINK_TOKEN); clearing it switches every
grant off at once. A leaked Argentine link is bounded by the monthly cap on
exempt grants, the 14-day expiry and an ops alert on every use.
"""
import hmac
import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone

from .models_review_access import ReviewAccess

logger = logging.getLogger(__name__)

REVIEW_COUNTRIES = {'AR': True, 'US': False, 'GB': False}  # country → geo_exempt
ACCESS_DAYS = 14
FAILED_ATTEMPTS_PER_HOUR = 5
REPEAT_WINDOW = timedelta(minutes=1)


def _token() -> str:
    return str(getattr(settings, 'REVIEW_LINK_TOKEN', '') or '').strip()


def active_review_access(user):
    """The account's live grant, or None. No token configured means none."""
    if not _token() or not getattr(user, 'pk', None):
        return None
    return (ReviewAccess.objects
            .filter(user_id=user.pk, superseded_at__isnull=True, expires_at__gt=timezone.now())
            .order_by('-created_at').first())


def is_review_link_exempt(user) -> bool:
    access = active_review_access(user)
    return bool(access and access.geo_exempt)


def latest_review_access(user):
    return ReviewAccess.objects.filter(user_id=user.pk).order_by('-created_at').first()


def apply_review_access(user, country: str, token: str, meta=None) -> tuple[bool, str | None]:
    """(ok, error). The account always comes from the caller (JWT)."""
    failures_key = f'review_link_failures:{user.pk}'
    if (cache.get(failures_key) or 0) >= FAILED_ATTEMPTS_PER_HOUR:
        return False, 'Demasiados intentos. Probá de nuevo en una hora.'
    expected = _token()
    if not expected or not hmac.compare_digest(str(token or ''), expected):
        cache.set(failures_key, (cache.get(failures_key) or 0) + 1, 3600)
        return False, 'Enlace inválido.'
    country = str(country or '').strip().upper()
    if country not in REVIEW_COUNTRIES:
        return False, 'País no disponible.'
    geo_exempt = REVIEW_COUNTRIES[country]

    now = timezone.now()
    with transaction.atomic():
        type(user).objects.select_for_update().filter(pk=user.pk).first()
        # The same link delivered twice (cold start and the link listener, or
        # a double tap) is one grant: a second row would count twice toward
        # the monthly cap.
        if ReviewAccess.objects.filter(
                user_id=user.pk, country=country, superseded_at__isnull=True,
                created_at__gte=now - REPEAT_WINDOW).exists():
            return True, None
        if geo_exempt:
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('review_link_cap'))")
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            granted = ReviewAccess.objects.filter(geo_exempt=True, created_at__gte=month_start).count()
            if granted >= int(getattr(settings, 'REVIEW_LINK_MONTHLY_CAP', 10)):
                return False, 'Este enlace ya no está disponible este mes.'
        user.refresh_from_db(fields=['country', 'country_source'])
        previous = ReviewAccess.objects.filter(user_id=user.pk).order_by('-created_at').first()
        if previous and user.country_source == user.COUNTRY_SOURCE_REVIEW:
            # Still on a review country (live, or ended but not yet restored
            # by the daily refresh): the country before review is the one
            # that grant remembered.
            before, before_source = previous.country_before_review, previous.source_before_review
        else:
            before, before_source = user.country, user.country_source
        ReviewAccess.objects.filter(user_id=user.pk, superseded_at__isnull=True).update(superseded_at=now)
        ReviewAccess.objects.create(
            user=user, country=country, geo_exempt=geo_exempt,
            country_before_review=before, source_before_review=before_source or '',
            expires_at=now + timedelta(days=ACCESS_DAYS),
        )
        user.country = country
        user.country_source = user.COUNTRY_SOURCE_REVIEW
        user.country_updated_at = now
        user.save(update_fields=['country', 'country_source', 'country_updated_at'])

    from security.geo import country_for_request
    try:
        ip_country = country_for_request(meta) or '?'
    except Exception:  # noqa: BLE001
        ip_country = '?'
    transaction.on_commit(lambda: _alert(user, country, geo_exempt, ip_country))
    return True, None


def _alert(user, country, geo_exempt, ip_country):
    try:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(
            f'Review link applied: user {user.pk} (joined {user.date_joined:%Y-%m-%d}) → {country}'
            f'{" GEO-EXEMPT" if geo_exempt else ""}, request IP country {ip_country}')
    except Exception:  # noqa: BLE001 — the grant stands; the alert is best-effort
        logger.exception('[REVIEW] ops alert failed user_id=%s', user.pk)
