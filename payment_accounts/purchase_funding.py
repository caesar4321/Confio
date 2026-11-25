"""Infinia to-bank journeys of a purchase the account pays (spec decisions 37 to 42, 3.6).

The shopping agent placed an order the person approved (agent_tasks.operate:
`order.pressed`, not `unapproved`) and read the store's payment off its order
page (agent_tasks.runner.after_checkout): the store's CLABE, the exact pesos
and the order's reference, priced as an ordinary store-order PaymentIntent.
When the person's Cuenta inteligente pays it, nobody signs anything now: the
owner signed the "Compras con Confío IA" Card rule once, with Face, and the
purchase spender pulls exactly this payment's dollars from it
(smart_account.purchases).

It rides contract_funding's machinery (funding_mode 'contract', the bridge's
binding and the flow's metadata under contract_funding.KEY, a one-time Relay
deposit, refunds to the account contract), and differs only here:

- Authority is a `PurchaseFunding`, issued from an AgentTask and re-read on
  every use: the order the person approved, its PaymentIntent (the store's
  CLABE, the approved pesos), the owner's live purchase rule. No GraphQL
  argument can make one. The bound terms carry `purpose: 'purchase'`, and
  contract_funding hands every rule-specific question to this module.
- The source is the purchase spender: the deposit is paid by the spender's
  pullTo, in the same transaction as the account's cardPull. That call is
  written (its relay row and hash) under the bridge's lock and the task's,
  so "a pull may be on the wire" is always known.
- Funding is proven only by that pull's final receipt: the spender's
  Forwarded event (this account, this rule, exactly the quoted units, to this
  deposit, this payment's ref), the account's CardPulled for the same rule
  and amount, and the USDT transfer spender -> deposit of exactly those units.
- The payee is the store's CLABE as the order page showed it: never another
  row, never another amount. The payout is the approved pesos exactly; what
  the conversion lands above them stays in the owner's peso account.
- The FX floor is the rate at which the guaranteed delivery covers the
  approved pesos: under it nothing converts (contract_funding.rate_refused).

Never a different amount than approved: the pull is the intent's dollars,
the payout the intent's pesos, both bound on the order and asked again.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone as dt_timezone
from decimal import ROUND_DOWN, Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import bridge_chain as chain
from . import contract_funding as cf
from .allbridge_next import TOKENS, address
from .models import MoneyFlow, PaymentBridgeQuote, PaymentBridgeTransfer
from .services import PaymentAccountError

logger = logging.getLogger(__name__)

PURPOSE = 'purchase'
RAIL = 'mx_clabe'
WAD = 10 ** 18
RATE_PLACES = Decimal('0.000001')
# The intent states a purchase may start from, and the one it takes.
START_STATES = ('quoted',)
# A pull that can never land: its nonce was dropped, or it was mined and reverted. A reorged one can be mined
# again (its nonce is unused: automation.slot_may_land), so it may still land.
FINAL_UNLANDED = ('reverted', 'dropped')


def is_purchase_bound(bound) -> bool:
    return isinstance(bound, dict) and bound.get('purpose') == PURPOSE


def bound_of(bridge) -> dict:
    return ((bridge.quote.money_flow.metadata or {}).get(cf.KEY) or {}) if bridge is not None else {}


def is_purchase(bridge) -> bool:
    return bridge is not None and bridge.funding_mode == cf.MODE and is_purchase_bound(bound_of(bridge))


# ------------------------------------------------------------- authority

_ISSUE = object()


class PurchaseFunding:
    """The authority for exactly one approved purchase. It holds the task's id
    and the terms first read for it; every use reads them again and refuses
    a change."""

    __slots__ = ('task_pk', 'intent_pk', '_seen')

    def __init__(self, task_pk, intent_pk, *, _issue=None):
        if _issue is not _ISSUE:
            raise TypeError('PurchaseFunding is issued by PurchaseFunding.for_task')
        self.task_pk, self.intent_pk, self._seen = int(task_pk), int(intent_pk), None

    @classmethod
    def for_task(cls, task_pk, intent_pk) -> 'PurchaseFunding':
        """`intent_pk`: the PaymentIntent read off this task's order page. It is
        the task's own once the pull is written, and never another's."""
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


def _refuse(code, text='No pude pagar esta compra desde tu Cuenta inteligente.'):
    return cf.Refused(code, text)


def purchase_terms(task_pk, intent_pk) -> dict:
    """What the person approved and who pays it, as the rows say now. Raises
    Refused for anything that is not one approved order of a subscriber's
    purchase rule."""
    from agent_tasks.models import AgentTask
    from smart_account import context, purchases
    from .models import PaymentIntent
    task = AgentTask.objects.select_related('account', 'user').filter(pk=task_pk).first()
    if task is None or getattr(task, 'kind', 'buy') != 'buy':
        raise _refuse('task_not_found')
    if task.payment_intent_id not in (None, int(intent_pk)):
        raise _refuse('not_the_approved_payment')
    order = task.order or {}
    intent = PaymentIntent.objects.select_related('destination').filter(pk=intent_pk).first()
    if not order.get('pressed') or order.get('unapproved') or not order.get('amount'):
        raise _refuse('not_approved')     # an order the store shows without the person: nothing is paid
    try:
        approved = Decimal(str(order['amount']))
    except ArithmeticError as exc:
        raise _refuse('not_approved') from exc
    store_order = ((intent.params or {}).get('store_order') or {}) if intent is not None else {}
    if (intent is None or intent.confio_account_id != task.account_id or intent.user_id != task.user_id
            or intent.source != 'agent_checkout' or intent.family != 'local_transfer'
            or intent.rail_method_id != RAIL or not intent.amount_exact or intent.currency != 'MXN'
            or intent.amount_local != approved or Decimal(str(store_order.get('amount') or 0)) != approved
            or intent.destination_id is None or intent.payee_level != 'store_checkout'
            or intent.total_usd is None or intent.total_usd <= 0):
        raise _refuse('not_the_approved_payment')
    destination = intent.destination
    if (destination.provider_data or {}).get('store_order') != store_order:
        raise _refuse('payee_changed')
    owner = task.account
    if owner.account_type != 'personal' or owner.user_id != task.user_id:
        raise _refuse('not_personal')
    own = context.own_account(task.user)
    rule = purchases.purchase_rule(own)
    spender = purchases.spender_address()
    if own is None or rule is None or not spender:
        raise _refuse('purchases_off')
    return {
        'task': task, 'intent': intent, 'owner': owner, 'destination': destination, 'own': own, 'rule': rule,
        'contract': own.contract_address, 'spender': spender, 'amount': intent.total_usd,
        'amount_local': approved, 'fee_ceiling': intent.fee_usd or Decimal(0),
        'clabe': str((destination.details or {}).get('clabe') or ''), 'reference': str(store_order.get('reference') or ''),
    }


def record(terms: dict) -> dict:
    """The terms as stored on the bridge, to bind it and to check every later use."""
    return {
        'purpose': PURPOSE, 'task': str(terms['task'].internal_id), 'intent': str(terms['intent'].internal_id),
        'request_id': str(terms['intent'].request_id), 'owner': terms['owner'].pk,
        'destination': str(terms['destination'].internal_id), 'rail': RAIL,
        'contract': address(terms['contract']), 'spender': address(terms['spender']),
        'rule': str(terms['rule'].internal_id), 'rule_id': int(terms['rule'].onchain_id),
        'amount': format(Decimal(terms['amount']).quantize(cf.CENT), 'f'),
        'amount_local': format(Decimal(terms['amount_local']).quantize(cf.CENT), 'f'),
        'fee_ceiling': format(Decimal(terms['fee_ceiling']).quantize(Decimal('0.000001')), 'f'),
        'clabe': terms['clabe'], 'reference': terms['reference'],
    }


def units_of(stored: dict) -> int:
    return int(Decimal(stored['amount']) * WAD)


# --------------------------------------------------------------- pricing

def price(funding: PurchaseFunding) -> cf.Priced:
    """Today's one-time deposit and FX quote for this purchase, as a payment
    rule's: the deposit is refunded to the account contract. Moves nothing.
    Refused unless the guaranteed delivery covers the approved pesos."""
    terms = funding.terms()
    stored = record(terms)
    priced = cf.price(owner=terms['owner'], destination=terms['destination'], rail=RAIL,
                      contract=stored['contract'], amount=Decimal(stored['amount']), units=units_of(stored),
                      fee_ceiling=Decimal(stored['fee_ceiling']))
    if priced.fx_target < Decimal(stored['amount_local']):
        raise cf.Refused('quote_changed', 'El precio cambió desde que lo preparamos.', retry=True)
    return priced


def fx_floor(priced: cf.Priced, amount_local) -> Decimal:
    """The rate at which the guaranteed delivery still covers the approved
    pesos: any conversion at or above it pays the order."""
    return (Decimal(amount_local) / priced.fx_source).quantize(RATE_PLACES, rounding=ROUND_DOWN) + RATE_PLACES


# ----------------------------------------------------------- persistence

def persist(funding: PurchaseFunding, priced: cf.Priced):
    """The purchase's one order (bridge and journey), the intent taken by it,
    or nothing at all. Its request id is the intent's: the card's status is
    this payment's."""
    from . import infinia_journeys
    from .bridge import exceeds_bridge_cap, verified_destination
    from .bridge_execution import execution_enabled
    from .models import PaymentIntent

    with transaction.atomic():
        terms = funding.terms()
        owner = type(terms['owner']).objects.select_for_update().get(pk=terms['owner'].pk)
        stored = record(terms)
        units = units_of(stored)
        intent = PaymentIntent.objects.select_for_update().get(pk=terms['intent'].pk)
        if (intent.state not in START_STATES or intent.bridge_id or intent.expires_at <= timezone.now()
                or str(intent.request_id) != stored['request_id']):
            raise _refuse('intent_not_open')
        from .payment_intents import display_hash
        if display_hash(intent) != intent.display_hash:
            raise _refuse('intent_changed')
        if priced.contract != stored['contract'] or priced.units != units or exceeds_bridge_cap(stored['amount']):
            raise cf.Refused('authorization_changed', cf.TRY_LATER, retry=True)
        cf.require_signed_fee(priced.fee, stored['fee_ceiling'], RAIL)
        cf.require_free(owner, priced.local, priced.crypto)
        execution_enabled(cf.SOURCE)
        priced.instruction.refresh_from_db()
        if verified_destination(priced.instruction, owner) != priced.recipient:
            raise cf.Refused('funding_account_changed', cf.TRY_LATER, retry=True)
        if priced.deadline < int(time.time()) + cf.MIN_LIFETIME_SECONDS:
            raise cf.Refused('quote_expired', cf.TRY_LATER, retry=True)
        if (priced.deposit in (stored['contract'], stored['spender'], priced.recipient)
                or PaymentBridgeTransfer.objects.filter(deposit_address__iexact=priced.deposit).exists()):
            raise cf.Refused('deposit_address_reused', cf.TRY_LATER, retry=True)
        request_id = uuid.UUID(stored['request_id'])
        if PaymentBridgeQuote.objects.filter(confio_account=owner, request_id=request_id).exists():
            raise _refuse('already_paying', 'Esta compra ya se está pagando.')
        floor = fx_floor(priced, stored['amount_local'])
        details = dict(stored, units=str(units), cost_bps=priced.cost_bps, rate=str(priced.rate),
                       fx_floor=format(floor, 'f'), fee=priced.fee)
        flow = MoneyFlow.objects.create(
            confio_account=owner, kind='withdraw', status='processing', source_asset='USDT_BSC',
            source_amount=Decimal(stored['amount']), target_asset='USDC_POL',
            metadata={'purpose': 'provider_bridge_funding', 'stage': 'awaiting_contract_funding',
                      'local_destination_id': stored['destination'], 'gross_spend_units': str(units),
                      cf.KEY: details})
        quote = PaymentBridgeQuote.objects.create(
            confio_account=owner, request_id=request_id, money_flow=flow, funding_instruction=priced.instruction,
            # Relay's refund address: the account contract, never the spender (it holds nothing).
            source_address=stored['contract'], destination_address=priced.recipient,
            amount_units=str(units), source_token_id=cf.SOURCE, destination_token_id=cf.DESTINATION,
            routes=[priced.route], expires_at=datetime.fromtimestamp(priced.deadline, tz=dt_timezone.utc))
        try:
            with transaction.atomic():
                bridge = PaymentBridgeTransfer.objects.create(
                    quote=quote, funding_mode=cf.MODE, status='submitted', deposit_address=priced.deposit,
                    amount_out_min=priced.build['amountOutMin'], amount_out=priced.build['amountOut'],
                    deadline=priced.deadline, calls=[],
                    binding=dict(priced.build['relay'],
                                 funding={'wallet_usdt_units': '0', 'fee_units': '0', 'gross_redeem_units': '0'},
                                 # `sender`: who pays the deposit (relay_settlement, reconcile_bridge).
                                 **{cf.KEY: {'sender': stored['spender'], 'recovery': priced.recovery,
                                             'reported': [], 'purpose': PURPOSE}}))
        except IntegrityError as exc:
            raise cf.Refused('deposit_address_reused', cf.TRY_LATER, retry=True) from exc
        try:
            journey = infinia_journeys.create_journey(
                owner=owner, local_account=priced.local, crypto_account=priced.crypto, request_id=request_id,
                minimum_fx_output=Decimal(stored['amount_local']), direction='to_bank', bridge=bridge,
                destination=terms['destination'], funding=funding)
        except infinia_journeys.JourneyBusy as exc:
            raise cf.Refused('account_busy', cf.BUSY, retry=True) from exc
        # The person's card can never be confirmed beside it: the intent is this payment's.
        intent.state, intent.bridge = 'submitted', bridge
        intent.save(update_fields=['state', 'bridge', 'updated_at'])
    return bridge, journey


