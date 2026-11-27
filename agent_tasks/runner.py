"""One step of a task per worker run; the state lives in the row.

Two phases, and the line between them is `checkout_at`:

  before  the model may search, follow a link by GET and add to the cart
          (guard.py). It never enters a checkout.
  after   the person has the browser. No model runs, no script runs in a
          page and nothing is pressed, typed or opened. When they say they
          are done, a picture is taken of the one tab they were shown, with
          everything embedded painted over. One payment-sized QR of the
          country's rail (countries.py) on a store page the agent never read,
          vouched for by that rail, becomes a payment card, which they
          approve like any other.

The lease makes a step single. Every write is conditional on that lease and
on a live state, so a cancellation wins over a step in flight.
"""
import hashlib
import logging
import re
import time
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from . import agent, browsers, conf, countries, guard, notes, page as pages, qr, sites
from .cdp import CdpError, Page
from .models import AgentProfile, AgentTask

logger = logging.getLogger(__name__)

LEASE = timedelta(seconds=180)
MAX_FAILURES = 3
MAX_LEFT_STORE = 3
# The decoder measures the symbol without its quiet zone: a 128 px payment QR
# image is about 110, a 90 px product thumbnail about 75. Size is no proof of
# who drew a QR, so a small one counts only when the page also writes that
# very code as text ("copia e cola"); with no code written, only a large one.
MIN_QR_CSS = 100
MIN_QR_CSS_ALONE = 140
MAX_VISITED = 200
AFTER_PRESS_SECONDS = 8
SESSION_MARGIN = timedelta(seconds=30)
PERSON_TURN_MIN = timedelta(seconds=90)
HISTORY_KEPT = 30
CHECKOUT_TURN_MIN = timedelta(minutes=5)
ASKED = 'asked the person: '
RESUMED = 'the person took the screen'
BACK_TO_AGENT = frozenset({'login', 'captcha', 'step'})
# A CAPTCHA is solved by the browser's vendor: the agent only waits for it.
CAPTCHA, CAPTCHA_TRIES, CAPTCHA_WAIT_SECONDS = 'captcha', 8, 6
# Products shown in the chat for the person to pick one.
CHOSEN, MAX_OPTIONS = 'the person chose', 5
UNREAD = 'the payment was not read'
# In these the person has the whole store in front of them and may well finish
# the purchase, so each is already the hand-over: the agent does not come back.
CARRIES_ON = frozenset({'details', 'choice', 'consent'})
GIVE_UP = frozenset({'not_found', 'no_payment', 'out_of_stock', 'cannot_do'})


class Lost(Exception):
    """The task was cancelled, ended or taken over while this step ran."""


# A purchase not started within this is stopped, never started late (the sweep and the step both check).
NEVER_STARTED_AFTER = timedelta(minutes=10)


def kick(task_id, countdown=0):
    def send():
        from .tasks import step
        turn = AgentTask.objects.filter(pk=task_id).values_list('steps', flat=True).first()
        try:
            # The step number is a token: a duplicate delivery finds it spent.
            # A step nobody took within minutes is stale: the sweep sends a fresh one if it still matters.
            step.apply_async(args=[task_id, turn], countdown=countdown, queue=conf.get('AGENT_TASKS_QUEUE'),
                             expires=countdown + 300)
        except Exception:  # noqa: BLE001 - the sweep picks it up
            logger.exception('agent task step was not queued')
    transaction.on_commit(send)


def close_session(task):
    """Release the vendor's browser and forget how to reach it. The sweep retries a failed release."""
    row = AgentTask.objects.filter(pk=task.pk).values('session_id', 'provider').first()
    if not row or not row['session_id']:
        return
    try:
        browsers.provider(row['provider']).close(row['session_id'])
    except Exception as exc:  # noqa: BLE001
        logger.warning('agent task browser was not released: %s', type(exc).__name__)
        return
    AgentTask.objects.filter(pk=task.pk, session_id=row['session_id']).update(session_id='', connect_url='')


def end(task, state, reason, *, lease=None, body=None, only=None, **fields):
    """End a task once. False when it had already ended (or the lease is lost)."""
    rows = AgentTask.objects.filter(pk=task.pk, state__in=AgentTask.ACTIVE).filter(**(only or {}))
    if lease is not None:
        rows = rows.filter(lease=lease)
    values = dict(fields, state=state, reason=reason, wait_until=None, lease=None, lease_until=None)
    if not rows.update(**values, updated_at=timezone.now()):
        return False
    task.refresh_from_db()
    close_session(task)
    notes.post(task, body or notes.stopped_text(task, reason), 'end',
               push='check' if task.checkout_at and state == 'stopped' else None)
    if task.phase == 'report':
        # Paid at a Venezuelan store and not reported (pagomovil.py): whatever ended it, ops are told.
        from . import pagomovil
        pagomovil.alert(task, reason)
    return True


def fingerprint(code):
    return hashlib.sha256(code.encode()).hexdigest()[:24]


def _whole(page_text, figure):
    """A figure written on the page as a whole number of its own (never a piece of "540 g" or "4.85")."""
    return bool(re.search(r'(?<![\d.,])' + re.escape(figure) + r'(?![\d]|[.,]\d)', str(page_text or '')[:100000]))


