"""A purchase paid by the person's Cuenta inteligente (spec decisions 37 to 42, section 3.6).

After the store's order page was read (runner.after_checkout) and its
PaymentIntent checked against the amount the person approved, a subscriber
whose "Compras con Confío IA" rule has room, and whose account holds the
dollars, is not shown a card to sign: the account pays it. The purchase
spender pulls exactly that payment's dollars from the rule, inside the cap the
owner signed with Face, and the store's CLABE is paid the approved pesos
(payment_accounts.purchase_funding). No Face per purchase (decision 38).

Once the purchase spender is configured, a purchase is NEVER paid from the
person's personal wallet (founder, 2026-11-24). When the account cannot pay
it now, the purchase WAITS (a hold): the payment details read off the store's
page are kept on the task (order['pay_hold']), the prepared PaymentIntent is
cancelled so no card can pay it, and the person is told the one thing that
lets the account pay it (switch purchases on, move money in, top up, raise
the cap). "Ya lo hice: pagar" (service.resume_payment) or the sweep's
re-check runs the runner again from the stored details, without the browser
(runner.Step.pay_held), up to AGENT_TASKS_ACCOUNT_WAIT_HOURS. A chain or
provider that could not be read is retried a few times, then an honest stop
with nothing paid.

Only before the spender exists does this return False: the person's card,
as before.
"""
import logging
from datetime import timedelta
from decimal import ROUND_UP, Decimal

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import conf, notes

logger = logging.getLogger(__name__)

WAD = 10 ** 18
# Rails a purchase can be paid from Cuenta inteligente on: a store CLABE (payment_accounts.purchase_funding)
# and a store's Pago Móvil in exact bolívares (payment_accounts.purchase_funding_ve).
MX_CLABE, VE_PAGOMOVIL = 'mx_clabe', 've_pagomovil_send'
PAYABLE_RAILS = frozenset({MX_CLABE, VE_PAGOMOVIL})
# What the person can do about it. 'renew': their Cuenta inteligente is not active or not paid (an 'off' standing
# whose why is 'account'). Anything else 'off' is retried or, for a spender ops must fix, stopped; never a card.
WAIT_CODES = ('no_rule', 'move', 'topup', 'cap', 'renew')
# The purchase spender is not allowed (not in the mirror, removed or paused on chain): Confío's to fix.
SPENDER_GAPS = ('spender_mirror', 'spender_chain')
# A CLABE read off a store's order page is made for that order and may lapse: the rails whose hold is short.
# A store's Pago Móvil data is its checkout's, shown before the order exists: as short-lived.
ONE_TIME_RAILS = (MX_CLABE, VE_PAGOMOVIL)
# An unread chain or provider: tried again this many times, this far apart, then an honest stop.
OFF_RETRIES = 3
OFF_DELAY_SECONDS = 30
# A raised cap is offered in whole steps of this.
CAP_STEP = Decimal('50')


def funding_module(rail_method_id):
    """The module that pays a purchase on this rail from the account."""
    if str(rail_method_id or '') == VE_PAGOMOVIL:
        from payment_accounts import purchase_funding_ve
        return purchase_funding_ve
    from payment_accounts import purchase_funding
    return purchase_funding


def units_of(intent) -> int:
    """The USDT the spender forwards for this purchase. Pago Móvil: what an exact-bolívar send of the
    approved dollars deposits (its conversion fee is the pull's own exit); raises ValueError when unread."""
    if getattr(intent, 'rail_method_id', '') == VE_PAGOMOVIL:
        return funding_module(VE_PAGOMOVIL).pull_units(intent)
    return int(Decimal(intent.total_usd) * WAD)


def standing(task, intent, units=None):
    """smart_account.purchases.Standing of this purchase (spec 3.6)."""
    from smart_account import purchases
    units = units_of(intent) if units is None else units
    return purchases.standing(task.user, units, personal_address=task.account.bsc_address or '')


