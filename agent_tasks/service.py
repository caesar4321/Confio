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
    'country': ('Por ahora compro en tiendas de Brasil (.br), México (.mx), Bolivia (.bo) y Venezuela (.ve). '
                'Escríbeme la dirección de la tienda.'),
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


def require_payable(account, user, country, meta, *, rail_needed=True):
    """A purchase this person could not pay here is never ordered, and they are never asked to confirm one.
    `rail_needed=False` at the start: any store may be searched (founder, 2026-11-25); the country's rail is
    asked when shopping turns into ordering, and its absence is said as the reason (stop 'no_rail')."""
    from payment_accounts import payment_intents
    from security.minors import minor_refusal
    if not user.is_active or not payment_intents.allowed(user):
        raise TaskRefused('unavailable')
    minor = minor_refusal(user)
    if minor:
        raise TaskRefused('unavailable', minor)
    rail = countries.rail(country)
    if rail_needed and rail is None:
        raise TaskRefused('country')
    # A verified identity, whoever pays it: the buying agent is not open to accounts nobody verified.
    # (Where Confío's own rail cannot serve them, pay_mode hands them the store's data instead.)
    from payment_accounts.schema import _verified_identity
    from payment_accounts.services import PaymentAccountError
    try:
        identity = _verified_identity(account)
    except PaymentAccountError as exc:
        raise TaskRefused('unavailable', 'Verifica tu identidad en Confío para que pueda comprar por ti.') from exc
    if rail_needed and rail.pay_before_order:
        # Paid before its order exists, by the Cuenta inteligente only: when it cannot, nothing is ordered
        # (stop 'no_rail'), never the person's card nor their own bank.
        try:
            rail.ready(account, identity, meta)
        except PaymentAccountError as exc:
            raise TaskRefused('country') from exc
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


def start(account, user, *, goal, site, meta=None, kind='buy', first_page='', chosen='', country=''):
    """A new purchase, or ('manage') help with an order already placed: its state, cancelling it,
    returning it, a refund. `goal` is the person's own words, stored verbatim. An earlier one still
    going is set aside for it: the person never manages them. `first_page`: a product's own page at
    this store, opened right after its home (an offer picked across stores, offers.py), and `chosen`
    the product's name as that offer wrote it; a page outside the store or one that acts is dropped.
    `country`: only for a store whose address does not say it (offers.country_of), never over its own."""
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
    country = countries.country_of(store, user) or (str(country or '').upper() if kind == 'buy' else '')
    from . import guard
    first_page = str(first_page or '').strip()
    if kind != 'buy' or (first_page and guard.address_refusal(first_page, store)):
        first_page = ''
    mine = AgentTask.objects.filter(user=user)
    # An order they may have confirmed at the store is never set aside by a new request.
    open_order = mine.filter(state__in=AgentTask.ACTIVE, checkout_at__isnull=False).first()
    # A Venezuelan store being paid before its order (pagomovil.py): its reference still goes to the store.
    open_order = open_order or mine.filter(state='payment_ready', phase='paying',
                                           updated_at__gte=timezone.now() - timedelta(hours=6)).first()
    if open_order is not None:
        raise TaskRefused('checkout_open', MESSAGES['checkout_open'].format(site=open_order.site))
    # Cancelled before its browser ever opened (no provider yet) costs nothing.
    # A browser never opened (cancelled first, or the vendor refused it) costs nothing and is not counted.
    free = Q(provider='') & ~Q(state__in=AgentTask.ACTIVE)
    per_day = conf.get('AGENT_TASKS_PER_DAY_PLUS' if _plus(user) else 'AGENT_TASKS_PER_DAY')
    if mine.filter(created_at__gte=timezone.now() - timedelta(days=1)).exclude(free).count() >= per_day:
        raise TaskRefused('daily_limit', MESSAGES['daily_limit'].format(limit=per_day))
    require_payable(account, user, country, meta, rail_needed=False)
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
                                            kind=kind, pending_url=first_page,
                                            history=([{'did': runner.CHOSEN, 'result': str(chosen)[:120]}]
                                                     if first_page and chosen else []))
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
    if task.state != 'needs_person' or task.reason in ('choose', 'login', 'otp', 'approve', 'subscribe',
                                                        'account_wait', 'address'):
        raise TaskRefused('not_open')
    if not task.wait_until or task.wait_until <= timezone.now():
        runner.end(task, 'stopped', 'person_timeout', only={'state': 'needs_person'})
        raise TaskRefused('not_open')
    shown = {'shown_target': viewed_target(task, view)} if view else {}
    history = [*(task.history or []), {'did': runner.RESUMED, 'result': 'they say it is done'}]
    with transaction.atomic():
        if not AgentTask.objects.filter(pk=task.pk, state='needs_person', steps=task.steps).update(
                # Reporting a paid Venezuelan order goes on in the browser, never back to the payment.
                state='awaiting_code' if task.checkout_at and task.phase != 'report' else 'working',
                reason='', wait_until=None,
                history=history[-runner.HISTORY_KEPT:], updated_at=timezone.now(), **shown):
            raise TaskRefused('not_open')
        runner.kick(task.pk)
    task.refresh_from_db()
    return task


