"""Hands-off chat trades by the Cuenta inteligente (hands-off-account design,
2026-11-25): where one trade the person asked for in the chat stands.

Dormant until SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS names the deployed v2
implementation (and the Cuenta inteligente itself is on): with it unset every
chat trade is today's signed card. No tester list or waitlist beyond that
(founder rule: live for everyone once deployed).

`route()` answers, for one proposed trade, which of these the chat offers:

  go         the account trades it hands-off now (relay_trades.py)
  personal   the personal wallet holds it / pays it: today's signed card
  paywall    not a subscriber: "Activa Cuenta inteligente" + "Hazlo tú"
  migrate    an older (v1) account: the one-Face migration prompt
  no_rule    no Trade rule yet (or one pinned to another asset, or one in cUSD): the cap card
  cap        the weekly cap has no room for this buy or sell (both count): offer to raise it
  move       the account is short and the personal wallet has it (after a top-up, say): move it in (Face)
  topup      neither wallet covers the buy: the Koywe top-up form (it lands in the personal wallet;
             asked again, the trade is then 'move')
  off        dormant, paused or anything unread: today's signed card

Every fact is read fresh from the chain; anything unread is 'off', never a
guess that the account trades. The relayer still simulates before sending.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from django.conf import settings
from django.core.cache import cache

from . import abi, chain

logger = logging.getLogger(__name__)

WAD = 10 ** 18
CENT = Decimal('0.01')
CAP_CHOICES = (Decimal('250'), Decimal('1000'), Decimal('2500'))
FREQUENCY = 'weekly'
_ADDRESS = re.compile(r'0x[0-9a-f]{40}')
# EIP-1167 minimal proxy runtime code: the implementation sits in the middle.
_CLONE = re.compile(r'0x363d3d373d3d3d363d73([0-9a-f]{40})5af43d82803e903d91602b57fd5bf3')
IMPL_CACHE_SECONDS = 600


def implementation_address() -> str:
    """The v2 account implementation, or '' while it is not deployed and configured."""
    value = str(getattr(settings, 'SMART_ACCOUNT_V2_IMPLEMENTATION_ADDRESS', '') or '').strip().lower()
    return value if _ADDRESS.fullmatch(value) and int(value, 16) else ''


def enabled() -> bool:
    return bool(implementation_address()) and chain.enabled()


def implementation_of(address: str) -> str:
    """The implementation an account clone delegates to, from its own code."""
    code = str(chain.rpc('eth_getCode', [address, 'latest']) or '').lower()
    found = _CLONE.fullmatch(code)
    if not found:
        raise chain.ChainError(f'{address} is not an EIP-1167 clone')
    return '0x' + found.group(1)


def is_v2(own) -> bool:
    """The account runs the configured v2 implementation. Raises when unread."""
    impl = implementation_address()
    if own is None or not impl:
        return False
    key = f'smart_account:impl:{own.contract_address.lower()}'
    found = cache.get(key)
    if found is None:
        found = implementation_of(own.contract_address)
        cache.set(key, found, IMPL_CACHE_SECONDS)
    return found == impl


def trade_paused() -> bool:
    signature, arg_types, out_types = abi.FACTORY_V2_VIEWS['tradePaused']
    return bool(chain._view(chain.factory_address(), signature, arg_types, [], out_types)[0])


def bucket_of(address: str, rule_id: int) -> tuple[int, int]:
    """(used wei, lastAt): `used` already leaked down to now by the contract."""
    signature, arg_types, out_types = abi.BUCKET_OF
    used, last_at = chain._view(address, signature, arg_types, [int(rule_id)], out_types)
    return int(used), int(last_at)


def trade_rule(own):
    """The live Trade rule of this account's current subscription, from the mirror."""
    from .models import SmartAccountRule
    if own is None:
        return None
    return SmartAccountRule.objects.filter(
        smart_account=own, kind='trade', state='onchain', active=True, onchain_id__isnull=False,
        epoch=own.subscription_epoch).order_by('-pk').first()


def subscribed(user) -> bool:
    try:
        from assistant.billing import has_plus
        return bool(has_plus(user))
    except Exception:  # noqa: BLE001 - unknown is "not subscribed": the paywall, never a trade
        logger.warning('hands-off subscription check failed', exc_info=True)
        return False


