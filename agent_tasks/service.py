"""What the owner (or the assistant, in their words) can do with a task."""
import logging
import uuid
from datetime import timedelta

from celery.exceptions import SoftTimeLimitExceeded
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from . import browsers, conf, countries, notes, qr, runner, sites, stores as store_names
from .models import AgentProfile, AgentTask

logger = logging.getLogger(__name__)

MAX_GOAL_CHARS = 400
LIVE_VIEW_MIN_SECONDS = 60
SWEEP_BATCH = 25
STARTS_LOCK = 47113502  # pg advisory lock: one start at a time

MESSAGES = {
    'unavailable': 'Todavía no puedo comprar por ti desde aquí.',
    'update_app': 'Actualiza la app para que pueda hacer compras por ti.',
    'not_personal': 'Las compras por ti funcionan solo en tu cuenta personal.',
    'country': ('Por ahora solo puedo comprar en tiendas de Brasil (.br, con Pix), Bolivia (.bo, con QR) y México '
                '(.mx, con transferencia SPEI). Escríbeme la dirección de la tienda.'),
    'store': 'No puedo trabajar en ese sitio.',
    'goal': 'Dime en una frase qué quieres comprar.',
    'active_task': 'Acabo de empezar esa compra hace un momento.',
    'checkout_open': ('Tu pedido en {site} sigue abierto. Termínalo o cancélalo en la pantalla de la tienda y '
                      'después te ayudo con lo nuevo.'),
    'daily_limit': 'Llegaste al máximo de compras por hoy. Mañana seguimos.',
    'busy': 'Ahora hay muchas compras en curso. Inténtalo en unos minutos.',
    'not_found': 'No encontré esa compra.',
    'not_open': 'Esto ya no está esperando tu respuesta.',
    'view': 'No reconozco esa pantalla. Ábrela de nuevo.',
    'left_store': 'El navegador salió de la tienda. Por seguridad no te muestro esa página.',
}


class TaskRefused(Exception):
    def __init__(self, code, message=None):
        super().__init__(message or MESSAGES.get(code, MESSAGES['unavailable']))
        self.code = code


def _version(value):
    try:
        return tuple(int(part) for part in str(value or '').strip().split('.'))
    except ValueError:
        return None


def build_supported(meta):
    floor = _version(conf.get('AGENT_TASKS_MIN_APP_VERSION'))
    version = _version((meta or {}).get('HTTP_X_CONFIO_VERSION'))
    return (floor is not None and version is not None and version >= floor
            and str((meta or {}).get(conf.get('AGENT_TASKS_CAPABLE_HEADER')) or '') == '1')


def require_owner(account, user):
    if (getattr(account, 'account_type', None) != 'personal'
            or account.user_id != getattr(user, 'pk', None)):
        raise TaskRefused('not_personal')


def require_payable(account, user, country, meta):
    """A purchase this person could not pay here is never started, and they
    are never asked to confirm one: so this is asked at both."""
    from payment_accounts import payment_intents
    from payment_accounts.schema import _verified_identity
    from payment_accounts.services import PaymentAccountError
    from security.minors import minor_refusal
    if not user.is_active or not payment_intents.allowed(user):
        raise TaskRefused('unavailable')
    minor = minor_refusal(user)
    if minor:
        raise TaskRefused('unavailable', minor)
    try:
        try:
            identity = _verified_identity(account)
        except PaymentAccountError:
            identity = None
        rail = countries.rail(country)
        if rail is None:
            raise TaskRefused('country')
        rail.ready(account, identity, meta)
    except PaymentAccountError as exc:
        raise TaskRefused('unavailable', str(exc) or None) from exc


# A browser worker leaves a mark that lasts a few minutes: when it answers the
# sweep's heartbeat (tasks.heartbeat, on its own queue) and whenever it runs a
# step. With no mark, purchases are not offered nor started: a queued one
# would wait forever. The mark is the key's own lifetime, not a clock compared
# across machines.
WORKER_KEY = 'agent_tasks:worker_seen'
HEARTBEAT_PENDING_KEY = 'agent_tasks:heartbeat_pending'
WORKER_FRESH_SECONDS = 300


def _shared_cache():
    """A per-process cache (LocMem: testnet, local) cannot carry the worker's mark to the web."""
    from django.conf import settings
    return 'locmem' not in str(settings.CACHES.get('default', {}).get('BACKEND', '')).lower()


