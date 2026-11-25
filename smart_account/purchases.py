"""Purchases by the assistant, paid by the account (spec decisions 37 to 42, 3.6).

One Card rule (decision 35), "Compras con Confío IA", whose payee is Confío's
purchase spender (contracts/smart_account/ConfioPurchaseSpender.sol), signed
once by the owner with Face: US$200 per 28 days by default, editable. For a
purchase the owner approved in the chat, Confío's operator (the BSC KMS
sponsor, the spender's immutable operator) calls the spender's pullTo: the
account's own cardPull sends exactly the purchase's USDT to the spender,
through the normal 0.9% exit counted against the cap, and the spender
forwards all of it to that one payment's bridge deposit in the same
transaction. Confío never holds the money.

This module answers three things and moves nothing by itself:
  - where a purchase stands (`standing`): the account pays it, it must first
    be moved in from the personal wallet, the cap is reached, or nothing
    pays it here;
  - the owner-signed batches the app shows (`prepare_purchase_rule`,
    `prepare_move_for_purchase`), through the ordinary prepare flows;
  - the one relayer call (`pull_call`, `simulate_pull`, `send_pull`).

Card rule creation stays behind SMART_ACCOUNT_CARD_RULES_ENABLED
(cards.creation_enabled), and nothing here runs without
SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_UP, Decimal, InvalidOperation

from django.conf import settings

from . import abi, cards, chain

logger = logging.getLogger(__name__)

WAD = 10 ** 18
BPS = 10_000
CENT = Decimal('0.01')
RULE_LABEL = 'Compras con Confío IA'
DEFAULT_CAP_USD = Decimal('200.00')
# 28 days: the Card rule's 'monthly' period (cards.period_days).
FREQUENCY = 'monthly'
# ConfioSmartAccount's cardPull: a cUSD+ pull redeems the gross plus this
# margin and rounding (PAYOUT_UNWRAP_MARGIN_BPS, CARD_REDEEM_ROUNDING).
PLUS_MARGIN_BPS = 5
PLUS_ROUNDING_WEI = 10
# A move offered from the personal wallet is more than this purchase
# (decision 39): the shortfall plus this, rounded up to whole dollars.
MOVE_EXTRA_USD = Decimal('20')
_ADDRESS = re.compile(r'0x[0-9a-f]{40}')


def spender_address() -> str:
    """The purchase spender, or '' while it is not deployed and configured."""
    value = str(getattr(settings, 'SMART_ACCOUNT_PURCHASE_SPENDER_ADDRESS', '') or '').strip().lower()
    return value if _ADDRESS.fullmatch(value) and int(value, 16) else ''


def sponsor_address() -> str:
    """The relayer key: the spender's immutable operator."""
    value = str(getattr(settings, 'BSC_SPONSOR_ADDRESS', '') or '').strip().lower()
    return value if _ADDRESS.fullmatch(value) else ''


def purchase_rule(own):
    """The live "Compras con Confío IA" rule of this account, from the mirror:
    on chain, active, a Card rule of the current subscription, paying the
    purchase spender. None otherwise."""
    from .models import SmartAccountRule
    spender = spender_address()
    if own is None or not spender:
        return None
    return SmartAccountRule.objects.filter(
        smart_account=own, kind='card', state='onchain', active=True, onchain_id__isnull=False,
        payee_address__iexact=spender, epoch=own.subscription_epoch).order_by('-pk').first()


def gross_wei(usdt_out_wei: int, fee_bps: int) -> int:
    """cardPull's own arithmetic: the smallest gross whose net after cUSD's
    ceil-rounded exit fee is exactly usdt_out. This is what the cap counts."""
    fee_bps = int(fee_bps)
    if not 0 <= fee_bps < BPS:
        raise ValueError('fee_bps')
    return (int(usdt_out_wei) * BPS + (BPS - fee_bps) - 1) // (BPS - fee_bps)


def plus_shares_needed(gross: int, p_plus: int) -> int:
    """cUSD+ shares a pull of `gross` redeems (gross, margin and rounding)."""
    usd = gross + gross * PLUS_MARGIN_BPS // BPS + PLUS_ROUNDING_WEI
    return (usd * WAD + p_plus - 1) // p_plus


def usd(wei) -> Decimal:
    return (Decimal(int(wei)) / Decimal(WAD)).quantize(CENT, rounding=ROUND_UP)


