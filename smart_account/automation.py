"""Bodies of the relayer tasks (spec 7.8): fee collection, payment notices,
forced sales, USDT conversion, rule execution, expiry returns, claim notices.

Rules for every function here:
- a no-op unless SMART_ACCOUNT_ENABLED and the factory address are set,
  except the protective ones (return_expired, claim_notices), which need
  only the factory: the flag being off must never trap assets or keep an
  owner from hearing that their account is being claimed;
- chain state is read fresh before any transaction; the mirror only says
  which accounts to look at;
- idempotent on (account, kind, period or rule run) through
  relayer.send_relayer_call;
- fail closed: an RPC or quote failure for one account leaves that account
  unchanged, is counted and logged, and is retried on the next run. It is
  never recorded as "nothing to do".
"""
from __future__ import annotations

import calendar
import logging
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import abi, assets as assets_mod, chain, notifications, quotes, relayer
from .models import (
    SmartAccount, SmartAccountBeneficiary, SmartAccountClaim, SmartAccountForcedSale,
    SmartAccountForcedSaleLeg, SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun,
)

logger = logging.getLogger(__name__)

WAD = 10 ** 18
BPS = 10_000
FORCED_SALE_MARGIN_BPS = 500          # contract cap: shortfall + 5% + US$1
FORCED_SALE_ROUNDING_WEI = WAD
RULE_SLOT_GIVE_UP = timedelta(hours=24)
NO_BALANCE = 'insufficient_balance'
BALANCE_GIVE_UP = timedelta(days=3)     # founder, 2026-11-22: no balance, monthly rules only
NO_BALANCE_TEXT = 'No había saldo suficiente en tu Cuenta inteligente.'
# A closed session, and one that could not be read: waited out to the next slot.
MARKET_WAITS = ('market_closed', 'market_status_unavailable')
# Kept by the waits that follow them and through a dropped transaction.
CARRIED_WAITS = (NO_BALANCE,) + MARKET_WAITS
NOT_PAID = 'No hicimos este pago.'
NOT_DONE = {'payout': 'No hicimos este pago', 'send': 'No hicimos este envío', 'buy': 'No hicimos esta compra'}
NOT_COMPLETED = 'No se pudo completar.'
UNCONFIRMED = 'No pudimos confirmar si este pago salió de tu Cuenta inteligente. Lo estamos revisando: no lo repitas.'
SESSION_UNKNOWN = 'No pudimos confirmar si el mercado está abierto: lo haremos cuando lo esté, antes de tu próxima fecha.'
MARKET_WAIT = 'El mercado está cerrado: lo haremos cuando abra, si es antes de tu próxima fecha.'
# What the owner can do about a skip that is retried.
RETRY_ACTION = {
    NO_BALANCE: 'Agrega saldo', 'account_unavailable': 'Escríbenos por soporte',
    'identity_hold': 'Escríbenos por soporte', 'trade_not_available': 'Escríbenos por soporte',
    'review_amount_cap': 'Edita la regla con un monto menor',
}
# Why a held owner's slot was given up: what they can do about it.
HELD_TEXT = {
    'account_suspended': 'Tu cuenta está suspendida. Escríbenos por soporte.',
    'identity_hold': 'Tu cuenta está en revisión. Escríbenos por soporte.',
    'account_unavailable': 'Tu cuenta no está disponible. Escríbenos por soporte.',
    'owner_held': 'Tu cuenta está en revisión. Escríbenos por soporte.',
}


def _held_text(error: str) -> str:
    code = _code(error)
    if code == 'owner_held':     # "owner_held: <the refusal's code>"
        return HELD_TEXT.get((error or '').partition(':')[2].strip(), HELD_TEXT[code])
    return HELD_TEXT.get(code, '')


# The assistant reads 160 characters of a run's message: the date must fit.
RETRY_TEXT_MAX = 160
# Nothing was broadcast, and the next pass reads the new state or gets the
# lock: the slot waits with its order.
RELAY_WAITS = ('rule_changed', 'rule_unreadable', 'order_closed', 'claim_busy', 'sponsor_lock_lost', 'sponsor_busy',
               'owner_held')
# Nothing was signed, for a reason of Confío's that may last: the slot waits
# too, its order stops holding the owner's accounts, and ops see an error.
INFRA_WAITS = ('simulation_unreadable', 'gas_price_too_high', 'sponsor_balance_low')
# Today's cost or rate outside the rule's signed limits: the slot is asked
# again, and its unfunded order stops holding the owner's accounts meanwhile.
LIMIT_RETRIES = ('bridge_cost_above_limit', 'fx_rate_below_limit')
# Each retry prices a new route: asked again hourly, not every pass.
LIMIT_RETRY_EVERY = timedelta(hours=1)
RUN_SENT = ('sent', 'ok')
MAX_SALE_LEGS = abi.MAX_SALE_LEGS


def _ready() -> bool:
    return chain.enabled()


def _report(name: str, out: dict) -> dict:
    """Errors are visible: logged, returned and alerted (deduped)."""
    if out.get('errors'):
        logger.error('smart_account.%s finished with errors: %s', name, out)
        try:
            from config.ops_alerts import send_ops_alert
            send_ops_alert(f'Cuenta inteligente · {name}: {out["errors"]} cuentas con error (se reintenta)',
                           dedupe_key=f'smart_account_task_errors_{name}', dedupe_seconds=3600)
        except Exception:  # noqa: BLE001
            logger.exception('ops alert failed')
    return out


def _referrer(account) -> tuple[str, int]:
    """(referrer, shareBps) for a relayer call that converts (decision 32),
    or (zero, 0). Off unless SMART_ACCOUNT_RELAYER_REFERRAL_ENABLED: an arm
    reverts until CusdVault recognises this factory."""
    if not getattr(settings, 'SMART_ACCOUNT_RELAYER_REFERRAL_ENABLED', False):
        return abi.ZERO_ADDRESS, 0
    from cusd_plus import fee_referral
    owner_address = (account.owner_account.bsc_address or '').lower()
    arm = fee_referral.eligible_arm(account.owner_user, owner_address)
    if arm is None or not fee_referral.onchain_ready() or arm.referrer_address.lower() == owner_address:
        return abi.ZERO_ADDRESS, 0
    return arm.referrer_address, int(arm.share_bps)


def _billing_candidates():
    """Own accounts whose paid period has ended without a signed cancel."""
    return (SmartAccount.objects
            .filter(plan__in=('monthly', 'annual'), paid_until__lte=timezone.now(),
                    cancel_requested_at__isnull=True, inherited_at__isnull=True)
            .select_related('owner_user', 'owner_account'))


def _billing_state(account) -> dict:
    """Fresh from the contract; raises when unreadable."""
    address = account.contract_address
    return {
        'status': int(chain.account_view(address, 'status')),
        'billing': int(chain.account_view(address, 'billingStatus')),
        'paid_until': int(chain.account_view(address, 'paidUntil')),
        'fee': int(chain.account_view(address, 'feeUsd')),
        'dollars': int(chain.account_view(address, 'dollarsUsd')),
        'notice_started_at': int(chain.account_view(address, 'noticeStartedAt')),
        'forced_sale_for_period': int(chain.account_view(address, 'forcedSaleForPeriod')),
    }


def _dollars_window(account, state) -> tuple[int, int]:
    """(least, most) dollarsUsd the contract can see when a call sent now is
    mined. collectFee, startPaymentNotice and forcedSale all accrue() first,
    so cUSD+ counts at the post-accrual pPlus, never the stored one the
    dollarsUsd view used. Without cUSD+ shares both are the view's value."""
    plus = chain.cusd_plus_address()
    shares = chain.balance_of(plus, account.contract_address) if plus else 0
    if not shares:
        return state['dollars'], state['dollars']
    cusd_token = chain.cusd_address()
    cusd = chain.balance_of(cusd_token, account.contract_address) if cusd_token else 0
    low, high = quotes.plus_price_window()
    return cusd + shares * low // WAD, cusd + shares * high // WAD


# ── USDT first (spec 4.6) ───────────────────────────────────────────────
# startPaymentNotice and forcedSale revert DollarsCover while the dollars,
# or the dollars plus the USDT convertUsdt would turn into dollars (net of
# the cUSD entry fee), cover the fee. The billing jobs convert the USDT
# first and treat DollarsCover as "no sale needed", never as an error.

def _usdt_net_wei(account) -> tuple[int, int]:
    """(USDT balance, the dollars it converts to net of the entry fee),
    read fresh. (0, 0) with no USDT configured."""
    usdt = chain.usdt_address()
    if not usdt:
        return 0, 0
    balance = chain.balance_of(usdt, account.contract_address)
    if balance <= 0:
        return 0, 0
    return balance, balance * (BPS - chain.conversion_fee_bps()) // BPS


def _usdt_may_cover(account, state, most_dollars: int) -> bool:
    """The contract's _covers may hold through the USDT: its net value
    reaches the gap at the most dollars the contract can see."""
    _balance, net = _usdt_net_wei(account)
    return net > 0 and net >= state['fee'] - most_dollars


def convert_account_usdt(account, *, for_fee: bool = False) -> bool:
    """Send one convertUsdt for this account. Returns whether a new
    transaction was sent (False: none needed, or one is already on the
    wire). Raises RelayError when it could not be sent.

    The dollar minted is the owner's by eligibility, as convert_usdt. For a
    fee (`for_fee`) a balance under the cUSD+ safe-mint floor is minted as
    cUSD instead of waiting for more USDT: the fee must not wait on it."""
    from cusd_plus import vault
    from cusd_plus.crypto_policy import DOLLAR, DOLLAR_PLUS
    from cusd_plus.eligibility import is_ondo_eligible
    balance, _net = _usdt_net_wei(account)
    if balance <= 0:
        return False
    dollar = DOLLAR_PLUS if is_ondo_eligible(account.owner_user) else DOLLAR
    if not vault.is_safe_mint_amount(balance):
        if not for_fee:
            return False
        dollar = DOLLAR
    fee_bps = chain.conversion_fee_bps()
    # The contract's floor is fee + 0.5%; ask for fee + 0.3%.
    min_out = balance * (BPS - fee_bps - 30) // BPS
    referrer, share = _referrer(account)
    _row, created = relayer.send_relayer_call(
        account, abi.encode_call('convertUsdt', dollar, min_out, referrer, share),
        'smart_convert_usdt', _sequence(account, 'smart_convert_usdt', 'usdt'))
    return created


