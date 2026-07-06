"""
Allbridge Core stableswap quote math — Python port of the client's
apps/src/services/allbridgeQuote.ts (itself a validated port of the
official SDK's getAmountToBeReceived; deltas ≤ 1 micro-unit).

Rule 8 of the sponsor checklist (ORCHESTRATION.md §6) uses this to
re-quote the route server-side immediately before signing: the sponsor
prices the conversion itself, so a stale or hostile client quote can
never commit a user to a bad fill.

Pure integer math end to end (Python ints are arbitrary precision, like
the BigInt port). Cross-validated against the TS port on a frozen
token-info snapshot — see tests/test_allbridge_math.py. Re-freeze the
vectors if Allbridge bumps their SDK major.
"""
from dataclasses import dataclass
from decimal import Decimal
from math import isqrt

WAD = 10 ** 18
SYSTEM_PRECISION = 3


def parse_fee_share_wad(fee_share: str) -> int:
    """'0.0015' → 1500000000000000, no float drift."""
    int_part, _, frac_part = fee_share.partition('.')
    frac = (frac_part + '0' * 18)[:18]
    return int(int_part) * WAD + int(frac)


@dataclass(frozen=True)
class Side:
    decimals: int
    fee_share_wad: int
    a_value: int
    d_value: int
    token_balance: int  # system precision (3)
    vusd_balance: int  # system precision (3)

    @classmethod
    def from_token_info(cls, token: dict) -> 'Side':
        pool = token['poolInfo']
        return cls(
            decimals=int(token['decimals']),
            fee_share_wad=parse_fee_share_wad(token['feeShare']),
            a_value=int(pool['aValue']),
            d_value=int(pool['dValue']),
            token_balance=int(pool['tokenBalance']),
            vusd_balance=int(pool['vUsdBalance']),
        )


def get_y(x: int, a: int, d: int) -> int:
    """y = (sqrt(x(4ad³ + x(4a(d−x) − d)²)) + x(4a(d−x) − d)) / 8ax, floored, +1."""
    common = 4 * a * (d - x) - d
    root = isqrt(x * (x * common * common + 4 * a * d * d * d))
    result = (common * x + root) // (8 * a * x)
    return 0 if result == 0 else result + 1


def swap_to_vusd(amount_units: int, side: Side) -> int:
    """Token units (source decimals) → vUsd (system precision 3)."""
    if amount_units <= 0:
        return 0
    net_scaled = amount_units * (WAD - side.fee_share_wad)
    divisor = WAD * 10 ** (side.decimals - SYSTEM_PRECISION)
    in_system = net_scaled // divisor
    y = get_y(side.token_balance + in_system, side.a_value, side.d_value)
    out = side.vusd_balance - y
    return out if out > 0 else 0


def swap_from_vusd(vusd: int, side: Side) -> int:
    """vUsd (system precision 3) → token units (dest decimals)."""
    if vusd <= 0:
        return 0
    y = get_y(vusd + side.vusd_balance, side.a_value, side.d_value)
    result_system = side.token_balance - y
    if result_system <= 0:
        return 0
    result_tokens = result_system * 10 ** (side.decimals - SYSTEM_PRECISION)
    return result_tokens * (WAD - side.fee_share_wad) // WAD


def quote_receive_units(amount_units: int, src: Side, dst: Side) -> int:
    return swap_from_vusd(swap_to_vusd(amount_units, src), dst)


# ── USD conveniences (Decimal in, exact ints inside) ─────────────────────

def usd_to_units(usd: Decimal, decimals: int) -> int:
    return int(usd.scaleb(6).to_integral_value()) * 10 ** (decimals - 6)


def units_to_usd(units: int, decimals: int) -> Decimal:
    return Decimal(units) / Decimal(10 ** decimals)


def quote_receive_usd(amount_usd: Decimal, src: Side, dst: Side) -> Decimal:
    receive = quote_receive_units(usd_to_units(amount_usd, src.decimals), src, dst)
    return units_to_usd(receive, dst.decimals)


def cost_bps(amount_usd: Decimal, receive_usd: Decimal) -> Decimal:
    if amount_usd <= 0:
        return Decimal(0)
    return (amount_usd - receive_usd) / amount_usd * 10_000


def max_fill_under_threshold_usd(
    max_usd: Decimal, threshold_bps: Decimal, src: Side, dst: Side,
) -> Decimal:
    """Largest amount ≤ max_usd whose cost stays under threshold_bps —
    integer bisection on cents (same boundary the TS port floors to)."""
    def cost_of_cents(cents: int) -> Decimal:
        usd = Decimal(cents).scaleb(-2)
        return cost_bps(usd, quote_receive_usd(usd, src, dst))

    hi = int(max_usd.scaleb(2).to_integral_value())
    if hi <= 0:
        return Decimal(0)
    if cost_of_cents(hi) <= threshold_bps:
        return Decimal(hi).scaleb(-2)
    lo = 0  # invariant: lo passes (0 trivially), hi fails
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if cost_of_cents(mid) <= threshold_bps:
            lo = mid
        else:
            hi = mid
    return Decimal(lo).scaleb(-2)