def raised_cap(found) -> Decimal:
    """The cap offered when this purchase does not fit the period's room
    (decision 40): what the period spent plus this purchase, rounded up to
    whole steps, never below the default."""
    from smart_account import purchases
    spent = Decimal(found.cap) - Decimal(found.room)
    need = spent + Decimal(found.gross)
    stepped = (need / CAP_STEP).quantize(Decimal('1'), rounding=ROUND_UP) * CAP_STEP
    return max(purchases.DEFAULT_CAP_USD, stepped, Decimal(found.cap) + CAP_STEP).quantize(Decimal('0.01'))


def situation_text(task, found) -> str:
    """What the order card or the assistant says when the account cannot pay
    it now ('' when it can, or when purchases are not Cuenta inteligente's
    for this person). Confío's words around the figures, never a store's."""
    from smart_account import purchases
    text = notes.ACCOUNT_PAY.get(found.code)
    if not text:
        return ''
    least, offered = purchases.move_offer(found.short, found.personal) if found.code == 'move' else (0, 0)
    return (notes.say(text, task).replace('{gross}', _usd(found.gross)).replace('{room}', _usd(found.room))
            .replace('{cap}', _usd(found.cap)).replace('{short}', _usd(least)).replace('{offer}', _usd(offered)))


def figures(task, found) -> dict:
    """order['account_wait']: the standing and the one action's amount, as the card shows them."""
    from smart_account import purchases
    amount = ''
    if found.code == 'no_rule':
        amount = format(purchases.DEFAULT_CAP_USD, 'f')
    elif found.code == 'cap':
        amount = format(raised_cap(found), 'f')
    elif found.code == 'move':
        amount = format(purchases.move_offer(found.short, found.personal)[1], 'f')
    return {'code': found.code, 'amount_usd': amount, 'gross': str(found.gross), 'room': str(found.room),
            'cap': str(found.cap), 'short': str(found.short), 'personal': str(found.personal),
            'text': situation_text(task, found)}


def _usd(value) -> str:
    return f'US${Decimal(value).quantize(Decimal("0.01")):,.2f}'


def deadline(held) -> 'timezone.datetime | None':
    return parse_datetime(str((held or {}).get('until') or '')) if held else None


PAY_FIRST_RAILS = ('ve_pagomovil_send',)


def hold_hours(rail_method_id) -> int:
    """How long a held payment is paid again from what was kept. No reader gives a payment's own validity
    today (spei.read: CLABE, amount, reference), so a one-time CLABE (a store's or Mercado Pago's order
    account) is kept for AGENT_TASKS_ACCOUNT_WAIT_CLABE_HOURS at most, never the longer wait."""
    hours = int(conf.get('AGENT_TASKS_ACCOUNT_WAIT_HOURS'))
    if str(rail_method_id or '') in ONE_TIME_RAILS:
        hours = min(hours, int(conf.get('AGENT_TASKS_ACCOUNT_WAIT_CLABE_HOURS')))
    return max(hours, 1)


def new_hold(code, extra, rail_method_id='') -> dict:
    """What a hold keeps: the store's payment as its page showed it, to prepare it again without the browser."""
    now = timezone.now()
    hours = hold_hours(rail_method_id)
    until = now + timedelta(hours=hours)
    if str(rail_method_id or '') in PAY_FIRST_RAILS:
        # Paid before the order: the store's checkout (and its rate) waits minutes, never the long hold.
        until = now + timedelta(minutes=int(conf.get('AGENT_TASKS_ACCOUNT_WAIT_PAY_FIRST_MINUTES')))
    return {'code': str(code), 'extra': {key: str(value) for key, value in (extra or {}).items()},
            'since': now.isoformat(), 'until': until.isoformat(), 'hours': hours, 'tries': 0}


def _cancel(task, intent):
    """No card can ever pay a held purchase: its intent is closed."""
    from payment_accounts import payment_intents
    try:
        payment_intents.cancel(task.account, intent.internal_id)
    except Exception as exc:  # noqa: BLE001 - it is attached to nothing and lapses by itself
        logger.warning('agent task %s: held intent not cancelled: %s', task.internal_id, type(exc).__name__)


