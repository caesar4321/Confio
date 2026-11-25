"""A Venezuelan store purchase paid by Pago Móvil from the person's Cuenta inteligente.

The Mexican twin is payment_accounts.purchase_funding (a store CLABE through an
Infinia journey). Here the store showed its Pago Móvil data (bank, phone,
document, the exact bolívares) BEFORE the order exists, and the order is placed
only after the payer types the payout's reference into the store's form
(agent_tasks: the browser leg). So this module pays, and hands the reference to
the task (agent_tasks.service.store_paid), or says it could not
(agent_tasks.service.store_unpaid).

The money rides the ordinary contract-funded VE send (ramps.ve_send, provider
'pagoasap'): one RampTransaction per purchase, the person as sender of record,
the account contract as actor_address (a Relay refund returns there), and the
purchase spender as funding_sender:

  spender.pullTo(account, rule, usdtOut, relayDeposit, ref)   BSC, one call
    -> Relay bridges the exact USDT to USDC at Confío's Pago ASAP Polygon address
    -> ve_send proves the pull by its reported hash (never a scan), and here by
       the pull's own events (purchase_funding.pull_problem: Forwarded, CardPulled
       and the USDT transfer, to this deposit, for this payment's ref)
    -> Relay's delivery proven on Polygon (pagoasap_send.settle)
    -> Pago ASAP payout of EXACTLY exact_ves to the store, polled to completion
    -> store_paid(reference, paid_ves, origin_bank, paid_at), once.

usdtOut is the USDT an ordinary exact-bolívar send of the approved dollars
deposits (ve_send.confio_amounts): the conversion fee is the account's own
cardPull exit, counted against the cap, so the account spends about the dollars
the card showed. Every leg is on the ramp row ops already see (ve_send_admin):
the pull (purchase_pull), its proof (purchase_proof), the Relay binding, the
payout id and reference, and an owed refund (refund_owed) when a payout fails
after the pull. Nothing here refunds by itself.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import bridge_chain as chain
from . import contract_funding as cf
from .allbridge_next import TOKENS, address
from .services import PaymentAccountError

logger = logging.getLogger(__name__)

PURPOSE = 'purchase'
RAIL = 've_pagomovil_send'
PROVIDER = 'pagoasap'
WAD = 10 ** 18
START_STATES = ('quoted',)
FINAL_UNLANDED = ('reverted', 'dropped')
# The ve_send FAILED detail of a purchase whose pull can never land.
PULL_NOT_LANDED = 'pull_not_landed'
REFUND_OWED = 'needs_review:purchase_refund_owed'
# A funded purchase the payout cannot be made for (balance or price) is given up
# after this many minutes: the store's checkout does not wait for ever.
DEFAULT_PAYOUT_WAIT_MINUTES = 60
# Purchase rows the sweep still tells the task about.
SWEEP_DAYS = 7


def is_purchase_terms(terms) -> bool:
    return isinstance(terms, dict) and terms.get('purpose') == PURPOSE


def _section(ramp) -> dict:
    return dict((ramp.metadata or {}).get('ve_send') or {})


def bound_of(ramp) -> dict:
    return dict(_section(ramp).get('funding_terms') or {})


def is_purchase(ramp) -> bool:
    return ramp is not None and is_purchase_terms(bound_of(ramp))


def _refuse(code, text='No pude pagar esta compra desde tu Cuenta inteligente.', *, retry=False):
    return cf.Refused(code, text, retry=retry)


# ------------------------------------------------------------- authority

_ISSUE = object()


class PurchaseFunding:
    """The authority for exactly one approved Venezuelan purchase, re-read on every use."""

    __slots__ = ('task_pk', 'intent_pk', '_seen')

    def __init__(self, task_pk, intent_pk, *, _issue=None):
        if _issue is not _ISSUE:
            raise TypeError('PurchaseFunding is issued by PurchaseFunding.for_task')
        self.task_pk, self.intent_pk, self._seen = int(task_pk), int(intent_pk), None

    @classmethod
    def for_task(cls, task_pk, intent_pk) -> 'PurchaseFunding':
        funding = cls(task_pk, intent_pk, _issue=_ISSUE)
        funding.terms()
        return funding

    def terms(self) -> dict:
        current = purchase_terms(self.task_pk, self.intent_pk)
        seen = record(current)
        if self._seen is not None and self._seen != seen:
            raise cf.Refused('authorization_changed', 'La compra cambió mientras preparábamos el pago.')
        self._seen = seen
        return current


def _bs(value) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() and amount > 0 else None


def purchase_terms(task_pk, intent_pk) -> dict:
    """What the person approved and who pays it, as the rows say now. Refused for anything that is not
    one approved store checkout of a subscriber's purchase rule, paid by Pago Móvil in exact bolívares."""
    from agent_tasks.models import AgentTask
    from ramps import ve_pagomovil
    from smart_account import context, purchases
    from .models import PaymentIntent
    task = AgentTask.objects.select_related('account', 'user').filter(pk=task_pk).first()
    if task is None or getattr(task, 'kind', 'buy') != 'buy':
        raise _refuse('task_not_found')
    if task.payment_intent_id not in (None, int(intent_pk)):
        raise _refuse('not_the_approved_payment')
    order = task.order or {}
    # Pay before order: nothing is pressed yet; the person's approval of this store total is the gate.
    # agent_tasks.pagomovil saves `pay_first` (and clears `approved`) once the approved total's Pago Móvil data was read.
    if order.get('unapproved') or not order.get('pay_first'):
        raise _refuse('not_approved')
    approved = _bs(order.get('amount'))
    if approved is None:
        raise _refuse('not_approved')
    intent = PaymentIntent.objects.filter(pk=intent_pk).first()
    params = (intent.params or {}) if intent is not None else {}
    if (intent is None or intent.confio_account_id != task.account_id or intent.user_id != task.user_id
            or intent.source != 'agent_checkout' or intent.rail_method_id != RAIL or not intent.amount_exact
            or intent.currency != 'VES' or _bs(intent.minimum_local) != approved or _bs(params.get('exact_ves')) != approved
            or intent.total_usd is None or intent.total_usd <= 0):
        raise _refuse('not_the_approved_payment')
    try:
        payee = {'cedula': ve_pagomovil.normalize_cedula(params.get('cedula')),
                 'phone': ve_pagomovil.normalize_phone(params.get('phone')),
                 'bank_code': ve_pagomovil.normalize_bank(params.get('bank_code'))}
    except Exception as exc:  # noqa: BLE001 - a payee that does not normalize is never paid
        raise _refuse('payee_changed') from exc
    if any(payee[key] != params.get(key) for key in payee):
        raise _refuse('payee_changed')
    owner = task.account
    if owner.account_type != 'personal' or owner.user_id != task.user_id:
        raise _refuse('not_personal')
    own = context.own_account(task.user)
    rule = purchases.purchase_rule(own)
    spender = purchases.spender_address()
    if own is None or rule is None or not spender or own.account_id is None:
        raise _refuse('purchases_off')
    return {'task': task, 'intent': intent, 'owner': owner, 'own': own, 'rule': rule,
            'contract': own.contract_address, 'spender': spender, 'amount': intent.total_usd,
            'exact_ves': approved, 'payee': payee, 'holder_name': str(params.get('holder_name') or '')[:140]}