def authorize_journey(funding, *, owner, destination, bridge, local_account) -> dict:
    """create_journey's gate in place of a Face grant: the approved purchase,
    bound to this very bridge. Returns what the journey records."""
    if type(funding) is not PurchaseFunding:
        raise PaymentAccountError(cf.OWNER_REFUSAL)
    terms = funding.terms()
    stored = record(terms)
    quote = bridge.quote
    bound = bound_of(bridge)
    data = (bridge.binding or {}).get(cf.KEY) or {}
    if (bridge.funding_mode != cf.MODE or bridge.batch_id or bridge.calls or bridge.source_tx_hash
            or any(bound.get(key) != value for key, value in stored.items())
            or stored['owner'] != owner.pk or quote.confio_account_id != owner.pk
            or stored['destination'] != str(destination.internal_id)
            or quote.source_address != stored['contract'] or str(quote.request_id) != stored['request_id']
            or str(quote.amount_units) != str(units_of(stored)) or str(bound.get('units')) != str(units_of(stored))
            or quote.money_flow.source_amount != Decimal(stored['amount'])
            or local_account.asset != destination.asset or destination.asset != 'MXN'
            or data.get('sender') != stored['spender'] or data.get('purpose') != PURPOSE):
        raise PaymentAccountError('The bridge does not match the approved purchase')
    cf.require_owner(owner)
    return dict(bound)


