"""Venue calldata for automation with nobody present (spec 7.5): rule buys
and forced-sale legs. Stocks use an Ondo binding quote; bitcoin and gold use
the catalog route with floors from a live requote.

Every builder ends by running the SAME decoder the relay policy applies to a
user's own trade (sponsor_7702._decode_stock_call / decode_crypto_call), so
automation can never send a shape a user-signed trade would be refused for.
Failures raise QuoteUnavailable: the caller records the attempt and retries;
nothing is sent.
"""
from __future__ import annotations

import logging
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal

from eth_abi import encode as abi_encode

from . import chain

logger = logging.getLogger(__name__)

WAD = 10 ** 18
BPS = 10_000
MIN_STOCK_ORDER_USD = Decimal('1.00')  # Ondo's minimum order is about US$0.98


class QuoteUnavailable(Exception):
    """`retry_later` marks a normal wait (market closed), not a fault."""

    def __init__(self, code: str, *, retry_later: bool = False, detail: str = ''):
        self.code = code
        self.retry_later = retry_later
        self.detail = detail
        super().__init__(f'{code}: {detail}' if detail else code)


def stock_market_open() -> bool:
    from cusd_plus import gm_api
    try:
        return gm_api.session_from_status(gm_api.market_status()) != 'closed'
    except Exception as exc:  # noqa: BLE001 — unknown session: do not trade
        raise QuoteUnavailable('market_status_unavailable', detail=str(exc)[:200]) from exc


def _binding_quote(symbol: str, side: str, notional: Decimal) -> dict:
    from cusd_plus import gm_api
    from cusd_plus.schema import _normalize_gm_quote, _validated_gm_trade_request
    if not stock_market_open():
        raise QuoteUnavailable('market_closed', retry_later=True)
    try:
        request = _validated_gm_trade_request(symbol, side, format(notional, 'f'), 'short')
        return _normalize_gm_quote(gm_api.binding_attestation(**request), request, binding=True)
    except QuoteUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise QuoteUnavailable('stock_quote_unavailable', detail=str(exc)[:200]) from exc


def _quote_tuple(quote: dict) -> tuple:
    return (
        int(quote['chain_id']), int(quote['attestation_id']), bytes.fromhex(quote['user_id'][2:]),
        quote['asset_address'], int(quote['price']), int(quote['token_amount']),
        int(quote['expiration']), int(quote['side']), bytes.fromhex(quote['additional_data_hex'][2:]),
    )


def _stock_fee() -> tuple[int, str]:
    from cusd_plus import stock_fees
    policy = stock_fees.client_fee_policy()
    if policy is None:
        raise QuoteUnavailable('stock_fee_policy_unavailable')
    return policy


def _checked_stock(call: dict) -> dict:
    from cusd_plus import sponsor_7702
    try:
        action = sponsor_7702._decode_stock_call(call)
    except sponsor_7702.PolicyError as exc:
        raise QuoteUnavailable('stock_call_rejected', detail=exc.code) from exc
    if action is None:
        raise QuoteUnavailable('stock_router_not_configured')
    return action


# ── sizing the cUSD+ a stock buy redeems ────────────────────────────────
#
# ConfioSmartAccount._runBuy reverts when the stock router hands back more
# than USDT_EXCESS_MAX of unspent USDT, and the router reverts when the
# redemption is below usdtSpend. The shares are therefore sized so the
# redemption lands inside [target, target + USDT_EXCESS_MAX) at inclusion,
# by reproducing the contracts' integer arithmetic:
#   CusdPlusVault.redeemToUsdt: accrue() (_applyGrowth at the live oracle
#     price), usdyOut = floor(shares * pPlus / p), gross = IM redeem at p
#     (floor(usdyOut * p / 1e18));
#   CusdVault.settleSavingsExit: fee = ceil(gross * feeBps / 1e4), net = gross - fee.
# pPlus only rises between quote and inclusion (a fall trips the vault's
# oracle guard and the redeem reverts), so sizing at the price live NOW
# keeps net >= target; the excess grows with accrual and is bounded over
# the quote's own lifetime (after its expiration GM refuses it anyway).

USDT_EXCESS_MAX = 10 ** 16           # ConfioSmartAccount.USDT_EXCESS_MAX
MAX_ACCRUAL_JUMP_BPS = 200           # CusdPlusVault.MAX_ACCRUAL_JUMP_BPS
INCLUSION_SLACK_SECONDS = 60         # clock skew + inclusion past expiration checks
DEFAULT_HORIZON_SECONDS = 300        # a quote without an expiration
APY_CEILING_NO_ORACLE = Decimal('0.10')  # no rate oracle wired: assume a high rate