def record(terms: dict) -> dict:
    """The terms as stored on the ramp (funding_terms), to bind it and to check every later use."""
    return {
        'purpose': PURPOSE, 'task': str(terms['task'].internal_id), 'intent': str(terms['intent'].internal_id),
        'request_id': str(terms['intent'].request_id), 'owner': terms['owner'].pk, 'rail': RAIL,
        'contract': address(terms['contract']), 'spender': address(terms['spender']),
        'rule': str(terms['rule'].internal_id), 'rule_id': int(terms['rule'].onchain_id),
        'amount': format(Decimal(terms['amount']).quantize(cf.CENT), 'f'),
        'exact_ves': format(Decimal(terms['exact_ves']).quantize(cf.CENT), 'f'),
        'cedula': terms['payee']['cedula'], 'phone': terms['payee']['phone'],
        'bank_code': terms['payee']['bank_code'],
    }


def pull_units(intent) -> int:
    """The USDT the spender forwards for this purchase: what an exact-bolívar send of the approved dollars
    deposits (ve_send.confio_amounts). Raises ValueError when it cannot be read now."""
    from ramps import ve_send
    try:
        _gross, deposit_wei = ve_send.confio_amounts(Decimal(intent.total_usd))
    except ve_send.VeSendError as exc:
        raise ValueError('purchase_units_unread') from exc
    if deposit_wei <= 0:
        raise ValueError('purchase_units_zero')
    return int(deposit_wei)