@dataclass
class Standing:
    """Where one purchase stands (spec 3.6). `code`:

      pay        the account pays it now, within the cap's room
      move       the account is short; the personal wallet holds the rest
      topup      neither has it
      cap        the period's cap has no room for it
      no_rule    subscribed, purchases not switched on (or not authorized)
      off        no purchase spender, no active account, or anything unread

    Figures are US dollars; `gross` is what the cap counts (exit fee in).

    `why`, for 'off' only: 'spender' (none configured), 'chain' (BSC reads
    off), 'account' (no account of theirs, or it is not active or not paid:
    the person can renew it), 'spender_mirror' (the spender is not in the
    mirror's allowlist), 'spender_chain' (the factory does not allow it now:
    removed or cards paused) or 'unread' (a read failed)."""
    code: str
    why: str = ''
    own: object = None
    rule: object = None
    gross: Decimal = Decimal(0)
    room: Decimal = Decimal(0)
    cap: Decimal = Decimal(0)
    short: Decimal = Decimal(0)
    personal: Decimal = Decimal(0)

    @property
    def pays(self) -> bool:
        return self.code == 'pay'


def _period_spent(onchain: dict, spent_wei: int, now: int) -> int | None:
    """What the cap has counted in the period running now, as cardPull reads
    it, or None before the rule's first period starts (TooEarly)."""
    start, gap = int(onchain['next_run_at']), abi.MIN_GAP_DAYS[onchain['frequency']] * 86400
    if now < start:
        return None
    return 0 if now >= start + gap else int(spent_wei)