def apply_growth(p_plus: int, last: int, new_price: int, share_bps: int) -> int:
    """CusdPlusVault._applyGrowth (mulDiv floors)."""
    if new_price <= last:
        return p_plus
    growth = (new_price - last) * WAD // last
    kept = growth * (BPS - share_bps) // BPS
    return p_plus * (WAD + kept) // WAD


def exit_net_usdt(shares: int, p_plus: int, oracle: int, exit_fee_bps: int) -> int:
    """USDT redeemToUsdt(shares) pays out at (pPlus, oracle) after accrue()."""
    usdy = shares * p_plus // oracle
    gross = usdy * oracle // WAD
    fee = (gross * exit_fee_bps + BPS - 1) // BPS if gross and exit_fee_bps else 0
    return gross - fee


def shares_for_usdt(target: int, p_plus: int, oracle: int, exit_fee_bps: int) -> int:
    """The fewest shares whose exit pays at least `target`."""
    if target <= 0:
        raise QuoteUnavailable('bad_spend')
    gross = (target * BPS + (BPS - exit_fee_bps) - 1) // (BPS - exit_fee_bps)
    shares = (gross * WAD + p_plus - 1) // p_plus
    for _ in range(1_000):
        if exit_net_usdt(shares, p_plus, oracle, exit_fee_bps) >= target:
            break
        shares += 1
    else:
        raise QuoteUnavailable('share_sizing_failed')
    while shares > 1 and exit_net_usdt(shares - 1, p_plus, oracle, exit_fee_bps) >= target:
        shares -= 1
    return shares


def _vault_state() -> dict:
    """Fresh vault state the next redeem will see. Raises QuoteUnavailable."""
    from cusd_plus import vault
    try:
        p_plus = int(vault.p_plus_wad(fresh=True))
        last = int(vault.last_oracle_price_wad(fresh=True))
        live = int(vault.current_oracle_price_wad(fresh=True))
        share_bps = int(vault.confio_yield_share_bps())
        daily = Decimal(str(vault.usdy_daily_rate())) if vault.rate_oracle_address() else None
    except Exception as exc:  # noqa: BLE001
        raise QuoteUnavailable('share_price_unavailable', retry_later=True, detail=str(exc)[:200]) from exc
    if p_plus <= 0 or last <= 0 or live < last or (live - last) * BPS > MAX_ACCRUAL_JUMP_BPS * last:
        # The redeem's accrue() would trip the oracle guard: it reverts.
        raise QuoteUnavailable('share_price_unavailable', retry_later=True)
    if daily is None:
        daily = Decimal(str((1.0 + float(APY_CEILING_NO_ORACLE)) ** (1.0 / 365.0) - 1.0))
    return {'p_plus': apply_growth(p_plus, last, live, share_bps), 'oracle': live,
            'share_bps': share_bps, 'daily_rate': max(daily, Decimal(0)),
            'stored_p_plus': p_plus, 'last_oracle': last}


def grown_prices(state: dict, horizon_seconds: int) -> tuple[int, int]:
    """(pPlus, oracle) at the end of `horizon_seconds`: the oracle grown at
    the daily rate (rounded up) and pPlus accrued to it as _applyGrowth does.
    pPlus only rises, so this is the HIGHEST price a call sent now can meet."""
    growth = state['daily_rate'] * Decimal(int(horizon_seconds)) / Decimal(86_400)
    late_oracle = int((Decimal(state['oracle']) * (1 + growth)).to_integral_value(rounding=ROUND_CEILING))
    return apply_growth(state['p_plus'], state['oracle'], late_oracle, state['share_bps']), late_oracle


RELAY_HORIZON_SECONDS = DEFAULT_HORIZON_SECONDS + INCLUSION_SLACK_SECONDS