# --------------------------------------------------------------- pricing

@dataclass
class Priced:
    """Today's exact quote for these bolívares, the dollars charged and the USDT pulled. `deposit` is
    known only once persist() claims the Relay deposit (DEPOSIT_AT_PERSIST)."""
    units: int
    estimate: dict = field(default_factory=dict)
    deposit: str = ''


# account_pay simulates the pull after persist(): the deposit is Relay's one-time address made at the claim.
DEPOSIT_AT_PERSIST = True


def price(funding: PurchaseFunding) -> Priced:
    """Pago ASAP's exact quote for the approved bolívares, asked fresh (never a cached price for the payment
    itself), against the approved dollars: never more, and not far below either (pagoasap_send.create's
    rule). Moves nothing."""
    from ramps import pagoasap_send
    from ramps.ve_pagomovil import VePagoMovilError
    terms = funding.terms()
    stored = record(terms)
    amount = Decimal(stored['amount'])
    try:
        estimate = pagoasap_send.quote_exact_now(stored['exact_ves'])
        fresh = Decimal(str(estimate['usd_amount']))
    except (VePagoMovilError, KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise _refuse('quote_unavailable', cf.TRY_LATER, retry=True) from exc
    tolerance = max(cf.CENT, (amount * pagoasap_send._price_tolerance()).quantize(cf.CENT))
    if fresh > amount or fresh < amount - tolerance:
        raise _refuse('quote_changed', 'El precio cambió desde que lo preparamos.', retry=True)
    try:
        units = pull_units(terms['intent'])
    except ValueError as exc:
        raise _refuse('quote_unavailable', cf.TRY_LATER, retry=True) from exc
    usdt = Decimal(units) / Decimal(WAD)
    estimate = {**{key: str(value) for key, value in estimate.items()}, 'usd_amount': stored['amount'],
                'usdt_amount': format(usdt, 'f'), 'exact_ves': stored['exact_ves'],
                'estimated_ves': stored['exact_ves']}
    return Priced(units=units, estimate=estimate)


def covers(route: dict, exact_ves) -> bool:
    """The least this Relay route delivers, after Pago ASAP's deposit fee, pays exactly these bolívares at
    Pago ASAP's own cost now. Unread is never 'covers'."""
    from ramps import pagoasap_send
    try:
        least = Decimal(int(str(route.get('amount_out_min')))) / Decimal(10 ** TOKENS[cf.DESTINATION][1])
        cost = pagoasap_send._cost(pagoasap_send._client(), Decimal(str(exact_ves)))
    except Exception:  # noqa: BLE001
        logger.warning('VE purchase coverage unreadable', exc_info=True)
        return False
    return cost > 0 and pagoasap_send._fee_free_usd(least) >= cost


# ----------------------------------------------------------- persistence

def persist(funding: PurchaseFunding, priced: Priced):
    """The purchase's one VE send, reserved and its Relay deposit claimed, with the intent taken by it; or
    nothing at all (Refused). Returns (ramp, None). Nothing is broadcast here."""
    from ramps import ve_send
    from ramps.models import RampTransaction
    from .models import PaymentIntent
    from .payment_intents import display_hash
    block = ve_send.current_block()
    if block is None:
        raise _refuse('chain_unread', cf.TRY_LATER, retry=True)
    try:
        with transaction.atomic():
            terms = funding.terms()
            stored = record(terms)
            intent = PaymentIntent.objects.select_for_update().get(pk=terms['intent'].pk)
            if (intent.state not in START_STATES or intent.bridge_id or intent.order_ref
                    or intent.expires_at <= timezone.now() or str(intent.request_id) != stored['request_id']):
                raise _refuse('intent_not_open')
            if display_hash(intent) != intent.display_hash:
                raise _refuse('intent_changed')
            if RampTransaction.objects.filter(
                    metadata__ve_send__funding_terms__request_id=stored['request_id']).exists():
                raise _refuse('already_paying', 'Esta compra ya se está pagando.')
            own = terms['own']
            beneficiary = {**terms['payee'], 'name': terms['holder_name']}
            bound = dict(stored, units=str(priced.units), attempt=1,
                         # Who may sign a refund Relay could not send (the account contract cannot).
                         recovery=(terms['owner'].bsc_address or '').lower())
            ramp = ve_send.reserve(provider=PROVIDER, user=terms['task'].user, account=own.account,
                                   gross_usd=Decimal(stored['amount']), beneficiary=beneficiary,
                                   gross_wei=int(Decimal(stored['amount']) * WAD), deposit_wei=priced.units,
                                   created_block=block, estimate=priced.estimate,
                                   funding_sender=stored['spender'], funding_terms=bound)
            ramp = ve_send.prepare(ramp)
            # The card's status is this order's from here; no card can be confirmed beside it.
            intent.state, intent.order_ref = 'submitted', str(ramp.internal_id)
            intent.save(update_fields=['state', 'order_ref', 'updated_at'])
    except ve_send.VeSendError as exc:
        raise _refuse('send_refused', str(exc) or cf.TRY_LATER, retry=True) from exc
    # The Relay deposit (an HTTP call, outside every lock): a one-time address for exactly these units.
    try:
        ramp = ve_send.start_funding(ramp, by_payout=True)
    except Exception as exc:  # noqa: BLE001 - nothing can have been paid: the address never left the server
        logger.warning('VE purchase %s: deposit not claimed: %s', ramp.pk, type(exc).__name__)
        _close_unfunded(ramp.pk, 'deposit_target_unavailable')
        raise _refuse('deposit_unavailable', cf.TRY_LATER, retry=True) from exc
    details = ve_send.funding_details(ramp) or {}
    route = _section(ramp).get('bridge') or {}
    expires = details.get('expires_at')
    problem = ''
    if str(details.get('deposit_amount_wei')) != str(priced.units) or details.get('network') != 'BSC':
        problem = 'deposit_mismatch'
    elif not expires or int(expires) < int(time.time()) + cf.MIN_LIFETIME_SECONDS:
        problem = 'quote_expired'
    elif not covers(route, stored['exact_ves']):
        problem = 'quote_changed'      # the guaranteed delivery would not pay the exact bolívares
    if problem:
        _close_unfunded(ramp.pk, 'deposit_target_unavailable')
        raise _refuse(problem, cf.TRY_LATER, retry=True)
    priced.deposit = str(details['deposit_address']).lower()
    return ramp, None


def reload(ramp_pk):
    from ramps.models import RampTransaction
    return RampTransaction.objects.get(pk=ramp_pk)


def pull_call_of(funding: PurchaseFunding, ramp) -> str:
    """The pull this ramp is funded by, exactly as send_pull signs it."""
    from smart_account import purchases
    terms = funding.terms()
    section = _section(ramp)
    return purchases.pull_call(terms['own'], terms['rule'], int(section['deposit_wei']),
                               section['deposit_address'], record(terms)['request_id'])


# ------------------------------------------------------------- the pull

class NotSent(Exception):
    """The pull was not broadcast. `code` is stable; nothing moved."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def send_pull(funding: PurchaseFunding, ramp_pk, *, lease=None):
    """Sign and broadcast the spender's pull for this ramp, once. Under the relay row's own transaction
    (`claim`): the ramp is still fundable (ve_send.lock_fundable), the task is still the live step holding
    `lease`, and the ramp records the pull's hash (as its reported funding hash) and the task says the
    account is paying, before the call exists anywhere else. Raises NotSent when nothing was broadcast;
    any error of the broadcast itself propagates (the ramp follows the hash)."""
    from agent_tasks.models import AgentTask
    from ramps import ve_send
    from smart_account import purchases, relayer
    terms = funding.terms()
    stored = record(terms)
    ramp = reload(ramp_pk)
    bound = bound_of(ramp)
    if not is_purchase(ramp) or any(bound.get(key) != value for key, value in stored.items()):
        raise NotSent('terms_changed')
    section = _section(ramp)
    deposit, units = str(section.get('deposit_address') or ''), str(section.get('deposit_wei') or '')
    if not deposit or units != str(bound.get('units')):
        raise NotSent('terms_changed')
    calldata = purchases.pull_call(terms['own'], terms['rule'], int(units), deposit, stored['request_id'])

    def claim(tx_hash):
        if ve_send.lock_fundable(ramp_pk, deposit, units) is None:
            raise relayer.RelayError('not_fundable')
        task = AgentTask.objects.select_for_update().filter(pk=funding.task_pk).first()
        # Pay before order: agent_tasks.pagomovil.pay_first pays from the working step itself (phase 'paying');
        # a held purchase resumes as awaiting_code.
        paying_now = (task is not None and task.state == 'working' and task.phase == 'paying'
                      and (task.order or {}).get('pay_first'))
        if (task is None or not (task.state == 'awaiting_code' or paying_now)
                or (lease is not None and task.lease != lease)):
            raise relayer.RelayError('task_moved')
        if _section(reload(ramp_pk)).get('purchase_pull'):
            raise relayer.RelayError('already_pulled')
        now = timezone.now().isoformat()
        ve_send._update(ramp_pk, purchase_pull={'tx': tx_hash.lower(), 'at': int(time.time())},
                        funding_tx_hashes=[tx_hash.lower()], funding_reported_at=now)
        AgentTask.objects.filter(pk=task.pk).update(state='payment_ready', reason='account', wait_until=None,
                                                    payment_intent=terms['intent'], updated_at=timezone.now())

    try:
        row, created = purchases.send_pull(terms['own'], calldata, str(ramp.internal_id), claim=claim)
    except relayer.RelayError as exc:
        raise NotSent(exc.code) from exc
    if not created:
        raise NotSent('already_sent')
    return row


def _nonce_taken(row) -> bool:
    from . import purchase_funding
    return purchase_funding._nonce_taken(row)


def may_land(ramp) -> bool:
    """A pull for this ramp was written (its relay row and hash) and may still be mined."""
    from smart_account.models import SmartAccountRelayTx
    pull = _section(ramp).get('purchase_pull') or {}
    if not pull.get('tx') or pull.get('reverted'):
        return False
    row = SmartAccountRelayTx.objects.filter(signed_tx_hash__iexact=pull['tx']).first()
    if row is not None and row.status == 'reorged' and _nonce_taken(row):
        return False
    return row is None or row.status not in FINAL_UNLANDED


def abandon(ramp_pk, reason: str) -> bool:
    """Nothing was broadcast, or what was can never land: the order is closed so it holds nothing, the
    intent expires, and a task the account was paying is told it was not paid."""
    return close(ramp_pk, reason)


def _expire_intent(ramp, reason: str) -> None:
    from .models import PaymentIntent
    PaymentIntent.objects.filter(order_ref=str(ramp.internal_id), state__in=('quoted', 'submitted')).update(
        state='expired', state_reason=reason[:40], updated_at=timezone.now())


def _close_unfunded(ramp_pk, detail: str) -> bool:
    """Close an order no pull was written for (persist's failures): FAILED, intent expired."""
    from ramps import ve_send
    ramp = reload(ramp_pk)
    closed = ve_send._update(
        ramp_pk, require=lambda c: c.status == 'PENDING' and not _section(c).get('purchase_pull')
        and not _section(c).get('funding_tx_hashes'), status='FAILED', detail=detail, quiet=True)
    _expire_intent(ramp, detail)
    return closed is not None


def close(ramp_pk, reason: str = PULL_NOT_LANDED) -> bool:
    """A purchase order whose pull can never land (or was never sent): closed, its intent expired, and a
    task still saying the account is paying it is told (store_unpaid). Never one whose pull may land or
    was proven."""
    from ramps import ve_send
    ramp = reload(ramp_pk)
    if may_land(ramp):
        return False
    detail = PULL_NOT_LANDED if _section(ramp).get('purchase_pull') else 'payout_not_sent'
    updated = ve_send._update(
        ramp_pk, require=lambda c: c.status == 'PENDING' and not _section(c).get('funding_tx_hash')
        and not may_land(c), status='FAILED', detail=detail, quiet=True, purchase_closed=reason[:40])
    if updated is None:
        return False
    _expire_intent(updated, reason)
    tell(updated)
    return True


# --------------------------------------------------------- funding proof

def funding_problem(ramp, tx_hash: str, funded_wei) -> str:
    """ve_send._terms_problem for a purchase: '' only while the funded transfer is exactly this purchase's
    pull, proven from its final receipt (purchase_funding.pull_problem). ve_send.EVENT_NOT_SEEN while that
    receipt is not final yet (nothing is parked)."""
    from ramps import ve_send
    from . import purchase_funding
    section = _section(ramp)
    bound = bound_of(ramp)
    tx = str(tx_hash or '').lower()
    if not is_purchase_terms(bound) or str(funded_wei) != str(bound.get('units')):
        return 'purchase_amount_changed'
    if (section.get('purchase_pull') or {}).get('tx') != tx:
        return 'not_the_purchase_pull'
    proof = section.get('purchase_proof') or {}
    if proof and proof.get('tx') == tx and str(proof.get('units')) == str(funded_wei) \
            and proof.get('to') == address(section.get('deposit_address') or '0x' + '0' * 40):
        return ''
    receipt = chain.final_receipt('BSC', tx)
    if receipt is None:
        return ve_send.EVENT_NOT_SEEN
    proof, problem = purchase_funding.pull_problem(
        receipt, SimpleNamespace(deposit_address=section.get('deposit_address') or ''), bound)
    if problem:
        return problem
    ve_send._update(ramp.pk, purchase_proof=proof)
    return ''


def pull_fate(ramp) -> str:
    """'landed', 'unlanded' (reverted, dropped, or orphaned with its nonce taken) or 'pending'."""
    from ramps import ve_send
    pull = _section(ramp).get('purchase_pull') or {}
    if not pull.get('tx'):
        return 'unlanded' if not may_land(ramp) else 'pending'
    try:
        receipt = chain.final_receipt('BSC', pull['tx'])
    except Exception:  # noqa: BLE001 - unread: it may still land
        logger.warning('VE purchase %s: pull receipt unread', ramp.pk, exc_info=True)
        return 'pending'
    if receipt is not None:
        if int(str(receipt.get('status') or '0x0'), 16) == 1:
            return 'landed'
        ve_send._update(ramp.pk, purchase_pull=dict(pull, reverted=True))
        return 'unlanded'
    return 'pending' if may_land(ramp) else 'unlanded'


# ------------------------------------------------------- the task is told

def _task_pk(ramp):
    from agent_tasks.models import AgentTask
    try:
        task_id = uuid.UUID(str(bound_of(ramp).get('task') or ''))
    except ValueError:
        return None
    return AgentTask.objects.filter(internal_id=task_id).values_list('pk', flat=True).first()


def _ops(text: str, key: str) -> None:
    try:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(text, dedupe_key=key, dedupe_seconds=86400)
    except Exception:  # noqa: BLE001
        logger.exception('VE purchase ops alert failed (%s)', key)


def _call(name: str, ramp, **kwargs) -> bool:
    """agent_tasks.service.<name>(task_pk, **kwargs). False (loudly) when it is not there or failed: the
    poller and the sweep call it again; both are idempotent."""
    task_pk = _task_pk(ramp)
    if task_pk is None:
        logger.error('VE purchase %s: no task for %s', ramp.pk, name)
        return False
    from agent_tasks import service
    function = getattr(service, name, None)
    if function is None:
        logger.error('VE purchase %s: agent_tasks.service.%s is missing; the task was not told', ramp.pk, name)
        _ops(f'⚠️ Compra VE {ramp.internal_id}: agent_tasks.service.{name} no existe; la tarea no se enteró.',
             f've_purchase:missing:{name}')
        return False
    try:
        told = function(task_pk, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception('VE purchase %s: service.%s failed', ramp.pk, name)
        return False
    if told is False:
        # Refused (a state it did not expect): not marked told, so the sweep and ops see it again.
        _ops(f'⚠️ Compra VE {ramp.internal_id}: service.{name} no aceptó el resultado; la tarea no se enteró.',
             f've_purchase:refused:{name}:{ramp.pk}')
        return False
    return True


def _paying_with(ramp) -> bool:
    """The task says the account is paying it, with THIS order (its intent is this ramp's)."""
    from agent_tasks.models import AgentTask
    task_pk = _task_pk(ramp)
    return task_pk is not None and AgentTask.objects.filter(
        pk=task_pk, state='payment_ready', reason='account',
        payment_intent__order_ref=str(ramp.internal_id)).exists()


def origin_bank(section) -> str:
    value = str(section.get('origin_bank') or '')
    return value if len(value) == 4 and value.isdigit() else ''


def _paid_at(ramp) -> str:
    when = ramp.completed_at or ramp.updated_at or timezone.now()
    return when.isoformat()


def record_refund_owed(ramp, why: str) -> None:
    """The pull landed and the dollars sit in Confío's Pago ASAP balance, but the store was not paid: an
    owed refund, on the row ops already review. Never refunded automatically."""
    from ramps import ve_send
    section = _section(ramp)
    if section.get('refund_owed'):
        return
    # What left the account (the gross its cap counted, CardPulled.usdSpent), not what Relay delivered.
    gross = str((section.get('purchase_proof') or {}).get('gross') or '')
    delivered = section.get('credited_usd') or format(Decimal(int(section.get('funded_wei') or 0)) / Decimal(WAD), 'f')
    usd = format(Decimal(int(gross)) / Decimal(WAD), 'f') if gross.isdigit() else delivered
    updated = ve_send._update(ramp.pk, require=lambda c: not _section(c).get('refund_owed'),
                              detail=f'{REFUND_OWED}:{why}'[:500],
                              refund_owed={'usd': str(usd), 'delivered_usd': str(delivered), 'why': why,
                                           'since': timezone.now().isoformat(),
                                           'to': bound_of(ramp).get('contract')})
    if updated is None:
        return
    _ops(f'⚠️ Compra VE {ramp.internal_id}: el pago a la tienda no salió ({why}) después de cobrar a la '
         f'Cuenta inteligente. US${usd} quedan en el saldo de Pago ASAP: devolución pendiente a '
         f'{bound_of(ramp).get("contract")} (a mano).', f've_purchase:refund_owed:{ramp.pk}')


def tell(ramp):
    """Tell the task where its payment ended, once: paid (the payout's reference), or not paid (a code).
    Idempotent (store_told on the ramp; the service calls are idempotent too)."""
    from ramps import ve_send
    ramp = reload(ramp.pk)
    if not is_purchase(ramp):
        return ramp
    section = _section(ramp)
    if section.get('store_told'):
        return ramp
    phase = section.get('phase') or ''
    if ramp.status == 'COMPLETED':
        reference = str(section.get('bank_reference') or '').strip()
        if not reference:
            _ops(f'⚠️ Compra VE {ramp.internal_id}: Pago ASAP pagó sin referencia; la tienda no puede '
                 f'confirmarse. Revísalo.', f've_purchase:no_reference:{ramp.pk}')
            return ramp
        paid_ves = str(section.get('delivered_ves') or section.get('payout_ves') or bound_of(ramp).get('exact_ves'))
        if _bs(paid_ves) != _bs(bound_of(ramp).get('exact_ves')):
            _ops(f'⚠️ Compra VE {ramp.internal_id}: se pagaron Bs {paid_ves}, no los Bs '
                 f'{bound_of(ramp).get("exact_ves")} aprobados.', f've_purchase:amount:{ramp.pk}')
        if _call('store_paid', ramp, reference=reference, paid_ves=paid_ves, origin_bank=origin_bank(section),
                 paid_at=_paid_at(ramp)):
            ve_send._update(ramp.pk, store_told={'paid': timezone.now().isoformat()})
        return reload(ramp.pk)
    why = ''
    if ramp.status == 'PROCESSING' and phase == 'payout_failed':
        why = 'payout_failed'
        record_refund_owed(ramp, str(ramp.status_detail or '').rsplit(':', 1)[-1] or why)
    elif ramp.status == 'FAILED':
        if ramp.status_detail == 'refunded_to_wallet':
            why = 'bridge_refunded'      # proven back in the account contract
        elif section.get('purchase_pull'):
            why = PULL_NOT_LANDED
        else:
            why = 'not_funded'
        _expire_intent(ramp, why)
    if not why:
        return ramp
    if not _paying_with(ramp):
        # Not the task's payment (a closed attempt the step itself retried or stopped): nothing to tell.
        ve_send._update(ramp.pk, store_told={'none': timezone.now().isoformat(), 'why': why})
        return reload(ramp.pk)
    if _call('store_unpaid', ramp, why=why):
        ve_send._update(ramp.pk, store_told={'unpaid': timezone.now().isoformat(), 'why': why})
    return reload(ramp.pk)


def _payout_wait() -> timedelta:
    minutes = int(getattr(settings, 'VE_PURCHASE_PAYOUT_WAIT_MINUTES', DEFAULT_PAYOUT_WAIT_MINUTES) or 0)
    return timedelta(minutes=max(minutes, 5))


def _give_up_payout(ramp):
    """Funded and settled, but no payout could be claimed (Pago ASAP's balance or price) for longer than
    the store waits: the payout is failed (under the row lock, so never beside a claim), the refund owed."""
    from ramps import ve_send
    section = _section(ramp)
    seen = section.get('purchase_settled_at')
    if not seen:
        ve_send._update(ramp.pk, purchase_settled_at=timezone.now().isoformat())
        return reload(ramp.pk)
    since = ve_send._parse_time(seen)
    if since is None or since > timezone.now() - _payout_wait():
        return ramp
    reason = ramp.status_detail if ramp.status_detail in ('waiting_balance', 'waiting_rate') else 'payout_wait'
    updated = ve_send._update(
        ramp.pk, require=lambda c: c.status == 'PROCESSING' and _section(c).get('phase') == 'settled',
        phase='payout_failed', detail=f'needs_review:payout_failed:purchase_{reason}')
    return updated or reload(ramp.pk)


def _give_up_review(ramp):
    """Funded but parked for review (owner, terms, an unknown payout) longer than the store waits: never paid
    later to a checkout that is gone. Failed under the row lock, the refund owed for ops to VERIFY (an unknown
    payout may still have paid the store) before returning anything."""
    from ramps import ve_send
    section = _section(ramp)
    seen = section.get('purchase_review_at')
    if not seen:
        ve_send._update(ramp.pk, purchase_review_at=timezone.now().isoformat())
        return reload(ramp.pk)
    since = ve_send._parse_time(seen)
    if since is None or since > timezone.now() - _payout_wait():
        return ramp
    updated = ve_send._update(
        ramp.pk, require=lambda c: c.status == 'PROCESSING' and _section(c).get('phase') == 'payout_review',
        phase='payout_failed', detail='needs_review:payout_failed:purchase_review_timeout')
    return updated or reload(ramp.pk)


def follow(ramp):
    """After every ve_send.sync of a purchase (the poller and Pago ASAP's webhook both run it): a pull that
    can never land closes the order; a payout that cannot be made in time is given up; and the task is
    told how it ended."""
    if not is_purchase(ramp):
        return ramp
    section = _section(ramp)
    if ramp.status == 'PENDING' and section.get('purchase_pull') and not section.get('funding_tx_hash'):
        if pull_fate(ramp) == 'unlanded':
            close(ramp.pk, PULL_NOT_LANDED)
            return reload(ramp.pk)
    if ramp.status == 'PROCESSING' and section.get('phase') == 'settled':
        ramp = _give_up_payout(ramp)
    elif ramp.status == 'PROCESSING' and section.get('phase') == 'payout_review':
        ramp = _give_up_review(ramp)
    return tell(ramp)


def told_unpaid(ramp) -> bool:
    return bool((_section(ramp).get('store_told') or {}).get('unpaid'))


def sweep() -> int:
    """Purchases that ended without the task being told (a service error, an ops mark-paid): told now."""
    from ramps.models import RampTransaction
    from django.db.models import Q
    since = timezone.now() - timedelta(days=SWEEP_DAYS)
    rows = (RampTransaction.objects.filter(provider=PROVIDER, updated_at__gte=since,
                                            metadata__ve_send__funding_terms__purpose=PURPOSE)
            .filter(Q(status__in=('COMPLETED', 'FAILED'))
                    | Q(metadata__ve_send__phase__in=('payout_failed', 'payout_review', 'settled')))
            .exclude(metadata__ve_send__has_key='store_told'))
    told = 0
    for ramp in rows[:50]:
        try:
            if follow(ramp) and _section(reload(ramp.pk)).get('store_told'):
                told += 1
        except Exception:  # noqa: BLE001
            logger.exception('VE purchase sweep failed for %s', ramp.pk)
    return told


def pulled_usd(ramp) -> Decimal | None:
    proof = _section(ramp).get('purchase_proof') or {}
    return Decimal(int(proof['units'])) / Decimal(WAD) if proof.get('units') else None


__all__ = ['PurchaseFunding', 'Priced', 'price', 'persist', 'send_pull', 'abandon', 'close', 'may_land',
           'funding_problem', 'follow', 'tell', 'sweep', 'NotSent', 'PaymentAccountError']