def _usd(wei) -> Decimal:
    return (Decimal(int(wei)) / Decimal(WAD)).quantize(CENT, rounding=ROUND_DOWN)


def dollar_usd(token: str, units: int) -> Decimal:
    """US dollars of a Confío dollar balance (cUSD at par, cUSD+ at pPlus)."""
    if token and token == chain.cusd_plus_address():
        return _usd(int(units) * chain.p_plus_wad() // WAD)
    return _usd(units)


# ── the cap the person chooses ──────────────────────────────────────────

def biggest_week_of_buys(user) -> Decimal:
    """The most this person bought in stocks in any 7 days on their
    personal wallet, from its confirmed stock_buy batches. Buys inside the
    Cuenta inteligente (smart_* batches or relayer transactions, in
    inbox/account_trades) are not counted here: a gap from before, not a
    choice."""
    from cusd_plus.stock_month import confirmed_trades
    from .context import personal_account
    # Sponsored batches carry the 7702 wallet, never the Cuenta inteligente
    # contract (its trades live in inbox/account_trades), so only the
    # personal wallet has any here.
    addresses = []
    personal = personal_account(user)
    if personal is not None and personal.bsc_address:
        addresses.append(personal.bsc_address)
    buys = []
    for address in addresses:
        try:
            buys += [(t.when, Decimal(t.usd)) for t in confirmed_trades(address)
                     if t.kind == 'stock_buy' and t.usd is not None]
        except Exception:  # noqa: BLE001 - no history read: the smallest choice
            logger.warning('trade history unreadable for the cap suggestion', exc_info=True)
    buys.sort()
    best = Decimal(0)
    for i, (start, _usd_) in enumerate(buys):
        total = sum((usd for when, usd in buys[i:] if when - start < timedelta(days=7)), Decimal(0))
        best = max(best, total)
    return best


def suggested_cap(user, at_least: Decimal = Decimal(0)) -> Decimal:
    """About twice their biggest week of buys, and never less than this
    trade: the smallest choice that covers it, or a round amount above."""
    from .services import MAX_RULE_USD
    target = max(biggest_week_of_buys(user) * 2, Decimal(at_least))
    for choice in CAP_CHOICES:
        if target <= choice:
            return choice
    rounded = (target / 100).quantize(Decimal('1'), rounding=ROUND_UP) * 100
    return min(rounded, MAX_RULE_USD)


# ── where one trade stands ──────────────────────────────────────────────

@dataclass
class Route:
    code: str
    why: str = ''
    own: object = None
    rule: object = None
    cap: Decimal = Decimal(0)
    room: Decimal = Decimal(0)
    suggested: Decimal = Decimal(0)
    facts: dict = field(default_factory=dict)

    @property
    def hands_off(self) -> bool:
        return self.code == 'go'


def create_trade_authorization(viewer, *, account, amount: Decimal):
    """The owner's Face for a Trade rule, like a Card rule's: claimed once
    when the rule is created or edited, bound to (account, cap, period)."""
    import hashlib
    import json
    from . import payouts
    digest = hashlib.sha256(json.dumps({
        'kind': 'trade', 'account': account.contract_address.lower(), 'frequency': FREQUENCY,
        'amount': format(Decimal(amount).quantize(CENT), 'f')}, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    return payouts._authorize(
        viewer, 'trade', digest, 'smart_account_trade_rule',
        {'account': account.contract_address.lower(), 'amount': format(amount, 'f'), 'frequency': FREQUENCY},
        'Confirma con Confío Face para que Confío pueda operar por ti.', create={},
        terms=dict(payout_destination=None, payee_address='', rail='', amount_usd=amount, frequency=FREQUENCY))


def exact_move(short: Decimal, personal: Decimal) -> Decimal:
    """What a trade's move card moves: the shortfall rounded up to the cent, one cent more for share rounding,
    never more than the wallet holds."""
    return min(Decimal(short).quantize(CENT, rounding=ROUND_UP) + CENT, Decimal(personal).quantize(CENT, rounding=ROUND_DOWN))


def move_amount(short: Decimal, personal: Decimal) -> Decimal:
    """What the move card offers: the shortfall plus a margin when the wallet has it (purchases.move_offer)."""
    from .purchases import move_offer
    return move_offer(short, personal)[1]


def route(user, *, side: str, asset_kind: str, token: str, amount: Decimal | None, sell_all: bool,
          personal_address: str = '') -> Route:
    """Which of the module docstring's paths this trade takes."""
    from .context import own_account
    if not enabled():
        return Route('off', why='dormant')
    own = own_account(user)
    if not subscribed(user) or own is None or own.status not in ('active', 'cancel_pending'):
        return Route('paywall', own=own)
    if own.billing_status != 'current':
        return Route('off', own=own, why='billing')
    token = (token or '').lower()
    try:
        if not is_v2(own):
            return Route('migrate', own=own)
        if trade_paused():
            return Route('off', own=own, why='paused')
        rule = trade_rule(own)
        held = chain.balance_of(token, own.contract_address) if side == 'sell' and token else 0
        if side == 'sell' and held <= 0:
            # Account first; what only the personal wallet holds is sold from there (signed card).
            return Route('personal', own=own, why='held_in_personal')
        if rule is None:
            return Route('no_rule', own=own, suggested=suggested_cap(user, amount or 0))
        onchain = chain.account_rule(own.contract_address, int(rule.onchain_id))
        if onchain['kind'] != 'trade' or not onchain['active']:
            return Route('no_rule', own=own, suggested=suggested_cap(user, amount or 0))
        if onchain['token_in'] != chain.cusd_plus_address():
            # Trade rules are cUSD+ only: an older cUSD one is replaced through the cap card.
            return Route('no_rule', own=own, suggested=suggested_cap(user, amount or 0))
        if onchain['token_out'] not in (abi.ZERO_ADDRESS, token):
            # Pinned to another asset: the same card widens it to every asset.
            return Route('no_rule', own=own, rule=rule, suggested=suggested_cap(user, amount or 0))
        cap_wei = int(onchain['amount_usd_wei'])
        used, _last = bucket_of(own.contract_address, int(rule.onchain_id))
        cap, room = _usd(cap_wei), _usd(max(0, cap_wei - used))
        facts = dict(own=own, rule=rule, cap=cap, room=room)
        if side == 'sell':
            # Sells count in the bucket too (audit): their dollar value, the whole holding for "todo".
            value = sell_value(own, token, amount, sell_all)
            if value > room:
                return Route('cap', suggested=suggested_cap(user, cap + value), **facts)
            return Route('go', **facts)
        amount = Decimal(amount or 0)
        if amount > room:
            return Route('cap', suggested=suggested_cap(user, cap + amount), **facts)
        dollar = chain.cusd_plus_address()
        account_usd = dollar_usd(dollar, chain.balance_of(dollar, own.contract_address))
        if account_usd >= amount:
            return Route('go', **facts)
        short = amount - account_usd
        personal_usd = (dollar_usd(dollar, chain.balance_of(dollar, personal_address))
                        if personal_address else Decimal(0))
        if personal_usd >= short:
            # A trade moves only what is missing (founder, 2026-11-25), plus a cent for share rounding; the
            # purchase cushion (purchases.move_offer) is for store and Comprar purchases.
            return Route('move', facts={'short': short, 'personal': personal_usd,
                                        'move': exact_move(short, personal_usd)}, **facts)
        return Route('topup', facts={'short': short}, **facts)
    except Exception as exc:  # noqa: BLE001 - unread is never "the account trades"
        logger.warning('hands-off route unreadable: %s', type(exc).__name__, exc_info=True)
        return Route('off', own=own, why='unread')


def sell_value(own, token: str, amount, sell_all: bool) -> Decimal:
    """US dollars a sell of `token` from the account is worth: what was asked,
    or the whole holding's value for "todo" (never more than it holds)."""
    from . import assets as assets_mod
    value = Decimal(0)
    for asset in assets_mod.assets_of(own.contract_address):
        if asset.address.lower() == token:
            value = Decimal(asset.value_usd or 0)
    return value if sell_all or amount is None else min(Decimal(amount), value)


def gap_wait_seconds(own, rule) -> int:
    """Seconds until the contract's minimum gap between relay trades passed."""
    _used, last_at = bucket_of(own.contract_address, int(rule.onchain_id))
    return max(0, int(last_at) + abi.RELAY_TRADE_MIN_GAP_SECONDS - int(time.time()))