# ------------------------------------------------------------- the pull

def may_land(bridge) -> bool:
    """A pull for this bridge was written (its relay row and hash) and may
    still be mined. A reverted, dropped or reorged one cannot fund it."""
    from smart_account.models import SmartAccountRelayTx
    pull = ((bridge.binding or {}).get(cf.KEY) or {}).get('pull') or {}
    if not pull.get('tx'):
        return False
    if pull.get('reverted'):
        return False
    row = SmartAccountRelayTx.objects.filter(signed_tx_hash__iexact=pull['tx']).first()
    if row is not None and row.status == 'reorged' and _nonce_taken(row):
        return False    # orphaned, and another transaction has its nonce now: it can never be mined
    return row is None or row.status not in FINAL_UNLANDED


def _nonce_taken(row) -> bool:
    """A reorged pull's nonce is past the sponsor's mined nonce and it has no receipt: the relayer's own
    rule for a dropped one (smart_account.relayer.drop_if_nonce_passed), which never looks at 'reorged'
    rows. Unread is never 'taken': it may still land."""
    from django.conf import settings
    from smart_account import chain
    sponsor = (getattr(settings, 'BSC_SPONSOR_ADDRESS', None) or '').strip()
    if row.sponsor_nonce is None or not sponsor:
        return False
    try:
        mined = int(chain.rpc('eth_getTransactionCount', [sponsor, 'latest']), 16)
        return mined > int(row.sponsor_nonce) and not chain.receipt(row.signed_tx_hash)
    except Exception:  # noqa: BLE001 - unread: it may still land
        return False


