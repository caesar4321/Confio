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
    'country': ('Por ahora compro en tiendas de Brasil (.br), México (.mx) y Bolivia (.bo). Escríbeme la dirección '
                'de la tienda.'),
    'store': 'No puedo trabajar en ese sitio.',
    'goal': 'Dime en una frase qué quieres comprar.',
    'active_task': 'Acabo de empezar esa compra hace un momento.',
    'store_busy': 'Estoy usando esa tienda para una compra tuya. Cuando termine puedes cerrar la sesión.',
    'checkout_open': ('Tu pedido en {site} sigue en curso. Espera a que termine o cancélalo en su tarjeta, y '
                      'después te ayudo con lo nuevo.'),
    'daily_limit': ('Llegaste al máximo de {limit} compras en 24 horas. En unas horas puedes pedirme otra.'),
    'busy': 'Ahora hay muchas compras en curso. Inténtalo en unos minutos.',
    'subscribe': 'Para que lo compre y lo pague yo, activa Cuenta inteligente. Después sigue aquí.',
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


def subscribed(user):
    """Buying and paying for the person is Cuenta inteligente's (spec decision 37)."""
    return _plus(user)


def _plus(user):
    """A Cuenta inteligente / IA+ subscriber: more purchases a day."""
    try:
        from assistant.billing import has_plus
        return bool(has_plus(user))
    except Exception:  # noqa: BLE001 - unknown is the ordinary limit, never none
        logger.warning('agent task plus check failed', exc_info=True)
        return False


def require_owner(account, user):
    if (getattr(account, 'account_type', None) != 'personal'
            or account.user_id != getattr(user, 'pk', None)):
        raise TaskRefused('not_personal')


def require_payable(account, user, country, meta):
    """A purchase this person could not pay here is never started, and they
    are never asked to confirm one: so this is asked at both."""
    from payment_accounts import payment_intents
    from security.minors import minor_refusal
    if not user.is_active or not payment_intents.allowed(user):
        raise TaskRefused('unavailable')
    minor = minor_refusal(user)
    if minor:
        raise TaskRefused('unavailable', minor)
    if countries.rail(country) is None:
        raise TaskRefused('country')
    # A verified identity, whoever pays it: the buying agent is not open to accounts nobody verified.
    # (Where Confío's own rail cannot serve them, pay_mode hands them the store's data instead.)
    from payment_accounts.schema import _verified_identity
    from payment_accounts.services import PaymentAccountError
    try:
        _verified_identity(account)
    except PaymentAccountError as exc:
        raise TaskRefused('unavailable', 'Verifica tu identidad en Confío para que pueda comprar por ti.') from exc
    # Whether Confío pays it or the person does from their bank is pay_mode's, at the order.


def pay_mode(task, meta):
    """('confio', '') or ('manual', the local account to offer): asked at the order card and
    again once the order is placed (an account opened meanwhile pays it)."""
    from payment_accounts.schema import _verified_identity
    from payment_accounts.services import PaymentAccountError
    rail = countries.rail(task.country)
    if rail is None:
        return 'manual', ''
    try:
        identity = _verified_identity(task.account)
    except PaymentAccountError:
        identity = None
    try:
        return rail.pay_mode(task.account, identity, meta)
    except Exception:  # noqa: BLE001 - an answer nobody could read is the person's own bank, never a card
        logger.warning('agent task pay mode failed', exc_info=True)
        return 'manual', ''


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


def start(account, user, *, goal, site, meta=None, kind='buy'):
    """A new purchase, or ('manage') help with an order already placed: its state, cancelling it,
    returning it, a refund. `goal` is the person's own words, stored verbatim. An earlier one still
    going is set aside for it: the person never manages them."""
    kind = 'manage' if kind == 'manage' else 'buy'
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
    # A browser never opened (cancelled first, or the vendor refused it) costs nothing and is not counted.
    free = Q(provider='') & ~Q(state__in=AgentTask.ACTIVE)
    per_day = conf.get('AGENT_TASKS_PER_DAY_PLUS' if _plus(user) else 'AGENT_TASKS_PER_DAY')
    if mine.filter(created_at__gte=timezone.now() - timedelta(days=1)).exclude(free).count() >= per_day:
        raise TaskRefused('daily_limit', MESSAGES['daily_limit'].format(limit=per_day))
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
            # Re-checked as it is set aside: one that reached the checkout meanwhile stays.
            mine.filter(pk__in=earlier, state__in=AgentTask.ACTIVE, checkout_at__isnull=True).update(
                state='cancelled', reason='replaced', wait_until=None, lease=None, lease_until=None, updated_at=now)
            earlier = list(mine.filter(pk__in=earlier, state='cancelled', reason='replaced', updated_at=now)
                           .values_list('pk', flat=True))
            task = AgentTask.objects.create(account=account, user=user, goal=goal, site=store, country=country,
                                            app_version=str((meta or {}).get('HTTP_X_CONFIO_VERSION') or '')[:20],
                                            kind=kind)
            runner.kick(task.pk)
    except IntegrityError as exc:
        # The earlier one reached the checkout as this one started: that order stays, said as such.
        open_order = mine.filter(state__in=AgentTask.ACTIVE, checkout_at__isnull=False).first()
        if open_order is not None:
            raise TaskRefused('checkout_open', MESSAGES['checkout_open'].format(site=open_order.site)) from exc
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
    # A card in the chat has its own answer (choose, sign_in, give_code, approve): this is not one.
    if task.state != 'needs_person' or task.reason in ('choose', 'login', 'otp', 'approve', 'subscribe'):
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