def _dollars_cover(exc: Exception) -> bool:
    """A relayer simulation that reverted DollarsCover."""
    return (isinstance(exc, relayer.RelayError) and exc.code == 'simulation_reverted'
            and abi.revert_error(exc.detail) == 'DollarsCover')


def _covered(account, out: dict) -> None:
    """The fee is covered once the USDT is converted: convert it now
    (collectFee follows on the next run). Counted, never an error."""
    out['covered'] = out.get('covered', 0) + 1
    try:
        convert_account_usdt(account, for_fee=True)
    except relayer.RelayError as exc:
        # Retried on the next run (and by convert_usdt); not an alert storm.
        logger.warning('USDT conversion before the fee not sent for %s: %s', account.contract_address, exc)


# ── fees and notices ────────────────────────────────────────────────────

def collect_due_fees() -> dict:
    out = {'sent': 0, 'short': 0, 'skipped': 0, 'errors': 0}
    if not _ready():
        return {'skipped': 'disabled'}
    if chain.relayer_paused():
        return {'skipped': 'relayer_paused'}
    for account in _billing_candidates():
        try:
            state = _billing_state(account)
            if state['status'] != 1 or state['billing'] == 0:
                out['skipped'] += 1  # the mirror is behind the chain
                continue
            least, most = _dollars_window(account, state)
            if least < state['fee']:
                if _usdt_may_cover(account, state, most):
                    _covered(account, out)  # the USDT pays it once converted
                else:
                    out['short'] += 1
                continue
            _row, created = relayer.send_relayer_call(
                account, abi.encode_call('collectFee'), 'smart_collect_fee', f'period:{state["paid_until"]}')
            out['sent' if created else 'skipped'] += 1
        except Exception:  # noqa: BLE001 — unchanged, retried next run
            logger.exception('collect fee failed for %s', account.contract_address)
            out['errors'] += 1
    return _report('collect_due_fees', out)


def sale_candidates(account) -> list:
    """Assets a forced sale may sell, largest dollar value first (5.3).
    CONFIO joins the order once the account has latched a CONFIO sale venue
    (5.5), read fresh from the chain (the mirror's flag can lag)."""
    confio_sale = chain.confio_sale_of(account.contract_address)
    if confio_sale is not None and not account.confio_sale_latched:
        SmartAccount.objects.filter(pk=account.pk).update(confio_sale_latched=True)
    held = assets_mod.assets_of(account.contract_address, confio_sale=confio_sale)
    sellable = [a for a in held if a.kind in ('stock', 'crypto', 'confio') and a.can_pay_fee and a.value_usd]
    return sorted(sellable, key=lambda a: a.value_usd, reverse=True)


def sale_candidate_symbols(account) -> list[str]:
    try:
        return [a.symbol for a in sale_candidates(account)][:MAX_SALE_LEGS]
    except Exception:  # noqa: BLE001 — display only
        logger.warning('sale candidates unavailable for %s', account.contract_address, exc_info=True)
        return []


def start_payment_notices() -> dict:
    out = {'sent': 0, 'notified': 0, 'skipped': 0, 'errors': 0}
    if not _ready():
        return {'skipped': 'disabled'}
    paused = chain.relayer_paused()
    now = timezone.now()
    for account in _billing_candidates():
        try:
            state = _billing_state(account)
            if state['status'] != 1 or state['billing'] == 0 or state['dollars'] >= state['fee']:
                out['skipped'] += 1
                continue
            most = _dollars_window(account, state)[1]
            if most < state['fee'] and _usdt_may_cover(account, state, most):
                # Covered once the USDT is converted: no notice (it would
                # revert DollarsCover) and no "fee due" message.
                if not paused:
                    _covered(account, out)
                else:
                    out['covered'] = out.get('covered', 0) + 1
                continue
            if state['notice_started_at'] == 0 and not paused and most < state['fee']:
                # (startPaymentNotice reverts when the accrued dollars cover the fee.)
                try:
                    _row, created = relayer.send_relayer_call(
                        account, abi.encode_call('startPaymentNotice'), 'smart_payment_notice',
                        f'period:{state["paid_until"]}')
                except relayer.RelayError as exc:
                    if not _dollars_cover(exc):
                        raise
                    _covered(account, out)
                    continue
                out['sent' if created else 'skipped'] += 1
            # "Fee due and dollars short": at period end, then daily until paid.
            if account.last_due_notice_at is None or now - account.last_due_notice_at >= timedelta(hours=23):
                if SmartAccount.objects.filter(pk=account.pk).filter(
                        last_due_notice_at=account.last_due_notice_at).update(last_due_notice_at=now):
                    notifications.safe(notifications.fee_due, account, chain.usd(state['fee']),
                                       chain.usd(state['fee'] - state['dollars']))
                    out['notified'] += 1
            # The day before a forced sale, once per notice.
            sale_at = account.sale_allowed_at
            if (sale_at is not None and now >= sale_at - timedelta(days=1)
                    and account.sale_eve_notified_for != sale_at):
                if SmartAccount.objects.filter(pk=account.pk).exclude(
                        sale_eve_notified_for=sale_at).update(sale_eve_notified_for=sale_at):
                    notifications.safe(notifications.forced_sale_eve, account, sale_candidate_symbols(account))
        except Exception:  # noqa: BLE001
            logger.exception('payment notice failed for %s', account.contract_address)
            out['errors'] += 1
    return _report('start_payment_notices', out)


# ── forced sale ─────────────────────────────────────────────────────────

class NothingSellable(Exception):
    pass


def forced_sale_target_wei(shortfall_wei: int, cap_shortfall_wei: int | None = None) -> tuple[int, int]:
    """(target gross proceeds, cap) in USD wei. The contract requires
    shortfall <= gross <= shortfall * 1.05 + US$1; aim at the middle so
    price movement in either direction still lands inside. The contract's
    shortfall is only known within a range (it accrues first): the target
    covers the largest (`shortfall_wei`), the cap is the smallest's
    (`cap_shortfall_wei`)."""
    base = shortfall_wei if cap_shortfall_wei is None else min(cap_shortfall_wei, shortfall_wei)
    cap = base + base * FORCED_SALE_MARGIN_BPS // BPS + FORCED_SALE_ROUNDING_WEI
    return shortfall_wei + (cap - shortfall_wei) // 2, cap


def plan_forced_sale(account, shortfall_wei: int, dollar: int, cap_shortfall_wei: int | None = None) -> list[dict]:
    """Sale legs covering the shortfall: largest position first, several
    legs when no single holding covers it. Notional per leg is the proceeds
    wanted grossed up for the 0.9% entry fee.

    The contract accepts shortfall <= proceeds <= cap (shortfall * 1.05 +
    US$1). Legs stop as soon as the planned proceeds cover the shortfall,
    and every leg is sized against the room left under the cap, so neither
    a quote's rounding nor the stock minimum order can push the plan over
    it: a leg that would is re-sized once, else that asset is skipped."""
    from cusd_plus.crypto_policy import live_fee_bps
    fee_bps = live_fee_bps()
    gross_up = Decimal(BPS) / Decimal(BPS - fee_bps)
    target_wei, cap_wei = forced_sale_target_wei(shortfall_wei, cap_shortfall_wei)
    candidates = sale_candidates(account)
    if not candidates:
        raise NothingSellable('no sellable asset')
    raised_wei = 0
    legs = []
    gas = abi.RELAY_GAS_SALE_BASE
    # The same (at most MAX_SALE_LEGS) assets the owner was told may be sold.
    for asset in candidates[:MAX_SALE_LEGS]:
        if raised_wei >= shortfall_wei:
            break
        # Largest positions first; a leg that would take the call over the
        # relayer's gas cap is not added (a cheaper, smaller one may still fit).
        leg_gas = abi.RELAY_GAS_SALE_LEG.get(asset.kind)
        if leg_gas is None or gas + leg_gas > relayer.max_relay_gas('smart_forced_sale'):
            continue
        want = Decimal(target_wei - raised_wei) / Decimal(WAD)   # proceeds still wanted (after fee)
        room = Decimal(cap_wei - raised_wei) / Decimal(WAD)      # most this leg may add
        # Gross notional this leg may sell without its estimate reaching the
        # cap (1% below it for quote rounding).
        room_gross = room * gross_up * Decimal('0.99')
        # Never plan to sell more than the position is worth (2% headroom
        # for price movement between this read and execution).
        available = asset.value_usd * Decimal('0.98')
        notional = min(want * gross_up, available, room_gross)
        if asset.kind == 'stock' and notional < quotes.MIN_STOCK_ORDER_USD:
            if available < quotes.MIN_STOCK_ORDER_USD or room_gross < quotes.MIN_STOCK_ORDER_USD:
                continue  # below Ondo's minimum order, or the minimum would overshoot the cap
            notional = quotes.MIN_STOCK_ORDER_USD
        leg = _sale_leg(account, asset, notional, dollar)
        if leg is not None and raised_wei + leg['expected_dollars_wei'] > cap_wei:
            # The quote came back richer than the estimate: once more, scaled into the room.
            scaled = notional * Decimal(cap_wei - raised_wei) / Decimal(leg['expected_dollars_wei']) * Decimal('0.99')
            leg = None
            if not (asset.kind == 'stock' and scaled < quotes.MIN_STOCK_ORDER_USD):
                leg = _sale_leg(account, asset, scaled, dollar)
            if leg is not None and raised_wei + leg['expected_dollars_wei'] > cap_wei:
                leg = None
        if leg is None:
            continue
        raised_wei += leg['expected_dollars_wei']
        gas += leg_gas
        legs.append(leg)
    if not legs or raised_wei < shortfall_wei:
        raise NothingSellable('holdings do not cover the shortfall')
    if raised_wei > cap_wei:  # unreachable by construction; never sent
        raise quotes.QuoteUnavailable('proceeds_above_cap')
    return legs