class NotSent(Exception):
    """The pull was not broadcast. `code` is stable; nothing moved."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def send_pull(funding: PurchaseFunding, bridge_pk, *, lease=None):
    """Sign and broadcast the spender's pull for this bridge, once.

    Under the durable relay row's own transaction (`claim`), the bridge is
    still fundable (contract_funding.lock_fundable), the task is still the
    live step that holds `lease`, and the bridge and the task record the pull
    before it exists anywhere else. Raises NotSent when nothing was
    broadcast; any error of the broadcast itself propagates with the row kept
    'signed' for the reconciler (the money may move: the bridge follows it)."""
    from agent_tasks.models import AgentTask
    from smart_account import purchases, relayer
    terms = funding.terms()
    stored = record(terms)
    bridge = PaymentBridgeTransfer.objects.select_related('quote__money_flow').get(pk=bridge_pk)
    if not is_purchase(bridge) or any(bound_of(bridge).get(key) != value for key, value in stored.items()):
        raise NotSent('terms_changed')
    calldata = purchases.pull_call(terms['own'], terms['rule'], units_of(stored), bridge.deposit_address,
                                   stored['request_id'])

    def claim(tx_hash):
        if not cf.lock_fundable(bridge_pk):
            raise relayer.RelayError('not_fundable')
        task = AgentTask.objects.select_for_update().filter(pk=funding.task_pk).first()
        if task is None or task.state != 'awaiting_code' or (lease is not None and task.lease != lease):
            raise relayer.RelayError('task_moved')
        locked = PaymentBridgeTransfer.objects.select_for_update().get(pk=bridge_pk)
        data = dict(locked.binding.get(cf.KEY) or {})
        if data.get('pull'):
            raise relayer.RelayError('already_pulled')
        data['pull'] = {'tx': tx_hash.lower(), 'at': int(time.time())}
        locked.binding = dict(locked.binding, **{cf.KEY: data})
        locked.save(update_fields=['binding', 'updated_at'])
        # Paid by the account from here: the task says so in the same commit.
        AgentTask.objects.filter(pk=task.pk).update(state='payment_ready', reason='account', wait_until=None,
                                                    payment_intent=terms['intent'], updated_at=timezone.now())

    try:
        row, created = purchases.send_pull(terms['own'], calldata, str(bridge.internal_id), claim=claim)
    except relayer.RelayError as exc:
        raise NotSent(exc.code) from exc
    if not created:
        raise NotSent('already_sent')
    return row


def abandon(bridge_pk, reason: str) -> bool:
    """Nothing was broadcast: close the order so it holds nothing, and the
    intent, so no card is ever confirmed for a request id an order used."""
    return close(bridge_pk, reason)


def close(bridge_pk, reason: str = 'pull_not_landed') -> bool:
    """contract_funding.close_unfunded for a purchase's bridge, and everything that said it was being paid:
    its intent expires, and a task the account was paying ("está pagando") ends, said to the person. True
    when the bridge is closed. Every close of a purchase-bound bridge goes through here."""
    from .models import PaymentIntent
    closed = cf.close_unfunded(bridge_pk)
    bridge = PaymentBridgeTransfer.objects.select_related('quote__money_flow').get(pk=bridge_pk)
    if not closed or bridge.status != 'expired':
        return False
    intent = PaymentIntent.objects.filter(bridge=bridge, state='submitted').first()
    if intent is not None:
        PaymentIntent.objects.filter(pk=intent.pk, state='submitted').update(
            state='expired', state_reason=reason[:40], updated_at=timezone.now())
    _end_task(bridge)
    return True


def _end_task(bridge) -> None:
    """The purchase task this bridge was paying, once the bridge is closed unfunded: stopped as unpaid, and
    the person told no money left. Only a task still saying the account is paying it."""
    from agent_tasks import notes
    from agent_tasks.models import AgentTask
    from agent_tasks.runner import close_session
    bound = bound_of(bridge)
    try:
        task_id = uuid.UUID(str(bound.get('task') or ''))
    except ValueError:
        return
    task = AgentTask.objects.filter(internal_id=task_id).first()
    if task is None:
        return
    if not AgentTask.objects.filter(pk=task.pk, state='payment_ready', reason='account').update(
            state='stopped', reason='unpaid', wait_until=None, lease=None, lease_until=None,
            updated_at=timezone.now()):
        return
    task.refresh_from_db()
    close_session(task)
    notes.post(task, notes.say(notes.ACCOUNT_NOT_PAID, task), 'end', push='check')


# --------------------------------------------------------- funding proof

def pull_problem(receipt, bridge, bound) -> tuple[dict | None, str]:
    """(proof, '') when this final receipt is the pull of exactly this
    purchase, else (None, why). Every fact is the chain's: the spender's
    Forwarded event, the account's CardPulled and the USDT transfer."""
    from smart_account import abi, purchases
    if int(receipt.get('status', '0x0'), 16) != 1:
        return None, 'pull_reverted'
    spender, contract = address(bound['spender']), address(bound['contract'])
    if address(receipt.get('to') or '0x' + '00' * 20) != spender:
        return None, 'not_a_spender_call'
    units, rule_id = int(bound['units']), int(bound['rule_id'])
    ref = '0x' + purchases.ref_for(bound['request_id']).hex()
    deposit = address(bridge.deposit_address)
    forwarded, pulled = [], []
    for log in receipt.get('logs') or []:
        if log.get('removed'):
            return None, 'log_removed'
        emitter = str(log.get('address') or '').lower()
        try:
            if emitter == spender:
                event = abi.decode_forwarded(log)
                if event is not None:
                    forwarded.append(event)
            elif emitter == contract:
                decoded = abi.decode_log(log)
                if decoded is not None and decoded[0] == 'CardPulled':
                    pulled.append(decoded[1])
        except ValueError:
            return None, 'log_unreadable'
    if len(forwarded) != 1 or len(pulled) != 1:
        return None, 'events_missing'
    event, card = forwarded[0], pulled[0]
    if (event['account'] != contract or int(event['ruleId']) != rule_id or event['to'] != deposit
            or int(event['usdtOut']) != units or event['ref'] != ref):
        return None, 'forwarded_mismatch'
    if int(card['id']) != rule_id or card['spender'] != spender or int(card['usdtOut']) != units:
        return None, 'card_pull_mismatch'
    if chain.received_units(receipt, cf.SOURCE, deposit, spender) != units:
        return None, 'transfer_mismatch'
    return {'tx': str(receipt['transactionHash']).lower(), 'units': str(units), 'account': contract,
            'rule_id': rule_id, 'to': deposit, 'ref': ref, 'gross': str(card.get('usdSpent') or '')}, ''


