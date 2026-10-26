"""Futuros money flow (docs/designs/hyperliquid-perps.md §3–§5).

Open:   exit (cUSD/cUSD+ → USDT, 0.9%) + Relay deposit, one sponsored 7702
        batch → Relay credits the member's HyperCore account → the member
        signs updateLeverage (isolated) and an IOC order.
Close:  reduce-only IOC → the member signs Relay's nonce mapping and a
        sendAsset of the whole withdrawable balance → USDT lands on the
        member's BSC address → the ordinary entry (0.9%) as kind perps_return.

The server issues every plan (exact calldata, exact Hyperliquid actions) and
stores it in PerpPosition.flow; the app signs exactly that, and the relay
accepts only an exact match. States move on observed facts only. Confío never
signs for the member and never holds their money.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone as dt_timezone
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import hl_signing, hyperliquid, perps_relay

logger = logging.getLogger(__name__)

WAD = 10 ** 18
USDC_UNIT = Decimal(10) ** perps_relay.HL_USDC_DECIMALS
BPS = 10_000

PERPS_KINDS = ('perps_open', 'perps_bridge_retry', 'perps_return')
MIN_MARGIN_USD = Decimal('10')
FIRST_MIN_MARGIN_USD = Decimal('12')
MIN_NOTIONAL_USD = Decimal('12')
VENUE_MIN_NOTIONAL_USD = Decimal('10')
RETURN_MIN_USD = Decimal('2')
NEW_ACCOUNT_CHARGE_USD = Decimal('1.20')
# Headroom between the cUSD+ exit preview and the Relay deposit: an oracle
# accrual only raises the output, a worse fill reverts the whole batch.
PLUS_EXIT_CUSHION_BPS = 5
# Taker fee headroom when sizing an order from the credited margin.
SIZE_FEE_BUFFER_BPS = 20
SIGNATURE_CHAIN_ID = 0xa4b1  # any chain works for Hyperliquid user-signed actions
REFUND_HOLD_S = 24 * 3600


class FlowError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _d(value) -> Decimal:
    return Decimal(str(value))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _request_id(prefix: str) -> str:
    return f'{prefix}-{secrets.token_hex(12)}'


# ── shared helpers ──────────────────────────────────────────────────────

def _side_sign(side: str) -> int:
    return 1 if side == 'long' else -1


def estimate_liquidation_px(entry_px: Decimal, size: Decimal, margin: Decimal, side: str,
                            max_leverage: int) -> Decimal | None:
    """Hyperliquid's isolated liquidation price, estimated before the fill:
    liq = P - s * (M - S*P*mmr) / S / (1 - mmr*s), mmr = 1 / (2 * maxLeverage)."""
    if entry_px <= 0 or size <= 0 or max_leverage <= 0:
        return None
    s = _side_sign(side)
    mmr = Decimal(1) / (2 * max_leverage)
    available = margin - size * entry_px * mmr
    liq = entry_px - s * available / size / (1 - mmr * s)
    return liq if liq > 0 else Decimal(0)


def _round_size(size: Decimal, sz_decimals: int) -> Decimal:
    return size.quantize(Decimal(1).scaleb(-sz_decimals), rounding=ROUND_DOWN)


def wire_price(px: Decimal, sz_decimals: int, *, up: bool) -> str:
    """A price Hyperliquid accepts: ≤ 5 significant figures and ≤ 6 - szDecimals
    decimals (perps), rounded away from the fill (up for buys)."""
    if px <= 0:
        raise FlowError('price_unavailable')
    rounding = ROUND_UP if up else ROUND_DOWN
    digits = px.adjusted() + 1  # digits before the point
    sig_places = max(5 - digits, 0)
    places = min(sig_places, max(6 - sz_decimals, 0))
    q = px.quantize(Decimal(1).scaleb(-places), rounding=rounding)
    if q.adjusted() + 1 > 5:  # an integer price above 5 sig figs: integers are allowed
        q = px.quantize(Decimal(1), rounding=rounding)
    return _wire(q)


def _wire(value: Decimal) -> str:
    text = format(value.normalize(), 'f')
    return '0' if text in ('-0', '') else text


def walk_book(book: dict, is_buy: bool, size: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """(average fill, mid, worst level) for `size` against the live book.
    Raises when the book cannot fill it (thin beyond the 20 visible levels)."""
    bids, asks = book['levels']
    try:
        best_bid, best_ask = _d(bids[0]['px']), _d(asks[0]['px'])
    except (IndexError, KeyError, ArithmeticError) as exc:
        raise FlowError('book_unavailable') from exc
    mid = (best_bid + best_ask) / 2
    remaining, cost, worst = size, Decimal(0), mid
    for level in (asks if is_buy else bids):
        px, sz = _d(level['px']), _d(level['sz'])
        take = min(remaining, sz)
        cost += take * px
        remaining -= take
        worst = px
        if remaining <= 0:
            break
    if remaining > 0:
        raise FlowError('market_too_thin')
    return cost / size, mid, worst


def impact_bps(avg: Decimal, mid: Decimal) -> int:
    if mid <= 0:
        return BPS
    return int(abs(avg - mid) / mid * BPS)


def _market_for(coin: str):
    from . import perps_catalog

    market = perps_catalog.by_coin(coin)
    if market is None:
        raise FlowError('market_not_listed')
    return market


def _position(user, position_id):
    from blockchain.models import PerpPosition

    try:
        return PerpPosition.objects.select_related('market').get(pk=int(position_id), user=user)
    except (PerpPosition.DoesNotExist, TypeError, ValueError) as exc:
        raise FlowError('position_not_found') from exc


def _save_flow(position, **changes):
    flow = dict(position.flow or {})
    flow.update(changes)
    position.flow = flow
    return flow


def _merge_flow(position_pk, **changes) -> dict:
    """Locked read-modify-write of a position's flow: merge `changes` into
    the CURRENT flow, never a stale snapshot (concurrent writers keep each
    other's keys)."""
    from blockchain.models import PerpPosition

    with transaction.atomic():
        row = PerpPosition.objects.select_for_update().get(pk=position_pk)
        flow = dict(row.flow or {})
        flow.update(changes)
        PerpPosition.objects.filter(pk=position_pk).update(flow=flow, updated_at=timezone.now())
        return flow


# ── open: quote + the exact BSC batch ───────────────────────────────────

def _dollar_for(user, meta) -> int:
    from .crypto_policy import DOLLAR, DOLLAR_PLUS
    from .eligibility import ONDO_POLICY

    return DOLLAR_PLUS if ONDO_POLICY.evaluate(user, meta or {}).allowed else DOLLAR


def _exit_call(dollar: int, wallet: str, margin_wei: int) -> tuple[dict, int, int]:
    """(call, gross USDT, deposit USDT) for leaving `margin_wei` of Confío dollars."""
    from eth_abi import encode as abi_encode

    from . import sponsor_7702, vault
    from .crypto_policy import DOLLAR, expected_exit_usdt

    if dollar == DOLLAR:
        cusd = (getattr(settings, 'CUSD_VAULT_ADDRESS', '') or '').lower()
        if not cusd:
            raise FlowError('cusd_not_configured')
        if vault.erc20_balance_raw(cusd, wallet) < margin_wei:
            raise FlowError('insufficient_funds')
        amount_in = margin_wei
        gross, net = expected_exit_usdt(dollar, amount_in)
        deposit = net
        selector, target = sponsor_7702.SEL_CUSD_REDEEM, cusd
    else:
        target = vault.vault_address()
        if not target:
            raise FlowError('vault_not_configured')
        pps = vault.p_plus_wad(fresh=True)
        if pps <= 0:
            raise FlowError('price_unavailable')
        amount_in = (margin_wei * WAD + pps - 1) // pps + 2
        if vault.erc20_balance_raw(target, wallet) < amount_in:
            raise FlowError('insufficient_funds')
        gross, net = expected_exit_usdt(dollar, amount_in)
        deposit = net * (BPS - PLUS_EXIT_CUSHION_BPS) // BPS
        selector = sponsor_7702.SEL_REDEEM_TO_USDT
    if deposit <= 0:
        raise FlowError('amount_too_small')
    data = '0x' + selector + abi_encode(['uint256', 'uint256', 'address'], [amount_in, deposit, wallet]).hex()
    return {'to': target.lower(), 'value': '0', 'data': data}, gross, deposit


def _approve_call(spender: str, amount: int) -> dict:
    from eth_abi import encode as abi_encode

    from . import sponsor_7702

    return {'to': perps_relay.BSC_USDT, 'value': '0',
            'data': '0x' + sponsor_7702.SEL_APPROVE + abi_encode(['address', 'uint256'], [spender, amount]).hex()}


def _bridge_out(wallet: str, deposit: int) -> tuple[dict, list, dict]:
    """(facts kept on the position, the calls, Relay's raw signed quote). The
    raw quote goes to the app, which authenticates the order (its id is the
    hash of its terms, signed by Relay's solver) before signing the deposit."""
    quote = perps_relay.quote_open(wallet, deposit)
    calls = [_approve_call(quote['depository'], deposit),
             {'to': quote['depository'], 'value': '0', 'data': quote['deposit_data']}]
    facts = {k: quote[k] for k in ('request_id', 'order_id', 'depository', 'expected_out',
                                    'minimum_out', 'deadline', 'time_estimate_s')}
    return facts, calls, quote['raw']


def _costs(margin: Decimal, gross: int, deposit: int, relay: dict, new_account: bool,
           leverage: int, taker_rate: Decimal) -> dict:
    gross_usd = Decimal(gross) / WAD
    deposit_usd = Decimal(deposit) / WAD
    credited = Decimal(relay['expected_out']) / USDC_UNIT
    activation = NEW_ACCOUNT_CHARGE_USD if new_account else Decimal(0)
    bridge = max(deposit_usd - credited - activation, Decimal(0))
    notional = credited * leverage
    return {
        'margin_usd': str(margin),
        'exit_fee_usd': str((gross_usd - (Decimal(deposit) / WAD)).quantize(Decimal('0.000001'))),
        'bridge_cost_usd': str(bridge.quantize(Decimal('0.000001'))),
        'activation_usd': str(activation),
        'credited_usd': str(credited.quantize(Decimal('0.000001'))),
        'notional_usd': str(notional.quantize(Decimal('0.01'))),
        'open_fee_usd': str((notional * taker_rate).quantize(Decimal('0.000001'))),
    }


def _new_account(wallet: str) -> bool:
    try:
        return hyperliquid.user_role(wallet) == 'missing'
    except hyperliquid.HyperliquidError as exc:
        raise FlowError('hyperliquid_unavailable') from exc


# ── per-position accounting ─────────────────────────────────────────────
#
# A member's HyperCore account has ONE withdrawable balance, shared by
# everything that is not an open position's isolated margin. So nothing
# here ever reads "the whole balance" as one position's money:
#   - an open is credited exactly what ITS Relay order delivered (the
#     member's Hyperliquid ledger entry for Relay's transfer hash);
#   - a margin top-up likewise;
#   - a return sends exactly that position's settled equity (credited +
#     realized P&L − venue fees + funding, from its own fills).
# Money arriving for an open (bridging / funded) is still serialized per
# member, so two deposits can never be told apart only by their timing.

ARRIVING_STATES = ('bridging', 'funded', 'refunded')
RETURNABLE_STATES = ('closed', 'liquidated', 'funded', 'return_failed')
PLAN_TTL_MS = 10 * 60 * 1000
RETRYABLE_BATCH_STATUSES = ('noop_failed', 'failed', 'dropped')
# 'reorged': orphaned with no receipt (cusd_plus/tasks.py); an entry is then
# re-issued for the USDT actually on hand, so it can never mint twice.
DEAD_BATCH_STATUSES = ('reverted', 'noop_failed', 'failed', 'dropped', 'reorged')
CREDIT_FALLBACK_S = 30 * 60
RETURN_RESEND_S = 90


def _wallet_lock(wallet: str) -> None:
    """Serialize this member's money movements (transaction-scoped)."""
    from django.db import connection

    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [f'perps:{wallet.lower()}'])


def wallet_busy(wallet: str, exclude_position=None, exclude_change=None):
    """The position with money arriving for an open or a top-up, or None."""
    from blockchain.models import PerpMarginChange, PerpPosition

    rows = PerpPosition.objects.filter(wallet=wallet, state__in=ARRIVING_STATES)
    if exclude_position is not None:
        rows = rows.exclude(pk=exclude_position)
    busy = rows.select_related('market').order_by('created_at').first()
    if busy is not None:
        return busy
    changes = PerpMarginChange.objects.filter(position__wallet=wallet, state__in=('bridging', 'funded'))
    if exclude_change is not None:
        changes = changes.exclude(pk=exclude_change)
    change = changes.select_related('position__market').first()
    return change.position if change is not None else None


def _transition(model, pk, from_states, match: dict | None = None, **fields) -> bool:
    """Compare-and-set: apply `fields` only if the row is still in one of
    `from_states` (and still matches `match`, e.g. the version a reconciler
    read), so a stale reader never overwrites a newer step."""
    from django.db.models import Q

    fields.setdefault('updated_at', timezone.now())
    return bool(model.objects.filter(Q(pk=pk), Q(state__in=from_states), **(match or {})).update(**fields))


def _cancel_quotes(wallet: str) -> None:
    from blockchain.models import PerpMarginChange, PerpPosition

    now = timezone.now()
    PerpPosition.objects.filter(wallet=wallet, state='quoted').update(state='cancelled', updated_at=now)
    PerpMarginChange.objects.filter(position__wallet=wallet, state='quoted').update(state='cancelled', updated_at=now)