def max_steps(task):
    """The step budget: more for a cart of several products (each is opened, added and set to its quantity)."""
    if getattr(task, 'kind', 'buy') == 'reserve':
        return conf.get('AGENT_TASKS_RESERVE_MAX_STEPS')   # a calendar, counters and a guest form
    cart = (task.order or {}).get('cart')
    extra = max(len(cart) - 1, 0) if isinstance(cart, list) else 0
    return conf.get('AGENT_TASKS_MAX_STEPS') + extra * conf.get('AGENT_TASKS_STEPS_PER_EXTRA_PRODUCT')


def max_cost(task):
    return Decimal(str(conf.get('AGENT_TASKS_RESERVE_MAX_COST_USD' if getattr(task, 'kind', 'buy') == 'reserve'
                                else 'AGENT_TASKS_MAX_COST_USD')))


def app_meta(task):
    """The request headers a rail checks, as the build that started the task sent them."""
    return {'HTTP_X_CONFIO_VERSION': task.app_version} if task.app_version else {}


def code_on_screen(shots, rail):
    """(code, '') when the two pictures show one QR of the rail the store stands behind, else ('', reason)."""
    readings = [qr.read(shot) for shot in shots]
    first, second = ({text for text, _ in found if text in rail.codes([text])} for found in readings)
    if first != second:
        return '', 'screen'
    if len(first) != 1:
        return '', 'several' if first else 'code'
    code = next(iter(first))
    # Every code the page writes must be this one: a seller's QR is never
    # the store's "copia e cola" beside it.
    written = rail.written(shots[0].words)
    if written and written != {code}:
        return '', 'several'
    # Only a copy field holding the code alone lowers the floor: a seller can
    # write a code into a product title, not into the store's own field.
    in_field = code in {field.strip() for field in shots[0].fields}
    floor = MIN_QR_CSS if in_field else MIN_QR_CSS_ALONE
    if any(side < floor for found in readings for text, side in found if text == code):
        return '', 'several'  # a payment QR the size of a photo is never guessed past
    return code, ''


def same_page(url):
    """What makes it the same page: the host and the path, and where a store
    routes by them, its route parameter or a "#/route" (never a "#section" or
    any other query a link can add)."""
    from urllib.parse import parse_qsl
    parts = urlsplit(url)
    route = ''.join(sorted(f'?{key.lower()}={value}' for key, value in parse_qsl(parts.query)
                           if key.lower() in ('route', 'controller', 'page_id', 'p', 'product', 'order-pay',
                                              'order-received', 'add-to-cart')))
    fragment = parts.fragment[1:] if parts.fragment.startswith('!/') else parts.fragment
    hashed = fragment.split('?')[0] if fragment.startswith('/') else ''
    return fingerprint(f'{parts.hostname}{parts.path.rstrip("/")}{route}#{hashed.rstrip("/")}')


def run_step(task_id, turn=None):
    from . import service
    service.worker_seen()   # a worker is here: running this proves it
    now, lease = timezone.now(), uuid.uuid4()
    rows = AgentTask.objects.filter(pk=task_id, state__in=AgentTask.RUNNING)
    if turn is not None:
        rows = rows.filter(steps=turn)
    claimed = rows.exclude(lease_until__gt=now).update(lease=lease, lease_until=now + LEASE, updated_at=now)
    if not claimed:
        return
    task = AgentTask.objects.select_related('account', 'user').get(pk=task_id)
    step = Step(task, lease)
    try:
        step.run()
    except Lost:
        pass
    except (CdpError, agent.AgentUnavailable) as exc:
        step.failed(exc)
    except browsers.BrowserUnavailable as exc:
        if exc.code == 'quota' or (exc.code == 'busy' and task.failures + 1 >= MAX_FAILURES):
            logger.error('agent task browser refused: %s', exc.code)
            end(task, 'stopped', 'busy', lease=lease)
        else:
            step.failed(exc)
            step.delay = 20
    except Exception as exc:  # noqa: BLE001 - counted; three end the task
        # The type only: a database error quotes the row, which holds a page's words.
        logger.error('agent task step failed: %s', type(exc).__name__)
        step.failed(exc)
    finally:
        step.finish()


def _proxy_country(task):
    """The country for the browser's geo proxy: the store's own country, else the person's (so a .com
    store still sees their region and currency, without binding task.country to a payment rail)."""
    code = str(task.country or '').strip().upper()
    if re.fullmatch(r'[A-Z]{2}', code) and code not in ('XX', 'T1'):
        return code
    try:
        from ramps.rail_country import primary_rail_country
        code = str(primary_rail_country(task.user) or '').strip().upper()
        return code if re.fullmatch(r'[A-Z]{2}', code) and code not in ('XX', 'T1') else ''
    except Exception:  # noqa: BLE001 - no hint is only no hint
        return ''