def standing(user, usdt_out_wei: int, *, personal_address: str = '') -> Standing:
    """Where a purchase of exactly `usdt_out_wei` USDT stands. Every fact the
    contract checks is read fresh from the chain; anything unread is 'off'
    (the person's own card, as before), never a guess that the account pays.
    The relayer's simulation is asked again right before the pull."""
    from . import context, payouts
    usdt_out_wei = int(usdt_out_wei)
    spender = spender_address()
    if usdt_out_wei <= 0 or not spender:
        return Standing('off', why='spender')
    if not chain.enabled():
        return Standing('off', why='chain')
    own = context.own_account(user)
    if own is None or own.status not in ('active', 'cancel_pending') or own.billing_status != 'current':
        return Standing('off', own=own, why='account')
    rule = purchase_rule(own)
    if rule is None or payouts.card_authorization_problem(rule) is not None:
        return Standing('no_rule', own=own)
    if cards.allowed_spender(spender) is None:
        return Standing('off', own=own, why='spender_mirror')
    try:
        if not chain.card_spender_allowed(spender):
            return Standing('off', own=own, why='spender_chain')
        onchain = chain.account_rule(own.contract_address, rule.onchain_id)
        if (onchain['kind'] != 'card' or not onchain['active'] or onchain['payee'] != spender
                or onchain['token_in'] != (rule.token_in or '').lower()):
            return Standing('no_rule', own=own)
        spent = _period_spent(onchain, chain.card_spent_usd_wei(own.contract_address, rule.onchain_id),
                              int(time.time()))
        if spent is None:
            return Standing('no_rule', own=own, rule=rule)
        fee_bps = chain.conversion_fee_bps()
        gross = gross_wei(usdt_out_wei, fee_bps)
        cap_wei = int(onchain['amount_usd_wei'])
        room = max(0, cap_wei - spent)
        facts = dict(own=own, rule=rule, gross=usd(gross), cap=usd(cap_wei),
                     room=(Decimal(room) / Decimal(WAD)).quantize(CENT, rounding=ROUND_DOWN))
        if gross > room:
            return Standing('cap', **facts)
        token = onchain['token_in']
        held = chain.balance_of(token, own.contract_address)
        if token == chain.cusd_plus_address():
            p_plus = chain.p_plus_wad()
            needed_shares = plus_shares_needed(gross, p_plus)
            if held >= needed_shares:
                return Standing('pay', **facts)
            short_wei = (needed_shares - held) * p_plus // WAD + 1
            personal_wei = (chain.balance_of(token, personal_address) * p_plus // WAD) if personal_address else 0
        else:
            if held >= gross:
                return Standing('pay', **facts)
            short_wei = gross - held
            personal_wei = chain.balance_of(token, personal_address) if personal_address else 0
    except Exception as exc:  # noqa: BLE001 - unread is never "the account pays"
        logger.warning('purchase standing unreadable: %s', type(exc).__name__)
        return Standing('off', own=own, why='unread')
    short = usd(short_wei)
    personal = (Decimal(personal_wei) / Decimal(WAD)).quantize(CENT, rounding=ROUND_DOWN)
    return Standing('move' if personal >= short else 'topup', short=short, personal=personal, **facts)


def move_offer(short: Decimal, personal: Decimal) -> tuple[Decimal, Decimal]:
    """(the least to move, the amount offered) for a purchase the account is
    short of (decision 39): more than this purchase when the wallet has it."""
    least = Decimal(short).quantize(CENT, rounding=ROUND_UP)
    offered = (least + MOVE_EXTRA_USD).quantize(Decimal('1'), rounding=ROUND_UP)
    offered = min(offered, Decimal(personal).quantize(CENT, rounding=ROUND_DOWN))
    return least, max(least, offered)


# ── owner-signed: switching purchases on, raising the cap, moving money in ──

def prepare_purchase_rule(viewer, amount_usd=DEFAULT_CAP_USD):
    """The "Compras con Confío IA" Card rule, created or (with a live one)
    edited to `amount_usd` per 28 days: the ordinary Card rule batch, signed
    with Face (payouts.create_card_authorization). Behind
    SMART_ACCOUNT_CARD_RULES_ENABLED like every Card rule."""
    from . import context, services
    spender = spender_address()
    if not spender:
        raise services.PrepareError('card_not_available')
    existing = purchase_rule(context.own_account(viewer.user))
    return services.prepare_card_rule(viewer, str(existing.internal_id) if existing else None, spender,
                                      amount_usd, FREQUENCY)


def _move_amount(value) -> Decimal:
    from . import services
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise services.PrepareError('bad_amount') from exc
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(CENT) \
            or amount > services.MAX_RULE_USD:
        raise services.PrepareError('bad_amount')
    return amount


def prepare_move_for_purchase(viewer, amount_usd):
    """Personal wallet -> account, `amount_usd` in the account's own dollar
    (decision 17), as the ordinary deposit batch: signed by the owner with
    Face like any move out of the personal wallet (decision 39)."""
    from . import context, services
    amount = _move_amount(amount_usd)
    own = context.own_account(viewer.user)
    if own is None:
        raise services.PrepareError('no_account')
    rule = purchase_rule(own)
    token = (rule.token_in if rule is not None else '') or services.account_dollar_token(own, viewer.user, viewer.meta)
    token = token.lower()
    if token == chain.cusd_plus_address():
        units = (int(amount * WAD) * WAD + services._chain(chain.p_plus_wad) - 1) // services._chain(chain.p_plus_wad)
        key = 'cusd_plus'
    elif token == chain.cusd_address():
        units, key = int(amount * WAD), 'cusd'
    else:
        raise services.PrepareError('chain_unavailable')
    return services.prepare_deposit(viewer, [{'asset_key': key, 'units': str(units)}])


# ── the relayer's call ──────────────────────────────────────────────────

def ref_for(request_id) -> bytes:
    """The pull's `ref`: the purchase payment's request id, so the event ties
    the pull to one approved purchase."""
    return uuid.UUID(str(request_id)).bytes.rjust(32, b'\0')


def pull_call(own, rule, usdt_out_wei: int, to: str, request_id) -> str:
    return abi.purchase_pull_call(own.contract_address, int(rule.onchain_id), int(usdt_out_wei), to,
                                  ref_for(request_id))


def simulate_pull(calldata: str) -> None:
    """The pull as the operator would send it, under its real gas budget.
    Raises relayer.RelayError (nothing is ever sent from here)."""
    from . import relayer
    spender, sponsor = spender_address(), sponsor_address()
    if not spender or not sponsor:
        raise relayer.RelayError('disabled')
    relayer.simulate(sponsor, spender, calldata, abi.RELAY_GAS[abi.PURCHASE_KIND])


def send_pull(own, calldata: str, source_id, *, claim=None):
    """Sign and broadcast the pull once per `source_id` (relayer.send_relayer_call:
    the durable row first, idempotent while one is live)."""
    from . import relayer
    return relayer.send_relayer_call(own, calldata, abi.PURCHASE_KIND, source_id, claim=claim)