@transaction.atomic
def prepare_open(user, wallet: str, meta, coin: str, side: str, leverage: int, margin_usd) -> dict:
    """Quote an open and issue its exact batch. Creates PerpPosition(quoted)."""
    from blockchain.models import PerpPosition

    from . import perps_catalog, perps_risk

    refusal = perps_risk.open_gate(user, meta)
    if refusal:
        raise FlowError(refusal)
    wallet = (wallet or '').lower()
    if not wallet:
        raise FlowError('no_bsc_address')
    if side not in ('long', 'short'):
        raise FlowError('bad_side')
    market = _market_for(coin)
    if not perps_catalog.is_openable(market):
        raise FlowError('market_not_openable')
    if not isinstance(leverage, int) or not 1 <= leverage <= market.max_leverage:
        raise FlowError('bad_leverage')
    try:
        margin = _d(margin_usd).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    except ArithmeticError as exc:
        raise FlowError('bad_amount') from exc
    _wallet_lock(wallet)
    # One quote at a time per member: a new one replaces any unsigned one.
    _cancel_quotes(wallet)
    # One live position per member: everything free on the member's
    # Hyperliquid account then belongs to exactly one position.
    live = (PerpPosition.objects.filter(wallet=wallet).exclude(state__in=PerpPosition.TERMINAL_STATES)
            .exclude(state='quoted').select_related('market').first())
    if live is not None:
        raise FlowError('position_exists' if live.market_id == market.id else 'one_position_at_a_time')
    new_account = _new_account(wallet)
    minimum = FIRST_MIN_MARGIN_USD if new_account else MIN_MARGIN_USD
    if margin < minimum:
        raise FlowError('margin_too_small')

    dollar = _dollar_for(user, meta)
    exit_call, gross, deposit = _exit_call(dollar, wallet, int(margin * WAD))
    relay, bridge_calls, relay_raw = _bridge_out(wallet, deposit)
    credited = Decimal(relay['minimum_out']) / USDC_UNIT
    if credited * leverage < MIN_NOTIONAL_USD:
        raise FlowError('notional_too_small')
    calls = [exit_call] + bridge_calls
    request_id = _request_id('perps-open')
    costs = _costs(margin, gross, deposit, relay, new_account, leverage, market.taker_fee_rate)
    position = PerpPosition.objects.create(
        user=user, wallet=wallet, market=market, side=side, leverage=leverage,
        margin_usd=margin, state='quoted',
        flow={'dollar': dollar, 'gross_wei': str(gross), 'deposit_wei': str(deposit),
              'relay_out': relay, 'calls': calls, 'request_id': request_id,
              'new_account': new_account, 'costs': costs},
        relay_out_id=relay['request_id'],
    )
    return {'position': position, 'calls': calls, 'request_id': request_id, 'kind': 'perps_open', 'relay_quote': relay_raw,
            'costs': costs, 'deadline': relay['deadline']}


@transaction.atomic
def prepare_bridge_retry(user, position_id) -> dict:
    """Re-bridge the USDT Relay refunded to the member: the same open, so no
    second exit (and no second fee). Never more than that open deposited."""
    from blockchain.models import PerpPosition

    from . import perps_risk, vault

    position = _locked(user, position_id)
    if position.state != 'refunded':
        raise FlowError('bad_state')
    if perps_risk.exit_gate():
        raise FlowError('trade_not_available')
    on_hand = vault.usdt_balance_raw(position.wallet, fresh=True)
    refunded = int((position.flow or {}).get('refund_wei') or (position.flow or {}).get('deposit_wei') or 0)
    deposit = min(refunded, on_hand)
    if deposit <= 0:
        raise FlowError('nothing_to_bridge')
    relay, calls, relay_raw = _bridge_out(position.wallet, deposit)
    request_id = _request_id('perps-retry')
    _save_flow(position, retry={'relay_out': relay, 'calls': calls, 'request_id': request_id,
                                'deposit_wei': str(deposit)})
    PerpPosition.objects.filter(pk=position.pk).update(flow=position.flow, relay_out_id=relay['request_id'],
                                                       updated_at=timezone.now())
    return {'position': position, 'calls': calls, 'request_id': request_id, 'kind': 'perps_bridge_retry',
            'relay_quote': relay_raw,
            'deadline': relay['deadline']}


@transaction.atomic
def release_refund(user, position_id) -> None:
    """The member keeps the refunded USDT: it goes back to Confío dollars
    through the ordinary sweep (the entry fee applies, like any return)."""
    from blockchain.models import PerpPosition

    position = _locked(user, position_id)
    if not _transition(PerpPosition, position.pk, ('refunded',), state='cancelled'):
        raise FlowError('bad_state')


@transaction.atomic
def prepare_margin_add(user, wallet: str, meta, position_id, amount_usd) -> dict:
    from blockchain.models import PerpMarginChange

    from . import perps_risk

    refusal = perps_risk.open_gate(user, meta)
    if refusal:
        raise FlowError(refusal)
    position = _locked(user, position_id)
    if position.state != 'open':
        raise FlowError('bad_state')
    try:
        amount = _d(amount_usd).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    except ArithmeticError as exc:
        raise FlowError('bad_amount') from exc
    if amount < RETURN_MIN_USD:
        raise FlowError('margin_too_small')
    _wallet_lock(position.wallet)
    _cancel_quotes(position.wallet)
    if wallet_busy(position.wallet) is not None:
        raise FlowError('finish_pending_first')
    dollar = _dollar_for(user, meta)
    exit_call, gross, deposit = _exit_call(dollar, position.wallet, int(amount * WAD))
    relay, bridge_calls, relay_raw = _bridge_out(position.wallet, deposit)
    calls = [exit_call] + bridge_calls
    request_id = _request_id('perps-add')
    change = PerpMarginChange.objects.create(
        position=position, direction='add', amount_usd=amount, state='quoted', relay_id=relay['request_id'],
        flow={'dollar': dollar, 'gross_wei': str(gross), 'deposit_wei': str(deposit), 'relay_out': relay,
              'calls': calls, 'request_id': request_id},
    )
    return {'position': position, 'change': change, 'calls': calls, 'request_id': request_id,
            'kind': 'perps_open', 'deadline': relay['deadline'], 'relay_quote': relay_raw,
            'costs': _costs(amount, gross, deposit, relay, False, position.leverage, position.market.taker_fee_rate)}


def _locked(user, position_id):
    from blockchain.models import PerpPosition

    try:
        return PerpPosition.objects.select_for_update().select_related('market').get(pk=int(position_id), user=user)
    except (PerpPosition.DoesNotExist, TypeError, ValueError) as exc:
        raise FlowError('position_not_found') from exc


# ── relay policy hooks (cusd_plus/sponsor_7702.py, cusd_plus/schema.py) ──

def has_relay_deposit(calls: list) -> bool:
    depository = perps_relay.bsc_depository()
    return any(c.get('to') == depository for c in calls)


def classify(calls: list) -> str | None:
    """The batch kind for a Relay-deposit batch (the app derives the same)."""
    from . import sponsor_7702

    if not has_relay_deposit(calls):
        return None
    selectors = {c['data'][2:10].lower() for c in calls}
    exits = {sponsor_7702.SEL_CUSD_REDEEM, sponsor_7702.SEL_REDEEM_TO_USDT}
    return 'perps_open' if selectors & exits else 'perps_bridge_retry'


def base_request_id(request_id: str) -> str:
    """The app's batch helper suffixes each attempt (`_a0`, `_a1`)."""
    return re.sub(r'_a\d+$', '', request_id or '')


def _deposit_order_id(calls: list, user_addr: str) -> str:
    from .sponsor_7702 import PolicyError

    depository = perps_relay.bsc_depository()
    deposits = [c for c in calls if c['to'] == depository]
    if len(deposits) != 1:
        raise PolicyError('bad_perps_batch')
    try:
        depositor, token, _amount, order_id = perps_relay.decode_deposit(deposits[0]['data'])
    except perps_relay.RelayError as exc:
        raise PolicyError('bad_perps_batch') from exc
    if depositor != user_addr.lower() or token != perps_relay.BSC_USDT:
        raise PolicyError('bad_perps_batch')
    return order_id


def _issued_record(user, user_addr: str, order_id: str, *, lock: bool = True):
    """(record, its issued plan) for the Relay order this batch funds: an
    open still quoted, a refund being re-bridged, or a margin top-up."""
    from blockchain.models import PerpMarginChange, PerpPosition

    positions = PerpPosition.objects.filter(user=user, wallet=user_addr, state__in=('quoted', 'refunded'))
    changes = PerpMarginChange.objects.filter(position__user=user, position__wallet=user_addr, state='quoted',
                                              position__state='open')
    if lock:
        positions, changes = positions.select_for_update(), changes.select_for_update()
    for row in positions.order_by('-id'):
        flow = row.flow or {}
        if row.state == 'quoted' and (flow.get('relay_out') or {}).get('order_id') == order_id:
            return row, flow
        retry = flow.get('retry') or {}
        if row.state == 'refunded' and (retry.get('relay_out') or {}).get('order_id') == order_id:
            return row, retry
    for change in changes:
        flow = change.flow or {}
        if (flow.get('relay_out') or {}).get('order_id') == order_id:
            return change, flow
    return None, None


def recorded_batch(user, calls: list, request_id: str):
    """A batch already signed and recorded with exactly these calls (a
    replay whose answer was lost): it must reach the existing-batch lookup,
    which returns its transaction, never a definitive rejection."""
    from blockchain.models import PERPS_BATCH_KINDS, SponsoredBatch

    if not request_id:
        return None
    rows = SponsoredBatch.objects.filter(user=user, kind__in=PERPS_BATCH_KINDS, client_request_id=request_id)
    for batch in rows.order_by('-id')[:5]:
        try:
            if json.loads(batch.calls_json or '[]') == calls:
                return batch
        except ValueError:
            continue
    return None


def validate_batch(calls: list, user, user_addr: str) -> None:
    """A Relay-deposit batch is accepted only as the EXACT calls the server
    issued for one of this member's quotes, before the quote's deadline."""
    from .sponsor_7702 import PolicyError

    order_id = _deposit_order_id(calls, user_addr)
    with transaction.atomic():
        record, flow = _issued_record(user, user_addr.lower(), order_id)
        if record is None:
            raise PolicyError('perps_quote_not_found')
        if flow.get('calls') != calls:
            raise PolicyError('perps_batch_mismatch')
        if int((flow.get('relay_out') or {}).get('deadline', 0)) <= int(time.time()) + 30:
            raise PolicyError('perps_quote_expired')


def _entry_owner(user, request_id: str, *, lock: bool = True):
    from blockchain.models import PerpPosition

    rows = PerpPosition.objects.filter(user=user, state='landed',
                                       flow__entry__request_id=base_request_id(request_id))
    return (rows.select_for_update() if lock else rows).first()


def return_kind(kind: str, calls: list, request_id: str, user) -> str:
    """'perps_return' for the entry the server issued after a landed return;
    otherwise the classified kind unchanged."""
    from .sponsor_7702 import PolicyError

    if not request_id or not request_id.startswith('perps-ret-'):
        return kind
    with transaction.atomic():
        position = _entry_owner(user, request_id)
        if position is None or position.return_batch_id is not None \
                or (position.flow.get('entry') or {}).get('calls') != calls:
            raise PolicyError('perps_return_mismatch')
    if kind not in ('subscribe', 'mint_cusd'):
        raise PolicyError('perps_return_mismatch')
    return 'perps_return'


def link_signed(batch, _raw=None) -> None:
    """Called by send_sponsored_batch INSIDE the transaction that writes the
    signed batch, before broadcast: the position and its batch are durable
    together, or neither is (an exception here aborts the broadcast)."""
    from blockchain.models import PerpMarginChange, PerpPosition

    calls = json.loads(batch.calls_json or '[]')
    wallet = batch.user_bsc_address.lower()
    _wallet_lock(wallet)
    if batch.kind == 'perps_return':
        position = _entry_owner(batch.user, batch.client_request_id)
        if position is None or not PerpPosition.objects.filter(
                pk=position.pk, state='landed', return_batch__isnull=True).update(
                return_batch=batch, updated_at=timezone.now()):
            raise FlowError('perps_return_not_found')
        return
    order_id = _deposit_order_id(calls, wallet)
    record, _ = _issued_record(batch.user, wallet, order_id)
    if isinstance(record, PerpMarginChange):
        if wallet_busy(wallet, exclude_change=record.pk) is not None:
            raise FlowError('finish_pending_first')
        if not _transition(PerpMarginChange, record.pk, ('quoted',), batch=batch, state='bridging'):
            raise FlowError('perps_quote_not_found')
    elif isinstance(record, PerpPosition):
        if wallet_busy(wallet, exclude_position=record.pk) is not None:
            raise FlowError('finish_pending_first')
        fields = {'state': 'bridging', 'step_error': ''}
        if batch.kind == 'perps_open':
            fields['open_batch'] = batch
        else:
            flow = dict(record.flow or {})
            flow['retry'] = dict(flow.get('retry') or {}, batch_id=batch.id)
            fields['flow'] = flow
        if not _transition(PerpPosition, record.pk, ('quoted', 'refunded'), **fields):
            raise FlowError('perps_quote_not_found')
    else:
        raise FlowError('perps_quote_not_found')


def on_broadcast(batch) -> None:
    """Kept for callers that predate link_signed: linkage happens before
    broadcast now, so there is nothing left to do here."""
    return None