def _end_wait(task):
    """A purchase that waited for the Cuenta inteligente and ran out of time: the order exists unpaid."""
    return runner.end(task, 'stopped', 'account_timeout', body=notes.say(notes.ACCOUNT_WAIT_EXPIRED, task),
                      only={'state': 'needs_person', 'reason': 'account_wait'})


def _ask_account_again(task, *, asked):
    """The held purchase goes back to the runner, which prepares its payment again from what was kept
    (runner.Step.pay_held) and lets the account pay it, or waits again. Never the personal wallet."""
    order = dict(task.order or {})
    held = dict(order.get('pay_hold') or {})
    if not held:
        return False
    if asked:
        held['asked'] = True
    order['pay_hold'] = held
    history = [*(task.history or []), {'did': 'account_wait', 'result': 'asked again' if asked else 'rechecked'}]
    with transaction.atomic():
        if not AgentTask.objects.filter(pk=task.pk, state='needs_person', reason='account_wait',
                                        steps=task.steps).update(
                state='awaiting_code', reason='', wait_until=None, order=order,
                history=history[-runner.HISTORY_KEPT:], updated_at=timezone.now()):
            return False
        runner.kick(task.pk)
    return True


def resume_payment(account, user, task_id):
    """"Ya lo hice: pagar": the person switched purchases on, moved money in or raised the cap. The account is
    asked again; if it still cannot pay, the purchase keeps waiting and they are told why."""
    if not conf.get('AGENT_TASKS_ENABLED'):
        raise TaskRefused('unavailable')
    task = get(account, user, task_id)
    if task.state != 'needs_person' or task.reason != 'account_wait':
        raise TaskRefused('not_open')
    if not task.wait_until or task.wait_until <= timezone.now():
        _end_wait(task)
        raise TaskRefused('not_open')
    if not _ask_account_again(task, asked=True):
        raise TaskRefused('not_open')
    task.refresh_from_db()
    return task


def account_wait(account, user, task_id):
    """order['account_wait'] of a purchase waiting for the account, or None."""
    task = get(account, user, task_id)
    if task.state != 'needs_person' or task.reason != 'account_wait':
        return None, task
    return (task.order or {}).get('account_wait') or None, task


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


def approve(account, user, task_id, total=None, address=None):
    """The person approved the order named in the chat: its item, that total and that address. The agent
    presses the store's final button only for the same total and address. Builds before 5.4.3 send no address."""
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
    if address is not None and str(address) != (order.get('address') or ''):
        # The same total to another address is another order (founder, 2026-11-26).
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


MAX_ADDRESS_CHANGES = 3


def change_address(account, user, task_id):
    """On the order card, the person wants it delivered elsewhere: the agent opens the store's own way to change
    this order's address and lists their saved ones on the card (operate._addresses). Nothing is approved."""
    task = get(account, user, task_id)
    if task.state != 'needs_person' or task.reason != 'approve' or not (task.order or {}).get('address'):
        raise TaskRefused('not_open')
    if int((task.counts or {}).get('address_changes') or 0) >= MAX_ADDRESS_CHANGES:
        raise TaskRefused('goal', 'Ya cambiamos la dirección varias veces. Elige la que quieres en la tienda y '
                                  'vuelve a pedírmelo.')
    order = {**(task.order or {}), 'approved': None, 'address_wanted': True, 'addresses': [],
             'address_choice': ''}
    entry = {'did': 'the person wants another delivery address',
             'result': 'open the store\'s way to change this order\'s address, then call show_addresses'}
    return _answered(account, user, task_id, 'approve', order=order,
                     counts={**(task.counts or {}), 'address_wanted': 0, 'address_changes':
                             int((task.counts or {}).get('address_changes') or 0) + 1},
                     history=[*(task.history or []), entry][-runner.Step.HISTORY_KEPT:])