def prove_funding(transfer):
    """contract_funding.prove_funding for a purchase: the worker's step while
    the bridge has no proven source hash. Returns the bridge afterwards."""
    bridge = PaymentBridgeTransfer.objects.select_related('quote__money_flow', 'quote__confio_account').get(
        pk=transfer.pk)
    if bridge.source_tx_hash:
        return bridge
    bound = bound_of(bridge)
    pull = ((bridge.binding or {}).get(cf.KEY) or {}).get('pull') or {}
    now = int(time.time())
    if not pull.get('tx'):
        # The pull and its record are written together: none means none was sent.
        if bridge.status in ('submitted', 'needs_review') and now > bridge.deadline + cf.CLOSE_AFTER_SECONDS:
            close(bridge.pk)
        bridge.refresh_from_db()
        return bridge
    receipt = chain.final_receipt('BSC', pull['tx'])
    if receipt is None:
        if not may_land(bridge):
            close(bridge.pk)
        elif now > bridge.deadline + cf.REVIEW_AFTER_SECONDS:
            cf._review(bridge, 'source_confirmation_delayed', 'el pago de la compra sigue sin recibo final')
        bridge.refresh_from_db()
        return bridge
    proof, problem = pull_problem(receipt, bridge, bound)
    if problem == 'pull_reverted':
        # Mined and reverted: nothing moved, nothing can land under this hash.
        cf._remember(bridge, pull=dict(pull, reverted=True))
        close(bridge.pk)
    elif problem:
        cf._review(bridge, 'source_transfer_mismatch', f'el pago de la compra no es el aprobado ({problem})')
    else:
        cf._remember(bridge, proof=proof)
        return cf._bind(bridge.pk, proof['tx'], int(proof['units']))
    bridge.refresh_from_db()
    return bridge