def plus_price_window(horizon_seconds: int = RELAY_HORIZON_SECONDS, state: dict | None = None) -> tuple[int, int]:
    """(low, high) pPlus a relayer call sent now executes at. The account
    calls accrue() before it converts dollars to shares, so the STORED pPlus
    is never the one it uses: `low` is pPlus accrued to the live oracle (the
    call's own accrue() if it were mined now), `high` that price grown over
    the inclusion horizon. Raises QuoteUnavailable (retry_later) when the
    vault cannot be read or its oracle guard would trip."""
    state = state or _vault_state()
    high, late_oracle = grown_prices(state, horizon_seconds)
    if state.get('stored_p_plus') and state.get('last_oracle'):
        # One accrue() from the stored baseline straight to the late oracle
        # compounds the kept share once, which is (slightly) above accruing
        # in two steps: the highest pPlus the call can meet is the larger.
        high = max(high, apply_growth(state['stored_p_plus'], state['last_oracle'], late_oracle,
                                      state['share_bps']))
    return state['p_plus'], high


def shares_ceil(amount_usd_wei: int, p_plus: int) -> int:
    """ConfioSmartAccount._toShares: ceil(usd * 1e18 / pPlus)."""
    if p_plus <= 0:
        raise QuoteUnavailable('share_price_unavailable', retry_later=True)
    return (int(amount_usd_wei) * WAD + p_plus - 1) // p_plus


def size_buy_shares(target_usdt: int, *, exit_fee_bps: int, expiration: int | None,
                    state: dict | None = None, now: int | None = None) -> int:
    """cUSD+ shares whose redemption pays at least `target_usdt` and, through
    the quote's lifetime, less than target + USDT_EXCESS_MAX. Raises
    QuoteUnavailable(retry_later) when accrual over that lifetime alone
    would exceed the window: the run is skipped and retried, never sent."""
    import time
    state = state or _vault_state()
    now = int(now if now is not None else time.time())
    p_plus, oracle = state['p_plus'], state['oracle']
    shares = shares_for_usdt(target_usdt, p_plus, oracle, exit_fee_bps)
    horizon = (max(0, int(expiration) - now) if expiration else DEFAULT_HORIZON_SECONDS) + INCLUSION_SLACK_SECONDS
    late_p_plus, late_oracle = grown_prices(state, horizon)
    excess = exit_net_usdt(shares, late_p_plus, late_oracle, exit_fee_bps) - target_usdt
    if excess >= USDT_EXCESS_MAX:
        raise QuoteUnavailable('usdt_excess_window', retry_later=True,
                               detail=f'excess {excess} over {horizon}s')
    return shares


def _exit_fee_for(mode: str) -> int:
    """The fee the router's redemption pays: cUSD's live exit fee on the
    perimeter (v2, redeemToUsdt); none on the legacy router (it takes its
    own 30 bps out of min_usdt, which is then the target)."""
    from cusd_plus import stock_fees
    if mode == stock_fees.MODE_ROUTER:
        return 0
    try:
        return int(chain.conversion_fee_bps())
    except Exception as exc:  # noqa: BLE001
        raise QuoteUnavailable('fee_unavailable', retry_later=True, detail=str(exc)[:200]) from exc


def resize_stock_buy_call(call: dict) -> dict:
    """The same buyWithSavings call with sharesIn re-sized by
    size_buy_shares (an account trade the app built from the personal-wallet
    quote, whose shares carry the personal flow's exit buffer)."""
    from cusd_plus import sponsor_7702, stock_fees
    data = (call.get('data') or '').lower()
    if data[2:10] != sponsor_7702.SEL_STOCK_BUY:
        raise QuoteUnavailable('not_a_stock_buy')
    from eth_abi import decode as abi_decode
    types = [sponsor_7702.GM_QUOTE_ABI, 'bytes', 'uint256', 'uint256', 'uint256', 'uint256']
    quote, signature, _shares, spend, min_usdt, max_fee = abi_decode(types, bytes.fromhex(data[10:]))
    mode = stock_fees.MODE_PERIMETER if min_usdt == spend else stock_fees.MODE_ROUTER
    shares = size_buy_shares(int(min_usdt), exit_fee_bps=_exit_fee_for(mode), expiration=int(quote[6]))
    encoded = abi_encode(types, [quote, signature, shares, spend, min_usdt, max_fee])
    return {'to': call['to'], 'value': '0', 'data': '0x' + sponsor_7702.SEL_STOCK_BUY + encoded.hex()}


def stock_buy_notional(amount_usd: Decimal) -> Decimal:
    """Largest notional whose cUSD+ exit (fee and buffer included) fits a
    rule's dollar amount."""
    from cusd_plus import stock_fees
    fee_bps, _mode = _stock_fee()
    room = Decimal(BPS - fee_bps - stock_fees.exit_buffer_bps() - 10) / Decimal(BPS)
    return (amount_usd * room).quantize(Decimal('0.01'), rounding=ROUND_DOWN)