def choose_address(account, user, task_id, index, address=None):
    """The person picked one of their saved addresses on the card (`address`: the words that card showed).
    The agent selects that one for this order; the order card then shows it and asks again."""
    task = get(account, user, task_id)
    listed = (task.order or {}).get('addresses') or []
    if task.state != 'needs_person' or task.reason != 'address' or not isinstance(index, int) \
            or not 0 <= index < len(listed):
        raise TaskRefused('not_open')
    picked = str(listed[index])
    if address is not None and str(address) != picked:
        raise TaskRefused('not_open')   # the card they tapped listed another one
    order = {**(task.order or {}), 'address_wanted': False, 'addresses': [], 'address_choice': picked,
             'approved': None}
    entry = {'did': 'the person chose the delivery address', 'result': f'select "{picked[:110]}" for this order, '
                                                                       'then go on to the final button'}
    return _answered(account, user, task_id, 'address', order=order,
                     history=[*(task.history or []), entry][-runner.Step.HISTORY_KEPT:])


NOTIFY_REASONS = ('no_rail', 'payer_data')


def store_paid(task_pk, *, reference, paid_ves, origin_bank='', paid_at=''):
    """The funding leg paid a Venezuelan store's Pago Móvil (pagomovil.py): the reference goes to the store in
    a fresh browser session (phase 'report'). Idempotent: the same values again are a no-op. True when kept."""
    from decimal import Decimal, InvalidOperation
    from . import pagomovil
    try:
        paid = {'reference': str(reference or '').strip()[:40], 'paid_ves': format(Decimal(str(paid_ves)), 'f'),
                'origin_bank': str(origin_bank or '')[:4], 'paid_at': str(paid_at or timezone.now().isoformat())}
    except (InvalidOperation, TypeError, ValueError):
        paid = None
    task = AgentTask.objects.filter(pk=task_pk).first()
    if task is None:
        logger.error('agent task store_paid: no task %s', task_pk)
        return False
    order = task.order or {}
    if order.get('paid'):
        same = paid is not None and {k: order['paid'].get(k) for k in ('reference', 'paid_ves')} == {
            k: paid[k] for k in ('reference', 'paid_ves')}
        if not same:
            logger.error('agent task %s: store_paid again with other values', task.internal_id)
        return same
    if paid is None or not paid['reference'] or task.phase != 'paying' or not order.get('pay_first'):
        logger.error('agent task %s: store_paid refused (phase %s)', task.internal_id, task.phase)
        try:
            from config.ops_alerts import send_ops_alert
            send_ops_alert(f'Compra VE {task.internal_id}: Pago Móvil pagado a {task.site} sin tarea que lo reporte '
                           f"(ref {str(reference or '?')[:40]}, Bs {paid_ves}).",
                           dedupe_key=f'agent_store_paid:{task.pk}', dedupe_seconds=86400)
        except Exception:  # noqa: BLE001
            logger.exception('agent store_paid alert failed')
        return False
    runner.close_session(task)
    counts = {**(task.counts or {}), 'report_tries': 0, 'report_steps': 0}
    try:
        with transaction.atomic():
            moved = AgentTask.objects.filter(pk=task.pk, phase='paying', state__in=('payment_ready', 'stopped')).update(
                order={**{key: value for key, value in order.items() if key != 'pay_hold'}, 'paid': paid},
                phase='report', state='queued', reason='', wait_until=None,
                session_id='', connect_url='', session_expires_at=None, lease=None, lease_until=None, failures=0,
                counts=counts, updated_at=timezone.now())
            if moved:
                runner.kick(task.pk)
    except IntegrityError:
        # Another purchase of theirs is open (start refuses this; a race): the person reports it themselves.
        AgentTask.objects.filter(pk=task.pk).update(order={**order, 'paid': paid}, phase='report', state='stopped',
                                                    reason='report_failed', updated_at=timezone.now())
        task.refresh_from_db()
        notes.post(task, notes.stopped_text(task, 'report_failed'), 'end', push='check')
        pagomovil.alert(task, 'another purchase open')
        return True
    if not moved:
        return False
    task.refresh_from_db()
    notes.post(task, notes.paid_words(task, notes.PAID_REPORTING), 'paid')
    return True