def terms_problem(bridge, tx_hash: str, units) -> str:
    """'' while the proven pull is exactly this purchase's (asked before any
    conversion or payout, from what prove_funding recorded: no network)."""
    bound = bound_of(bridge)
    proof = ((bridge.binding or {}).get(cf.KEY) or {}).get('proof') or {}
    if not is_purchase_bound(bound) or not proof:
        return 'purchase_not_proven'
    if (proof.get('tx') != str(tx_hash or '').lower() or proof.get('account') != bound.get('contract')
            or int(proof.get('rule_id') or -1) != int(bound.get('rule_id') or -2)
            or proof.get('to') != address(bridge.deposit_address)
            or str(proof.get('units')) != str(bound.get('units'))
            or str(bound.get('units')) != str(bridge.quote.amount_units)
            or (units is not None and str(units) != str(bound.get('units')))):
        return 'purchase_terms_changed'
    return ''


def payee_problem(journey) -> tuple[str, bool]:
    """(why funded money may not be paid, wait instead of parking). The store's
    CLABE and order, as the person approved them, on the row being paid."""
    from .models import PayoutDestination
    if not (journey.funding_credit_id or journey.bridge.provider_credit_id):
        return '', False
    bound = bound_of(journey.bridge)
    destination = PayoutDestination.objects.filter(internal_id=bound.get('destination')).first()
    if destination is None:
        return 'payee_not_found', False
    order = (destination.provider_data or {}).get('store_order') or {}
    if (str((destination.details or {}).get('clabe') or '') != bound.get('clabe')
            or Decimal(str(order.get('amount') or 0)) != Decimal(bound.get('amount_local') or -1)
            or str(order.get('reference') or '') != bound.get('reference')
            or (journey.destination_snapshot or {}).get('destination_internal_id') != bound.get('destination')):
        return 'payee_changed', False
    return '', False


def pulled_usd(bridge) -> Decimal | None:
    """The dollars this purchase pulled, once proven."""
    proof = ((bridge.binding or {}).get(cf.KEY) or {}).get('proof') or {}
    return Decimal(int(proof['units'])) / Decimal(10 ** TOKENS[cf.SOURCE][1]) if proof.get('units') else None