def _quote_deadline(record) -> int:
    flow = record.flow or {}
    retry = flow.get('retry') or {}
    relay = (retry.get('relay_out') if retry.get('batch_id') else None) or flow.get('relay_out') or {}
    return int(relay.get('deadline') or 0)


def on_receipt(batch, receipt=None) -> None:
    """Apply a perps batch's FINAL status to its position. Idempotent: every
    change is compare-and-set, so a second worker or the reconciler running
    the same batch again changes nothing."""
    from blockchain.models import PerpMarginChange, PerpPosition

    if batch.kind not in PERPS_KINDS:
        return
    ok = batch.status == 'confirmed'
    dead = batch.status in DEAD_BATCH_STATUSES
    if not ok and not dead:
        return
    with transaction.atomic():
        if batch.kind == 'perps_return':
            position = PerpPosition.objects.select_for_update().filter(return_batch=batch).first()
            if position is None:
                return
            if ok:
                net = None
                if receipt:
                    net = _history_usd(batch, receipt, 'entry')
                else:
                    row = getattr(batch, 'unified_transaction', None)
                    net = Decimal(str(row.amount)) if row is not None else None
                if _transition(PerpPosition, position.pk, ('landed',), state='done', done_at=timezone.now(),
                               returned_usd=net):
                    _fold_unapplied(position)
            else:
                # Nothing entered: issue a fresh entry next time (new request id).
                flow = dict(position.flow or {})
                flow.pop('entry', None)
                PerpPosition.objects.filter(pk=position.pk, state='landed', return_batch=batch).update(
                    return_batch=None, flow=flow, step_error='entry_reverted', updated_at=timezone.now())
            return
        change = PerpMarginChange.objects.select_for_update().filter(batch=batch).first()
        if change is not None:
            if dead:
                retryable = batch.status in RETRYABLE_BATCH_STATUSES and _quote_deadline(change) > time.time() + 60
                _transition(PerpMarginChange, change.pk, ('bridging',), state='quoted' if retryable else 'failed',
                            batch=None if retryable else batch)
            return
        if batch.kind == 'perps_open':
            position = PerpPosition.objects.select_for_update().filter(open_batch=batch).first()
            if position is None or not dead:
                return
            if batch.status in RETRYABLE_BATCH_STATUSES and _quote_deadline(position) > time.time() + 60:
                _transition(PerpPosition, position.pk, ('bridging',), state='quoted', open_batch=None)
            else:
                # Atomic batch: nothing left Confío dollars.
                _transition(PerpPosition, position.pk, ('bridging',), state='failed', step_error='open_reverted')
            return
        position = (PerpPosition.objects.select_for_update()
                    .filter(user=batch.user, flow__retry__batch_id=batch.id).first())
        if position is not None and dead:
            flow = dict(position.flow or {})
            flow['retry'] = {k: v for k, v in (flow.get('retry') or {}).items() if k != 'batch_id'}
            _transition(PerpPosition, position.pk, ('bridging',), state='refunded', flow=flow,
                        step_error='retry_reverted')


# ── history (activity ledger) ───────────────────────────────────────────

def _history_usd(batch, receipt, direction: str) -> Decimal:
    from .tasks import _cusd_fee_events

    events = [e for e in _cusd_fee_events(receipt or {}) if e['direction'] == direction]
    if len(events) != 1:
        raise ValueError(f'perps batch {batch.id} has no unique {direction} fee event')
    event = events[0]
    wei = event['gross_wei'] if direction == 'exit' else event['net_wei']
    return Decimal(wei) / WAD


def history_description(position, kind: str, margin_add: bool = False) -> str:
    from . import perps_catalog

    ticker = perps_catalog.view(position.market).ticker
    if margin_add:
        return f'Futuros: Margen extra en {ticker}'
    if kind == 'perps_open':
        side = 'Largo' if position.side == 'long' else 'Corto'
        return f'Futuros: {side} {ticker} {position.leverage}x'
    return f'Futuros: Cierre de {ticker}'


def sync_history(batch, receipt) -> None:
    """One activity row per open (dollars out, exit fee included) and per
    return (dollars in, entry fee deducted)."""
    from blockchain.models import PerpMarginChange, PerpPosition
    from users.models import Account
    from users.models_unified import UnifiedTransactionTable

    from .crypto_policy import DOLLAR_PLUS

    change = None
    if batch.kind == 'perps_open':
        position = PerpPosition.objects.filter(open_batch=batch).select_related('market').first()
        if position is None:
            change = PerpMarginChange.objects.filter(batch=batch).select_related('position__market').first()
            position = change.position if change else None
        direction = 'exit'
    else:
        position = PerpPosition.objects.filter(return_batch=batch).select_related('market').first()
        direction = 'entry'
    if position is None:
        raise ValueError(f'perps batch {batch.id} has no position')
    account = Account.objects.filter(
        bsc_address__iexact=batch.user_bsc_address, deleted_at__isnull=True,
    ).select_related('user', 'business').first()
    if account is None:
        raise ValueError('perps batch account not found')
    usd = _history_usd(batch, receipt, direction)
    if direction == 'exit':
        dollar = int(((change.flow if change else position.flow) or {}).get('dollar', 1))
    else:
        dollar = int((position.flow.get('entry') or {}).get('dollar', 1))
    token_type = 'CUSD_PLUS' if dollar == DOLLAR_PLUS else 'CUSD_BSC'
    out = direction == 'exit'
    name = account.business.name if account.business_id else (
        account.user.get_full_name() or account.user.username or '')
    venue = 'Hyperliquid'
    UnifiedTransactionTable.objects.update_or_create(
        sponsored_batch=batch,
        defaults={
            'transaction_type': 'send',
            'amount': format(usd.normalize(), 'f'),
            'token_type': token_type,
            'amount_denomination': 'USD_VALUE',
            'status': 'CONFIRMED',
            'error_message': '',
            'transaction_hash': batch.tx_hash,
            'description': history_description(position, batch.kind, margin_add=change is not None),
            'transaction_date': batch.created_at,
            'deleted_at': None,
            'sender_user': account.user if out else None,
            'sender_business': account.business if out else None,
            'sender_type': 'business' if (not out or account.business_id) else 'user',
            'sender_display_name': name if out else venue,
            'sender_phone': (getattr(account.user, 'phone_number', '') or '') if out else '',
            'sender_address': batch.user_bsc_address if out else '',
            'counterparty_user': None if out else account.user,
            'counterparty_business': None if out else account.business,
            'counterparty_type': 'business' if (out or account.business_id) else 'user',
            'counterparty_display_name': venue if out else name,
            'counterparty_phone': None,
            'counterparty_address': '' if out else batch.user_bsc_address,
            'from_address': batch.user_bsc_address if out else '',
            'to_address': '' if out else batch.user_bsc_address,
        },
    )


# ── Hyperliquid reads ───────────────────────────────────────────────────

def _withdrawable(wallet: str, dex: str) -> Decimal:
    state = hyperliquid.clearinghouse_state(wallet, dex)
    return _d(state['withdrawable'])


def _live_position(wallet: str, market) -> dict | None:
    state = hyperliquid.clearinghouse_state(wallet, market.dex)
    for entry in state['assetPositions']:
        pos = entry.get('position') or {}
        if pos.get('coin') == market.coin and _d(pos.get('szi', '0')) != 0:
            return pos
    return None


def _relay_status(request_id: str) -> dict:
    try:
        body = perps_relay.status(request_id)
    except perps_relay.RelayError:
        return {}
    return body if isinstance(body, dict) else {}


def _hl_credit(wallet: str, status: dict, since_ms: int) -> Decimal | None:
    """USDC Relay actually credited to this member on HyperCore: the
    member's own ledger entry for Relay's transfer hash (None if unseen)."""
    hashes = {h.lower() for h in status.get('txHashes') or [] if isinstance(h, str)}
    if not hashes:
        return None
    try:
        rows = hyperliquid.ledger_updates(wallet, since_ms)
    except hyperliquid.HyperliquidError:
        return None
    total, seen = Decimal(0), False
    for row in rows:
        delta = row.get('delta') if isinstance(row, dict) else None
        if not isinstance(delta, dict) or str(row.get('hash', '')).lower() not in hashes:
            continue
        if str(delta.get('destination', '')).lower() != wallet.lower():
            continue
        amount = delta.get('usdc') if delta.get('type') == 'internalTransfer' else delta.get('amount')
        try:
            total += _d(amount)
        except (ArithmeticError, TypeError, ValueError):
            return None
        seen = True
    return total if seen else None