def store_unpaid(task_pk, *, why=''):
    """The funding leg could not pay a Venezuelan store's Pago Móvil: no order is placed. Idempotent."""
    task = AgentTask.objects.filter(pk=task_pk).first()
    if task is None or task.phase != 'paying' or not (task.order or {}).get('pay_first'):
        return False
    if task.state == 'stopped' and task.reason == 'unpaid':
        return True
    order = {**(task.order or {}), 'unpaid_why': str(why or 'unpaid')[:40]}
    if not AgentTask.objects.filter(pk=task.pk, phase='paying').exclude(state__in=('stopped', 'cancelled')).update(
            state='stopped', reason='unpaid', order=order, wait_until=None, lease=None, lease_until=None,
            updated_at=timezone.now()):
        return False
    task.refresh_from_db()
    runner.close_session(task)
    notes.post(task, notes.stopped_text(task, 'unpaid'), 'end', push='check')
    return True


def answer_notify(account, user, task_id, yes):
    """Sí, avísame / Solo miraba on a purchase stopped because its store's country cannot be paid yet (stop
    'no_rail'): the fake-door probe for store payments there. Kept on the task, whose country is the store's;
    the last answer counts."""
    task = get(account, user, task_id)
    # Also a Venezuelan store that matches its Pago Móvil by the payer (stop 'payer_data').
    if task.state != 'stopped' or task.reason not in NOTIFY_REASONS:
        raise TaskRefused('not_open')
    task.order = {**(task.order or {}), 'notify': 'yes' if yes else 'no',
                  'notify_at': timezone.now().isoformat()}
    task.save(update_fields=['order', 'updated_at'])
    return task


def choose(account, user, task_id, index, cap=None):
    """The person picked one of the products offered in the chat: the agent goes on with it."""
    from . import operate
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
                options=[picked], history=history[-runner.HISTORY_KEPT:], updated_at=timezone.now(),
                # "Elegir" approves this item up to the top total its card showed (spec decision 42): only
                # when the app sent back that very top total (a build that never showed one sets none), and
                # only for a subscriber then (a choice made before subscribing is never a purchase).
                order={**(task.order or {}), 'cap': {
                    'item': str(picked.get('title') or ''), 'amount': picked['cap_amount'],
                    'text': picked.get('cap') or '', 'subscribed': subscribed(user),
                    'price': format(operate.unit_price(picked.get('price'), task.country), 'f')}}
                if picked.get('cap_amount') and cap is not None and str(cap) == picked.get('cap')
                else (task.order or {})):
            raise TaskRefused('not_open')
        runner.kick(task.pk)
    task.refresh_from_db()
    return task


def choose_cart(account, user, task_id, picks, cap=None):
    """The person chose one or more of the products offered, each with a quantity, and confirmed once (spec
    decision 42: "Elegir"). `picks` is [{'index', 'quantity'}]; `cap` the top total the app showed above the
    confirm button. The agent opens each product and adds it in its quantity; the store's cart must then hold
    exactly those. Choosing approves the purchase up to that top total only when the app sent back the very
    top total worked out here from the chosen prices and quantities (operate.cart_top), and only for a
    subscriber then; otherwise the ordinary order card asks."""
    from . import operate
    if not conf.get('AGENT_TASKS_ENABLED'):
        raise TaskRefused('unavailable')
    task = get(account, user, task_id)
    options = task.options or []
    if task.state != 'needs_person' or task.reason != 'choose' or not task.wait_until:
        raise TaskRefused('not_open')
    if task.wait_until <= timezone.now():
        runner.end(task, 'stopped', 'person_timeout', only={'state': 'needs_person'})
        raise TaskRefused('not_open')
    chosen = {}
    try:
        for pick in list(picks or [])[:runner.MAX_OPTIONS + 1]:
            index, quantity = pick['index'], pick['quantity']
            if isinstance(index, bool) or isinstance(quantity, bool):
                raise TypeError
            index, quantity = int(index), int(quantity)
            if not 0 <= index < len(options) or index in chosen or not 1 <= quantity <= operate.MAX_QUANTITY:
                raise ValueError
            chosen[index] = quantity
    except (KeyError, TypeError, ValueError) as exc:
        raise TaskRefused('not_found') from exc
    if not chosen or len(chosen) > len(options) or len(list(picks or [])) != len(chosen):
        raise TaskRefused('not_found')
    # In the order they were offered: the first one's price gives the top total its currency mark.
    picked = [{**options[index], 'quantity': chosen[index]} for index in sorted(chosen)]
    cart = [{'title': str(one.get('title') or ''), 'price': str(one.get('price') or ''),
             'href': str(one.get('href') or ''), 'image': str(one.get('image') or ''),
             'quantity': one['quantity'], 'opened': False} for one in picked]
    order = {**(task.order or {}), 'cart': cart}
    order.pop('cap', None)
    # Every chosen price was read off the results page (its own top total was set): only then a top total.
    if all(one.get('cap_amount') for one in picked):
        amount, text = operate.cart_top([(one['price'], one['quantity']) for one in cart], task.country)
        if amount is not None and cap is not None and str(cap) == text:
            order['cap'] = {'item': operate.cart_summary(cart), 'amount': format(amount, 'f'), 'text': text,
                            'subscribed': subscribed(user),
                            'items': [{'title': one['title'], 'quantity': one['quantity'],
                                       'price': format(operate.unit_price(one['price'], task.country), 'f')}
                                      for one in cart]}
    history = [*(task.history or []), {'did': runner.CHOSEN, 'result': operate.cart_summary(cart)[:120]}]
    with transaction.atomic():
        if not AgentTask.objects.filter(pk=task.pk, state='needs_person', reason='choose', steps=task.steps).update(
                state='working', reason='', wait_until=None, pending_url=cart[0]['href'], options=picked,
                order=order, history=history[-runner.HISTORY_KEPT:], updated_at=timezone.now()):
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