def worker_seen():
    from django.core.cache import cache
    try:
        cache.set(WORKER_KEY, 1, WORKER_FRESH_SECONDS)
        cache.delete(HEARTBEAT_PENDING_KEY)
    except Exception:  # noqa: BLE001 - the next answer marks it
        logger.warning('agent task worker mark not saved', exc_info=True)


def worker_alive():
    if not _shared_cache():
        return True   # nothing to read here: never strand or refuse on a cache that cannot know
    from django.core.cache import cache
    try:
        return cache.get(WORKER_KEY) is not None
    except Exception:  # noqa: BLE001 - unknown is not alive
        return False


def start(account, user, *, goal, site, meta=None):
    """A new purchase. `goal` is the person's own words, stored verbatim. An
    earlier one still going is set aside for it: the person never manages them."""
    if (not conf.get('AGENT_TASKS_ENABLED') or not qr.available() or not conf.browserbase_api_key()
            or not worker_alive()):
        raise TaskRefused('unavailable')
    if not build_supported(meta):
        raise TaskRefused('update_app')
    require_owner(account, user)
    goal = str(goal or '').strip()
    if not 3 <= len(goal) <= MAX_GOAL_CHARS:
        raise TaskRefused('goal')
    store = sites.store(site)
    if store is None or store_names.imitates(store):
        raise TaskRefused('store')
    # The store's country decides how its checkout is paid, not the person's.
    country = countries.country_of(store, user)
    if country not in conf.get('AGENT_TASKS_COUNTRIES') or countries.rail(country) is None:
        raise TaskRefused('country')
    mine = AgentTask.objects.filter(user=user)
    # An order they may have confirmed at the store is never set aside by a new request.
    open_order = mine.filter(state__in=AgentTask.ACTIVE, checkout_at__isnull=False).first()
    if open_order is not None:
        raise TaskRefused('checkout_open', MESSAGES['checkout_open'].format(site=open_order.site))
    # Cancelled before its browser ever opened (no provider yet) costs nothing.
    free = Q(state='cancelled', provider='')
    if (mine.filter(created_at__gte=timezone.now() - timedelta(days=1)).exclude(free).count()
            >= conf.get('AGENT_TASKS_PER_DAY')):
        raise TaskRefused('daily_limit')
    require_payable(account, user, country, meta)
    now = timezone.now()
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [STARTS_LOCK])
            everyone = AgentTask.objects.all()
            # Their own earlier one is about to be set aside: it does not count against the new one.
            if (everyone.filter(state__in=AgentTask.ACTIVE).exclude(user=user).count()
                    >= conf.get('AGENT_TASKS_MAX_CONCURRENT')
                    or everyone.filter(created_at__gte=now - timedelta(days=1)).exclude(free).count()
                    >= conf.get('AGENT_TASKS_ALL_PER_DAY')):
                raise TaskRefused('busy')
            # Only now, with nothing left to refuse the new one: the earlier one is set aside
            # (its step, if one runs, loses its lease and stops). The new request is what they want.
            earlier = list(mine.filter(state__in=AgentTask.ACTIVE, checkout_at__isnull=True)
                           .values_list('pk', flat=True))
            mine.filter(pk__in=earlier, state__in=AgentTask.ACTIVE).update(
                state='cancelled', reason='replaced', wait_until=None, lease=None, lease_until=None, updated_at=now)
            task = AgentTask.objects.create(account=account, user=user, goal=goal, site=store, country=country,
                                            app_version=str((meta or {}).get('HTTP_X_CONFIO_VERSION') or '')[:20])
            runner.kick(task.pk)
    except IntegrityError as exc:
        raise TaskRefused('active_task') from exc
    for gone in AgentTask.objects.filter(pk__in=earlier):
        runner.close_session(gone)
        notes.post(gone, notes.stopped_text(gone, 'replaced'), 'end')
    notes.post(task, notes.say(notes.STARTED, task), 'start')
    return task


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise TaskRefused('not_found') from exc


def get(account, user, task_id):
    require_owner(account, user)
    task = AgentTask.objects.filter(internal_id=_uuid(task_id), account=account, user=user).first()
    if task is None:
        raise TaskRefused('not_found')
    return task