def _answered(account, user, task_id, reason, **fields):
    """The person answered a card in the chat: the agent goes on. `fields` may
    hold a callable `history` entry builder's result."""
    if not conf.get('AGENT_TASKS_ENABLED'):
        raise TaskRefused('unavailable')
    task = get(account, user, task_id)
    if task.state != 'needs_person' or task.reason != reason or not task.wait_until:
        raise TaskRefused('not_open')
    if task.wait_until <= timezone.now():
        runner.end(task, 'stopped', 'person_timeout', only={'state': 'needs_person'})
        raise TaskRefused('not_open')
    with transaction.atomic():
        if not AgentTask.objects.filter(pk=task.pk, state='needs_person', reason=reason, steps=task.steps).update(
                state='working', reason='', wait_until=None, updated_at=timezone.now(), **fields):
            raise TaskRefused('not_open')
        runner.kick(task.pk)
    task.refresh_from_db()
    return task


def sign_in(account, user, task_id, identifier, password):
    """The person's account at the store, from the card in the chat: into the vault, never anywhere else."""
    from . import vault
    identifier, password = str(identifier or '').strip(), str(password or '')
    if not identifier or not password or len(identifier) > vault.MAX_CHARS or len(password) > vault.MAX_CHARS:
        raise TaskRefused('goal', 'Escribe tu usuario y tu contraseña de la tienda.')
    task = get(account, user, task_id)
    if task.state != 'needs_person' or task.reason != 'login':
        raise TaskRefused('not_open')
    vault.save(user, task.site, identifier, password)
    return _answered(account, user, task_id, 'login')


def give_code(account, user, task_id, code):
    from . import vault
    code = ''.join(str(code or '').split())
    if not 3 <= len(code) <= 12:
        raise TaskRefused('goal', 'Escribe el código que te envió la tienda.')
    task = get(account, user, task_id)
    if task.state != 'needs_person' or task.reason != 'otp':
        raise TaskRefused('not_open')
    vault.put_code(task, code)
    return _answered(account, user, task_id, 'otp')


def approve(account, user, task_id, total=None):
    """The person approved the order named in the chat: its item and that total. The agent presses the
    store's final button only for the same total."""
    task = get(account, user, task_id)
    if task.reason == 'subscribe':
        # Held for Cuenta inteligente (decision 37). Subscribed now, the purchase goes on, and the ordinary
        # order card follows with who pays and the balance: this tap approves nothing.
        if not subscribed(user):
            raise TaskRefused('subscribe')
        entry = {'did': 'the person has Cuenta inteligente now', 'result': 'call ready_to_order again'}
        return _answered(account, user, task_id, 'subscribe',
                         history=[*(task.history or []), entry][-runner.Step.HISTORY_KEPT:])
    order = dict(task.order or {})
    if not order.get('total') or not order.get('button') or not order.get('page'):
        raise TaskRefused('not_open')
    if total is not None and str(total) != order['total']:
        # The card they tapped showed another order: they approve what they saw, or nothing.
        raise TaskRefused('not_open')
    # Bound to that item, that total, that button, on that page; used once (operate._order).
    order['approved'] = {key: order.get(key) for key in ('total', 'button', 'page', 'item', 'address')}
    order['approved']['manual'] = bool(order.get('manual'))   # who pays it, as their card said
    entry = {'did': 'the person approved the order', 'result': 'call ready_to_order again: it is pressed for you'}
    return _answered(account, user, task_id, 'approve', order=order,
                     history=[*(task.history or []), entry][-runner.Step.HISTORY_KEPT:])