def account_changed(task):
    """Whether the account's standing for this held purchase is not what the person was told (it pays now, or
    something else is missing). Read with the dollars of its last prepared payment; the runner prices it again
    before anything moves. Unread is 'no change'."""
    from smart_account import purchases
    held = (task.order or {}).get('pay_hold') or {}
    told = ((task.order or {}).get('account_wait') or {}).get('code')
    try:
        units = int(held.get('units') or 0)
        if units <= 0:
            return False
        found = purchases.standing(task.user, units, personal_address=task.account.bsc_address or '')
    except Exception as exc:  # noqa: BLE001 - asked again next time
        logger.warning('agent task account recheck failed: %s', type(exc).__name__)
        return False
    return found.pays or (found.code != told and found.code != 'off')


def _sweep():
    """Expired waits end (first: they are the person's), lost steps run again,
    finished tasks release their browser, and what is old or a deleted
    person's is not kept."""
    now = timezone.now()
    active = AgentTask.objects.filter(state__in=AgentTask.ACTIVE)

    def expire(task):
        if task.reason == 'account_wait':
            # The order exists at the store, unpaid: said so, never "pídemelo otra vez".
            runner.end(task, 'stopped', 'account_timeout', body=notes.say(notes.ACCOUNT_WAIT_EXPIRED, task),
                       only={'state': 'needs_person', 'reason': 'account_wait', 'wait_until__lte': now})
            return
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

    def recheck(task):
        # Touched first, so a slow chain is one look per interval, not one per sweep.
        if not AgentTask.objects.filter(pk=task.pk, state='needs_person', reason='account_wait',
                                        updated_at=task.updated_at).update(updated_at=now):
            return
        task.refresh_from_db()
        if account_changed(task):
            _ask_account_again(task, asked=False)

    # A purchase waiting for the Cuenta inteligente is asked again every few minutes: when the person has
    # done what it needed, it is paid without another tap.
    _each(active.filter(state='needs_person', reason='account_wait', wait_until__gt=now,
                        updated_at__lt=now - timedelta(seconds=conf.get('AGENT_TASKS_ACCOUNT_RECHECK_SECONDS')))
          .order_by('updated_at'), recheck, 'account waits')

    # Random order, so rows that keep failing cannot starve the others.
    _each(AgentTask.objects.exclude(session_id='').exclude(state__in=AgentTask.ACTIVE).order_by('?'), release, 'sessions')
    # A worker that died between the payment card's row and its message.
    # A purchase the account pays (reason 'account') has no card: its note is account_pay's.
    _each(AgentTask.objects.filter(state='payment_ready', payment_intent__isnull=False,
                                   updated_at__gt=now - timedelta(minutes=10),
                                   updated_at__lt=now - timedelta(seconds=90)).exclude(reason__in=('account', 'reported'))
          .order_by('?'),
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
    # A held purchase (order['pay_hold']) needs no browser: its payment is read from what was kept.
    _each(active.filter(state__in=AgentTask.RUNNING, session_expires_at__lt=now).exclude(lease_until__gt=now)
          .exclude(order__has_key='pay_hold').exclude(phase='report'),
          lambda task: runner.end(task, 'stopped', 'session_expired', only={'state__in': AgentTask.RUNNING}),
          'expired sessions')