def active(account, user):
    require_owner(account, user)
    return AgentTask.objects.filter(account=account, user=user, state__in=AgentTask.ACTIVE).first()


def resume(account, user, task_id, view=None):
    """The person finished in the live view. With `view` (the token of the
    screen they were looking at) that tab is the one read; without it (an
    older app), the one the last open recorded."""
    if not conf.get('AGENT_TASKS_ENABLED'):
        raise TaskRefused('unavailable')
    task = get(account, user, task_id)
    if task.state != 'needs_person':
        raise TaskRefused('not_open')
    if not task.wait_until or task.wait_until <= timezone.now():
        runner.end(task, 'stopped', 'person_timeout', only={'state': 'needs_person'})
        raise TaskRefused('not_open')
    shown = {'shown_target': viewed_target(task, view)} if view else {}
    history = [*(task.history or []), {'did': runner.RESUMED, 'result': 'they say it is done'}]
    with transaction.atomic():
        if not AgentTask.objects.filter(pk=task.pk, state='needs_person', steps=task.steps).update(
                state='awaiting_code' if task.checkout_at else 'working', reason='', wait_until=None,
                history=history[-runner.HISTORY_KEPT:], updated_at=timezone.now(), **shown):
            raise TaskRefused('not_open')
        runner.kick(task.pk)
    task.refresh_from_db()
    return task


def cancel(account, user, task_id):
    task = get(account, user, task_id)
    if not runner.end(task, 'cancelled', 'cancelled'):
        raise TaskRefused('not_open')
    task.refresh_from_db()
    return task


# The tab a live view showed, signed for this task: "Ya terminé" sends it back
# and the code is read off that tab, the one the person was looking at, even
# if a later open (whose answer the phone never got) recorded another.
_VIEW_SALT = 'agent_tasks.view'


def view_token(task, target):
    from django.core import signing
    return signing.Signer(salt=_VIEW_SALT).sign(f'{task.internal_id}|{target[:64]}')


def viewed_target(task, view):
    """The tab a token names, if it was signed for this task; else TaskRefused('view')."""
    from django.core import signing
    try:
        task_id, _, target = signing.Signer(salt=_VIEW_SALT).unsign(str(view or '')).partition('|')
    except signing.BadSignature as exc:
        raise TaskRefused('view') from exc
    if task_id != str(task.internal_id) or not target:
        raise TaskRefused('view')
    return target


def live_view(account, user, task_id):
    """(url, seconds, host, view): a short-lived screen of that one browser, only
    while it is the person's turn; `view` names the tab it shows (view_token)."""
    if not conf.get('AGENT_TASKS_ENABLED'):
        raise TaskRefused('unavailable')
    task = get(account, user, task_id)
    if task.state != 'needs_person' or not task.session_id or not task.wait_until:
        raise TaskRefused('not_open')
    seconds = int((task.wait_until - timezone.now()).total_seconds())
    if seconds < LIVE_VIEW_MIN_SECONDS:
        raise TaskRefused('not_open')  # the vendor's shortest link would outlive the turn
    try:
        url, showing, target = browsers.provider(task.provider).live_view(task.session_id, seconds=seconds)
    except browsers.BrowserUnavailable as exc:
        logger.warning('agent task live view unavailable: %s', exc)
        raise TaskRefused('unavailable') from exc
    # The agent's browser never shows a page outside the store to type a password
    # in. Once the checkout is the person's it may really be elsewhere (3DS, a
    # gateway): they are shown it, with its real host above it.
    if task.checkout_at is None and not sites.within(showing, task.site):
        raise TaskRefused('left_store')
    # What is read later is this tab and no other: the one they are looking at.
    AgentTask.objects.filter(pk=task.pk, state='needs_person').update(shown_target=target[:64])
    return url, seconds, sites.host_of(showing), view_token(task, target)


def stores(account, user):
    require_owner(account, user)
    return sorted(set(AgentProfile.objects.filter(user=user).values_list('site', flat=True)))


def forget_store(account, user, site):
    """Delete a store's sign-in, at the vendor and here. Works with the switch off."""
    require_owner(account, user)
    if AgentTask.objects.filter(user=user, site=site, state__in=AgentTask.ACTIVE).exists():
        raise TaskRefused('active_task')
    for profile in AgentProfile.objects.filter(user=user, site=site):
        try:
            browsers.provider(profile.provider).delete_profile(profile.external_id)
        except browsers.BrowserUnavailable as exc:
            raise TaskRefused('unavailable', 'No pude borrar esa sesión ahora. Inténtalo de nuevo.') from exc
        profile.delete()