def answer_request(account, user, task_id, yes, what=None):
    """Yes or no to the request the agent named about an order already placed (manage.py): yes, exactly
    that request (the one the card showed: `what`), that button on that page, is pressed once; no, nothing
    is sent and the task ends, straight from waiting (never through working)."""
    task = get(account, user, task_id)
    order = dict(task.order or {})
    request = order.get('request') or {}
    if not request.get('label') or task.state != 'needs_person' or task.reason != 'act':
        raise TaskRefused('not_open')
    if what is not None and str(what) != request.get('what'):
        raise TaskRefused('not_open')   # the card they tapped showed another request
    if not yes:
        if not runner.end(task, 'stopped', 'declined', only={'state': 'needs_person', 'reason': 'act'}):
            raise TaskRefused('not_open')
        task.refresh_from_db()
        return task
    order['request_approved'] = request
    return _answered(account, user, task_id, 'act', order=order,
                     history=[*(task.history or []), {'did': 'the person approved the request',
                                                      'result': 'call submit_request with it again'}
                              ][-runner.Step.HISTORY_KEPT:])


def answer_step(account, user, task_id, yes):
    """The person said yes or no to one step the click judge could not tell ("¿lo hago?"). Yes: that very
    control, on that very page, is pressed once (operate.checkout). No: the agent finds another way."""
    task = get(account, user, task_id)
    order = dict(task.order or {})
    asked = order.pop('ask_step', None) or {}
    if not asked.get('label'):
        raise TaskRefused('not_open')
    if yes:
        order['allowed_step'] = asked
        entry = {'did': f"the person allowed \"{asked['label']}\"", 'result': 'press it now'}
    else:
        entry = {'did': f"the person said no to \"{asked['label']}\"", 'result': 'find another way, never that'}
    return _answered(account, user, task_id, 'step', order=order,
                     history=[*(task.history or []), entry][-runner.Step.HISTORY_KEPT:])


def choose(account, user, task_id, index):
    """The person picked one of the products offered in the chat: the agent goes on with it."""
    if not conf.get('AGENT_TASKS_ENABLED'):
        raise TaskRefused('unavailable')
    task = get(account, user, task_id)
    options = task.options or []
    if task.state != 'needs_person' or task.reason != 'choose' or not task.wait_until:
        raise TaskRefused('not_open')
    if task.wait_until <= timezone.now():
        runner.end(task, 'stopped', 'person_timeout', only={'state': 'needs_person'})
        raise TaskRefused('not_open')
    try:
        picked = options[int(index)]
    except (IndexError, TypeError, ValueError) as exc:
        raise TaskRefused('not_found') from exc
    if int(index) < 0:
        raise TaskRefused('not_found')
    history = [*(task.history or []), {'did': runner.CHOSEN, 'result': str(picked.get('title') or '')[:120]}]
    with transaction.atomic():
        if not AgentTask.objects.filter(pk=task.pk, state='needs_person', reason='choose', steps=task.steps).update(
                state='working', reason='', wait_until=None, pending_url=str(picked.get('href') or ''),
                options=[picked], history=history[-runner.HISTORY_KEPT:], updated_at=timezone.now()):
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
    from .models import AgentCredential
    return sorted(set(AgentProfile.objects.filter(user=user).values_list('site', flat=True))
                  | set(AgentCredential.objects.filter(user=user).values_list('site', flat=True)))


def forget_store(account, user, site):
    """Delete a store's sign-in, at the vendor and here. Works with the switch off."""
    require_owner(account, user)
    if AgentTask.objects.filter(user=user, site=site, state__in=AgentTask.ACTIVE).exists():
        raise TaskRefused('store_busy')
    from . import vault
    vault.forget(user, site)
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
        # stopped and the person told. One a worker already touched is left to its own path.
        _each(active.filter(state='queued', provider='', checkout_at__isnull=True,
                            created_at__lt=now - timedelta(minutes=3)),
              lambda task: runner.end(task, 'stopped', 'unavailable', only={'state': 'queued', 'provider': ''}),
              'stranded')
    # Never started within minutes, worker or not: the person has moved on. It is not started late.
    _each(active.filter(state='queued', provider='', checkout_at__isnull=True,
                        created_at__lt=now - runner.NEVER_STARTED_AFTER),
          lambda task: runner.end(task, 'stopped', 'unavailable', only={'state': 'queued', 'provider': ''}),
          'never started')

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
        AgentTask.objects.filter(pk=task.pk).update(goal='', history=[], shown_target='', visited_pages=[],
                                                    options=[], order={}, pending_url='', secret_once='', trace=[])

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
    # A store's saved sign-in is not kept for a deleted person (deletion is soft: no cascade) nor past its use.
    from .models import AgentCredential
    unused = Q(updated_at__lt=now - timedelta(days=conf.get('AGENT_TASKS_PROFILE_IDLE_DAYS')))
    AgentCredential.objects.filter(unused | Q(user__is_active=False)).exclude(
        user__in=active.values('user')).delete()
    # A purchase a worker left behind after its browser closed is ended and said, never left in the way.
    _each(active.filter(state__in=AgentTask.RUNNING, session_expires_at__lt=now).exclude(lease_until__gt=now),
          lambda task: runner.end(task, 'stopped', 'session_expired', only={'state__in': AgentTask.RUNNING}),
          'expired sessions')