def _sale_leg(account, asset, notional: Decimal, dollar: int) -> dict | None:
    """One planned leg selling about `notional` (gross USD) of `asset`, or
    None when this asset cannot be sold now. Raises QuoteUnavailable for a
    stock quote failure (the sale waits or fails as a whole)."""
    from cusd_plus import crypto_catalog
    from cusd_plus.crypto_policy import DOLLAR_PLUS
    if notional <= 0:
        return None
    if asset.kind == 'stock':
        if dollar != DOLLAR_PLUS and not chain.cusd_plus_address():
            return None
        built = quotes.stock_sell_call(asset.key.split(':', 1)[1], notional)
        venue = chain.stock_router_address()
    elif asset.kind == 'confio':
        sale = chain.confio_sale_of(account.contract_address)
        amount_in = int(Decimal(asset.units) * notional / asset.value_usd)
        if sale is None or amount_in <= 0:
            return None
        try:
            built = quotes.confio_sell_call(sale[0], dollar, min(amount_in, asset.units))
        except quotes.QuoteUnavailable as exc:
            logger.warning('CONFIO leg not planned for %s: %s', account.contract_address, exc)
            return None
        venue = sale[0]
    else:
        token = crypto_catalog.by_address(asset.address, include_unlisted=True)
        if token is None:
            return None
        amount_in = int(Decimal(asset.units) * notional / asset.value_usd)
        if amount_in <= 0:
            return None
        built = quotes.crypto_sell_call(token, dollar, min(amount_in, asset.units))
        venue = chain.swap_router_address()
    expected = int(built['expected_dollars_wei'])  # net of the entry fee
    return {'venue': venue, 'token': built['token'], 'max_in': int(built['max_in']),
            'data': built['call']['data'], 'asset_key': asset.key, 'kind': asset.kind,
            'expected_dollars_wei': expected, 'quote_ref': built.get('quote_ref', '')}


def _account_dollar(account) -> int:
    """Which dollar a relayer conversion mints for this account: the one it
    already holds (with both, the one worth more: payout dust never
    decides), else the owner's by eligibility (no request: phone)."""
    from cusd_plus.crypto_policy import DOLLAR, DOLLAR_PLUS
    from cusd_plus.eligibility import is_ondo_eligible
    held = assets_mod.held_dollar(account.contract_address)
    if held == 'cusd_plus':
        return DOLLAR_PLUS
    if held == 'cusd':
        return DOLLAR
    return DOLLAR_PLUS if is_ondo_eligible(account.owner_user) else DOLLAR


def run_forced_sales() -> dict:
    out = {'sent': 0, 'skipped': 0, 'waiting': 0, 'unsellable': 0, 'errors': 0}
    if not _ready():
        return {'skipped': 'disabled'}
    if chain.relayer_paused():
        return {'skipped': 'relayer_paused'}
    for account in _billing_candidates().filter(notice_started_at__isnull=False):
        try:
            state = _billing_state(account)
            if (state['status'] != 1 or state['billing'] != 3 or state['dollars'] >= state['fee']
                    or state['forced_sale_for_period'] == state['paid_until']):
                out['skipped'] += 1
                continue
            source_id = f'period:{state["paid_until"]}'
            if relayer.live_tx(account, 'smart_forced_sale', source_id) is not None:
                out['skipped'] += 1  # one is on the wire: no second quote, no second sale
                continue
            period_end = chain.to_dt(state['paid_until'])
            sale, _ = SmartAccountForcedSale.objects.get_or_create(
                smart_account=account, period_end=period_end,
                defaults={'notice_started_at': chain.to_dt(state['notice_started_at'])})
            if sale.status == 'succeeded':
                out['skipped'] += 1
                continue
            _attempt_forced_sale(account, sale, state, source_id, out)
        except Exception:  # noqa: BLE001
            logger.exception('forced sale failed for %s', account.contract_address)
            out['errors'] += 1
    return _report('run_forced_sales', out)


def _attempt_forced_sale(account, sale, state, source_id: str, out: dict) -> None:
    now = timezone.now()
    try:
        # The contract's shortfall is fee - dollarsUsd AFTER its accrue():
        # between these two, never the stored-pPlus figure.
        least, most = _dollars_window(account, state)
        shortfall, shortfall_floor = state['fee'] - least, state['fee'] - most
        if shortfall_floor <= 0:
            out['skipped'] += 1  # the accrued dollars cover the fee: collectFee's job
            return
        if _usdt_may_cover(account, state, most):
            # No sale needed: the USDT covers the gap once converted (the
            # sale would revert DollarsCover). Not an attempt, not a failure.
            _covered(account, out)
            return
        dollar = _account_dollar(account)
        legs = plan_forced_sale(account, shortfall, dollar, shortfall_floor)
    except quotes.QuoteUnavailable as exc:
        if exc.retry_later:
            out['waiting'] += 1  # market closed: not an attempt
            return
        _record_sale_failure(account, sale, f'quote: {exc}', now)
        out['errors'] += 1
        return
    except NothingSellable as exc:
        # Stays paused; nothing is returned (5.2). Recorded, retried later.
        _record_sale_failure(account, sale, f'unsellable: {exc}', now, alert=False)
        out['unsellable'] += 1
        return
    referrer, share = _referrer(account)
    calldata = abi.encode_call(
        'forcedSale',
        [(leg['venue'], leg['token'], leg['max_in'], bytes.fromhex(leg['data'][2:])) for leg in legs],
        shortfall_floor, referrer, share)
    gas = abi.RELAY_GAS_SALE_BASE + sum(abi.RELAY_GAS_SALE_LEG[leg['kind']] for leg in legs)
    attempt = sale.attempts + 1
    with transaction.atomic():
        SmartAccountForcedSale.objects.filter(pk=sale.pk).update(
            attempts=attempt, last_attempt_at=now, updated_at=now)
        for position, leg in enumerate(legs):
            SmartAccountForcedSaleLeg.objects.create(
                forced_sale=sale, attempt=attempt, position=position, asset=leg['token'],
                asset_key=leg['asset_key'], amount_in=str(leg['max_in']),
                dollars_out='', quote_ref=leg['quote_ref'])
    try:
        row, created = relayer.send_relayer_call(account, calldata, 'smart_forced_sale', source_id, gas=gas)
    except relayer.RelayError as exc:
        if _dollars_cover(exc):
            # The dollars (with the USDT) cover the fee: no sale is needed.
            # Not a failure, no alert; the USDT is converted and collectFee
            # takes the fee on its next run.
            SmartAccountForcedSaleLeg.objects.filter(forced_sale=sale, attempt=attempt).delete()
            SmartAccountForcedSale.objects.filter(pk=sale.pk).update(
                attempts=sale.attempts, last_error='', updated_at=timezone.now())
            _covered(account, out)
            return
        sale.attempts = attempt
        _record_sale_failure(account, sale, f'relay: {exc}', now, count_attempt=False)
        out['errors'] += 1
        return
    SmartAccountForcedSale.objects.filter(pk=sale.pk).exclude(status='succeeded').update(
        status='sent', tx_hash=row.signed_tx_hash, last_error='', updated_at=timezone.now())
    out['sent' if created else 'skipped'] += 1


def _record_sale_failure(account, sale, error: str, now, *, alert: bool = True, count_attempt: bool = True) -> None:
    attempts = sale.attempts + (1 if count_attempt else 0)
    SmartAccountForcedSale.objects.filter(pk=sale.pk).exclude(status='succeeded').update(
        status='failed', attempts=attempts, last_error=error[:2000], last_attempt_at=now, updated_at=now)
    if attempts == 3:
        notifications.safe(notifications.forced_sale_failed, account)
    if alert and attempts and attempts % 5 == 0:
        try:
            from config.ops_alerts import send_ops_alert
            send_ops_alert(
                f'Cuenta inteligente: venta forzada falló {attempts} veces ({account.contract_address}): {error[:200]}',
                dedupe_key=f'smart_forced_sale_{sale.pk}_{attempts}', dedupe_seconds=86400)
        except Exception:  # noqa: BLE001
            logger.exception('ops alert failed')


def on_relay_tx_final(row) -> None:
    """A relayer transaction reached a final status (tasks.check_relay_tx).
    Success is mirrored from EVENTS; only failures are recorded here."""
    if row.status not in ('reverted', 'dropped', 'reorged'):
        return
    if row.kind == 'smart_forced_sale':
        sale = SmartAccountForcedSale.objects.filter(
            smart_account=row.smart_account, tx_hash=row.signed_tx_hash).first()
        if sale is not None and sale.status != 'succeeded':
            _record_sale_failure(row.smart_account, sale, f'transaction {row.status}', timezone.now(),
                                 count_attempt=False)
    elif row.kind == 'smart_execute_rule':
        values = dict(status='failed', tx_hash=row.signed_tx_hash, updated_at=timezone.now())
        sent = SmartAccountRuleRun.objects.filter(tx_hash__iexact=row.signed_tx_hash, status='sent')
        run = sent.select_related('rule__smart_account__owner_user').first()
        if run is not None:
            error = _unlanded(run.error, row.status)
            if sent.filter(pk=run.pk).update(**values, error=error, message=_not_completed(run, error)):
                return
        # A hash that was never saved on its run: the row's source names it.
        # A run on the wire under another transaction's hash is that one's.
        run = run_of_relay(row)
        if (run is not None and run.rule.scheduled_for == run.scheduled_for     # not a slot already finished
                and relayer.live_tx(row.smart_account, row.kind, row.source_id) is None):
            error = _unlanded(run.error, row.status)
            (SmartAccountRuleRun.objects.filter(pk=run.pk, status__in=('pending', 'failed', 'sent'))
             .exclude(Q(status='sent') & ~Q(tx_hash=''))
             .update(**values, error=error, message=_not_completed(run, error)))