def _each(rows, work, what):
    for row in rows[:SWEEP_BATCH]:
        try:
            work(row)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - one row never stops the rest
            logger.warning('agent task sweep (%s) failed: %s', what, type(exc).__name__)


def sweep():
    from django.core.cache import cache

    from .tasks import heartbeat
    try:
        # Answered only by a browser worker (worker_alive() reads its mark). One at a
        # time: with no worker, they would pile up in the queue.
        if cache.add(HEARTBEAT_PENDING_KEY, 1, 120):
            heartbeat.apply_async(queue=conf.get('AGENT_TASKS_QUEUE'), expires=120)
    except Exception:  # noqa: BLE001 - the sweep goes on
        logger.warning('agent task heartbeat not sent', exc_info=True)
    _sweep()


def _sweep():
    """Expired waits end (first: they are the person's), lost steps run again,
    finished tasks release their browser, and what is old or a deleted
    person's is not kept."""
    now = timezone.now()
    active = AgentTask.objects.filter(state__in=AgentTask.ACTIVE)

    def expire(task):
        runner.end(task, 'stopped', 'person_timeout', only={'state': 'needs_person', 'wait_until__lte': now})

    _each(active.filter(state='needs_person', wait_until__lte=now).order_by('wait_until'), expire, 'waits')
    # Deletion here is a soft delete, so no FK cascade does any of this.
    _each(active.filter(user__is_active=False), lambda task: runner.end(task, 'cancelled', 'cancelled'), 'deleted')

    if not worker_alive():
        # No browser worker: a purchase that never opened a browser (queued, no provider) is
        # stopped and the person told. Anything a worker ever touched has its own timeouts.
        _each(active.filter(state='queued', provider='', checkout_at__isnull=True,
                            created_at__lt=now - timedelta(minutes=3)),
              lambda task: runner.end(task, 'stopped', 'unavailable', only={'state': 'queued', 'provider': ''}),
              'stranded')

    def rerun(task):
        # Touched first, so a backlog is one delivery per interval, not one per sweep.
        if AgentTask.objects.filter(pk=task.pk, updated_at=task.updated_at).update(updated_at=now):
            runner.kick(task.pk)

    _each(active.filter(state__in=AgentTask.RUNNING, updated_at__lt=now - timedelta(seconds=90))
          .exclude(lease_until__gt=now).order_by('updated_at'), rerun, 'lost steps')

    def release(task):
        if task.session_expires_at and task.session_expires_at <= now:
            AgentTask.objects.filter(pk=task.pk).update(session_id='', connect_url='')  # ended at the vendor by itself
        else:
            runner.close_session(task)

    # Random order, so rows that keep failing cannot starve the others.
    _each(AgentTask.objects.exclude(session_id='').exclude(state__in=AgentTask.ACTIVE).order_by('?'), release, 'sessions')
    # A worker that died between the payment card's row and its message.
    _each(AgentTask.objects.filter(state='payment_ready', payment_intent__isnull=False,
                                   updated_at__gt=now - timedelta(minutes=10),
                                   updated_at__lt=now - timedelta(seconds=90)).order_by('?'),
          lambda task: runner.post_payment(task, task.payment_intent), 'payment cards')

    def scrub(task):
        AgentTask.objects.filter(pk=task.pk).update(goal='', history=[], shown_target='', visited_pages=[])

    old = Q(created_at__lt=now - timedelta(days=conf.get('AGENT_TASKS_KEEP_DAYS')))
    _each(AgentTask.objects.exclude(state__in=AgentTask.ACTIVE).exclude(goal='')
          .filter(old | Q(user__is_active=False)).order_by('?'), scrub, 'retention')

    def forget(profile):
        if active.filter(user=profile.user_id, site=profile.site).exists():
            return
        browsers.provider(profile.provider).delete_profile(profile.external_id)
        profile.delete()

    idle = Q(last_used_at__lt=now - timedelta(days=conf.get('AGENT_TASKS_PROFILE_IDLE_DAYS')))
    _each(AgentProfile.objects.filter(idle | Q(user__is_active=False)).order_by('?'), forget, 'profiles')