def min_stock_rule_amount() -> Decimal:
    """The smallest rule amount (cents) whose stock_buy_notional reaches
    MIN_STOCK_ORDER_USD. Raises QuoteUnavailable when the fee policy is
    unreadable."""
    from cusd_plus import stock_fees
    fee_bps, _mode = _stock_fee()
    room = Decimal(BPS - fee_bps - stock_fees.exit_buffer_bps() - 10) / Decimal(BPS)
    if room <= 0:
        raise QuoteUnavailable('stock_fee_policy_unavailable')
    amount = (MIN_STOCK_ORDER_USD / room).quantize(Decimal('0.01'), rounding=ROUND_CEILING)
    while stock_buy_notional(amount) < MIN_STOCK_ORDER_USD:
        amount += Decimal('0.01')
    return amount


def stock_buy_call(symbol: str, notional_usd: Decimal, share_limit: int) -> dict:
    """buyWithSavings calldata spending at most `share_limit` cUSD+ shares."""
    from cusd_plus import sponsor_7702, stock_fees
    if notional_usd < MIN_STOCK_ORDER_USD:
        raise QuoteUnavailable('below_minimum_order')
    fee_bps, mode = _stock_fee()
    quote = _binding_quote(symbol, 'buy', notional_usd)
    spend = int(quote['notional_wei'])
    if mode == stock_fees.MODE_ROUTER:
        min_usdt = spend + (spend * fee_bps + (BPS - fee_bps) - 1) // (BPS - fee_bps)
    else:
        min_usdt = spend
    # Sized to the contract's one-cent excess window, never with the
    # personal flow's exit buffer (that buffer comes back as excess USDT).
    shares = size_buy_shares(min_usdt, exit_fee_bps=_exit_fee_for(mode), expiration=int(quote['expiration']))
    if shares > share_limit:
        raise QuoteUnavailable('exceeds_rule_amount')
    encoded = abi_encode(
        [sponsor_7702.GM_QUOTE_ABI, 'bytes', 'uint256', 'uint256', 'uint256', 'uint256'],
        [_quote_tuple(quote), bytes.fromhex(quote['signature_hex'][2:]), shares, spend, min_usdt, fee_bps])
    call = {'to': chain.stock_router_address(), 'value': '0', 'data': '0x' + sponsor_7702.SEL_STOCK_BUY + encoded.hex()}
    action = _checked_stock(call)
    return {'call': call, 'token': action['asset'], 'max_in': shares,
            'min_out': int(quote['token_amount']) * 99 // 100,
            'quote_ref': str(quote['attestation_id']), 'expiration': int(quote['expiration'])}