def _not_completed(run, error: str) -> str:
    """A call that did not land: until when, while this slot still retries."""
    rule = run.rule
    if (rule.active and rule.scheduled_for == run.scheduled_for
            and timezone.now() <= retry_deadline(_code(error), rule.frequency, run.scheduled_for)):
        return _pending_message(rule, run.scheduled_for, 'failed', NOT_COMPLETED, error)
    return NOT_COMPLETED


def run_of_relay(row):
    """The (rule, slot) an executeRule was sent for, from its source_id."""
    try:
        kind, rule_pk, slot = str(row.source_id).split(':')
        start = chain.to_dt(int(slot))
        rule_pk = int(rule_pk)
    except (TypeError, ValueError):
        return None
    if kind != 'rule' or start is None:
        return None
    return SmartAccountRuleRun.objects.filter(
        rule_id=rule_pk, rule__smart_account_id=row.smart_account_id,
        scheduled_for__gte=start, scheduled_for__lt=start + timedelta(seconds=1)).order_by('pk').first()


def run_of_transaction(account, rule, tx_hash: str):
    """The run whose executeRule this transaction is, by its durable row."""
    row = SmartAccountRelayTx.objects.filter(
        smart_account=account, kind='smart_execute_rule', signed_tx_hash__iexact=tx_hash).first()
    run = run_of_relay(row) if row is not None else None
    return run if run is not None and run.rule_id == rule.pk else None


# ── USDT conversion ─────────────────────────────────────────────────────

def _sequence(account, kind: str, prefix: str) -> str:
    """Idempotency key for an action that can legitimately repeat: the
    number of confirmed ones so far. A retry before confirmation reuses the
    key; the next occurrence gets a new one."""
    done = SmartAccountRelayTx.objects.filter(
        smart_account=account, kind=kind, source_id__startswith=prefix + ':', status='confirmed').count()
    return f'{prefix}:{done}'


def convert_usdt() -> dict:
    from cusd_plus import vault
    out = {'sent': 0, 'skipped': 0, 'errors': 0}
    if not _ready():
        return {'skipped': 'disabled'}
    usdt = chain.usdt_address()
    if not usdt:
        return {'skipped': 'usdt_not_configured'}
    if chain.relayer_paused():
        return {'skipped': 'relayer_paused'}
    accounts = (SmartAccount.objects.filter(status__in=('active', 'cancel_pending'))
                .select_related('owner_user', 'owner_account'))
    for account in accounts:
        try:
            balance = chain.balance_of(usdt, account.contract_address)  # fresh, never the stored one
            if balance <= 0:
                continue
            if not vault.is_safe_mint_amount(balance):
                # The personal path's floor (cusd_plus.vault.sweepable_usdt_wei):
                # minting about US$1 or less can round below Ondo's exact
                # redeem floor. It stays as USDT until more arrives.
                out['skipped'] += 1
                continue
            if int(chain.account_view(account.contract_address, 'status')) not in (1, 2):
                out['skipped'] += 1
                continue
            out['sent' if convert_account_usdt(account) else 'skipped'] += 1
        except Exception:  # noqa: BLE001
            logger.exception('USDT conversion failed for %s', account.contract_address)
            out['errors'] += 1
    return _report('convert_usdt', out)


# ── rules ───────────────────────────────────────────────────────────────

def next_slot(frequency: str, after):
    """The calendar slot after `after` (missed runs are never caught up)."""
    if frequency == 'monthly':
        year, month = (after.year + 1, 1) if after.month == 12 else (after.year, after.month + 1)
        day = min(after.day, calendar.monthrange(year, month)[1])
        return after.replace(year=year, month=month, day=day)
    return after + timedelta(days={'daily': 1, 'weekly': 7, 'biweekly': 14}[frequency])


def retry_deadline(code: str, frequency: str, slot):
    """Until when a slot is retried after this outcome, for the executor and
    for what the owner is told. Only a monthly rule waits days for balance:
    a late run moves the next weekly or biweekly date for good. A market
    wait lasts to the next slot (spec 7.5)."""
    if code in MARKET_WAITS:
        return next_slot(frequency, slot)
    window = BALANCE_GIVE_UP if code == NO_BALANCE and frequency == 'monthly' else RULE_SLOT_GIVE_UP
    return min(slot + window, next_slot(frequency, slot))


def _code(error: str) -> str:
    """A wait that follows one of CARRIED_WAITS is kept as "<that>: why"."""
    return (error or '').split(':')[0]


def _carried(error: str) -> str:
    code = _code(error)
    return code if code in CARRIED_WAITS else ''


def _sent_error(error: str) -> str:
    """What a sent run keeps, in case its transaction never lands."""
    carried = _carried(error)
    return f'{carried}: sent' if carried else ''


def _unlanded(error: str, status: str) -> str:
    """A dropped call loses no promise; a real revert keeps 24 hours."""
    carried = _carried(error) if status != 'reverted' else ''
    return f'{carried}: transaction {status}' if carried else f'transaction {status}'


def _monthly_anchor(rule):
    """A monthly rule's own day: its first slot since the owner last set it.
    A late run moves February's date (the contract's 28 days) for that month
    only. None when the mirror has no such event or slot."""
    if rule.frequency != 'monthly' or not rule.pk or rule.onchain_id is None:
        return None
    from . import payouts
    applied = [e for e in payouts._rule_settings(rule.smart_account.contract_address, rule.onchain_id)
               if e.applied_at is not None]
    if not applied:
        return None
    return (rule.runs.filter(scheduled_for__gte=applied[-1].block_time).order_by('scheduled_for')
            .values_list('scheduled_for', flat=True).first())


def _following(frequency: str, slot, anchor=None):
    if anchor is None:
        return next_slot(frequency, slot)
    # Pushed past the end of its month (the 30th run on March 2): that
    # month's own date is still ahead.
    month = slot if anchor.day - slot.day > 15 else next_slot(frequency, slot)
    day = min(anchor.day, calendar.monthrange(month.year, month.month)[1])
    return anchor.replace(year=month.year, month=month.month, day=day)


def schedule_next(rule, *, after=None) -> None:
    """Move the rule's calendar slot on. Never earlier than the contract's
    own minimum gap (rule.next_run_at)."""
    now = timezone.now()
    anchor = _monthly_anchor(rule)
    slot = _following(rule.frequency, rule.scheduled_for or after or now, anchor)
    while slot <= now:
        slot = _following(rule.frequency, slot, anchor)
    if rule.next_run_at and slot < rule.next_run_at:
        slot = rule.next_run_at
    SmartAccountRule.all_objects.filter(pk=rule.pk).update(scheduled_for=slot, updated_at=now)
    rule.scheduled_for = slot


class RuleSkip(Exception):
    def __init__(self, code: str, message: str, *, final: bool = False, deactivate: str = ''):
        self.code, self.message, self.final, self.deactivate = code, message, final, deactivate
        super().__init__(code)


# Kept under the contract's own share limit when the amount is ours to pick
# (a crypto buy's amount_in): rounding and a slightly faster accrual.
SHARE_LIMIT_MARGIN_BPS = 3


class _PlusPrices:
    """pPlus a relayer call sent now executes at, read once per call and only
    when cUSD+ is involved. The contract runs accrue() first, so the stored
    pPlus (chain.p_plus_wad) is never the price it converts at: `low` is
    pPlus accrued to the live oracle, `high` that price grown over the
    inclusion horizon (quotes.plus_price_window)."""

    def __init__(self):
        self._window = None

    def window(self) -> tuple[int, int]:
        if self._window is None:
            self._window = quotes.plus_price_window()
        return self._window

    def limit_bounds(self, amount_wei: int) -> tuple[int, int]:
        """(fewest, most) shares the contract's limit ceil(amountUsd * 1e18 /
        pPlus) can come to at inclusion."""
        low, high = self.window()
        return quotes.shares_ceil(amount_wei, high), quotes.shares_ceil(amount_wei, low)