class Step:
    ASKED, GIVE_UP, HISTORY_KEPT = ASKED, GIVE_UP, HISTORY_KEPT
    fingerprint = staticmethod(fingerprint)
    same_page = staticmethod(same_page)

    def __init__(self, task, lease):
        self.task, self.lease, self.meter = task, lease, agent.Meter()
        self.delay = 0
        self.only_get = False
        self.operating = False   # in a sign-in, cart or checkout: real clicks, the store's own requests
        self.seen_url = ''

    def app_meta(self):
        return app_meta(self.task)

    # ---------------------------------------------------------------- the row

    def save(self, **fields):
        fields['updated_at'] = timezone.now()
        if not AgentTask.objects.filter(pk=self.task.pk, lease=self.lease,
                                        state__in=AgentTask.ACTIVE).update(**fields):
            raise Lost()
        for key, value in fields.items():
            setattr(self.task, key, value)

    def remember(self, did, result, **fields):
        history = [*(self.task.history or []), {'did': did[:120], 'result': result[:120]}][-HISTORY_KEPT:]
        self.save(history=history, steps=self.task.steps + 1, failures=0, **fields)

    def stop(self, reason, **fields):
        if self.task.phase == 'report' and reason != 'report_failed':
            # Paid already: a session that cannot report it is followed by a fresh one (pagomovil.retry).
            from . import pagomovil
            return pagomovil.retry(self, reason)
        # Where it stopped, without any query (a store's sign-in carries tokens there): the next
        # failure is read off the log, not guessed.
        where = urlsplit(getattr(self, 'seen_url', '') or '')
        logger.info('agent task %s stopped: %s at %s%s', self.task.internal_id, reason, where.hostname or '',
                    where.path[:120])
        if not end(self.task, 'stopped', reason, lease=self.lease, **fields):
            raise Lost()

    def failed(self, exc):
        told = exc if isinstance(exc, (CdpError, agent.AgentUnavailable, browsers.BrowserUnavailable)) else ''
        logger.warning('agent task %s: %s %s', self.task.internal_id, type(exc).__name__, told)
        try:
            if self.task.failures + 1 >= MAX_FAILURES:
                # After the order was placed, say so: it waits to be paid at the store.
                self.stop('error')   # after an order its words say an order may exist (notes.stopped_text)
            else:
                self.save(failures=self.task.failures + 1, steps=self.task.steps + 1)
                self.delay = 5
        except Lost:
            pass

    def finish(self):
        rows = AgentTask.objects.filter(pk=self.task.pk)
        if self.meter.usd:
            # Spent money is recorded even when the step lost the task.
            rows.update(cost_usd=F('cost_usd') + self.meter.usd.quantize(Decimal('0.000001')),
                        google_cost_usd=F('google_cost_usd') + self.meter.google_usd.quantize(Decimal('0.000001')))
        released = rows.filter(lease=self.lease).update(lease=None, lease_until=None)
        state = rows.values_list('state', flat=True).first()
        if released and state in AgentTask.RUNNING:
            kick(self.task.pk, self.delay)

    # --------------------------------------------------------------- one step

    def run(self):
        task = self.task
        if not conf.get('AGENT_TASKS_ENABLED'):
            return self.stop('busy')
        # The ceilings are the agent's. After the hand-over reading a code costs no model.
        if not task.checkout_at and task.phase != 'report' and (task.steps >= max_steps(task)
                                     or task.cost_usd >= max_cost(task)):
            return self.stop('too_long')
        if task.state == 'awaiting_code' and (task.order or {}).get('pay_hold'):
            # A purchase waiting for the Cuenta inteligente: its payment is read from what was kept, no browser.
            return self.pay_held()
        if not task.session_id:
            if task.state != 'queued':
                return self.stop('session_expired')
            if task.phase != 'report' and task.created_at < timezone.now() - NEVER_STARTED_AFTER:
                return self.stop('unavailable')   # the person has moved on: never started late
            self.open_browser()
        elif task.session_expires_at <= timezone.now() + SESSION_MARGIN:
            return self.stop('session_expired')
        handed = task.state == 'awaiting_code'
        with Page(task.connect_url, active=not handed) as browser:
            if handed:
                return self.after_checkout(browser)
            return self.work(browser)

    def open_browser(self):
        task = self.task
        vendor = browsers.provider()
        profile = AgentProfile.objects.filter(user=task.user, site=task.site, provider=vendor.name).first()
        if profile is None:
            external = vendor.create_profile()
            try:
                with transaction.atomic():
                    profile = AgentProfile.objects.create(user=task.user, site=task.site, provider=vendor.name,
                                                          external_id=external)
            except IntegrityError:
                vendor.delete_profile(external)
                profile = AgentProfile.objects.get(user=task.user, site=task.site, provider=vendor.name)
        profile.save(update_fields=['last_used_at'])
        session = vendor.open(profile_id=profile.external_id, country=_proxy_country(task),
                              seconds=conf.get('AGENT_TASKS_SESSION_SECONDS'))
        try:
            self.save(provider=vendor.name, session_id=session.id, connect_url=session.connect_url,
                      session_expires_at=session.expires_at)
        except Exception:
            vendor.close(session.id)
            raise

    def hand_over(self, kind, body=None, push_text=None, **fields):
        task = self.task
        seconds = conf.get('AGENT_TASKS_PERSON_WAIT_SECONDS' if kind in BACK_TO_AGENT
                           else 'AGENT_TASKS_CHECKOUT_WAIT_SECONDS')
        # Before they confirm an order at the store: what they have to pay it with. Read
        # before their clock is set. In the chat only: a push shows on the lock screen.
        # Not when the person pays it from their bank: their Confío balance is not what pays it.
        extra = notes.balance_line(task) if kind == 'approve' and not (fields.get('order') or {}).get('manual') else ''
        now = timezone.now()
        until = min(now + timedelta(seconds=seconds), task.session_expires_at - SESSION_MARGIN)
        # Said before they order, not while they are ordering.
        if until < now + (CHECKOUT_TURN_MIN if 'checkout_at' in fields else PERSON_TURN_MIN):
            return self.stop('session_expired')  # a turn too short to open is not handed over
        self.remember(f'{ASKED}{kind}', 'waiting', state='needs_person', reason=kind, wait_until=until, **fields)
        text = body or notes.say(notes.NEEDS_PERSON[kind], task)
        notes.post(task, text + extra, f'person:{task.steps}', push='person', push_body=push_text or text)

    # ----------------------------------------------------- before the checkout

    def work(self, browser):
        """As many steps as fit in one guarded connection: between two
        connections nobody checks what a page goes on to load."""
        task = self.task
        # While shopping, only reading the store. In its sign-in and checkout, the store's own
        # pages and its payment house, whatever they send.
        browser.guard_documents(lambda url, method: (
            (sites.within(url, task.site, house=True) and not guard.account_address(url)) if self.operating
            else guard.hop_allowed(url, method, task.site, only_get=self.only_get)))
        until = time.monotonic() + conf.get('AGENT_TASKS_HOLD_SECONDS')
        while True:
            from . import operate
            # From the cart on, the store's own redirects (to its checkout, its payment house) are its own.
            # An order already placed is worked with real clicks, under the same lines (manage.py).
            self.only_get, self.delay = False, 0
            self.operating = (operate.ordering(task) or task.phase == 'report'
                              or getattr(task, 'kind', 'buy') in ('manage', 'reserve'))
            browser.refused_document = browser.refused_send = False
            self.before_checkout(browser)
            if task.state != 'working' or time.monotonic() >= until:
                return
            if not conf.get('AGENT_TASKS_ENABLED'):
                return self.stop('busy')
            if task.phase != 'report' and (task.steps >= max_steps(task)
                                           or task.cost_usd + self.meter.usd >= max_cost(task)):
                return self.stop('too_long')
            if task.session_expires_at <= timezone.now() + SESSION_MARGIN:
                return
            self.save(lease_until=timezone.now() + LEASE)
            if self.delay:
                browser.pump(self.delay)

    def before_checkout(self, browser):
        task = self.task
        if task.state == 'queued':
            browser.goto(f'https://{task.site}/')
            if browser.refused_document is True:
                return self.stop('cannot_do')
            return self.remember(f'open {task.site}', 'ok', state='working')
        if task.pending_url:
            # The product the person picked: its address was checked when it was offered.
            address = task.pending_url
            if guard.address_refusal(address, task.site):
                return self.stop('cannot_do')
            # One of several products chosen into one cart (service.choose_cart): marked opened only once its
            # page loaded, so a page that failed is opened again by next_product (opening twice is harmless;
            # adding twice is what the reviewer checks), and the driver is told which and how many.
            cart = (task.order or {}).get('cart') if isinstance((task.order or {}).get('cart'), list) else []
            entry = next((one for one in cart if one.get('href') == address and not one.get('opened')), None)
            self.save(pending_url='')
            browser.goto(address)
            if entry is not None:
                marked = [{**one, 'opened': True} if one is entry else one for one in cart]
                self.save(order={**task.order, 'cart': marked})
            if entry is None:
                self.remember('open the chosen product', 'ok')
                # Picked: from its own page the agent buys it, pressing what the store needs (its add to
                # cart included) under the checkout's lines (operate.py, guard.may_press).
                return self.hand_checkout()
            self.hand_checkout()
            if task.state != 'working':
                return None
            # Said last, so it is what the driver reads first: which product this is, and how many.
            left = sum(not one.get('opened') for one in task.order['cart'])
            return self.remember(f"open the chosen product: {int(entry.get('quantity') or 1)} × "
                                 f"{guard.clean(entry.get('title'), 60)}",
                                 f'set that quantity and add it to the cart, then '
                                 f'{"next_product" if left else "go to the cart"}')
        reader = pages.Reader(browser)
        seen = reader.read()
        self.seen_url = seen.url
        from . import operate
        inside = sites.within(seen.url, task.site)
        page = same_page(seen.url)
        needed = guard.person_needed(seen)
        # The store's own sign-in, cart and checkout: no seller writes there, and its payment
        # data is read off such a page later, so they are not "pages the agent read".
        # From the cart on, the order's own pages are not "read while shopping"; any other page
        # (a product a link led back to) still is: a seller writes there.
        store_only = guard.is_checkout(seen) or guard.login_address(seen.url) or operate.ordered(task)
        if inside and not store_only and page not in (task.visited_pages or []) \
                and len(task.visited_pages or []) < MAX_VISITED:
            self.save(visited_pages=[*(task.visited_pages or []), page])
        if not inside:
            if sites.within(seen.url, task.site, house=True) and task.phase == 'report':
                from . import pagomovil
                return pagomovil.report_step(self, browser, reader, seen)
            if sites.within(seen.url, task.site, house=True) and operate.ordering(task):
                return operate.checkout(self, browser, reader, seen)  # the store's payment house
            if sum(entry.get('did') == 'left the store' for entry in task.history or []) >= MAX_LEFT_STORE:
                return self.stop('cannot_do')  # its home keeps sending us away
            browser.goto(f'https://{task.site}/')
            return self.remember('left the store', 'back to its home page')
        if guard.blocked(seen):
            return self.stop('blocked')
        if needed == 'captcha':
            return self.await_captcha()
        if needed == 'login':
            done = operate.sign_in(self, browser, reader, seen)
            if done is not operate.NOT_A_FORM:
                return done
        if task.phase == 'report':
            # Paid by Pago Móvil before the order: back to its step, to type the reference (pagomovil.py).
            from . import pagomovil
            return pagomovil.report_step(self, browser, reader, seen)
        from . import manage, reserve
        if manage.managing(task):
            return manage.step(self, browser, reader, seen)   # an order already placed
        if reserve.reserving(task):
            return reserve.step(self, browser, reader, seen)  # a room, a table, a seat: no card
        if guard.is_checkout(seen) or operate.ordering(task):
            return operate.checkout(self, browser, reader, seen)
        name, args = agent.decide(task, seen, self.meter)
        return self.act(browser, reader, seen, name, args)

    def offer(self, seen, args):
        """The products the person picks from, in the chat: only links this store
        page really has, that may be opened. Their names and prices are the page's."""
        task = self.task
        if task.options:
            return self.remember('offer_products', 'refused: already offered. Work on the product page.')
        pictures = {}
        for element in seen.elements:
            if element.get('image') and element.get('href'):
                pictures.setdefault(element['href'].split('#')[0], element['image'])
        options, seen_links = [], set()
        for item in (args.get('items') or [])[:MAX_OPTIONS * 2]:
            element = seen.element(item.get('ref')) if isinstance(item, dict) else None
            if element is None or guard.link_refusal(element, task.site, seen):
                continue
            href = element['href']
            if href.split('#')[0] in seen_links:
                continue
            seen_links.add(href.split('#')[0])
            title = guard.clean(agent.redact(item.get('title') or element.get('label')), 120)
            if not title:
                continue
            from . import operate
            price = guard.clean(agent.redact(item.get('price')), 30)
            cap, cap_text = operate.top_total(price, task.country)
            if cap is not None and not operate.figure_on(seen.text, operate.unit_price(price, task.country)):
                cap, cap_text = None, ''   # a price the page does not write sets no top total
            # Stars and reviews as the page writes them for it: kept only when those very figures are on the page.
            rating = guard.clean(agent.redact(item.get('rating')), 8)
            rating = rating if re.fullmatch(r'[0-5][.,]\d', rating) and _whole(seen.text, rating) else ''
            reviews = guard.clean(agent.redact(item.get('reviews')), 12)
            reviews = reviews if rating and re.fullmatch(r'\d[\d.,]*', reviews) and _whole(seen.text, reviews) else ''
            options.append({'title': title, 'price': price, 'rating': rating, 'reviews': reviews,
                            'cap': cap_text, 'cap_amount': format(cap, 'f') if cap else '',
                            'image': element.get('image') or pictures.get(href.split('#')[0], ''), 'href': href})
            if len(options) >= MAX_OPTIONS:
                break
        if not options:
            return self.remember('offer_products', 'refused: none of those is a product link of this store')
        # Even one: "Elegir" is the person's approval of the purchase up to its top total (spec decision 42).
        return self.hand_over('choose', options=options)

    def await_captcha(self):
        """The browser's vendor solves a CAPTCHA by itself: look again in a few
        seconds. The person is never asked. One it cannot solve ends the purchase."""
        from . import operate
        if operate.count(self.task, 'captcha') >= CAPTCHA_TRIES:
            return self.stop('blocked')
        self.delay = CAPTCHA_WAIT_SECONDS
        return self.remember(CAPTCHA, 'the browser is solving it: look again',
                             counts=operate.counted(self.task, 'captcha'))

    def hand_checkout(self, kind='checkout', body=None):
        from . import service
        try:
            # Never ask someone to confirm an order they could not pay here.
            service.require_payable(self.task.account, self.task.user, self.task.country, app_meta(self.task))
        except service.TaskRefused as exc:
            return self.stop('no_rail' if exc.code == 'country' else 'cannot_pay')
        # From here the agent buys it itself (operate.py): into the cart if it is not there, then the checkout.
        return self.remember('ready for the checkout', 'add the item to the cart if it is not there, then go to '
                                                       'the checkout', phase='ordering')

    def act(self, browser, reader, seen, name, args):
        task = self.task
        if name == 'wait':
            self.delay = 2
            return self.remember('wait', 'ok')
        if name == 'ask_person':
            kind = args.get('kind')
            if kind == 'captcha':
                return self.await_captcha()
            if kind == 'login':
                return self.remember('ask_person', 'refused: there is no sign-in form here; open the sign-in page')
            # The person is not at the store: what to buy is chosen from what is offered (offer_products).
            return self.remember('ask_person', 'refused: the person picks from what you offer; call offer_products '
                                               'with the closest products on this or a search page')
        if name == 'ready_for_checkout':
            return self.hand_checkout()
        if name == 'offer_products':
            return self.offer(seen, args)
        if name == 'give_up':
            reason = args.get('reason')
            return self.stop(reason if reason in GIVE_UP else 'cannot_do',
                             order={**(task.order or {}), 'why': notes.reason_text(args.get('why'))})
        element = seen.element(args.get('ref'))
        if name not in ('click', 'search') or element is None:
            return self.remember(f'{name}'[:30], 'refused: no such element')
        label = guard.clean(agent.redact(element.get('label')), 70)
        if name == 'search':
            text = str(args.get('text') or '').strip()
            refused = guard.search_refusal(element, text, seen, task.site, task.goal)
            if not refused:
                self.save()  # still ours, right before acting
                self.only_get = True
                reader.address = None
                browser.only_sending(guard.sent_to)
                refused = reader.search(element, text)
                browser.only_sending(None)  # before the results load: only the sending is checked that closely
                if not refused and isinstance(reader.address, str):
                    refused = guard.address_refusal(reader.address, task.site)
                    if not refused:
                        browser.goto(reader.address)
                elif not refused and browser.refused_send is True:
                    refused = 'the store searches in a way I may not use: ask_person(choice) if there are no results'
        elif element.get('tag') == 'a':
            refused = guard.link_refusal(element, task.site, seen)
            if not refused:
                self.save()
                browser.goto(element['href'])  # the address, never a click on the link
        else:
            refused = guard.press_refusal(element, seen, task.site)
            did, where = f'{name} "{label}"', fingerprint(seen.url)
            if not refused and any(entry.get('at') == where and entry.get('did') == did[:120]
                                   for entry in (task.history or [])[-6:]):
                refused = 'already pressed'
            if not refused:
                # Written down first: an answer lost on the way is not a reason to press again.
                before = list(task.history or [])
                self.save(history=[*before, {'did': did[:120], 'result': 'sent', 'at': where}][-HISTORY_KEPT:])
                browser.only_sending(lambda method, url: guard.sent_to(method, url, element['action']))
                refused = reader.press(element)
                if not refused:
                    browser.pump(AFTER_PRESS_SECONDS)  # what a script sends a little later is checked too
                browser.only_sending(None)
                if refused:
                    self.save(history=before)  # not sent: it may be tried again
                if not refused and browser.refused_send is not True and not reader.landed_on_a_page():
                    browser.refused_send = True  # the cart answered data or an error, not a page
                if not refused and browser.refused_send is True:
                    # Something it sent was stopped: never called done.
                    return self.hand_checkout(body=notes.say(notes.NEEDS_PERSON['checkout'], task)
                                              + notes.MAYBE_NOT_ADDED)
                if not refused and browser.refused_document is True:
                    # It was sent, and the store went on to its checkout (or out): the person's, from here.
                    return self.hand_checkout()
        if not refused and browser.refused_document is True:
            refused = 'it led out of the store or into an act'
        return self.remember(f'{name} "{label}"', f'refused: {refused}' if refused else 'ok')

    # ------------------------------------------------------ after the checkout

    def after_checkout(self, browser):
        """The order's payment data, read off the tab the agent left on it. No
        script runs and nothing is touched. What cannot be read goes back to
        the agent to find the page (operate.AFTER), a few times."""
        task = self.task
        shots = browser.capture(task.shown_target) if task.shown_target else None
        if not shots:
            return self.unread('screen')
        # The store's own site (or its payment house's ticket for it). Which of its pages shows this order's
        # payment is the model's reading (payment_shown); what follows are facts no page can talk its way past.
        if not sites.house_ticket(shots[0].url, task.site) and not sites.within(shots[0].url, task.site):
            return self.unread('offsite')
        if same_page(shots[0].url) in (task.visited_pages or []):
            return self.unread('code')  # a shopping page: a QR there is a seller's picture
        if same_page(shots[0].url) in ((task.order or {}).get('pressed_at') or []):
            return self.unread('code')  # the checkout the order was pressed on: its payment page is new since
        rail = countries.rail(task.country)
        if rail is None or rail.pay_before_order:
            return self.stop('unpaid')   # a Pago Móvil step is read before the order (pagomovil.pay_first)
        if rail.kind == 'manual':
            return self.read_manual(shots, rail)
        if rail.kind == 'qr':
            (code, why), extra = code_on_screen(shots, rail), {}
        else:
            ticket = sites.house_ticket(shots[0].url, task.site)
            # A CLABE made for this one order (Mercado Pago's ticket; a known store's own order page: Amazon
            # México "compartirá la cuenta CLABE de 18 dígitos") may come with no reference printed.
            # Read by facts once the person approved an amount: one valid CLABE on the page, and that amount.
            placed = task.order or {}
            expected = placed.get('amount') if placed.get('pressed') and not placed.get('unapproved') else None
            code, extra, why = rail.read(shots, reference_optional=True, expected=expected,
                                         item=placed.get('item') or '', before=placed.get('seen_clabes') or ())
            if code and not extra.get('reference') and rail.method_id == 'mx_clabe':
                from . import spei
                if ticket:
                    # Mercado Pago's own payment number, from its ticket's address: the transfer's concept.
                    found = re.search(r'/payments/(\d+)/ticket', urlsplit(shots[0].url).path, re.I)
                    concept = found.group(1) if found else 'Pedido ' + re.sub(r'[^A-Za-z0-9]+', ' ', task.site)
                else:
                    # The order's own number as the page prints it, else the store's name.
                    concept = spei.order_number(shots[0].text) or ('Pedido ' + re.sub(r'[^A-Za-z0-9]+', ' ', task.site))
                extra = {**extra, 'reference': concept.strip()[:40]}
        if not code:
            return self.unread(why)
        return self.pay_read(rail, code, extra)

    def pay_held(self):
        """A purchase the Cuenta inteligente did not pay yet (account_pay.wait or retry_later): the payment
        prepared again from the details kept off the store's page, with the same checks, never the browser."""
        from . import account_pay
        task = self.task
        held = (task.order or {}).get('pay_hold') or {}
        until = account_pay.deadline(held)
        if until is None or until <= timezone.now():
            return self.stop('account_timeout', body=notes.say(notes.ACCOUNT_WAIT_EXPIRED, task))
        rail = countries.rail(task.country)
        if rail is None or rail.kind == 'manual' or not held.get('code'):
            return self.stop('unpaid', body=notes.say(notes.ACCOUNT_NOT_PAID, task))
        return self.pay_read(rail, str(held['code']), dict(held.get('extra') or {}), held=held)

    def pay_read(self, rail, code, extra, held=None):
        """The order's payment, read off its page now or kept by a hold: prepared, checked against the approved
        order, and paid by the account (or, before a purchase spender exists, offered as the person's card)."""
        from payment_accounts import payment_intents
        from payment_accounts.services import PaymentAccountError
        task = self.task
        from . import service
        # Asked again now: an account opened since the order card pays it.
        mode, offer = service.pay_mode(task, app_meta(task))
        first = rail.pay_before_order
        if mode == 'manual' and first:
            # Never the person's own bank nor their card for a store paid before its order: nothing moved.
            return self.stop('unpaid', body=notes.say(notes.PAY_FIRST_NOT_PAID, task))
        if mode == 'manual':
            return self.hand_manual(rail, code=code, extra=extra, offer=offer)
        placed = task.order or {}
        # Venezuela pays before the order exists: what the person approved is the order at its final button.
        ordered = placed.get('pay_first') if first else placed.get('pressed')
        if not placed.get('amount') or not ordered or placed.get('unapproved'):
            # No order the person approved (the store shows one nobody named): nothing is prepared.
            return self.stop('unpaid')
        self.save()
        try:
            intent = payment_intents.prepare(task.account, task.user, None if first else code, created_by='assistant',
                                             source='agent_checkout',
                                             request={**rail.request(app_meta(task)), **extra})
        except PaymentAccountError as exc:
            if rail.can_go_manual and getattr(exc, 'code', None) in MANUAL_WHEN:
                # Confío cannot pay anything for this person right now: their bank can. Never when the
                # refusal is about the QR itself ('rail', 'no_code', 'no_amount'): the provider is the
                # one that says it is the store's payment code.
                return self.hand_manual(rail, code=code, extra=extra, offer=rail.opens)
            # Nobody vouched for that code, so it is not handed on as this order's.
            why = guard.clean(str(exc), 200)
            # The screen stays: many refusals pass, and it may be the only place that code is.
            # A balance or what is missing stays in the chat, off the lock screen.
            return self.stop('unpaid', body=f"{notes.stopped_text(task, 'unpaid')} {why}".strip())
        # An exact bolívar card prices an estimate (amount_local); what it pays exactly is minimum_local.
        local = getattr(intent, 'minimum_local', None) if first else intent.amount_local
        if (intent.currency != rail.currency or not intent.amount_exact or intent.rail_method_id != rail.method_id
                or local is None or ('amount_local' in extra and local != Decimal(extra['amount_local']))):
            payment_intents.cancel(task.account, intent.internal_id)
            return self.stop('unpaid')
        order = task.order or {}
        # Only the order the agent placed carries an amount to pay: `pressed` is written only when the
        # person's approval matched (operate._order), and the approval itself is then used up.
        approved = order.get('amount') if ordered and not order.get('unapproved') else None
        # No amount the person approved (an order the store shows as placed without them): no card.
        if not approved or local != Decimal(approved):
            # Not the order the person approved (another order's page, or a seller's): never offered.
            payment_intents.cancel(task.account, intent.internal_id)
            return self.stop('unpaid')
        if intent.payee_level not in rail.payees:
            # A name the QR wrote about itself is not read off a screen. Pasted, it is asked about (confirm.py).
            payment_intents.cancel(task.account, intent.internal_id)
            return self.stop('unpaid')
        from . import account_pay
        if account_pay.pay(self, intent, code=code, extra=extra, held=held):
            return   # the person's Cuenta inteligente pays it, or the purchase waits for it: never a card then
        if first:
            # Only the account pays a store before its order exists (countries.PagoMovilRail.ready).
            payment_intents.cancel(task.account, intent.internal_id)
            return self.stop('unpaid', body=notes.say(notes.PAY_FIRST_NOT_PAID, task))
        if held:
            # A held purchase is never handed to the personal wallet's card.
            payment_intents.cancel(task.account, intent.internal_id)
            return self.stop('unpaid', body=notes.say(notes.ACCOUNT_NOT_PAID, task))
        try:
            self.save(payment_intent=intent, state='payment_ready', reason='', wait_until=None)
        except Lost:
            payment_intents.cancel(task.account, intent.internal_id)
            raise
        close_session(task)
        post_payment(task, intent)


    def hand_manual(self, rail, *, code='', extra=None, details=(), offer=''):
        """Confío cannot pay it now: the person pays the store's own payment data from their bank.
        Only for the order the agent placed with their approval, and only data that is this order's."""
        task = self.task
        order = task.order or {}
        if not order.get('pressed') or order.get('unapproved') or not order.get('total'):
            return self.stop('unpaid')
        extra = extra or {}
        try:
            approved = Decimal(str(order.get('amount')))
        except Exception:  # noqa: BLE001 - no amount the person approved: nothing to hand them
            return self.stop('unpaid')
        pay_qr = ''
        if rail.kind == 'text':
            # SPEI: the CLABE, the exact pesos and the reference, read off the order's page (spei.py).
            try:
                if Decimal(extra['amount_local']) != approved:
                    return self.stop('unpaid')
            except Exception:  # noqa: BLE001
                return self.stop('unpaid')
            details = [('CLABE', code), ('Monto', str(order.get('total'))),
                       ('Referencia', str(extra.get('reference') or ''))]
        elif code:
            # Nobody decodes it for us here: what the code says of itself must be this order's.
            from payment_accounts import local_money
            # A bank's QR may carry a scheme prefix ("QRSIMPLE:") before its EMV body.
            fields = local_money.emv_fields(re.sub(r'^[^:]{1,20}:', '', code)) or {}
            try:
                amount_ok = '54' not in fields or Decimal(fields['54']) == approved
            except Exception:  # noqa: BLE001
                amount_ok = False
            if not amount_ok or fields.get('58') not in (None, rail.country) \
                    or (rail.numeric and fields.get('53') not in (None, rail.numeric)):
                return self.stop('unpaid')
            if rail.kind == 'manual' and not (fields.get('58') == rail.country and rail.numeric
                                              and fields.get('53') == rail.numeric and '54' in fields):
                code = ''   # nothing vouches for a QR there: only one that says this order's own amount
            pay_qr = code
        details = [{'label': label, 'value': str(value)} for label, value in details if str(value or '').strip()]
        if not pay_qr and not any(item['label'] != 'Monto' for item in details):
            return self.stop('unpaid')   # an amount alone pays nothing
        if not any(item['label'] == 'Monto' for item in details):
            details.insert(0, {'label': 'Monto', 'value': str(order.get('total'))})
        self.save(order={**order, 'pay_qr': pay_qr, 'pay_details': details, 'offer': offer},
                  state='payment_ready', reason='manual', wait_until=None)
        close_session(task)
        text = notes.manual_text(task)
        notes.post(task, text, 'payment', push='payment', push_body=text)

    def read_manual(self, shots, rail):
        """A country Confío pays no store in: what the order's page prints beside the store's own
        payment labels (manual.py, never the model's copy), for the amount the person approved,
        and its QR when the QR itself says this country, currency and amount."""
        from . import manual
        task = self.task
        order = task.order or {}
        try:
            approved = Decimal(str(order.get('amount')))
        except Exception:  # noqa: BLE001 - no amount the person approved: nothing to hand them
            return self.stop('unpaid')
        details, why = manual.read(shots, approved, str(order.get('item') or ''),
                                   marketplace=sites.marketplace(task.site))
        if why == 'several':
            return self.unread(why)   # doubtful: nothing is handed over, not even a QR beside it
        code, _ = code_on_screen(shots, rail)
        if why and not code:
            return self.unread(why)
        return self.hand_manual(rail, code=code, details=[('Monto', str(order.get('total')))] + (details or []))

    def unread(self, why):
        from . import operate
        if operate.count(self.task, 'unread') >= operate.MAX_UNREAD:
            return self.stop('unpaid')
        return self.remember(UNREAD, str(why), state='working', reason='',
                             counts=operate.counted(self.task, 'unread'))

# Refusals that say nothing about the code: Confío cannot pay for this person now.
MANUAL_WHEN = frozenset({'unavailable', 'not_personal', 'rate_limited'})

def post_payment(task, intent):
    """Idempotent: the sweep calls it again if the worker died before it."""
    from payment_accounts import payment_intents
    text = notes.say(notes.PAYMENT_READY, task)
    # What is missing is said in the chat, never on the lock screen.
    message_id = notes.post(task, text + notes.shortfall_line(task, intent), 'payment', intent=intent,
                            push='payment', push_body=text)
    if message_id:
        payment_intents.attach_message(intent.internal_id, message_id)