def _delivered_usdt(status: dict, wallet: str) -> int | None:
    """USDT Relay actually delivered to the member on BSC, from the
    destination transaction's own Transfer logs (None when unreadable)."""
    from .tasks import _rpc

    transfer = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
    me = '0x' + wallet.lower().replace('0x', '').rjust(64, '0')
    total, seen = 0, False
    for tx_hash in status.get('txHashes') or []:
        if not isinstance(tx_hash, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', tx_hash):
            continue
        try:
            receipt = _rpc('eth_getTransactionReceipt', [tx_hash])
        except Exception:  # noqa: BLE001
            return None
        if not receipt or receipt.get('status') != '0x1':
            continue
        for log in receipt.get('logs') or []:
            topics = [t.lower() for t in log.get('topics') or []]
            if ((log.get('address') or '').lower() == perps_relay.BSC_USDT and len(topics) == 3
                    and topics[0] == transfer and topics[2] == me):
                total += int(log.get('data') or '0x0', 16)
                seen = True
    return total if seen else None


def _return_sent(wallet: str, nonce, since_ms: int) -> bool | None:
    """Whether the member's ledger shows the return transfer with this
    nonce (None when the ledger can't be read)."""
    try:
        rows = hyperliquid.ledger_updates(wallet, since_ms)
    except hyperliquid.HyperliquidError:
        return None
    for row in rows:
        delta = row.get('delta') if isinstance(row, dict) else None
        if (isinstance(delta, dict) and delta.get('type') == 'send' and delta.get('nonce') == nonce
                and str(delta.get('destination', '')).lower() == perps_relay.hl_depository()):
            return True
    return False


def _cloid(position_id: int, purpose: str, issued_ms: int) -> str:
    """Hyperliquid client order id (16 bytes): finds an order whose response was lost."""
    import hashlib

    return '0x' + hashlib.sha256(f'confio:{position_id}:{purpose}:{issued_ms}'.encode()).hexdigest()[:32]


def _order_status(wallet: str, cloid: str) -> dict | None:
    try:
        body = hyperliquid.info({'type': 'orderStatus', 'user': wallet, 'oid': cloid})
    except hyperliquid.HyperliquidError:
        return None
    if not isinstance(body, dict) or body.get('status') != 'order':
        return None
    return body.get('order') if isinstance(body.get('order'), dict) else None


# ── Hyperliquid plans the member signs, forwarded after policy ──────────

def _order_action(asset: int, is_buy: bool, px: str, sz: str, reduce_only: bool, cloid: str | None = None) -> dict:
    # SDK field order: msgpack hashes the dict in insertion order ('c' last).
    order = {'a': asset, 'b': is_buy, 'p': px, 's': sz, 'r': reduce_only, 't': {'limit': {'tif': 'Ioc'}}}
    if cloid:
        order['c'] = cloid
    return {'type': 'order', 'orders': [order], 'grouping': 'na'}


def _impact_limits() -> tuple[int, int, int]:
    return (int(getattr(settings, 'PERPS_IMPACT_WARN_BPS', 100)),
            int(getattr(settings, 'PERPS_IMPACT_MAX_BPS', 300)),
            int(getattr(settings, 'PERPS_SLIPPAGE_BPS', 50)))


def _plan_order(market, is_buy: bool, size: Decimal, reduce_only: bool, cloid: str | None = None) -> dict:
    book = hyperliquid.l2_book(market.coin)
    warn, cap, slip = _impact_limits()
    try:
        avg, mid, _ = walk_book(book, is_buy, size)
    except FlowError as exc:
        if not reduce_only or exc.code != 'market_too_thin':
            raise
        # A close is never refused: an IOC at the deepest visible level fills
        # what the book holds and leaves the rest open to close again.
        levels = book['levels'][1 if is_buy else 0]
        bids, asks = book['levels']
        mid = (_d(bids[0]['px']) + _d(asks[0]['px'])) / 2
        avg = _d(levels[-1]['px'])
    impact = impact_bps(avg, mid)
    bound = avg * (BPS + slip) / BPS if is_buy else avg * (BPS - slip) / BPS
    px = wire_price(bound, market.sz_decimals, up=is_buy)
    return {'action': _order_action(market.asset_id, is_buy, px, _wire(size), reduce_only, cloid),
            'avg_px': str(avg), 'mid_px': str(mid), 'impact_bps': impact,
            'impact_warn': impact > warn, 'impact_blocked': (not reduce_only) and impact > cap}


def _user_action(kind: str, **fields) -> dict:
    """A user-signed action, nonce left for the signer (SDK field order)."""
    return {'type': kind, 'signatureChainId': hex(SIGNATURE_CHAIN_ID), 'hyperliquidChain': hl_signing.MAINNET,
            **fields, 'nonce': None}


def _send_asset(wallet: str, source_dex: str, destination_dex: str, amount: Decimal, destination=None) -> dict:
    return _user_action('sendAsset', destination=destination or wallet, sourceDex=source_dex,
                        destinationDex=destination_dex, token=perps_relay.HL_USDC_TOKEN,
                        amount=_wire(amount.quantize(Decimal('0.000001'), rounding=ROUND_DOWN)),
                        fromSubAccount='')


RECONCILED_PLANS = ('open_plan', 'margin_plan')


def _store_plan(position, name: str, steps: list, **extra) -> None:
    """Issue a plan (merged into the current flow under lock). A plan with
    a step being sent right now is never replaced underneath it."""
    from blockchain.models import PerpPosition

    with transaction.atomic():
        row = PerpPosition.objects.select_for_update().get(pk=position.pk)
        flow = dict(row.flow or {})
        current = flow.get(name) or {}
        for claim in (current.get('claims') or {}).values():
            if claim.get('status') == 'sending' and _now_ms() - int(claim.get('at') or 0) < 120_000:
                raise FlowError('step_in_flight')
            if name in RECONCILED_PLANS and claim.get('status') in ('sending', 'unconfirmed'):
                # Money-moving steps with a reconciler (an open's order, a
                # top-up): an unresolved claim is resolved there, at any age,
                # never replaced by a plan that could execute it a second time.
                raise FlowError('step_unconfirmed')
        flow[name] = {'steps': steps, 'consumed': [], 'claims': {}, 'issued_ms': _now_ms(), **extra}
        PerpPosition.objects.filter(pk=position.pk).update(flow=flow, updated_at=timezone.now())
    position.flow = flow


def _pending_claim(position, name: str) -> bool:
    """A step of this plan is being sent or was sent with no answer."""
    plan = (position.flow or {}).get(name) or {}
    return any(c.get('status') in ('sending', 'unconfirmed') for c in (plan.get('claims') or {}).values())


def _open_in_flight(position) -> bool:
    """A step of the open is being sent (or its answer was lost) while the
    open is still pending: an order may fill, a dex transfer may move the
    money the return would read. The reconciler releases a stale one
    (_release_lost_open), so it never blocks the return for long. Once the
    position is open, an old claim is history."""
    return position.state == 'funded' and _pending_claim(position, 'open_plan')


def _pending_claim_index(position, name: str) -> int | None:
    plan = (position.flow or {}).get(name) or {}
    for index, claim in (plan.get('claims') or {}).items():
        if claim.get('status') in ('sending', 'unconfirmed'):
            return int(index)
    return None


def _open_policy(user, meta, market) -> None:
    """Opening is checked against the policy as it is now (switches, country,
    the market itself), not as it was when the money left: the return path
    never depends on it."""
    from . import perps_catalog, perps_risk

    refusal = perps_risk.open_gate(user, meta)
    if refusal:
        raise FlowError(refusal)
    if not perps_catalog.is_openable(market):
        raise FlowError('market_not_openable')


def open_plan(user, position_id, meta=None) -> dict:
    """The Hyperliquid steps that turn a funded position into an open one."""
    from blockchain.models import PerpPosition

    position = _position(user, position_id)
    if position.state != 'funded':
        raise FlowError('bad_state')
    _open_policy(user, meta, position.market)
    market, wallet = position.market, position.wallet
    credited = Decimal(position.credited_usdc or 0)
    if credited <= 0:
        raise FlowError('not_funded')
    steps = []
    try:
        # An order sent before may have filled with its answer lost.
        if _filled_cloid(position):
            reconcile_position(position)
            raise FlowError('already_open')
        if _live_position(wallet, market) is not None:
            reconcile_position(position)
            raise FlowError('already_open')
        if (hyperliquid.user_abstraction(wallet) != 'disabled'
                and not (position.flow or {}).get('done_abstraction')):
            # Standard mode first: separate core and per-dex balances, the
            # model this flow is built on (unified mode waits for a canary).
            steps.append({'purpose': 'abstraction',
                          'action': _user_action('userSetAbstraction', user=wallet, abstraction='disabled')})
            _store_plan(position, 'open_plan', steps)
            return {'position': position, 'steps': steps, 'replan': True, 'impact_bps': 0,
                    'impact_warn': False, 'avg_px': None, 'size': None, 'liquidation_px': None}
        if market.dex:
            # What is already on the dex counts (a transfer whose answer was lost).
            need = credited - _withdrawable(wallet, market.dex)
            if need > Decimal('0.000001'):
                core = _withdrawable(wallet, '')
                if core < need * Decimal('0.999'):
                    raise FlowError('not_funded')
                steps.append({'purpose': 'fund_dex', 'action': _send_asset(wallet, '', market.dex, min(need, core))})
        else:
            if _withdrawable(wallet, '') < credited * Decimal('0.999'):
                raise FlowError('not_funded')
        setting = (hyperliquid.info({'type': 'activeAssetData', 'user': wallet, 'coin': market.coin}) or {}).get('leverage')
        if not isinstance(setting, dict):
            raise FlowError('hyperliquid_unavailable')
        if not (setting.get('type') == 'isolated' and int(setting.get('value') or 0) == position.leverage):
            # Only a real change is signed: a no-op update would let a withheld
            # signature pass as "the setting is already live" (the app relies on it).
            steps.append({'purpose': 'leverage', 'action': {
                'type': 'updateLeverage', 'asset': market.asset_id, 'isCross': False, 'leverage': position.leverage}})
        is_buy = position.side == 'long'
        book = hyperliquid.l2_book(market.coin)
        _, mid, _ = walk_book(book, is_buy, Decimal('0.00000001'))
        # Hyperliquid margins the order at its MARK price and takes the taker
        # fee from the same balance: size so both fit what was credited, at
        # the dearer of mid and mark plus the slippage the order may pay.
        meta, ctxs = hyperliquid.meta_and_asset_ctxs(market.dex)
        index = next((i for i, u in enumerate(meta.get('universe') or []) if u.get('name') == market.coin), None)
        mark = _d((ctxs[index] or {}).get('markPx') or '0') if index is not None and index < len(ctxs) else Decimal(0)
        if mark <= 0:
            raise FlowError('hyperliquid_unavailable')
        _warn, _cap, slip = _impact_limits()
        price = max(mid, mark) * (BPS + slip) / BPS
        per_unit = price / position.leverage + price * _d(market.taker_fee_rate)
        size = _round_size(credited * (BPS - SIZE_FEE_BUFFER_BPS) / BPS / per_unit, market.sz_decimals)
        if size <= 0 or size * mid < VENUE_MIN_NOTIONAL_USD:
            raise FlowError('notional_too_small')
        issued = _now_ms()
        order = _plan_order(market, is_buy, size, False, cloid=_cloid(position.pk, 'open', issued))
    except hyperliquid.HyperliquidError as exc:
        raise FlowError('hyperliquid_unavailable') from exc
    if order['impact_blocked']:
        raise FlowError('impact_too_high')
    steps.append({'purpose': 'open_order', 'action': order['action']})
    liq = estimate_liquidation_px(_d(order['avg_px']), size, credited, position.side, market.max_leverage)
    _store_plan(position, 'open_plan', steps, credited_usd=str(credited))
    return {'position': position, 'steps': steps, 'replan': False, 'impact_bps': order['impact_bps'],
            'impact_warn': order['impact_warn'], 'avg_px': order['avg_px'], 'size': str(size),
            'liquidation_px': str(liq) if liq is not None else None}


def close_plan(user, position_id) -> dict:
    position = _position(user, position_id)
    if position.state != 'open':
        raise FlowError('bad_state')
    market = position.market
    try:
        live = _live_position(position.wallet, market)
        if live is None:
            reconcile_position(position)
            raise FlowError('position_already_closed')
        szi = _d(live['szi'])
        # A client order id on the close too: the app ties every signed
        # order to one nonce record, so a withheld close can never execute
        # alongside a later open.
        order = _plan_order(market, szi < 0, abs(szi), True, cloid=_cloid(position.pk, 'close', _now_ms()))
    except hyperliquid.HyperliquidError as exc:
        raise FlowError('hyperliquid_unavailable') from exc
    steps = [{'purpose': 'close_order', 'action': order['action']}]
    _store_plan(position, 'close_plan', steps)
    return {'position': position, 'steps': steps, 'impact_bps': order['impact_bps'],
            'impact_warn': order['impact_warn'], 'avg_px': order['avg_px'], 'size': str(abs(szi))}


def protections(position) -> list:
    """The position's live take-profit / stop-loss trigger orders on the venue."""
    market = position.market
    return [o for o in hyperliquid.frontend_open_orders(position.wallet, market.dex)
            if o.get('coin') == market.coin and o.get('isTrigger') and o.get('reduceOnly') and o.get('oid') is not None]


def tpsl_plan(user, position_id, take_profit_px, stop_loss_px) -> dict:
    """Native Hyperliquid trigger orders on the whole position (reduce-only)."""
    position = _position(user, position_id)
    if position.state != 'open':
        raise FlowError('bad_state')
    market = position.market
    try:
        live = _live_position(position.wallet, market)
    except hyperliquid.HyperliquidError as exc:
        raise FlowError('hyperliquid_unavailable') from exc
    if live is None:
        raise FlowError('position_already_closed')
    szi = _d(live['szi'])
    close_is_buy = szi < 0
    long = szi > 0
    try:
        # Judged against the market now, not the entry: a stop may lock in profit.
        _, reference, _ = walk_book(hyperliquid.l2_book(market.coin), not long, Decimal('0.00000001'))
    except hyperliquid.HyperliquidError as exc:
        raise FlowError('hyperliquid_unavailable') from exc
    orders = []
    for px, kind in ((take_profit_px, 'tp'), (stop_loss_px, 'sl')):
        if px in (None, ''):
            continue
        try:
            trigger = _d(px)
        except ArithmeticError as exc:
            raise FlowError('bad_price') from exc
        if not trigger.is_finite() or trigger <= 0:
            raise FlowError('bad_price')
        wire = wire_price(trigger, market.sz_decimals, up=close_is_buy)
        above = _d(wire) > reference
        # Take-profit above the market for a long, below for a short; stop-loss the reverse.
        if _d(wire) == reference or (kind == 'tp') != (above == long):
            raise FlowError('bad_trigger_side')
        # A client order id on each trigger: the app ties every protection
        # signature to one nonce record, so a withheld old trigger can never
        # execute after its replacement.
        orders.append({'a': market.asset_id, 'b': close_is_buy, 'p': wire, 's': _wire(abs(szi)), 'r': True,
                       't': {'trigger': {'isMarket': True, 'triggerPx': wire, 'tpsl': kind}},
                       'c': _cloid(position.pk, f'tpsl-{kind}', _now_ms())})
    if not orders:
        raise FlowError('nothing_to_set')
    try:
        existing = protections(position)
    except hyperliquid.HyperliquidError as exc:
        raise FlowError('hyperliquid_unavailable') from exc
    # The new triggers first, the old ones cancelled after: a failure in
    # between leaves extra protection, never none.
    steps = [{'purpose': 'tpsl', 'action': {'type': 'order', 'orders': orders, 'grouping': 'positionTpsl'}}]
    if existing:
        steps.append({'purpose': 'tpsl_cancel', 'action': {'type': 'cancel', 'cancels': [
            {'a': market.asset_id, 'o': int(o['oid'])} for o in existing]}})
    _store_plan(position, 'tpsl_plan', steps)
    return {'position': position, 'steps': steps}


def margin_plan(user, position_id) -> dict:
    """Put a funded margin top-up into the open position's isolated margin:
    exactly what that top-up's own Relay order credited."""
    position = _position(user, position_id)
    if position.state != 'open':
        raise FlowError('bad_state')
    change = position.margin_changes.filter(direction='add', state='funded').order_by('id').first()
    if change is None:
        raise FlowError('nothing_to_add')
    if _pending_claim(position, 'margin_plan'):
        reconcile_position(position)
        raise FlowError('step_unconfirmed')
    credited = _d((change.flow or {}).get('credited') or '0').quantize(Decimal('0.000001'), rounding=ROUND_DOWN)
    if credited <= 0:
        raise FlowError('not_funded')
    market, wallet = position.market, position.wallet
    try:
        live = _live_position(wallet, market)
        if live is None:
            raise FlowError('position_already_closed')
        raw_before = str(((live.get('leverage') or {}).get('rawUsd')) or '')
        steps = []
        if market.dex:
            need = credited - _withdrawable(wallet, market.dex)
            if need > Decimal('0.000001'):
                core = _withdrawable(wallet, '')
                if core < need * Decimal('0.999'):
                    raise FlowError('not_funded')
                steps.append({'purpose': 'margin_fund_dex', 'action': _send_asset(wallet, '', market.dex, min(need, core))})
    except hyperliquid.HyperliquidError as exc:
        raise FlowError('hyperliquid_unavailable') from exc
    # updateIsolatedMargin: ntli in 6-decimal USD integers, isBuy True.
    steps.append({'purpose': 'margin_add', 'action': {
        'type': 'updateIsolatedMargin', 'asset': market.asset_id, 'isBuy': True,
        'ntli': int(credited * 1_000_000)}})
    _store_plan(position, 'margin_plan', steps, change_id=change.id, raw_before=raw_before)
    return {'position': position, 'steps': steps}


PLAN_OF_PURPOSE = {
    'abstraction': 'open_plan', 'fund_dex': 'open_plan', 'leverage': 'open_plan', 'open_order': 'open_plan',
    'close_order': 'close_plan', 'tpsl_cancel': 'tpsl_plan', 'tpsl': 'tpsl_plan',
    'margin_fund_dex': 'margin_plan', 'margin_add': 'margin_plan',
    'return_dex': 'return_plan',
}


OPEN_PURPOSES = ('abstraction', 'fund_dex', 'leverage', 'open_order')
# Inside Hyperliquid's own window (nonces up to 2 days old are accepted).
OPEN_NONCE_MAX_AGE_MS = 46 * 3600 * 1000


def _return_quoted(flow: dict) -> bool:
    return int(((flow or {}).get('return_relay') or {}).get('deadline') or 0) > time.time()


def _claim_step(position_id, purpose: str, action: dict, nonce: int,
                required: tuple = ()) -> tuple[str, int, dict]:
    """Atomically claim the issued, unconsumed, unexpired step this signed
    action is, BEFORE it is sent: steps go in order and each is sent once.
    State and the open/return exclusion are re-checked under the same lock."""
    from blockchain.models import PerpPosition

    name = PLAN_OF_PURPOSE.get(purpose)
    with transaction.atomic():
        position = PerpPosition.objects.select_for_update().get(pk=position_id)
        if required and position.state not in required:
            raise FlowError('bad_state')
        if purpose in OPEN_PURPOSES and _return_quoted(position.flow):
            raise FlowError('return_in_progress')
        flow = dict(position.flow or {})
        plan = dict(flow.get(name) or {})
        if not plan or _now_ms() - int(plan.get('issued_ms') or 0) > PLAN_TTL_MS:
            raise FlowError('plan_expired')
        consumed = set(plan.get('consumed') or [])
        claims = dict(plan.get('claims') or {})
        for index, step in enumerate(plan.get('steps') or []):
            if index in consumed:
                continue
            if step['purpose'] != purpose:
                # An earlier step is still pending: this one may not jump the queue.
                raise FlowError('step_out_of_order')
            want = dict(step['action'])
            if 'nonce' in want:
                want['nonce'] = nonce
            if want != action:
                raise FlowError('action_mismatch')
            if str(index) in claims:
                raise FlowError('step_in_flight')
            orders = action.get('orders') or [{}]
            claims[str(index)] = {'status': 'sending', 'at': _now_ms(), 'cloid': orders[0].get('c')}
            plan['claims'] = claims
            flow[name] = plan
            if purpose == 'open_order' and orders[0].get('c'):
                # Kept for good: finds the order even after its claim settles.
                flow['open_cloids'] = list(flow.get('open_cloids') or []) + [orders[0]['c']]
            PerpPosition.objects.filter(pk=position_id).update(flow=flow, updated_at=timezone.now())
            # What this request claimed: it settles only that (never a newer plan's claim).
            return name, index, {'issued_ms': plan.get('issued_ms'), 'claim': claims[str(index)]}
        raise FlowError('action_mismatch')


def _settle_claim(position_id, name: str, index: int, outcome: str, observed: dict | None = None,
                  **flow_extra) -> bool:
    """outcome: 'consumed' (done), 'released' (refused: may be signed again)
    or 'unconfirmed' (sent, answer lost: never sent again blindly).
    `observed` = {'issued_ms', 'claim'}: settle only if the plan and claim are
    still the ones a reconciler read (a newer plan's claim is never touched)."""
    from blockchain.models import PerpPosition

    with transaction.atomic():
        position = PerpPosition.objects.select_for_update().get(pk=position_id)
        flow = dict(position.flow or {})
        plan = dict(flow.get(name) or {})
        claims = dict(plan.get('claims') or {})
        if observed is not None and (plan.get('issued_ms') != observed.get('issued_ms')
                                     or claims.get(str(index)) != observed.get('claim')):
            return False
        if outcome == 'consumed':
            plan['consumed'] = sorted(set(plan.get('consumed') or []) | {index})
            claims.pop(str(index), None)
        elif outcome == 'released':
            claims.pop(str(index), None)
        else:
            claims[str(index)] = dict(claims.get(str(index)) or {}, status='unconfirmed')
        plan['claims'] = claims
        flow[name] = plan
        flow.update(flow_extra)
        PerpPosition.objects.filter(pk=position_id).update(flow=flow, updated_at=timezone.now())
        return True


def _fill_of(body: dict) -> tuple[dict | None, str | None]:
    response = body.get('response') or {}
    data = response.get('data') if isinstance(response, dict) else None
    statuses = data.get('statuses') if isinstance(data, dict) else None
    if not isinstance(statuses, list) or not statuses:
        return None, 'no_status'
    first = statuses[0]
    if isinstance(first, dict) and isinstance(first.get('filled'), dict):
        return first['filled'], None
    return None, str((first or {}).get('error') if isinstance(first, dict) else first)[:120]


def submit_action(user, position_id, purpose: str, action_json: str, nonce: int, signature: dict,
                  meta=None) -> dict:
    """Forward ONE member-signed Hyperliquid action that is the next step of
    a live plan. Claimed before sending: a duplicate or replay is refused."""
    from blockchain.models import PerpMarginChange, PerpPosition

    from . import perps_risk

    position = _position(user, position_id)
    gate = perps_risk.exit_gate()
    if gate:
        raise FlowError(gate)
    required = {
        'abstraction': ('funded',), 'fund_dex': ('funded',), 'leverage': ('funded',), 'open_order': ('funded',),
        'close_order': ('open',), 'tpsl_cancel': ('open',), 'tpsl': ('open',), 'margin_fund_dex': ('open',),
        'margin_add': ('open',),
        'return_dex': RETURNABLE_STATES,
    }.get(purpose)
    if required is None:
        raise FlowError('bad_purpose')
    if position.state not in required:
        raise FlowError('bad_state')
    if purpose in OPEN_PURPOSES and _return_quoted(position.flow):
        # A return was quoted for this money: finish or let it lapse first.
        raise FlowError('return_in_progress')
    if purpose in OPEN_PURPOSES:
        _open_policy(user, meta, position.market)
    try:
        action = json.loads(action_json)
        nonce = int(nonce)
    except (TypeError, ValueError) as exc:
        raise FlowError('bad_action') from exc
    # An open may be re-signed with its first nonce (the app keeps it), so a
    # retry can never authorize a second, independent order: either may
    # execute, never both.
    max_age = OPEN_NONCE_MAX_AGE_MS if purpose in ('open_order', 'close_order', 'leverage', 'tpsl') else 120_000
    if not isinstance(action, dict) or nonce - _now_ms() > 120_000 or _now_ms() - nonce > max_age:
        raise FlowError('bad_action')
    try:
        signer = hl_signing.recover_action_signer(action, nonce, signature)
    except hl_signing.SignatureError as exc:
        raise FlowError('bad_signature') from exc
    if signer != position.wallet:
        raise FlowError('bad_signature')
    if purpose in ('margin_fund_dex', 'margin_add'):
        change_id = ((position.flow or {}).get('margin_plan') or {}).get('change_id')
        if not PerpMarginChange.objects.filter(pk=change_id, position=position, state='funded').exists():
            raise FlowError('nothing_to_add')
    if purpose == 'open_order':
        # A plan lives 10 minutes; the book may not. The impact cap is checked
        # again on the book as it is now, right before the order goes out.
        order = (action.get('orders') or [{}])[0]
        _, cap, _slip = _impact_limits()
        try:
            avg, mid, _ = walk_book(hyperliquid.l2_book(position.market.coin), bool(order.get('b')), _d(order.get('s')))
        except hyperliquid.HyperliquidError as exc:
            raise FlowError('hyperliquid_unavailable') from exc
        if impact_bps(avg, mid) > cap:
            raise FlowError('impact_too_high')
    name, index, observed = _claim_step(position.pk, purpose, action, nonce, required)
    payload = {'action': action, 'nonce': nonce, 'signature': signature}
    if action['type'] in hl_signing.L1_TYPES:
        payload['vaultAddress'] = None
    if purpose == 'margin_add':
        # Durable BEFORE sending: a crash or a lost answer is resolved by
        # re-posting this same signed action (the same nonce applies once).
        _merge_flow(position.pk, margin_pending_payload=payload)
    try:
        body = hyperliquid.exchange(payload)
    except hyperliquid.HyperliquidError as exc:
        # Unknown outcome: never assume and never re-send blindly. An order
        # is found by its client id, a margin change by the position's raw
        # margin (reconcile_position).
        _settle_claim(position.pk, name, index, 'unconfirmed', observed=observed)
        PerpPosition.objects.filter(pk=position.pk).update(step_error='unconfirmed', updated_at=timezone.now())
        raise FlowError('hyperliquid_unavailable') from exc

    if body.get('status') != 'ok':
        if purpose == 'abstraction':
            # An account already in standard mode may refuse the switch; any
            # other refusal stops here (the flow assumes separate balances).
            try:
                mode = hyperliquid.user_abstraction(position.wallet)
            except hyperliquid.HyperliquidError:
                mode = ''
            if mode in ('disabled', 'default'):
                _settle_claim(position.pk, name, index, 'consumed', observed=observed, done_abstraction=_now_ms(),
                              abstraction_error=str(body.get('response') or '')[:120])
                return {'position': position, 'response': body}
        if purpose == 'margin_add' and 'nonce' in str(body.get('response') or '').lower():
            # The same signed top-up may already have applied (the reconciler
            # re-posts it): ambiguous, so the claim and its payload stay for
            # the reconciler, never a fresh plan that could add it twice.
            _settle_claim(position.pk, name, index, 'unconfirmed', observed=observed)
            raise FlowError('step_unconfirmed')
        _settle_claim(position.pk, name, index, 'released', observed=observed)
        PerpPosition.objects.filter(pk=position.pk).update(
            step_error=str(body.get('response') or 'hyperliquid_error')[:120], updated_at=timezone.now())
        raise FlowError('hyperliquid_rejected')

    if purpose in ('open_order', 'close_order'):
        filled, error = _fill_of(body)
        if filled is None:
            _settle_claim(position.pk, name, index, 'released', observed=observed)
            PerpPosition.objects.filter(pk=position.pk).update(step_error=error or 'order_not_filled',
                                                               updated_at=timezone.now())
            raise FlowError('order_not_filled')
        if purpose == 'open_order':
            if _transition(PerpPosition, position.pk, ('funded',), state='open', entry_oid=filled.get('oid'),
                           entry_avg_px=_d(filled.get('avgPx')), size=_d(filled.get('totalSz')),
                           opened_at=timezone.now(), step_error=''):
                _merge_flow(position.pk, size_initial=str(_d(filled.get('totalSz'))))
            _settle_claim(position.pk, name, index, 'consumed', observed=observed)
        else:
            _settle_claim(position.pk, name, index, 'consumed', observed=observed)
            PerpPosition.objects.filter(pk=position.pk, state='open').update(
                close_oid=filled.get('oid'), close_avg_px=_d(filled.get('avgPx')), updated_at=timezone.now())
            reconcile_position(PerpPosition.objects.select_related('market').get(pk=position.pk))
    elif purpose == 'tpsl':
        response = body.get('response') or {}
        statuses = ((response.get('data') or {}) if isinstance(response, dict) else {}).get('statuses') or []
        errors = [st.get('error') for st in statuses if isinstance(st, dict) and st.get('error')]
        if errors or len(statuses) != len(action.get('orders') or []):
            _settle_claim(position.pk, name, index, 'released', observed=observed)
            PerpPosition.objects.filter(pk=position.pk).update(
                step_error=str(errors[0] if errors else 'tpsl_incomplete')[:120], updated_at=timezone.now())
            raise FlowError('tpsl_rejected')
        _settle_claim(position.pk, name, index, 'consumed', observed=observed, done_tpsl=_now_ms())
    elif purpose == 'margin_add':
        with transaction.atomic():
            # Credited only while this request's claim is still the live one.
            locked = PerpPosition.objects.select_for_update().get(pk=position.pk)
            now_plan = (locked.flow or {}).get(name) or {}
            if (now_plan.get('issued_ms') == observed['issued_ms']
                    and (now_plan.get('claims') or {}).get(str(index)) == observed['claim']):
                _apply_margin_add(position.pk, now_plan.get('change_id'), Decimal(action['ntli']) / 1_000_000)
                _settle_claim(position.pk, name, index, 'consumed', observed=observed, margin_pending_payload=None)
    elif purpose in ('fund_dex', 'margin_fund_dex'):
        amount = _d(action['amount'])
        if purpose == 'fund_dex':
            moved = _d((position.flow or {}).get('dex_moved') or '0') + amount
            _settle_claim(position.pk, name, index, 'consumed', observed=observed, dex_moved=str(moved))
        else:
            change_id = ((position.flow or {}).get('margin_plan') or {}).get('change_id')
            with transaction.atomic():
                if _settle_claim(position.pk, name, index, 'consumed', observed=observed):
                    change = PerpMarginChange.objects.select_for_update().get(pk=change_id)
                    flow = dict(change.flow or {})
                    flow['dex_moved'] = str(_d(flow.get('dex_moved') or '0') + amount)
                    PerpMarginChange.objects.filter(pk=change_id).update(flow=flow, updated_at=timezone.now())
    else:
        _settle_claim(position.pk, name, index, 'consumed', observed=observed, **({f'done_{purpose}': _now_ms()}))
    return {'position': PerpPosition.objects.get(pk=position.pk), 'response': body}


def _apply_margin_add(position_pk, change_id, add: Decimal) -> None:
    from blockchain.models import PerpMarginChange, PerpPosition

    with transaction.atomic():
        if not _transition(PerpMarginChange, change_id, ('funded',), state='done'):
            return
        locked = PerpPosition.objects.select_for_update().get(pk=position_pk)
        flow = dict(locked.flow or {})
        flow['credit_events'] = list(flow.get('credit_events') or []) + [
            {'at': timezone.now().isoformat(), 'usd': str(add), 'change_id': change_id}]
        PerpPosition.objects.filter(pk=position_pk).update(
            credited_usdc=(locked.credited_usdc or Decimal(0)) + add, flow=flow, updated_at=timezone.now())


# ── return: Relay withdrawal of exactly this position's money ──────────

def _fold_unapplied(position) -> None:
    """Top-ups that arrived but were never applied came home with the
    position: finished, keeping their credit (history values them)."""
    from blockchain.models import PerpMarginChange

    for change in PerpMarginChange.objects.filter(position=position, state='funded'):
        flow = dict(change.flow or {})
        flow['unapplied'] = True
        PerpMarginChange.objects.filter(pk=change.pk, state='funded').update(
            state='done', flow=flow, updated_at=timezone.now())


def settled_equity(position) -> Decimal:
    """What this position is worth on Hyperliquid once closed: its credited
    margin plus realized P&L, minus venue fees, plus funding received."""
    if position.state == 'funded':
        return Decimal(position.credited_usdc or 0)
    equity = (Decimal(position.credited_usdc or 0) + Decimal(position.realized_pnl or 0)
              - Decimal(position.venue_fees or 0) + Decimal(position.funding or 0))
    return max(equity, Decimal(0))


def return_plan(user, position_id) -> dict:
    """Bring home exactly this position's money (plus any of its top-ups
    that arrived but were never applied) in one Relay withdrawal."""
    from blockchain.models import PerpPosition

    from . import perps_risk

    position = _position(user, position_id)
    if position.state not in RETURNABLE_STATES:
        raise FlowError('bad_state')
    if perps_risk.exit_gate():
        raise FlowError('trade_not_available')
    if position.margin_changes.filter(state='bridging').exists():
        raise FlowError('margin_change_in_flight')
    # A top-up step may be moving money between the member's balances right
    # now (core → the market's dex): the return reads them only once it settled.
    _release_stale_margin(position)
    position.refresh_from_db()
    if _pending_claim(position, 'margin_plan'):
        raise FlowError('step_in_flight')
    wallet, market = position.wallet, position.market
    if _open_in_flight(position):
        raise FlowError('step_in_flight')
    # What the balances are read against: if any open or top-up step moves
    # before the finish below, the read is stale (a dex transfer may have
    # just moved the money between the balances).
    steps_seen = json.dumps([(position.flow or {}).get('open_plan'), (position.flow or {}).get('margin_plan')],
                            sort_keys=True, default=str)
    _guard_not_live(position)
    unapplied = sum((_d((c.flow or {}).get('credited') or '0')
                     for c in position.margin_changes.filter(state='funded')), Decimal(0))
    amount = (settled_equity(position) + unapplied).quantize(Decimal('0.000001'), rounding=ROUND_DOWN)
    try:
        if market.dex:
            # One live position per member: what is free on its dex is its own
            # (released margin, an unapplied top-up).
            on_dex = _withdrawable(wallet, market.dex)
            if on_dex > Decimal('0.000001') and _live_position(wallet, market) is None:
                steps = [{'purpose': 'return_dex', 'action': _send_asset(wallet, market.dex, '', on_dex)}]
                _store_plan(position, 'return_plan', steps)
                return {'position': position, 'steps': steps, 'relay': None, 'replan': True}
        core = _withdrawable(wallet, '')
    except hyperliquid.HyperliquidError as exc:
        raise FlowError('hyperliquid_unavailable') from exc
    # Everything free is this position's (one live position per member);
    # settled equity is the expectation, the venue's balance is the truth.
    amount = core.quantize(Decimal('0.000001'), rounding=ROUND_DOWN)
    # The venue's own word on what this position's money came to (one live
    # position per member): it settles a top-up whose outcome was unknowable.
    _merge_flow(position.pk, venue_free_at_return=str(amount))
    if amount < RETURN_MIN_USD:
        # Dust under the return minimum stays on Hyperliquid; the position
        # is finished with nothing returned.
        with transaction.atomic():
            locked = PerpPosition.objects.select_for_update().get(pk=position.pk)
            steps_now = json.dumps([(locked.flow or {}).get('open_plan'), (locked.flow or {}).get('margin_plan')],
                                   sort_keys=True, default=str)
            if locked.state not in RETURNABLE_STATES or _open_in_flight(locked) \
                    or _pending_claim(locked, 'margin_plan') or steps_now != steps_seen:
                raise FlowError('step_in_flight')
            PerpPosition.objects.filter(pk=position.pk).update(
                state='done', done_at=timezone.now(), returned_usd=Decimal(0), updated_at=timezone.now())
        _fold_unapplied(position)
        return {'position': position, 'steps': [], 'relay': None, 'finished': True}
    units = int((amount * USDC_UNIT).to_integral_value(rounding=ROUND_DOWN))
    units -= units % 100  # sendAsset amounts are 6-decimal strings
    quote = perps_relay.quote_return(wallet, units)
    mapping_typed = hl_signing.relay_nonce_mapping_typed_data(quote['mapping'], SIGNATURE_CHAIN_ID)
    send_action = {'type': 'sendAsset', 'signatureChainId': hex(SIGNATURE_CHAIN_ID),
                   'hyperliquidChain': hl_signing.MAINNET, **quote['send_asset']}
    relay = {k: quote[k] for k in ('request_id', 'order_id', 'expected_out', 'minimum_out', 'deadline',
                                    'nonce', 'mapping')}
    relay['units'] = units
    position.flow = _merge_flow(position.pk, return_relay=relay, return_send=send_action)
    return {'position': position, 'steps': [], 'relay': relay, 'mapping_typed': mapping_typed,
            'send_action': send_action, 'relay_quote': quote['raw']}


def _send_return(position_pk, payload: dict) -> str:
    """POST the stored signed sendAsset (see _repost)."""
    outcome = _repost(payload)
    # The return is followed through Relay's own status, never this answer alone.
    return {'used': 'ok', 'nonce': 'rejected'}.get(outcome, outcome)


def _repost(payload: dict) -> str:
    """POST a stored signed action: 'ok' (applied now) | 'rejected' |
    'unknown', 'used' (the nonce was used: by this action, or by another one
    of the same signer, so not proof on its own) or 'nonce' (another nonce
    refusal). Safe to repeat: the same nonce never applies twice."""
    try:
        body = hyperliquid.exchange(payload)
    except hyperliquid.HyperliquidError:
        return 'unknown'
    if body.get('status') == 'ok':
        return 'ok'
    text = str(body.get('response') or '').lower()
    if 'nonce' in text:
        return 'used' if 'used' in text else 'nonce'
    return 'rejected'


def _guard_not_live(position) -> None:
    """Never send home the margin of a position that is live on the venue
    (an order whose answer was lost may have filled)."""
    try:
        live = _live_position(position.wallet, position.market) is not None
        # Before an open was ever confirmed, a filled order is a lost answer;
        # after a close, it is just history (the venue check above decides).
        filled = position.state == 'funded' and _filled_cloid(position)
    except hyperliquid.HyperliquidError as exc:
        raise FlowError('hyperliquid_unavailable') from exc
    if live or filled:
        reconcile_position(position)
        raise FlowError('already_open')


def submit_return(user, position_id, mapping_signature: dict, send_signature: dict) -> dict:
    from blockchain.models import PerpPosition

    from . import perps_risk

    position = _position(user, position_id)
    if position.state not in RETURNABLE_STATES:
        raise FlowError('bad_state')
    if _open_in_flight(position):
        raise FlowError('step_in_flight')
    _guard_not_live(position)
    if perps_risk.exit_gate():
        raise FlowError('trade_not_available')
    relay = (position.flow or {}).get('return_relay')
    send_action = (position.flow or {}).get('return_send')
    if not relay or not send_action or int(relay['deadline']) <= int(time.time()) + 15:
        raise FlowError('return_quote_expired')
    try:
        mapping_signer = hl_signing.recover(
            hl_signing.relay_nonce_mapping_typed_data(relay['mapping'], SIGNATURE_CHAIN_ID), mapping_signature)
        send_signer = hl_signing.recover_action_signer(send_action, relay['nonce'], send_signature)
    except hl_signing.SignatureError as exc:
        raise FlowError('bad_signature') from exc
    if mapping_signer != position.wallet or send_signer != position.wallet:
        raise FlowError('bad_signature')
    # Relay first: the transfer is only attributable once its nonce is mapped.
    try:
        perps_relay.authorize(relay['mapping'], hl_signing.signature_hex(mapping_signature), SIGNATURE_CHAIN_ID)
    except perps_relay.RelayError as exc:
        raise FlowError('relay_unavailable') from exc
    payload = {'action': send_action, 'nonce': relay['nonce'], 'signature': send_signature}
    flow = dict(position.flow or {})
    # Durable BEFORE sending: a crash or a lost answer is resumed by the
    # reconciler re-posting this same signed transfer (never a new one).
    flow['return_pending'] = {'payload': payload, 'request_id': relay['request_id'],
                              'expected_out': relay['expected_out'], 'minimum_out': relay['minimum_out'],
                              'deadline': relay['deadline'], 'at': int(time.time())}
    with transaction.atomic():
        locked = PerpPosition.objects.select_for_update().get(pk=position.pk)
        if locked.state not in RETURNABLE_STATES:
            raise FlowError('bad_state')
        if _open_in_flight(locked) or _pending_claim(locked, 'margin_plan'):
            raise FlowError('step_in_flight')
        if (locked.flow or {}).get('return_relay') != relay:
            raise FlowError('return_quote_expired')
        flow = {**(locked.flow or {}), 'return_pending': flow['return_pending']}
        PerpPosition.objects.filter(pk=position.pk).update(
            relay_back_id=relay['request_id'], state='returning', flow=flow, step_error='',
            updated_at=timezone.now())
    outcome = _send_return(position.pk, payload)
    if outcome == 'rejected':
        _transition(PerpPosition, position.pk, ('returning',), match={'relay_back_id': relay['request_id']},
                    state='return_failed', step_error='send_rejected')
        raise FlowError('hyperliquid_rejected')
    if outcome == 'unknown':
        PerpPosition.objects.filter(pk=position.pk).update(step_error='send_unconfirmed', updated_at=timezone.now())
    return {'position': PerpPosition.objects.get(pk=position.pk)}


def entry_plan(user, meta, position_id) -> dict:
    """The ordinary entry for USDT that came home: exact calls, a durable
    request id the relay recognizes as this position's return."""
    from eth_abi import encode as abi_encode

    from blockchain.models import PerpPosition

    from . import sponsor_7702, vault
    from .crypto_policy import DOLLAR, DOLLAR_PLUS
    from .eligibility import check_savings_mint_eligibility

    position = _position(user, position_id)
    if position.state != 'landed':
        raise FlowError('bad_state')
    if position.return_batch_id is not None:
        raise FlowError('entry_in_flight')
    existing = (position.flow or {}).get('entry')
    stale_request_id = None
    if existing and existing.get('dollar') == DOLLAR_PLUS and not check_savings_mint_eligibility(user, meta or {}):
        # Unsent and no longer sponsorable as Confío Dollar+: issue it again.
        stale_request_id, existing = existing.get('request_id'), None
    if existing:
        return {'position': position, **existing}
    on_hand = vault.usdt_balance_raw(position.wallet, fresh=True)
    landed = int((position.flow or {}).get('landed_wei') or 0)
    amount = min(on_hand, landed)
    if amount <= 0:
        raise FlowError('nothing_to_enter')
    dollar = DOLLAR_PLUS if (check_savings_mint_eligibility(user, meta or {})
                             and vault.is_safe_mint_amount(amount)) else DOLLAR
    wallet = position.wallet
    if dollar == DOLLAR_PLUS:
        target = vault.vault_address()
        pps = vault.p_plus_wad(fresh=True)
        oracle = vault.current_oracle_price_wad(fresh=True)
        if pps <= 0 or oracle <= 0:
            raise FlowError('price_unavailable')
        usdy = amount * WAD // oracle
        min_shares = (usdy * oracle // pps) * (BPS - 100) // BPS
        data = '0x' + sponsor_7702.SEL_SUBSCRIBE_AND_MINT + abi_encode(
            ['uint256', 'uint256', 'address'], [amount, min_shares, wallet]).hex()
    else:
        target = (getattr(settings, 'CUSD_VAULT_ADDRESS', '') or '').lower()
        from .cusd_vault import preview_mint_wei
        net = preview_mint_wei(amount).net_wei
        data = '0x' + sponsor_7702.SEL_CUSD_MINT + abi_encode(
            ['uint256', 'uint256', 'address'], [amount, net, wallet]).hex()
    calls = [_approve_call(target.lower(), amount), {'to': target.lower(), 'value': '0', 'data': data}]
    entry = {'calls': calls, 'request_id': _request_id('perps-ret'), 'dollar': dollar,
             'amount_wei': str(amount), 'kind': 'subscribe' if dollar == DOLLAR_PLUS else 'mint_cusd'}
    with transaction.atomic():
        locked = PerpPosition.objects.select_for_update().get(pk=position.pk)
        if locked.state != 'landed' or locked.return_batch_id is not None:
            raise FlowError('entry_in_flight')
        current = (locked.flow or {}).get('entry')
        if current and current.get('request_id') != stale_request_id:
            return {'position': locked, **current}  # another request won
        flow = dict(locked.flow or {})
        flow['entry'] = entry
        PerpPosition.objects.filter(pk=position.pk).update(flow=flow, updated_at=timezone.now())
    return {'position': position, **entry}


# ── reconciler: observed facts only ─────────────────────────────────────

def _settle_closed(position, liquidation: str = '') -> bool:
    """Realized result from this episode's own fills (from its opening
    fill on) and funding; applied only if the position is still open."""
    from blockchain.models import PerpPosition

    # One live position per member: every fill in this market since the
    # position was quoted is its own (the previous one finished before).
    since = int(position.created_at.timestamp() * 1000)
    fills = [f for f in hyperliquid.user_fills_by_time(position.wallet, since)
             if f.get('coin') == position.market.coin and int(f.get('time') or 0) >= since]
    closed_pnl = sum((_d(f.get('closedPnl', '0')) for f in fills), Decimal(0))
    fees = sum((_d(f.get('fee', '0')) for f in fills), Decimal(0))
    funding = sum((_d((e.get('delta') or {}).get('usdc', '0'))
                   for e in hyperliquid.user_funding(position.wallet, since)
                   if (e.get('delta') or {}).get('coin') == position.market.coin), Decimal(0))
    closes = [f for f in fills if str(f.get('dir', '')).startswith('Close') or f.get('liquidation')]
    if not liquidation and any(f.get('liquidation') for f in fills):
        liquidation = 'book'
    # The venue's own time of the closing fill, not when we noticed it: Liga
    # values a past midnight with the exposure it really had.
    closed_ms = max((int(f.get('time') or 0) for f in closes), default=0)
    closed_at = (datetime.fromtimestamp(closed_ms / 1000, tz=dt_timezone.utc) if closed_ms else timezone.now())
    fields = {'realized_pnl': closed_pnl, 'venue_fees': fees, 'funding': funding,
              'liquidation': liquidation, 'state': 'liquidated' if liquidation else 'closed',
              'closed_at': closed_at}
    if closes and position.close_avg_px is None:
        total = sum((_d(f['sz']) for f in closes), Decimal(0))
        if total > 0:
            fields['close_avg_px'] = sum((_d(f['px']) * _d(f['sz']) for f in closes), Decimal(0)) / total
    events = _size_events(fills)
    # Partial closes and costs never seen while it was open still date past days.
    _merge_flow(position.pk, cost_events=_cost_events(position), costs_synced_at=time.time(),
                **({'size_events': events} if events else {}))
    return _transition(PerpPosition, position.pk, ('open',), **fields)


def _entry_fill_ms(position, oid) -> int | None:
    if oid is None:
        return None
    since = int(position.created_at.timestamp() * 1000)
    times = [int(f.get('time') or 0) for f in hyperliquid.user_fills_by_time(position.wallet, since)
             if f.get('oid') == oid]
    return min(times) if times else None


def _open_cloids(position) -> list:
    flow = position.flow or {}
    claims = ((flow.get('open_plan') or {}).get('claims') or {}).values()
    return list(dict.fromkeys(list(flow.get('open_cloids') or []) + [c['cloid'] for c in claims if c.get('cloid')]))


def _release_stale_margin(position) -> None:
    """Once the position is no longer open, a top-up step older than two
    minutes has settled one way or the other (a closed position takes no
    margin; a dex transfer either moved or not): its claim is released and
    the return reads the balances as they are."""
    if position.state == 'open':
        return
    from blockchain.models import PerpMarginChange

    plan = (position.flow or {}).get('margin_plan') or {}
    steps = plan.get('steps') or []
    for i, c in (plan.get('claims') or {}).items():
        if c.get('status') in ('sending', 'unconfirmed') and _now_ms() - int(c.get('at') or 0) > 120_000:
            released = _settle_claim(position.pk, 'margin_plan', int(i), 'released',
                                     observed={'issued_ms': plan.get('issued_ms'), 'claim': c})
            if released and int(i) < len(steps) and steps[int(i)].get('purpose') == 'margin_add':
                # It may have joined the margin before the close: unknowable now.
                # The position is valued from the venue's own balance at its
                # return instead (perps_portfolio.episodes).
                change = PerpMarginChange.objects.filter(pk=plan.get('change_id')).first()
                if change is not None:
                    flow = dict(change.flow or {})
                    flow['ambiguous'] = True
                    PerpMarginChange.objects.filter(pk=change.pk).update(flow=flow, updated_at=timezone.now())


def _release_lost_open(position) -> None:
    """An opening order with no answer that Hyperliquid never recorded (or
    recorded dead, unfilled), past the plan's lifetime: it can never fill
    later (a request is processed or not), so the claim is released and the
    member can open again or bring the money home."""
    plan = (position.flow or {}).get('open_plan') or {}
    steps = plan.get('steps') or []
    index, claim = None, {}
    for i, c in (plan.get('claims') or {}).items():
        if c.get('status') not in ('sending', 'unconfirmed') or _now_ms() - int(c.get('at') or 0) < PLAN_TTL_MS:
            continue
        if int(i) < len(steps) and steps[int(i)].get('purpose') == 'open_order':
            index, claim = int(i), c
        else:
            # Setup steps (abstraction, leverage, dex funding) are safe to
            # plan again: a new plan reads the account as it is.
            _settle_claim(position.pk, 'open_plan', int(i), 'released',
                          observed={'issued_ms': plan.get('issued_ms'), 'claim': c})
    cloid = claim.get('cloid')
    if index is None or not cloid:
        return
    # Strict: only Hyperliquid saying "never seen" or "dead, unfilled" releases
    # it; an unreadable answer keeps the claim (unknown is not a no).
    body = hyperliquid.info({'type': 'orderStatus', 'user': position.wallet, 'oid': cloid})
    if isinstance(body, dict) and body.get('status') == 'unknownOid':
        _settle_claim(position.pk, 'open_plan', index, 'released', observed={'issued_ms': plan.get('issued_ms'), 'claim': claim})
        return
    order = body.get('order') if isinstance(body, dict) and body.get('status') == 'order' else None
    if isinstance(order, dict) and order.get('status') not in ('open', 'filled') and not _had_fill(order):
        _settle_claim(position.pk, 'open_plan', index, 'released', observed={'issued_ms': plan.get('issued_ms'), 'claim': claim})


def _opened_from_fills(position) -> dict:
    """{'szi', 'entryPx'} of the opening, from the open orders' own fills."""
    oids = set()
    for cloid in _open_cloids(position):
        order = _order_status(position.wallet, cloid)
        if _had_fill(order):
            oids.add((order.get('order') or {}).get('oid'))
    since = int(position.created_at.timestamp() * 1000)
    fills = [f for f in hyperliquid.user_fills_by_time(position.wallet, since) if f.get('oid') in oids]
    size = sum((_d(f.get('sz', '0')) for f in fills), Decimal(0))
    if size <= 0:
        return {'szi': '0', 'entryPx': '0'}
    px = sum((_d(f['px']) * _d(f['sz']) for f in fills), Decimal(0)) / size
    sign = 1 if position.side == 'long' else -1
    return {'szi': str(size * sign), 'entryPx': str(px)}


def _had_fill(order: dict | None) -> bool:
    """Filled, or an IOC that filled part and cancelled the rest."""
    if order is None:
        return False
    if order.get('status') == 'filled':
        return True
    inner = order.get('order') or {}
    try:
        return _d(inner.get('origSz') or '0') > _d(inner.get('sz') or '0')
    except ArithmeticError:
        return False


def _filled_cloid(position) -> bool:
    return any(_had_fill(_order_status(position.wallet, cloid)) for cloid in _open_cloids(position))


def _adopt_open(position, live: dict) -> bool:
    """A funded position whose order filled but whose answer was lost: its
    real entry from the order (found by client id) and the live position."""
    from blockchain.models import PerpPosition

    oid = None
    for cloid in _open_cloids(position):
        order = _order_status(position.wallet, cloid)
        if _had_fill(order):
            oid = ((order.get('order') or {}).get('oid'))
    flow = dict(position.flow or {})
    fill_ms = _entry_fill_ms(position, oid)
    if fill_ms:
        flow['entry_fill_ms'] = fill_ms
    opened = datetime.fromtimestamp(fill_ms / 1000, tz=dt_timezone.utc) if fill_ms else timezone.now()
    szi = _d(live.get('szi', '0'))
    # The size and price at the fill, from the opening's own fills (a part may
    # have closed since): partial closes are rebuilt from the venue's fills.
    opening = _opened_from_fills(position)
    initial = abs(_d(opening['szi'])) or abs(szi)
    flow['size_initial'] = str(initial)
    since = int(position.created_at.timestamp() * 1000)
    events = _size_events([f for f in hyperliquid.user_fills_by_time(position.wallet, since)
                           if f.get('coin') == position.market.coin and int(f.get('time') or 0) >= since])
    if events:
        flow['size_events'] = events
    entry_px = _d(opening['entryPx']) if _d(opening['entryPx']) > 0 else _d(live.get('entryPx') or '0')
    # The lost answer is found: its claim is done, never in flight again.
    plan = dict(flow.get('open_plan') or {})
    claims = {i: ({**c, 'status': 'consumed'} if c.get('status') in ('sending', 'unconfirmed') else c)
              for i, c in (plan.get('claims') or {}).items()}
    if claims:
        plan['claims'] = claims
        plan['consumed'] = sorted(set(plan.get('consumed') or []) | {int(i) for i in claims})
        flow['open_plan'] = plan
    return _transition(PerpPosition, position.pk, ('funded',), state='open', size=abs(szi), entry_oid=oid,
                       entry_avg_px=entry_px, opened_at=opened, flow=flow, step_error='')


def _size_events(fills: list) -> list:
    """Rebuilt from the venue's fills, one event per closing fill at its own
    time: two partial closes either side of midnight stay two events.
    Realized is gross; every venue fee is counted once, in cost_events."""
    events, realized = [], Decimal(0)
    for f in sorted(fills, key=lambda f: int(f.get('time') or 0)):
        realized += _d(f.get('closedPnl', '0'))
        if not (str(f.get('dir', '')).startswith('Close') or f.get('liquidation')):
            continue
        signed = _d(f.get('sz', '0')) * (1 if f.get('side') == 'B' else -1)
        after = abs(_d(f.get('startPosition', '0')) + signed)
        at = datetime.fromtimestamp(int(f.get('time') or 0) / 1000, tz=dt_timezone.utc)
        events.append({'at': at.isoformat(), 'size': str(after), 'realized': str(realized)})
    return events


def _track_size(position, live: dict) -> None:
    """A partial close: record the size from now on (and realized so far),
    so a past day is valued with the exposure it had then."""
    from blockchain.models import PerpPosition

    size = abs(_d(live.get('szi', '0')))
    if position.size is None or size == Decimal(position.size):
        return
    since = int(position.created_at.timestamp() * 1000)
    fills = [f for f in hyperliquid.user_fills_by_time(position.wallet, since)
             if f.get('coin') == position.market.coin and int(f.get('time') or 0) >= since]
    events = _size_events(fills)
    if not events:
        return
    with transaction.atomic():
        locked = PerpPosition.objects.select_for_update().get(pk=position.pk)
        if locked.state != 'open':
            return
        flow = dict(locked.flow or {})
        flow['size_events'] = events
        PerpPosition.objects.filter(pk=position.pk).update(size=size, flow=flow, updated_at=timezone.now())


COST_EVENT_EVERY_S = 3600


def _cost_events(position) -> list:
    """Venue fees and funding, dated by the venue (each fill, each funding
    payment), cumulative: a past day is valued with the costs it really had.
    One event per UTC day (the day's last): Liga values past midnights, and
    the history never needs a cap that would rewrite old days' signatures."""
    since = int(position.created_at.timestamp() * 1000)
    coin = position.market.coin
    rows = [(int(f.get('time') or 0), _d(f.get('fee', '0')), Decimal(0))
            for f in hyperliquid.user_fills_by_time(position.wallet, since)
            if f.get('coin') == coin and int(f.get('time') or 0) >= since]
    rows += [(int(e.get('time') or 0), Decimal(0), -_d((e.get('delta') or {}).get('usdc', '0')))  # + = paid
             for e in hyperliquid.user_funding(position.wallet, since)
             if (e.get('delta') or {}).get('coin') == coin]
    by_day, fees, paid = {}, Decimal(0), Decimal(0)
    for ms, fee, funding in sorted(rows, key=lambda r: r[0]):
        fees += fee
        paid += funding
        by_day[ms // 86_400_000] = {
            'at': datetime.fromtimestamp(ms / 1000, tz=dt_timezone.utc).isoformat(),
            'funding_paid': str(paid), 'fees': str(fees)}
    return list(by_day.values())


def _track_costs(position, live: dict) -> None:
    """Hourly: rebuild the dated costs from the venue's own history."""
    synced = (position.flow or {}).get('costs_synced_at')
    if synced and time.time() - float(synced) < COST_EVENT_EVERY_S:
        return
    _merge_flow(position.pk, cost_events=_cost_events(position), costs_synced_at=time.time())


def _margin_add_applied(position, live: dict) -> bool:
    plan = (position.flow or {}).get('margin_plan') or {}
    before = plan.get('raw_before')
    raw_now = (live.get('leverage') or {}).get('rawUsd')
    change_add = None
    for step in plan.get('steps') or []:
        if step['purpose'] == 'margin_add':
            change_add = Decimal(step['action']['ntli']) / 1_000_000
    if not before or raw_now is None or change_add is None:
        return False
    # rawUsd moves by margin transfers (and a little funding), never by
    # price: adding margin raises it by the amount, long or short.
    return _d(raw_now) - _d(before) >= change_add * Decimal('0.98')


def reconcile_position(position) -> str:
    """Advance one position by what the chain, Relay and Hyperliquid say.
    Every change is compare-and-set from the state it was read in."""
    from blockchain.models import PerpMarginChange, PerpPosition, SponsoredBatch

    from . import vault

    state = position.state
    try:
        if state == 'bridging':
            retry = (position.flow or {}).get('retry') or {}
            batch_id = retry.get('batch_id') or position.open_batch_id
            batch = SponsoredBatch.objects.filter(pk=batch_id).first() if batch_id else None
            if batch is not None and batch.status in DEAD_BATCH_STATUSES:
                on_receipt(batch)
                return PerpPosition.objects.get(pk=position.pk).state
            relay_id = (retry.get('relay_out') or {}).get('request_id') if retry.get('batch_id') else position.relay_out_id
            status_body = _relay_status(relay_id)
            status = status_body.get('status')
            if status == 'success':
                since = int(((batch.created_at if batch else position.created_at).timestamp() - 120) * 1000)
                credit = _hl_credit(position.wallet, status_body, since)
                if credit is None and time.time() - position.updated_at.timestamp() > CREDIT_FALLBACK_S:
                    # The ledger entry never showed: the quote's floor, bounded by the balance.
                    floor = Decimal(int(((retry.get('relay_out') if retry.get('batch_id') else None)
                                         or (position.flow or {}).get('relay_out') or {}).get('minimum_out') or 0))
                    credit = min(floor / USDC_UNIT, _withdrawable(position.wallet, ''))
                if credit is not None and credit > 0:
                    flow = dict(position.flow or {})
                    flow['credited_initial'] = str(credit)
                    _transition(PerpPosition, position.pk, ('bridging',), state='funded', credited_usdc=credit,
                                flow=flow, step_error='')
            elif status == 'refund':
                flow = dict(position.flow or {})
                flow['refunded_at'] = int(time.time())
                deposited = int((retry.get('deposit_wei') if retry.get('batch_id') else flow.get('deposit_wei')) or 0)
                delivered = _delivered_usdt(status_body, position.wallet)
                if delivered is None and time.time() - position.updated_at.timestamp() < CREDIT_FALLBACK_S:
                    return position.state  # wait for the refund's own receipt
                if delivered is None:
                    from . import vault
                    delivered = min(deposited, vault.usdt_balance_raw(position.wallet, fresh=True))
                    flow['refund_exact'] = False
                # What actually came back (Relay keeps its refund gas).
                flow['refund_wei'] = str(min(delivered, deposited))
                # Only the attempt this read observed: a retry since then is untouched.
                _transition(PerpPosition, position.pk, ('bridging',), match={'updated_at': position.updated_at},
                            state='refunded', flow=flow)
            elif status == 'failure':
                PerpPosition.objects.filter(pk=position.pk, state='bridging').update(
                    step_error='relay_failure', updated_at=timezone.now())
        elif state == 'funded':
            live = _live_position(position.wallet, position.market)
            if live is not None:
                _adopt_open(position, live)
            elif _pending_claim(position, 'open_plan') and not _filled_cloid(position):
                _release_lost_open(position)
            elif _filled_cloid(position):
                # Filled (answer lost) and already gone: liquidated or closed
                # before anyone looked. Its opening size and price come from
                # its own fills, so past days keep the exposure they had.
                if _adopt_open(position, _opened_from_fills(position)):
                    _settle_closed(PerpPosition.objects.select_related('market').get(pk=position.pk))
        elif state == 'open':
            live = _live_position(position.wallet, position.market)
            if live is None:
                member_closed = position.close_oid is not None
                if _settle_closed(position) and not member_closed:
                    # Take-profit, stop-loss or liquidation while away.
                    _notify(PerpPosition.objects.select_related('market').get(pk=position.pk))
            else:
                if position.entry_oid and not (position.flow or {}).get('entry_fill_ms'):
                    fill_ms = _entry_fill_ms(position, position.entry_oid)
                    if fill_ms:
                        _merge_flow(position.pk, entry_fill_ms=fill_ms)
                _track_size(position, live)
                _track_costs(position, live)
                index = _pending_claim_index(position, 'margin_plan')
                if index is not None:
                    plan = (position.flow or {}).get('margin_plan') or {}
                    step = plan['steps'][index]
                    stored = (position.flow or {}).get('margin_pending_payload')
                    outcome = None
                    if step['purpose'] == 'margin_add' and stored and stored.get('action') == step['action']:
                        # The signed top-up itself, re-posted: Hyperliquid either
                        # applies it now or says its nonce was already used.
                        outcome = _repost(stored)
                    observed = {'issued_ms': plan.get('issued_ms'), 'claim': (plan.get('claims') or {}).get(str(index))}
                    if step['purpose'] == 'margin_add' and (outcome == 'ok' or (
                            outcome in (None, 'used', 'nonce') and _margin_add_applied(position, live))):
                        with transaction.atomic():
                            # Only the plan and claim this read observed: a newer
                            # top-up's claim (and its payload) is never touched.
                            locked = PerpPosition.objects.select_for_update().get(pk=position.pk)
                            now_plan = (locked.flow or {}).get('margin_plan') or {}
                            if (now_plan.get('issued_ms') == observed['issued_ms']
                                    and (now_plan.get('claims') or {}).get(str(index)) == observed['claim']):
                                _apply_margin_add(position.pk, plan.get('change_id'),
                                                  Decimal(step['action']['ntli']) / 1_000_000)
                                _settle_claim(position.pk, 'margin_plan', index, 'consumed',
                                              margin_pending_payload=None)
                    elif outcome in ('used', 'nonce'):
                        # Applied or not, unknowable: never re-plan a second
                        # top-up. The money is on the account and comes home
                        # with the position's return (the whole free balance).
                        PerpPosition.objects.filter(pk=position.pk).update(step_error='margin_unconfirmed')
                    elif outcome == 'rejected' or (
                            outcome is None
                            and _now_ms() - int((plan['claims'][str(index)] or {}).get('at') or 0) > 120_000):
                        # Unanswered and not visible on the venue: a fresh plan
                        # (it reads the dex balance, so a transfer is never repeated).
                        _settle_claim(position.pk, 'margin_plan', index, 'released', observed=observed)
                # Rotate open positions through the reconciler's window.
                PerpPosition.objects.filter(pk=position.pk, state='open').update(updated_at=timezone.now())
        elif state == 'returning':
            pending = (position.flow or {}).get('return_pending') or {}
            status_body = _relay_status(position.relay_back_id)
            status = status_body.get('status')
            if status == 'success':
                delivered = _delivered_usdt(status_body, position.wallet)
                landed_for = time.time() - int(pending.get('at') or 0)
                if delivered is None and landed_for > CREDIT_FALLBACK_S:
                    delivered = int(pending.get('minimum_out') or 0)
                if delivered:
                    flow = dict(position.flow or {})
                    flow['landed_wei'] = str(delivered)
                    if _transition(PerpPosition, position.pk, ('returning',),
                                   match={'relay_back_id': position.relay_back_id}, state='landed', flow=flow):
                        if landed_for > 120:
                            _notify(PerpPosition.objects.select_related('market').get(pk=position.pk), 'landed')
            elif status == 'refund':
                # Relay sent the USDC back to the member's Hyperliquid balance.
                _transition(PerpPosition, position.pk, ('returning',),
                            match={'relay_back_id': position.relay_back_id}, state='return_failed',
                            step_error='relay_refund')
            elif status == 'failure':
                # Not final: Relay refunds a failed order. Keep following it.
                PerpPosition.objects.filter(pk=position.pk, state='returning').update(
                    step_error='relay_failure', updated_at=timezone.now())
            elif pending.get('payload') and time.time() - int(pending.get('at') or 0) > RETURN_RESEND_S:
                if int(pending.get('deadline') or 0) > time.time() + 15:
                    # Same signed transfer again (Hyperliquid refuses a used nonce).
                    if _send_return(position.pk, pending['payload']) == 'rejected':
                        _transition(PerpPosition, position.pk, ('returning',),
                                    match={'relay_back_id': position.relay_back_id}, state='return_failed',
                                    step_error='send_rejected')
                elif time.time() > int(pending.get('deadline') or 0) + 900:
                    nonce = (pending.get('payload') or {}).get('nonce')
                    sent = _return_sent(position.wallet, nonce, int(pending.get('at') or 0) * 1000 - 600_000)
                    if sent is False:
                        # The quote lapsed and the member's ledger shows no
                        # transfer: nothing left. Quote again.
                        _transition(PerpPosition, position.pk, ('returning',),
                                    match={'relay_back_id': position.relay_back_id}, state='return_failed',
                                    step_error='return_expired')
                    # Sent (or unknown): Relay delivers or refunds it; keep waiting.
        elif state == 'refunded':
            refunded_at = int((position.flow or {}).get('refunded_at') or 0)
            if refunded_at and time.time() - refunded_at > REFUND_HOLD_S:
                # Unclaimed refund: released to the ordinary sweep (back to dollars).
                _transition(PerpPosition, position.pk, ('refunded',), state='cancelled')
        elif state == 'landed':
            if position.return_batch_id is not None:
                batch = SponsoredBatch.objects.filter(pk=position.return_batch_id).first()
                if batch is not None and (batch.status == 'confirmed' or batch.status in DEAD_BATCH_STATUSES):
                    on_receipt(batch)
            elif vault.usdt_balance_raw(position.wallet, fresh=True) == 0:
                PerpPosition.objects.filter(pk=position.pk, state='landed').update(
                    step_error='usdt_missing', updated_at=timezone.now())
    except (hyperliquid.HyperliquidError, perps_relay.RelayError) as exc:
        logger.warning('perps reconcile %s: %s', position.id, exc)

    for change in PerpMarginChange.objects.filter(position=position, state='bridging'):
        if change.batch_id:
            batch = SponsoredBatch.objects.filter(pk=change.batch_id).first()
            if batch is not None and batch.status in DEAD_BATCH_STATUSES:
                on_receipt(batch)
                continue
        status_body = _relay_status(change.relay_id)
        status = status_body.get('status')
        if status == 'success':
            since = int(((change.batch.created_at if change.batch else change.created_at).timestamp() - 120) * 1000)
            credit = _hl_credit(position.wallet, status_body, since)
            if credit is None and time.time() - change.updated_at.timestamp() > CREDIT_FALLBACK_S:
                credit = Decimal(int(((change.flow or {}).get('relay_out') or {}).get('minimum_out') or 0)) / USDC_UNIT
            if credit is not None and credit > 0:
                flow = dict(change.flow or {})
                flow['credited'] = str(credit)
                _transition(PerpMarginChange, change.pk, ('bridging',), state='funded', flow=flow)
        elif status == 'refund':
            # A refunded top-up goes back to dollars through the ordinary sweep.
            flow = dict(change.flow or {})
            delivered = _delivered_usdt(status_body, position.wallet)
            deposited = int(flow.get('deposit_wei') or 0)
            if delivered is None and time.time() - change.updated_at.timestamp() < CREDIT_FALLBACK_S:
                continue
            if delivered is None:
                from . import vault
                delivered = min(deposited, vault.usdt_balance_raw(position.wallet, fresh=True))
            flow['refund_wei'] = str(min(delivered, deposited))
            _transition(PerpMarginChange, change.pk, ('bridging',), state='refunded', flow=flow)
        elif status == 'failure':
            # Not final: Relay refunds a failed order; keep watching for it.
            PerpMarginChange.objects.filter(pk=change.pk).update(step_error='relay_failure', updated_at=timezone.now())
    return PerpPosition.objects.get(pk=position.pk).state


def reserved_usdt_wei(wallet: str) -> int:
    """BSC USDT that belongs to a perps flow and must not be auto-swept: an
    open's deposit while it bridges (a refund can land before anyone looks),
    a refund waiting for the member's choice, and proceeds in flight or
    landed until their entry settles."""
    from blockchain.models import PerpPosition

    total = 0
    for position in PerpPosition.objects.filter(
            wallet=(wallet or '').lower(), state__in=('bridging', 'refunded', 'returning', 'landed')):
        flow = position.flow or {}
        if position.state in ('bridging', 'refunded'):
            retry = flow.get('retry') or {}
            total += int((retry.get('deposit_wei') if retry.get('batch_id') else None)
                         or flow.get('refund_wei') or flow.get('deposit_wei') or 0)
        elif position.state == 'returning':
            total += int((flow.get('return_pending') or {}).get('expected_out') or 0)
        else:
            total += int(flow.get('landed_wei') or 0)
    from blockchain.models import PerpMarginChange

    # A top-up on the bridge: its refund can land any second and is only
    # released to the sweep once its amount is recorded.
    for change in PerpMarginChange.objects.filter(
            position__wallet=(wallet or '').lower(), state='bridging'):
        total += int((change.flow or {}).get('deposit_wei') or 0)
    return total


# ── notifications ───────────────────────────────────────────────────────

_NOTICES = {
    'closed': ('Tu posición en {ticker} se cerró', 'Abre Confío para traer el dinero a tus dólares.'),
    'liquidated': ('Tu posición en {ticker} se liquidó', 'Revisa el resultado en Futuros.'),
    'landed': ('Tu dinero de {ticker} ya llegó', 'Confirma para sumarlo a tus dólares.'),
}


def _notify(position, event: str | None = None) -> None:
    """Only about the member's own money (never promotional)."""
    event = event or position.state
    if event not in _NOTICES:
        return
    try:
        from notifications.utils import create_notification

        from . import perps_catalog

        ticker = perps_catalog.view(position.market).ticker
        title, message = (text.format(ticker=ticker) for text in _NOTICES[event])
        create_notification(
            user=position.user,
            notification_type='PERPS_POSITION_UPDATE',
            title=title,
            message=message,
            data={'position_id': str(position.id), 'event': event, 'coin': position.market.coin},
            related_object_type='PerpPosition',
            related_object_id=str(position.id),
            action_url=f'confio://app/deeplink/FuturesPosition|{position.id}',
        )
    except Exception:  # noqa: BLE001 — a notice never blocks the money flow
        logger.warning('perps notice failed for position %s', position.id, exc_info=True)