def build_rule_call(rule, onchain: dict | None = None) -> tuple[str, int, str]:
    """(calldata, gas, user message) for one run. Raises RuleSkip,
    QuoteUnavailable or PayoutSkip. `onchain` is the rule as the contract
    holds it right now (read fresh by _run_rule); a send rule runs only
    while its Face authorization matches it."""
    from cusd_plus import crypto_catalog
    from cusd_plus.crypto_policy import DOLLAR, DOLLAR_PLUS
    from cusd_plus.eligibility import is_ondo_eligible
    from security.identity_reuse import outgoing_identity_restriction

    account = rule.smart_account
    owner = account.owner_user
    amount_wei = int(rule.amount * WAD)
    plus = chain.cusd_plus_address()
    in_plus = rule.token_in.lower() == plus
    prices = _PlusPrices()
    # cUSD+: the contract's limit after its accrue(). `limit` is the least it
    # can come to (what a call may rely on being allowed); the balance must
    # cover the most it can come to.
    limit, limit_most = prices.limit_bounds(amount_wei) if in_plus else (amount_wei, amount_wei)
    if chain.balance_of(rule.token_in, account.contract_address) < limit_most:
        raise RuleSkip(NO_BALANCE, NO_BALANCE_TEXT)
    referrer, share = _referrer(account)

    if rule.kind == 'send':
        refusal = owner_refusal(owner)
        if refusal is not None:
            raise refusal
        payee = rule.payee_user
        from .context import personal_account
        payee_account = personal_account(payee) if payee is not None else None
        if (payee is None or not payee.is_active or payee_account is None
                or (payee_account.bsc_address or '').lower() != rule.payee_address.lower()):
            raise RuleSkip('payee_changed', 'La billetera de quien recibe cambió. Crea la regla de nuevo.',
                           final=True, deactivate='payee_wallet_changed')
        from .payouts import send_authorization_problem
        problem = send_authorization_problem(
            rule, onchain if onchain is not None else chain.account_rule(account.contract_address,
                                                                         int(rule.onchain_id)))
        if problem:
            raise RuleSkip(problem, 'Confirma de nuevo esta regla con Confío Face para reactivarla.',
                           final=True, deactivate=problem)
        payee_dollar = DOLLAR_PLUS if is_ondo_eligible(payee) else DOLLAR
        if (payee_dollar == DOLLAR_PLUS) == in_plus:
            min_out = limit * 999 // 1000
        elif in_plus:   # cUSD+ -> cUSD, fee-free unwrap: about the dollar amount
            min_out = amount_wei * 995 // 1000
        else:           # cUSD -> cUSD+, fee-free wrap: amount / pPlus shares, at
            # most the grown price (fewest shares) at inclusion.
            min_out = (amount_wei * WAD // prices.window()[1]) * 995 // 1000
        data = abi.send_rule_data(payee_dollar, min_out)
        return (abi.encode_call('executeRule', int(rule.onchain_id), data, abi.ZERO_ADDRESS, 0),
                abi.RELAY_GAS_RULE['send'], 'Enviado.')

    if rule.kind == 'buy':
        crypto = crypto_catalog.by_address(rule.token_out, include_unlisted=True)
        refusal = buy_rule_refusal(rule, crypto)
        if refusal is not None:
            raise refusal
        if crypto is not None:
            # The router pulls exactly amount_in: never above the contract's
            # post-accrual limit, whatever the price at inclusion.
            amount_in = limit * (BPS - SHARE_LIMIT_MARGIN_BPS) // BPS if in_plus else amount_wei
            built = quotes.crypto_buy_call(crypto, DOLLAR_PLUS if in_plus else DOLLAR, amount_in)
            data = abi.buy_rule_data(chain.swap_router_address(), built['call']['data'], built['min_out'])
            gas = abi.RELAY_GAS_RULE['buy_crypto']
        else:
            stock = assets_mod.stock_by_address(rule.token_out)
            built = quotes.stock_buy_call(stock[0], quotes.stock_buy_notional(rule.amount), limit)
            data = abi.buy_rule_data(chain.stock_router_address(), built['call']['data'], built['min_out'])
            gas = abi.RELAY_GAS_RULE['buy_stock']
        return abi.encode_call('executeRule', int(rule.onchain_id), data, referrer, share), gas, 'Compra realizada.'

    # payout
    from . import payouts
    if outgoing_identity_restriction(owner):
        # As contract_funding.require_owner: a hold may be lifted inside the slot.
        raise payouts.PayoutSkip('identity_hold', 'Tu cuenta está en revisión.', wait=True)
    if onchain:
        # The contract exits what IT holds; the deposit is quoted from the
        # mirror. A mirror behind an update waits for its event.
        amount_moved = 'amount_usd_wei' in onchain and int(onchain['amount_usd_wei']) != amount_wei
        ref = str(onchain.get('payout_ref') or '').lower()
        token = str(onchain.get('token_in') or '').lower()
        # updateRule always sets nextRunAt, so it also shows an update that
        # kept the amount and the recipient (another authorization).
        set_again = (rule.next_run_at is not None and 'next_run_at' in onchain
                     and int(onchain['next_run_at']) != int(rule.next_run_at.timestamp()))
        if (amount_moved or set_again or (ref and ref != (rule.payout_ref or '').lower())
                or (token and token != (rule.token_in or '').lower())
                or onchain.get('frequency', rule.frequency) != rule.frequency):
            raise payouts.PayoutSkip('rule_mirror_behind', 'Tu regla se está actualizando.', wait=True)
    fee_bps = chain.conversion_fee_bps()
    usdt_estimate = amount_wei * (BPS - fee_bps) // BPS
    run = rule.runs.filter(scheduled_for=rule.scheduled_for).first()
    plan = payouts.plan_run(rule, run, usdt_estimate, window=prices.window() if in_plus else None)
    if in_plus:
        # cUSD+: exact usdtOut and the grossCusd that nets it (payouts.payout_exit);
        # the two-word cUSD form reverts on a cUSD+ rule.
        if not plan.gross_wei:
            raise payouts.PayoutSkip('provider_path_unverified', payouts.EXIT_UNAVAILABLE)
        data = abi.payout_plus_rule_data(plan.deposit_address, plan.min_usdt_out, plan.gross_wei)
    else:
        data = abi.payout_rule_data(plan.deposit_address, plan.min_usdt_out)
    return (abi.encode_call('executeRule', int(rule.onchain_id), data, referrer, share),
            abi.RELAY_GAS_RULE['payout'], 'Pago en camino.')


def owner_refusal(owner) -> RuleSkip | None:
    """The owner's own state, with nobody present to be refused by
    SecurityMiddleware. Skips the run only: the rule stays as it is and the
    owner's withdrawals are not asked here."""
    from security.identity_reuse import outgoing_identity_restriction
    from security.utils import check_user_banned
    if not owner.is_active or getattr(owner, 'deleted_at', None):
        return RuleSkip('account_unavailable', 'Tu cuenta no está disponible para reglas automáticas.')
    if check_user_banned(owner)[0]:
        return RuleSkip('account_suspended', 'Tu cuenta está suspendida. Escríbenos por soporte.')
    if outgoing_identity_restriction(owner):
        return RuleSkip('identity_hold', 'Tu cuenta está en revisión.')
    return None


def buy_rule_refusal(rule, crypto=None) -> RuleSkip | None:
    """The SAME entry gates prepare_buy_rule applied, re-run at every run
    (eligibility can change after the rule was created: a new country, a
    country added to a blocked list, a switch turned off). There is no
    request at run time, so the request-aware policies are evaluated
    without request meta (phone and stored country only). A refusal skips
    this run and tells the owner; the rule stays and is retried."""
    owner = rule.smart_account.owner_user
    unavailable = RuleSkip('trade_not_available', 'La compra automática no está disponible para tu cuenta por ahora.')
    # Same hold as creating or changing the rule (sponsor_7702: smart_rule
    # is not exempt): no automatic purchase runs while it lasts.
    refusal = owner_refusal(owner)
    if refusal is not None:
        return refusal
    from security.geo import review_cap_exceeded
    if review_cap_exceeded(owner, rule.amount):
        return RuleSkip('review_amount_cap', 'Ese monto supera el límite de tu cuenta.')
    if crypto is not None:
        from cusd_plus import crypto_risk
        if not assets_mod.is_feed_token(crypto):
            return RuleSkip('asset_unavailable', 'Ese activo ya no está disponible.', final=True)
        if not crypto_risk.trading_ready() or not crypto_risk.buy_enabled(owner, {}):
            return unavailable
        return None
    stock = assets_mod.stock_by_address(rule.token_out)
    if stock is None:
        return RuleSkip('asset_unavailable', 'Ese activo ya no está disponible.', final=True)
    from cusd_plus.eligibility import check_stock_buy_eligibility
    if not getattr(settings, 'CUSD_PLUS_STOCK_TRADING_ENABLED', False):
        return unavailable
    if not check_stock_buy_eligibility(owner, {}):
        return unavailable
    from cusd_plus import complex_products
    if complex_products.factor_for_symbol(stock[0]) is not None and not complex_products.acknowledged(owner):
        return unavailable
    return None


def due_rules():
    now = timezone.now()
    # Only kinds the relayer runs: a Card rule (decision 35) is pulled by its
    # spender and executeRule on it reverts BadRule.
    # Only rules of the account's current subscription epoch: an earlier
    # one's executeRule reverts BadRule (spec 4.4, invariant 22).
    from django.db.models import F
    return (SmartAccountRule.objects
            .filter(active=True, state='onchain', onchain_id__isnull=False, kind__in=abi.EXECUTABLE_RULE_KINDS,
                    epoch=F('smart_account__subscription_epoch'),
                    scheduled_for__lte=now, next_run_at__lte=now,
                    smart_account__status__in=('active', 'cancel_pending'),
                    smart_account__billing_status='current')
            .select_related('smart_account', 'smart_account__owner_user', 'smart_account__owner_account',
                            'payee_user', 'payout_method', 'pagomovil_destination', 'standing_authorization'))


def run_rules() -> dict:
    out = {'sent': 0, 'skipped': 0, 'waiting': 0, 'errors': 0}
    if not _ready():
        return {'skipped': 'disabled'}
    # Mirror the Pago Móvil sends and Infinia journeys already under way (no
    # transaction).
    try:
        from . import payouts
        payouts.mirror_ramp_payouts()
    except Exception:  # noqa: BLE001 — retried next run
        logger.exception('payout mirror failed')
    try:
        from . import infinia_payouts
        infinia_payouts.mirror_payouts()
    except Exception:  # noqa: BLE001 — retried next run
        logger.exception('journey payout mirror failed')
    if chain.relayer_paused():
        return {'skipped': 'relayer_paused'}
    for rule in due_rules():
        try:
            _run_rule(rule, out)
        except Exception:  # noqa: BLE001 — this rule is unchanged and retried
            logger.exception('rule %s failed', rule.pk)
            out['errors'] += 1
    return _report('run_rules', out)


def _left_the_account(run) -> bool:
    """The slot's payout was seen sent, whatever the run row says."""
    from .models import SmartAccountPayout
    return (SmartAccountPayout.objects.filter(rule_run=run)
            .exclude(status__in=('reserving', 'prepared', 'pending', 'cancelled')).exists())


def _lock_slot(rule, run):
    """(run, rule) fresh, with the account and the run locked, in the order
    the event mirror takes them (account first). Inside a transaction."""
    SmartAccount.all_objects.select_for_update().filter(pk=rule.smart_account_id).first()
    current = SmartAccountRuleRun.objects.select_for_update().get(pk=run.pk)
    return current, SmartAccountRule.all_objects.get(pk=rule.pk)


def _with_tail(reason: str, tail: str) -> str:
    """`reason` without its own promise of a retry, cut before the tail is."""
    reason = re.sub(r'\s*(Volveremos a intentarlo|Lo intentaremos[^.]*)\.', '', reason or '').strip()
    room = RETRY_TEXT_MAX - len(tail) - 1
    if len(reason) > room:
        reason = reason[:room - 1].rstrip() + '…'
    return f'{reason} {tail}'.strip()


def _until(rule, slot, code: str) -> str:
    return notifications._date(retry_deadline(code, rule.frequency, slot), rule.smart_account.owner_user)


def _pending_message(rule, slot, status: str, reason: str, error: str) -> str:
    code = _code(error)
    # What the owner can do is about the outcome itself, not a wait it kept.
    action = RETRY_ACTION.get(error, 'No tienes que hacer nada' if status == 'failed' else '')
    tail = f'{action}: lo reintentamos' if action else 'Lo reintentamos'
    return _with_tail(reason, f'{tail} hasta el {_until(rule, slot, code)}.')


def _not_done_message(rule, reason: str = '') -> str:
    when = notifications._date(rule.scheduled_for, rule.smart_account.owner_user)
    what = NOT_DONE.get(rule.kind, 'No se realizó')
    return _with_tail(reason, f'{what}; el próximo intento es el {when}.' if when else f'{what}.')


def _tell(rule, run) -> None:
    run.rule = rule     # as it now stands: retrying, or moved on
    notifications.safe(notifications.rule_run, run)


def _finish_run(rule, run, status: str, message: str, error: str = '', *, final: bool) -> None:
    """Compare-and-set: never over a run that was sent or executed, nor over
    a slot another worker already finished (the sender's claim takes the
    same locks)."""
    now = timezone.now()
    with transaction.atomic():
        current, fresh = _lock_slot(rule, run)
        if current.status in RUN_SENT or fresh.scheduled_for != run.scheduled_for:
            return
        if rule.kind == 'payout' and (slot_may_land(rule, run) or _left_the_account(run)):
            return
        retrying = current.status in ('skipped', 'failed')
        timed_out = final and now > retry_deadline(_code(error), rule.frequency, run.scheduled_for)
        if final:
            schedule_next(rule)
            fresh.scheduled_for = rule.scheduled_for
        if not final:
            message = _pending_message(rule, run.scheduled_for, status, message, error)
        elif fresh.active and (retrying or timed_out):
            # The end of the slot: nothing will be retried or "done later".
            held = _held_text(error)
            message = _not_done_message(rule, held or ('' if timed_out and status == 'failed' else message))
        # The rule's own limits are the owner's, not an incident: the owner is told, ops are not.
        alert = (final and rule.kind == 'payout' and (status == 'failed' or error.startswith(f'{NO_BALANCE}:'))
                 and _code(error) not in LIMIT_RETRIES)
        values = dict(status=status, message=message[:200], error=error[:2000], updated_at=now)
        SmartAccountRuleRun.objects.filter(pk=run.pk).update(**values)
        run.status, run.message, run.error = values['status'], values['message'], values['error']
        # One message per transition: pending at the first skip or failure,
        # then given up (or done, reconcile._rule_executed). Never one a pass.
        tell = SmartAccountRuleRun.objects.filter(pk=run.pk, notified_at__isnull=True).update(notified_at=now) == 1
        if final and retrying and not tell:
            tell = SmartAccountRuleRun.objects.filter(pk=run.pk).update(notified_at=now) == 1
    if tell:
        _tell(fresh, run)
    if final:
        _close_unsent_payout(rule, run)
    if alert:
        _alert_not_paid(rule, run)


def _alert_not_paid(rule, run) -> None:
    try:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Cuenta inteligente: pago automático no hecho, se agotó su plazo (regla {rule.pk}, '
                       f'run {run.pk}, {run.error[:120]}).',
                       dedupe_key=f'smart_payout_given_up_{run.pk}', dedupe_seconds=86400)
    except Exception:  # noqa: BLE001
        logger.exception('ops alert failed')


def _alert_unconfirmed(rule, run) -> None:
    try:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Cuenta inteligente: fecha de pago superada sin ejecución confirmada (regla {rule.pk}, '
                       f'run {run.pk}): el pago pudo salir. Revisar la cadena y su orden; el dueño fue avisado.',
                       dedupe_key=f'smart_payout_unconfirmed_{run.pk}', dedupe_seconds=86400)
    except Exception:  # noqa: BLE001
        logger.exception('ops alert failed')


def slot_may_land(rule, run) -> bool:
    """A relayer transaction of this slot is on the wire, confirmed, or
    reorged out (it can be mined again)."""
    from .models import SmartAccountRelayTx
    source_id = f'rule:{rule.pk}:{int(run.scheduled_for.timestamp())}'
    return SmartAccountRelayTx.objects.filter(
        smart_account=rule.smart_account, kind='smart_execute_rule', source_id=source_id,
        status__in=SmartAccountRelayTx.LIVE_STATUSES + ('reorged',)).exists()


def _close_unsent_payout(rule, run, *, quiet: bool = False) -> None:
    """A payout slot that ends, or a pass whose call was refused, without its
    executeRule on the wire closes its own order now (a VE send, or a bridge
    and journey that would keep holding the owner's accounts). Not while any
    relayer transaction of the slot may still land. `quiet`: the slot will
    try again with a fresh order."""
    if rule.kind != 'payout' or slot_may_land(rule, run):
        return
    try:
        from . import payouts
        payouts.close_unsent_order(run, quiet=quiet)
    except Exception:  # noqa: BLE001 — ramps' own expiry still closes it
        logger.exception('closing the order of run %s failed', run.pk)


def _supersede_slot(rule, run, now) -> None:
    """This slot's time is over (the next calendar slot is due) and it never
    ran. Recorded as skipped and told once (only when there was a reason to
    tell, e.g. the market stayed closed; a slot told it would be retried
    hears that it was not done), then the rule moves to the latest slot that
    is due, which runs on its own: the current slot is never lost and the
    old one never runs into it."""
    tell = close = gave_up = False
    payout = rule.kind == 'payout'
    with transaction.atomic():
        current, fresh = _lock_slot(rule, run)
        if current.status in RUN_SENT or fresh.scheduled_for != run.scheduled_for:
            return
        slot = run.scheduled_for
        while next_slot(rule.frequency, slot) <= now:
            slot = next_slot(rule.frequency, slot)
        if rule.next_run_at and slot < rule.next_run_at:
            slot = rule.next_run_at
        SmartAccountRule.all_objects.filter(pk=rule.pk, scheduled_for=run.scheduled_for).update(
            scheduled_for=slot, updated_at=now)
        rule.scheduled_for = slot
        reached = payout and (slot_may_land(rule, run) or _left_the_account(run))
        fresh.scheduled_for = slot
        if reached:
            # It may have left, and it never executed: not "not done" either.
            run.status, run.message = 'failed', UNCONFIRMED
            run.error = current.error or 'slot_superseded'
            SmartAccountRuleRun.objects.filter(pk=run.pk).update(
                status=run.status, message=run.message, error=run.error, notified_at=now, updated_at=now)
        if current.status in ('pending', 'failed', 'skipped') and not reached:
            reason = current.error or ''
            retrying = current.status in ('failed', 'skipped')
            run.status = 'skipped'
            if payout or retrying:
                run.message = _not_done_message(rule, NO_BALANCE_TEXT if reason == NO_BALANCE else (
                    'El mercado estaba cerrado.' if reason.startswith('market_closed') else ''))
            elif reason.startswith('market_closed'):
                run.message = 'El mercado estaba cerrado.'
            else:
                run.message = 'No se pudo completar a tiempo.'
            run.error = reason or 'slot_superseded'
            SmartAccountRuleRun.objects.filter(pk=run.pk).update(
                status=run.status, message=run.message, error=run.error, updated_at=now)
            if reason:
                tell = SmartAccountRuleRun.objects.filter(
                    pk=run.pk, notified_at__isnull=True).update(notified_at=now) == 1
            if retrying and not tell:
                tell = SmartAccountRuleRun.objects.filter(pk=run.pk).update(notified_at=now) == 1
            close = True
            # Ops hear of a payment that could not be made, not of no balance.
            gave_up = bool(payout and reason and (current.status != 'skipped' or reason.startswith(f'{NO_BALANCE}:')))
    if reached:
        notifications.safe(notifications.payout_unconfirmed, run)
        _alert_unconfirmed(rule, run)
    if tell:
        _tell(fresh, run)
    if close:
        _close_unsent_payout(rule, run)
    if gave_up:
        _alert_not_paid(rule, run)


def _rule_change_on_the_wire(account, rule) -> bool:
    """An owner batch that updates or stops this rule is signed and not mined
    yet. Asked under the sponsor nonce lock, which those batches are signed
    under too: one signed later has a later nonce and lands after this call."""
    from . import inflight
    from .models import SmartAccountPreparedAction
    actions = SmartAccountPreparedAction.objects.filter(
        target_address=account.contract_address.lower(), consumed=True,
        kind__in=('smart_rule', 'smart_rule_cancel'), sponsored_batch__status__in=inflight.ON_WIRE,
        sponsored_batch__created_at__gte=timezone.now() - inflight.IN_FLIGHT_MAX_AGE)
    return any(rule.pk in ((action.payload or {}).get('replaces_pk'), (action.payload or {}).get('cancel_rule_pk'))
               for action in actions)


def _update_unmirrored(account, rule) -> bool:
    """The owner's update of this rule is on chain and the mirror has not
    applied it: what would run is not what the mirror says. An update can
    keep the amount, the recipient and nextRunAt (another authorization),
    so the contract's storage alone does not show it."""
    from . import payouts
    from .models import SmartAccountPreparedAction
    events = payouts._rule_settings(account.contract_address, rule.onchain_id)
    if any(e.name == 'RuleUpdated' and e.applied_at is None for e in events):
        return True
    confirmed = set(SmartAccountPreparedAction.objects.filter(
        target_address=account.contract_address.lower(), consumed=True, kind='smart_rule',
        payload__replaces_pk=rule.pk, sponsored_batch__status='confirmed',
    ).values_list('sponsored_batch__tx_hash', flat=True))
    applied = {e.tx_hash.lower() for e in events if e.applied_at is not None}
    return any(tx.lower() not in applied for tx in confirmed if tx)


class _Send:
    """The two checks of one executeRule send (relayer.send_relayer_call)."""

    def __init__(self, rule, run, onchain: dict, calldata: str, message: str):
        self.rule, self.run, self.onchain = rule, run, onchain
        self.calldata, self.message = calldata, message
        self.claimed = False

    def before_sign(self) -> None:
        """The contract pays what IT stores when mined: read it again now,
        and sign nothing over a difference, nor for an owner held since the
        call was built."""
        account = self.rule.smart_account
        seen = account.owner_user
        owner = type(seen)._base_manager.filter(pk=seen.pk).first()     # as committed now
        refusal = owner_refusal(owner) if owner is not None else None
        if owner is None or refusal is not None:
            raise relayer.RelayError('owner_held', refusal.code if refusal is not None else '')
        try:
            current = chain.account_rule(account.contract_address, int(self.rule.onchain_id))
        except Exception as exc:  # noqa: BLE001 — unknown is never signed
            raise relayer.RelayError('rule_unreadable', str(exc)[:300]) from exc
        if (current != self.onchain or _rule_change_on_the_wire(account, self.rule)
                or _update_unmirrored(account, self.rule)):
            raise relayer.RelayError('rule_changed')

    def claim(self, tx_hash: str) -> None:
        """In the transaction that writes the relay row: this is still the
        slot's call and (a payout) its order is still open. The run turns
        'sent' with the hash there, so a closer, a finisher or a second
        worker sees all of it or none."""
        rule, run = self.rule, self.run
        current, fresh = _lock_slot(rule, run)
        wanted = lambda r: (r.standing_authorization_id, r.amount, (r.payout_ref or '').lower(),  # noqa: E731
                            (r.payee_address or '').lower(), r.epoch, r.token_in.lower())
        if current.status in RUN_SENT:
            raise relayer.RelayError('order_closed', 'already sent')
        if (fresh.deleted_at or not fresh.active or fresh.state != 'onchain'
                or fresh.scheduled_for != run.scheduled_for or wanted(fresh) != wanted(rule)):
            raise relayer.RelayError('rule_changed')
        if fresh.standing_authorization is not None and fresh.standing_authorization.revoked_at is not None:
            raise relayer.RelayError('rule_changed', 'revoked')
        if rule.kind == 'payout':
            from . import payouts
            if not payouts.lock_sendable(fresh, current, self.calldata):
                raise relayer.RelayError('order_closed')
        SmartAccountRuleRun.objects.filter(pk=run.pk).update(
            status='sent', tx_hash=tx_hash, message=self.message[:200], error=_sent_error(current.error),
            updated_at=timezone.now())
        self.claimed = True


def _heal_sent_run(account, run) -> None:
    """A run left 'sent' whose transaction finally did not land (the worker
    that resolved it died before saying so)."""
    row = SmartAccountRelayTx.objects.filter(
        smart_account=account, kind='smart_execute_rule', signed_tx_hash__iexact=run.tx_hash,
        status__in=('reverted', 'dropped', 'reorged')).first() if run.tx_hash else None
    if row is not None:
        on_relay_tx_final(row)


def _wait_code(run, code: str) -> str:
    """A wait keeps the deadline of what it follows: the days promised after
    no balance, or a market wait's next slot. A market wait has its own,
    also for a slot funded in time."""
    return code if code in MARKET_WAITS else (_carried(run.error) or code)


def _note_wait(rule, run, reason: str, now) -> None:
    code = _code(reason)
    kept = _wait_code(run, code)
    values = dict(error=reason if kept == code else f'{kept}: {reason}'[:2000])
    if code in MARKET_WAITS:
        if run.status in ('skipped', 'failed'):
            values['message'] = MARKET_WAIT if code == 'market_closed' else SESSION_UNKNOWN
    elif kept == NO_BALANCE:
        # The balance is there now (it is checked before anything that waits).
        values['message'] = f'Ya hay saldo. Lo reintentamos hasta el {_until(rule, run.scheduled_for, NO_BALANCE)}.'
    if all(getattr(run, name) == value for name, value in values.items()):
        return
    SmartAccountRuleRun.objects.filter(pk=run.pk).exclude(status__in=RUN_SENT).update(**values, updated_at=now)


def _run_rule(rule, out: dict) -> None:
    if rule.kind not in abi.EXECUTABLE_RULE_KINDS:
        return  # never executeRule a Card (or unknown) rule: it reverts
    account = rule.smart_account
    if int(rule.epoch) != int(account.subscription_epoch):
        out['skipped'] += 1  # a rule of an earlier subscription never runs
        return
    slot = rule.scheduled_for
    run, first_look = SmartAccountRuleRun.objects.get_or_create(rule=rule, scheduled_for=slot)
    if run.status == 'ok':
        schedule_next(rule)
        out['skipped'] += 1
        return
    source_id = f'rule:{rule.pk}:{int(slot.timestamp())}'
    if run.status == 'sent' or relayer.live_tx(account, 'smart_execute_rule', source_id) is not None:
        if run.status == 'sent':
            _heal_sent_run(account, run)
        out['skipped'] += 1  # on the wire: its event (or its revert) decides
        return
    now = timezone.now()
    if next_slot(rule.frequency, slot) <= now:
        # The next calendar slot is due and this one never ran (a closed
        # session that never reopened in time): skip it once, never run it
        # into the next slot's time.
        _supersede_slot(rule, run, now)
        out['skipped'] += 1
        return
    # Skips, failures and waits give the slot up at retry_deadline (for a
    # market wait, and what follows one, the next slot).
    def expired(code: str) -> bool:
        return now > retry_deadline(code, rule.frequency, slot)
    # Fresh state: the mirror can be behind.
    if (int(chain.account_view(account.contract_address, 'status')) not in (1, 2)
            or int(chain.account_view(account.contract_address, 'billingStatus')) != 0):
        out['skipped'] += 1
        return
    onchain = chain.account_rule(account.contract_address, int(rule.onchain_id))
    if not onchain['active'] or int(onchain['epoch']) != int(rule.epoch):
        out['skipped'] += 1  # stopped, or of an earlier epoch (the mirror lags)
        return
    if onchain['next_run_at'] > int(timezone.now().timestamp()):
        out['waiting'] += 1
        return
    if not first_look and expired(_code(run.error)):
        # Asked before anything is built, whatever it was waiting for: never
        # done after its deadline. A slot never looked at (Confío or billing
        # paused through it) still gets its one attempt.
        status = run.status if run.status in ('skipped', 'failed') else 'failed'
        reason = NO_BALANCE_TEXT if run.error == NO_BALANCE else ''
        _finish_run(rule, run, status, reason, run.error or 'slot_expired', final=True)
        out['skipped'] += 1
        return
    if (run.status == 'failed' and _code(run.error) in LIMIT_RETRIES
            and run.updated_at is not None and run.updated_at > now - LIMIT_RETRY_EVERY):
        out['waiting'] += 1     # today's cost or rate: asked again an hour after the last attempt
        return
    if _update_unmirrored(account, rule):
        _note_wait(rule, run, 'rule_mirror_behind', now)
        out['waiting'] += 1
        return
    try:
        calldata, gas, message = build_rule_call(rule, onchain)
    except RuleSkip as exc:
        if exc.deactivate:
            SmartAccountRule.objects.filter(pk=rule.pk).update(active=False, deactivated_reason=exc.deactivate)
        _finish_run(rule, run, 'skipped', exc.message, exc.code,
                    final=exc.final or bool(exc.deactivate) or expired(exc.code))
        out['skipped'] += 1
        return
    except quotes.QuoteUnavailable as exc:
        reason = str(exc)[:2000]
        code = _code(reason)
        if (exc.retry_later or code in MARKET_WAITS) and not expired(_wait_code(run, code)):
            # A wait, untold: the reason is kept on the run for that skip's
            # one message. A closed session (spec 7.5) runs at the next open
            # one before the next calendar slot; any other ends at the deadline.
            _note_wait(rule, run, reason, now)
            out['waiting'] += 1
            return
        _finish_run(rule, run, 'failed', 'No pudimos obtener un precio.', str(exc), final=expired(_code(str(exc))))
        out['errors'] += 1
        return
    except Exception as exc:
        from .payouts import PayoutSkip
        if not isinstance(exc, PayoutSkip):
            raise
        if exc.deactivate:
            # The Face authorization no longer matches what the rule pays:
            # stopped until the owner signs it again (spec 7.1).
            SmartAccountRule.objects.filter(pk=rule.pk).update(active=False, deactivated_reason=exc.deactivate)
        late = expired(_wait_code(run, exc.code) if exc.wait else exc.code)
        if exc.wait and not exc.deactivate and not late:
            # An ordinary wait (the owner's own send holds the accounts):
            # retried within the slot, and nobody is told unless it gives up.
            _note_wait(rule, run, exc.code, now)
            out['waiting'] += 1
            return
        if getattr(exc, 'retry_later', False) and not exc.deactivate:
            # A passing refusal (e.g. an identical payout still open):
            # retried within the slot until it gives up.
            _finish_run(rule, run, 'failed', exc.message, exc.code, final=late)
            if exc.code in LIMIT_RETRIES and not late:
                _close_unsent_payout(rule, run, quiet=True)
            out['errors'] += 1
            return
        _finish_run(rule, run, 'skipped', exc.message, exc.code, final=True)
        out['skipped'] += 1
        return
    send = _Send(rule, run, onchain, calldata, message)
    try:
        row, created = relayer.send_relayer_call(account, calldata, 'smart_execute_rule', source_id, gas=gas,
                                                 before_sign=send.before_sign, claim=send.claim)
    except relayer.RelayError as exc:
        waits = exc.code in RELAY_WAITS + INFRA_WAITS
        late = expired(_wait_code(run, exc.code) if waits else exc.code)
        if waits and not late:
            # Nothing left: untold, asked again. A held owner's reason is kept for the give-up.
            _note_wait(rule, run, str(exc) if exc.code == 'owner_held' else exc.code, now)
            if exc.code in INFRA_WAITS:
                logger.warning('rule %s waits: %s', rule.pk, exc)
                _close_unsent_payout(rule, run, quiet=True)
                out['errors'] += 1
            else:
                out['waiting'] += 1
            return
        _finish_run(rule, run, 'failed', NOT_COMPLETED, str(exc), final=late)
        # The order was reserved before the simulation and nothing was
        # broadcast: it stops holding the owner's accounts now. Refused under
        # the order's lock while a recorded call may still land.
        _close_unsent_payout(rule, run, quiet=True)
        out['errors'] += 1
        return
    if not created or not send.claimed:
        # Another worker's live transaction of this slot: record its hash.
        SmartAccountRuleRun.objects.filter(pk=run.pk).exclude(status='ok').update(
            status='sent', tx_hash=row.signed_tx_hash, message=message[:200], error=_sent_error(run.error),
            updated_at=timezone.now())
    out['sent' if created else 'skipped'] += 1


# ── expiry return ───────────────────────────────────────────────────────

def return_expired() -> dict:
    """An exit: runs whenever the factory is configured, even with
    SMART_ACCOUNT_ENABLED off (switching the feature off must never trap an
    owner's assets in an expired account)."""
    out = {'sent': 0, 'skipped': 0, 'emptied': 0, 'errors': 0}
    if not chain.factory_address():
        return {'skipped': 'disabled'}
    from . import reconcile
    reconcile.refresh_all_derived()
    for account in SmartAccount.objects.filter(status='expired').select_related('owner_user'):
        try:
            if int(chain.account_view(account.contract_address, 'status')) != 3:
                out['skipped'] += 1
                continue
            held = [a for a in assets_mod.assets_of(account.contract_address) if a.units > 0]
        except Exception:  # noqa: BLE001
            logger.exception('expiry return could not read %s', account.contract_address)
            out['errors'] += 1
            continue
        if not held:
            if account.returned_notified_at is None and SmartAccount.objects.filter(
                    pk=account.pk, returned_notified_at__isnull=True).update(returned_notified_at=timezone.now()):
                notifications.safe(notifications.assets_returned, account)
                out['emptied'] += 1
            continue
        for asset in held:
            # Per token: one that fails is recorded and retried without
            # blocking the others (decision 7).
            try:
                _row, created = relayer.send_relayer_call(
                    account, abi.encode_call('returnAsset', asset.address), 'smart_return',
                    _sequence(account, 'smart_return', f'return:{asset.address}'))
                out['sent' if created else 'skipped'] += 1
            except Exception:  # noqa: BLE001
                logger.exception('returnAsset(%s) failed for %s', asset.address, account.contract_address)
                out['errors'] += 1
    return _report('return_expired', out)


# ── claims, designations, reminders ─────────────────────────────────────

def claim_notice_interval(remaining: timedelta) -> timedelta:
    """Fixed schedule across the window; frequency rises near the end."""
    if remaining <= timedelta(days=7):
        return timedelta(days=1)
    if remaining <= timedelta(days=30):
        return timedelta(days=3)
    return timedelta(days=7)


def claim_notices() -> dict:
    """Protective: runs whenever the factory is configured, even with
    SMART_ACCOUNT_ENABLED off (an owner must hear about a claim on their
    account). The renewal price reminder is about a fee only an enabled
    feature collects, so it stays behind the flag."""
    out = {'owner_notices': 0, 'executable': 0, 'reminders': 0, 'lapsed': 0, 'stale': 0, 'deactivated': 0,
           'price': 0}
    if not chain.factory_address():
        return {'skipped': 'disabled'}
    now = timezone.now()
    for claim in SmartAccountClaim.objects.filter(state='pending').select_related(
            'beneficiary_row', 'beneficiary_row__smart_account', 'beneficiary_row__beneficiary_user',
            'beneficiary_row__smart_account__owner_user'):
        last = claim.last_owner_notice_at or claim.initiated_at
        if now - last >= claim_notice_interval(claim.executable_at - now):
            if SmartAccountClaim.objects.filter(pk=claim.pk, last_owner_notice_at=claim.last_owner_notice_at).update(
                    last_owner_notice_at=now, owner_notices_sent=claim.owner_notices_sent + 1):
                notifications.safe(notifications.claim_initiated_owner, claim, reminder=True)
                out['owner_notices'] += 1
        if now >= claim.executable_at and claim.executable_notified_at is None:
            if SmartAccountClaim.objects.filter(pk=claim.pk, executable_notified_at__isnull=True).update(
                    executable_notified_at=now):
                notifications.safe(notifications.claim_executable, claim)
                out['executable'] += 1

    from .context import personal_account
    for row in SmartAccountBeneficiary.objects.filter(
            state__in=('pending_acceptance', 'active')).select_related(
            'beneficiary_user', 'smart_account', 'smart_account__owner_user'):
        if row.state == 'pending_acceptance' and row.expires_at and row.expires_at <= now:
            SmartAccountBeneficiary.objects.filter(pk=row.pk, state='pending_acceptance').update(
                state='lapsed', updated_at=now)
            out['lapsed'] += 1
            continue
        current = personal_account(row.beneficiary_user)
        if current is None or (current.bsc_address or '').lower() != row.beneficiary_address.lower():
            if SmartAccountBeneficiary.objects.filter(pk=row.pk, state=row.state).update(
                    state='stale_address', stale_notified_at=now, updated_at=now):
                notifications.safe(notifications.beneficiary_address_changed, row)
                out['stale'] += 1
            continue
        if row.state == 'pending_acceptance' and now - (row.last_reminder_at or row.designated_at or now) >= timedelta(days=7):
            if SmartAccountBeneficiary.objects.filter(pk=row.pk, last_reminder_at=row.last_reminder_at).update(
                    last_reminder_at=now):
                notifications.safe(notifications.beneficiary_named, row, reminder=True)
                out['reminders'] += 1

    from . import payouts
    out['deactivated'] = payouts.deactivate_changed_rules()
    if _ready():
        out['price'] = _renewal_price_reminders(now)
    return out


def _renewal_price_reminders(now) -> int:
    """A scheduled price change is announced again before each subscriber's
    own renewal (spec 7.7)."""
    from . import offer
    prices = offer.factory_prices(fresh=True)
    if not prices:
        return 0
    sent = 0
    upcoming = SmartAccount.objects.filter(
        status='active', cancel_requested_at__isnull=True,
        paid_until__gt=now, paid_until__lte=now + timedelta(days=7)).select_related('owner_user')
    for account in upcoming:
        plan = account.next_plan or account.plan
        row = prices.get(plan)
        if not row or not row['next_wei'] or not row['next_at']:
            continue
        effective = chain.to_dt(row['next_at'])
        if effective > account.paid_until or account.renewal_price_notified_for == account.paid_until:
            continue
        if SmartAccount.objects.filter(pk=account.pk).exclude(
                renewal_price_notified_for=account.paid_until).update(renewal_price_notified_for=account.paid_until):
            notifications.safe(
                notifications.price_change_scheduled, account.owner_user,
                'anual' if plan == 'annual' else 'mensual', offer._usd_text(row['next_wei']), effective,
                before_renewal=True)
            sent += 1
    return sent


# ── CONFIO slot ─────────────────────────────────────────────────────────

def latch_confio_sale() -> dict:
    """Latch every account as soon as the factory's CONFIO slot is set (5.5)."""
    out = {'sent': 0, 'skipped': 0, 'errors': 0}
    if not _ready():
        return {'skipped': 'disabled'}
    venue, _ref = chain.confio_sale()
    if not int(venue, 16):
        return {'skipped': 'slot_unset'}
    for account in SmartAccount.objects.filter(confio_sale_latched=False, inherited_at__isnull=True):
        try:
            if int(chain.account_view(account.contract_address, 'confioSaleVenue'), 16):
                SmartAccount.objects.filter(pk=account.pk).update(confio_sale_latched=True)
                out['skipped'] += 1
                continue
            _row, created = relayer.send_relayer_call(
                account, abi.encode_call('latchConfioSale'), 'smart_latch_confio', 'latch')
            out['sent' if created else 'skipped'] += 1
        except Exception:  # noqa: BLE001
            logger.exception('latch failed for %s', account.contract_address)
            out['errors'] += 1
    return _report('latch_confio_sale', out)


def check_price_settings() -> bool:
    """Alert when the display fallback differs from the factory outside a
    scheduled change (spec 7.9). True when they agree or cannot be compared."""
    from . import offer
    prices = offer.factory_prices(fresh=True)
    if not prices:
        return True
    differ = [plan for plan in offer.PLANS
              if offer._usd_text(prices[plan]['price_wei']) != offer.settings_price(plan)
              and not prices[plan]['next_wei']]
    if differ:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Cuenta inteligente: el precio en settings difiere de la fábrica ({", ".join(differ)})',
                       dedupe_key='smart_account_price_mismatch', dedupe_seconds=86400)
    return not differ