def stock_sell_call(symbol: str, notional_usd: Decimal) -> dict:
    """sellToSavings calldata for about `notional_usd` of one stock."""
    from cusd_plus import sponsor_7702, stock_fees, vault
    if notional_usd < MIN_STOCK_ORDER_USD:
        notional_usd = MIN_STOCK_ORDER_USD
    fee_bps, mode = _stock_fee()
    quote = _binding_quote(symbol, 'sell', notional_usd.quantize(Decimal('0.01'), rounding=ROUND_DOWN))
    quantity, price = int(quote['token_amount']), int(quote['price'])
    quote_cost = quantity * price // WAD
    min_usdt = quote_cost * 995 // 1000
    if mode == stock_fees.MODE_ROUTER:
        net = min_usdt - (min_usdt * stock_fees.LEGACY_STOCK_FEE_BPS // BPS)
    else:
        net = min_usdt - stock_fees.perimeter_fee(min_usdt, fee_bps)
    pps = vault.p_plus_wad(fresh=True)
    if pps <= 0 or net <= 0:
        raise QuoteUnavailable('share_price_unavailable')
    min_shares = (net * WAD // pps) * 995 // 1000
    if min_shares <= 0:
        raise QuoteUnavailable('below_minimum_order')
    encoded = abi_encode(
        [sponsor_7702.GM_QUOTE_ABI, 'bytes', 'uint256', 'uint256', 'uint256'],
        [_quote_tuple(quote), bytes.fromhex(quote['signature_hex'][2:]), min_usdt, min_shares, fee_bps])
    call = {'to': chain.stock_router_address(), 'value': '0', 'data': '0x' + sponsor_7702.SEL_STOCK_SELL + encoded.hex()}
    action = _checked_stock(call)
    return {'call': call, 'token': action['asset'], 'max_in': quantity,
            'expected_dollars_wei': net, 'quote_ref': str(quote['attestation_id']),
            'expiration': int(quote['expiration'])}


def _checked_crypto(call: dict) -> dict:
    from cusd_plus.crypto_policy import CryptoPolicyError, decode_crypto_call
    try:
        action = decode_crypto_call(call)
    except CryptoPolicyError as exc:
        raise QuoteUnavailable('crypto_call_rejected', detail=str(exc)) from exc
    if action is None:
        raise QuoteUnavailable('crypto_router_not_configured')
    return action


def _midpoint_floor(amount: int) -> int:
    """Between the policy's slippage floor and the quote itself."""
    from cusd_plus.crypto_policy import _slip_floor
    floor = _slip_floor(amount)
    return floor + (amount - floor) // 2


def crypto_buy_call(token, dollar: int, amount_in: int) -> dict:
    from cusd_plus import crypto_policy
    from cusd_plus.crypto_prices import quote_exact_in
    try:
        fee = crypto_policy.live_fee_bps()
        _gross, net = crypto_policy.expected_exit_usdt(dollar, amount_in)
        expected_out = quote_exact_in(token, 'buy', net)
    except Exception as exc:  # noqa: BLE001
        raise QuoteUnavailable('crypto_quote_unavailable', detail=str(exc)[:200]) from exc
    if net <= 0 or expected_out <= 0:
        raise QuoteUnavailable('crypto_quote_unavailable')
    min_usdt = _midpoint_floor(net)
    min_token = _midpoint_floor(expected_out)
    encoded = abi_encode(crypto_policy.BUY_TYPES,
                         [dollar, amount_in, min_usdt, token.route_bytes('buy'), token.address, min_token, fee])
    call = {'to': chain.swap_router_address(), 'value': '0',
            'data': '0x' + crypto_policy.SEL_CRYPTO_BUY + encoded.hex()}
    _checked_crypto(call)
    return {'call': call, 'token': token.address, 'max_in': amount_in, 'min_out': min_token}


def crypto_sell_call(token, dollar: int, amount_in: int) -> dict:
    from cusd_plus import crypto_policy
    from cusd_plus.crypto_prices import quote_exact_in
    try:
        fee = crypto_policy.live_fee_bps()
        net = quote_exact_in(token, 'sell', amount_in)
    except Exception as exc:  # noqa: BLE001
        raise QuoteUnavailable('crypto_quote_unavailable', detail=str(exc)[:200]) from exc
    if net <= 0:
        raise QuoteUnavailable('crypto_quote_unavailable')
    min_usdt = _midpoint_floor(net)
    entry_net = min_usdt - (min_usdt * fee + BPS - 1) // BPS
    try:
        expected_dest = entry_net if dollar == crypto_policy.DOLLAR else crypto_policy._expected_plus_shares(entry_net)
    except Exception as exc:  # noqa: BLE001
        raise QuoteUnavailable('crypto_quote_unavailable', detail=str(exc)[:200]) from exc
    min_dest = _midpoint_floor(expected_dest)
    if min_dest <= 0:
        raise QuoteUnavailable('crypto_quote_unavailable')
    encoded = abi_encode(crypto_policy.SELL_TYPES,
                         [dollar, token.address, amount_in, token.route_bytes('sell'), min_usdt, min_dest, fee])
    call = {'to': chain.swap_router_address(), 'value': '0',
            'data': '0x' + crypto_policy.SEL_CRYPTO_SELL + encoded.hex()}
    _checked_crypto(call)
    return {'call': call, 'token': token.address, 'max_in': amount_in, 'expected_dollars_wei': entry_net}


def confio_sell_call(venue: str, dollar: int, amount_in: int) -> dict:
    """A CONFIO forced-sale leg through the venue the account latched (5.5).
    The venue speaks the swap router's `sell`; until CONFIO has a catalog
    route through the configured swap router there is no quote to build, and
    the leg is not planned (the account's other holdings are tried)."""
    from cusd_plus import crypto_catalog
    if (venue or '').lower() != chain.swap_router_address():
        raise QuoteUnavailable('confio_venue_unsupported', detail=venue)
    token = crypto_catalog.by_address(chain.confio_address(), include_unlisted=True)
    if token is None:
        raise QuoteUnavailable('confio_route_unavailable')
    return crypto_sell_call(token, dollar, amount_in)