def pay(step, intent, *, code='', extra=None, held=None) -> bool:
    """True when the account took this purchase over: paying it, waiting for
    the person (a hold), retrying an unread chain, or an honest stop. False
    only while no purchase spender is configured (the person's card, as before).

    `code`/`extra`: the payment as the store's page showed it (kept by a hold).
    `held`: the hold this run resumes (runner.Step.pay_held)."""
    from payment_accounts import contract_funding
    from payment_accounts.services import PaymentAccountError
    from smart_account import purchases, relayer
    from .runner import Lost, close_session
    task = step.task
    if getattr(intent, 'rail_method_id', '') not in PAYABLE_RAILS and not held:
        # Only where the account can pay a store (a CLABE, a Pago Móvil in exact bolívares): elsewhere
        # the person's card, as before, never a purchase that waits for a payment that cannot come.
        return False
    if not purchases.spender_address():
        if held:
            # Switched off while it waited: never the card now, nothing was paid.
            _cancel(task, intent)
            step.stop('unpaid', body=notes.say(notes.ACCOUNT_NOT_PAID, task))
            return True
        return False    # not deployed or not configured: every purchase is the person's card, as before
    held = dict(held or new_hold(code, extra, intent.rail_method_id))
    funding_mod = funding_module(intent.rail_method_id)
    try:
        units = units_of(intent)
    except ValueError as exc:
        if intent.rail_method_id == VE_PAGOMOVIL and str(exc).startswith('purchase_units_unread'):
            return retry_later(step, intent, held, 'units_unread')   # a chain read: tried again
        units = None
    except (ArithmeticError, TypeError, AttributeError):
        units = None
    try:
        if units is None:
            raise ValueError('no units')
        found = standing(task, intent, units)
    except (ArithmeticError, TypeError, ValueError, AttributeError):
        _cancel(task, intent)   # an intent with no dollar total is never the account's to pay, nor a card's
        step.stop('unpaid', body=notes.say(notes.ACCOUNT_NOT_PAID, task))
        return True
    if found.code == 'off' and found.why == 'account' and found.own is None:
        # No Cuenta inteligente at all (the order-card wall should have stopped this): never "renew" one.
        _cancel(task, intent)
        step.stop('unpaid', body=notes.say(notes.ACCOUNT_NOT_PAID, task))
        return True
    if found.code == 'off' and found.why == 'account':
        # Their Cuenta inteligente lapsed or is not active: theirs to renew, then it pays.
        found = purchases.Standing('renew', own=found.own)
    if found.code in WAIT_CODES:
        return wait(step, intent, found, held)
    if not found.pays and found.why in SPENDER_GAPS:
        return spender_gap(step, intent, found)
    if not found.pays:
        return retry_later(step, intent, held, found.why or 'off')
    late_deposit = getattr(funding_mod, 'DEPOSIT_AT_PERSIST', False)
    try:
        funding = funding_mod.PurchaseFunding.for_task(task.pk, intent.pk)
        priced = funding_mod.price(funding)
        terms = funding.terms()
        if not late_deposit:
            # Asked of the chain as the operator would send it, before anything is reserved.
            purchases.simulate_pull(purchases.pull_call(terms['own'], terms['rule'], units, priced.deposit,
                                                        intent.request_id))
    except (contract_funding.Refused, relayer.RelayError, PaymentAccountError) as exc:
        logger.info('agent task %s: the account does not pay it yet: %s', task.internal_id,
                    getattr(exc, 'code', type(exc).__name__))
        return retry_later(step, intent, held, getattr(exc, 'code', '') or type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - an unread chain or provider is tried again, never a guess
        logger.warning('agent task %s: account pay check failed: %s', task.internal_id, type(exc).__name__)
        return retry_later(step, intent, held, type(exc).__name__)
    # Still this step's, right before an order is reserved; the dollars the card will say.
    step.save(order={**(task.order or {}), 'pay_hold': held, 'account_usd': str(found.gross)})
    try:
        bridge, _journey = funding_mod.persist(funding, priced)
    except (contract_funding.Refused, PaymentAccountError) as exc:
        logger.info('agent task %s: account order not reserved: %s', task.internal_id,
                    getattr(exc, 'code', type(exc).__name__))
        return retry_later(step, intent, held, getattr(exc, 'code', '') or type(exc).__name__)
    if late_deposit:
        # Its deposit is Relay's one-time address made by persist: the pull is asked of the chain now, to
        # it, before anything is signed. A refusal closes the order (nothing was sent) and tries later.
        try:
            purchases.simulate_pull(funding_mod.pull_call_of(funding, bridge))
        except Exception as exc:  # noqa: BLE001
            logger.info('agent task %s: the account does not pay it yet: %s', task.internal_id,
                        getattr(exc, 'code', type(exc).__name__))
            funding_mod.abandon(bridge.pk, 'pull_refused')
            return retry_later(step, intent, held, getattr(exc, 'code', '') or type(exc).__name__)
    try:
        funding_mod.send_pull(funding, bridge.pk, lease=step.lease)
    except funding_mod.NotSent as exc:
        if exc.code == 'task_moved':
            funding_mod.abandon(bridge.pk, 'pull_not_sent')
            raise Lost() from exc
        logger.warning('agent task %s: purchase pull not sent: %s', task.internal_id, exc.code)
        return unsent(step, bridge, broadcast=False, rail=intent.rail_method_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning('agent task %s: purchase pull broadcast unclear: %s', task.internal_id, type(exc).__name__)
        return unsent(step, bridge, rail=intent.rail_method_id)
    task.refresh_from_db()
    from . import pagomovil
    if not pagomovil.keeps_session(task):
        close_session(task)   # a booking keeps its tab, with its form, for the reference
    text = paid_text(task)
    notes.post(task, text, 'payment', push='payment', push_body=notes.say(notes.PAID_BY_ACCOUNT_PUSH, task))
    return True


def unsent(step, bridge, *, broadcast=True, rail=MX_CLABE) -> bool:
    """The pull call did not come back as sent. Its claim (the bridge's pull record and the task's
    payment_ready/account) may have committed before the failure (sponsor_lock_lost after the row, or a
    broadcast error): asked again, never assumed.

      - a pull is written and may still be mined: the bridge follows it by its hash
        (purchase_funding.prove_funding), and closes it, telling the person, if it never lands;
      - none can land: the order is closed; a task already saying it is paid is ended and told there
        (purchase_funding.close), one still this step's is stopped here, said honestly."""
    from .models import AgentTask
    from .runner import Lost, close_session
    funding_mod = funding_module(rail)
    task = step.task
    if rail == VE_PAGOMOVIL:
        fresh = funding_mod.reload(bridge.pk)
    else:
        fresh = type(bridge).objects.select_related('quote__money_flow').get(pk=bridge.pk)
    claimed = AgentTask.objects.filter(pk=task.pk, state='payment_ready', reason='account').exists()
    if funding_mod.may_land(fresh):
        if not claimed:
            raise Lost()    # written by nobody this step knows: the bridge is followed by its own worker
        task.refresh_from_db()
        close_session(task)
        if broadcast:
            # Maybe on the wire: said as paying. Never for one known unsent (written, not broadcast): its
            # bridge closes it and close() tells the person, so they never hear "paying" then "not paid".
            notes.post(task, paid_text(task), 'payment', push='payment',
                       push_body=notes.say(notes.PAID_BY_ACCOUNT_PUSH, task))
        return True
    funding_mod.abandon(bridge.pk, 'pull_not_sent')
    if claimed:
        return True     # close() ended the task and told the person
    step.stop('unpaid', body=notes.say(notes.ACCOUNT_NOT_PAID, task))
    return True


def spender_gap(step, intent, found) -> bool:
    """The purchase spender is configured but not allowed (missing from the mirror's allowlist, removed or
    paused on chain): Confío's gap, never the person's. Ops are told once a day; the purchase stops with
    nothing paid and says so. Not held: nothing the person does fixes it."""
    from smart_account import purchases
    task = step.task
    _cancel(task, intent)
    try:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Compras con Confío IA: el purchase spender {purchases.spender_address()} no está permitido '
                       f'({found.why}). Una compra quedó sin pagar.',
                       dedupe_key=f'purchase_spender_gap:{found.why}', dedupe_seconds=86400)
    except Exception:  # noqa: BLE001 - the person is told either way
        logger.exception('purchase spender gap alert failed')
    step.stop('unpaid', body=notes.say(notes.ACCOUNT_PAUSED, task))
    return True


def paid_text(task) -> str:
    order = task.order or {}
    usd = order.get('account_usd')
    return (notes.say(notes.PAID_BY_ACCOUNT, task).replace('{total}', str(order.get('total') or ''))
            .replace('{usd}', _usd(usd) if usd not in (None, '') else ''))


def wait(step, intent, found, held) -> bool:
    """The account cannot pay it now and the person can change that: the
    purchase waits for them, with nothing a card could pay."""
    from .runner import close_session
    task = step.task
    _cancel(task, intent)
    until = deadline(held)
    if until is None or until <= timezone.now():
        step.stop('account_timeout', body=notes.say(notes.ACCOUNT_WAIT_EXPIRED, task))
        return True
    previous = ((task.order or {}).get('account_wait') or {}).get('code')
    asked = bool(held.pop('asked', False))
    try:
        units = str(units_of(intent))
    except (ArithmeticError, TypeError, ValueError, AttributeError):
        units = str(held.get('units') or '')   # an unread vault: the hold still waits, the next try reads it
    held.update(tries=0, units=units)
    shown = figures(task, found)
    order = {**(task.order or {}), 'pay_hold': held, 'account_wait': shown}
    step.remember('account_wait', found.code, state='needs_person', reason='account_wait', wait_until=until,
                  order=order)
    from . import pagomovil
    if not pagomovil.keeps_session(task):
        close_session(task)
    if found.code != previous or asked:
        # Said again when it changed, or when the person said they had done it and it still cannot pay.
        hours = int(held.get('hours') or conf.get('AGENT_TASKS_ACCOUNT_WAIT_HOURS'))
        text = (notes.say(notes.ACCOUNT_STILL, task) if asked and found.code == previous else '') + shown['text'] \
            + notes.say(notes.ACCOUNT_WAIT_TAIL, task).replace('{hours}', str(hours))
        notes.post(task, text, f'account_wait:{task.steps}', push='person',
                   push_body=notes.say(notes.ACCOUNT_WAIT_PUSH, task))
    return True


def retry_later(step, intent, held, why) -> bool:
    """Something could not be read or reserved now: nothing is paid and no
    card is offered. Tried again shortly from the kept details; after a few
    tries, an honest stop."""
    from .runner import close_session
    task = step.task
    _cancel(task, intent)
    tries = int(held.get('tries') or 0) + 1
    logger.info('agent task %s: account pay retry %s (%s)', task.internal_id, tries, why)
    until = deadline(held)
    if tries > OFF_RETRIES or until is None or until <= timezone.now():
        step.stop('unpaid', body=notes.say(notes.ACCOUNT_UNREAD, task))
        return True
    held['tries'] = tries
    held.pop('asked', None)
    step.remember('account_retry', str(why)[:60], state='awaiting_code', reason='', wait_until=None,
                  order={**(task.order or {}), 'pay_hold': held})
    from . import pagomovil
    if not pagomovil.keeps_session(task):
        close_session(task)
    step.delay = OFF_DELAY_SECONDS
    return True
