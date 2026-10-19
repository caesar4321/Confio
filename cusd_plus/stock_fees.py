"""Which stock-trade fee caps Confío's relay will sponsor.

Router v2 charges no fee of its own: a stock buy pays cUSD's ordinary 0.9%
exit fee and a sell pays its 0.9% entry fee, exactly like a USDT withdrawal
or deposit. The router keeps a transitional legacy path for pre-v2 app
builds, which always sign maxFeeBps = 30 and size amounts for the old 0.30%
router fee. Both router entry points are sponsor-originated, so this module
is the switch that decides how long legacy intents are honored.

Rollout:
  1. Router v2 live  -> CUSD_PLUS_STOCK_CONVERSION_FEE_BPS = 90 (mirror of
     cUSD.feeBps); legacy stays enabled so old builds keep trading at 0.30%.
  2. New build live on both stores -> CUSD_PLUS_STOCK_LEGACY_FEE_ENABLED =
     False, force-update, then the single-mode router upgrade.
"""
from django.conf import settings

LEGACY_STOCK_FEE_BPS = 30
BPS = 10_000

MODE_ROUTER = 'router'  # v1 math: 30 bps accrued by the router
MODE_PERIMETER = 'perimeter'  # v2 math: cUSD's fee on the cUSD+ exit/entry


def conversion_fee_bps() -> int:
    """cUSD's fee as configured for router v2; 0 until v2 is live."""
    return int(getattr(settings, 'CUSD_PLUS_STOCK_CONVERSION_FEE_BPS', 0) or 0)


def legacy_fee_enabled() -> bool:
    """Whether a cap of 30 is sponsored as the legacy router path.

    The router treats cap 30 as legacy only while cUSD's live fee is ABOVE
    30; at or below it, 30 settles on the perimeter path where legacy floors
    revert. So legacy is honored only with router v1 (no v2 fee yet) or a v2
    fee strictly above 30 (Codex audit 2026-10-19 [P2]).
    """
    if not getattr(settings, 'CUSD_PLUS_STOCK_LEGACY_FEE_ENABLED', True):
        return False
    conversion = conversion_fee_bps()
    return conversion == 0 or conversion > LEGACY_STOCK_FEE_BPS


def accepted_fee_caps() -> dict[int, str]:
    """Signed maxFeeBps values the relay sponsors, mapped to their math mode."""
    caps: dict[int, str] = {}
    if legacy_fee_enabled():
        caps[LEGACY_STOCK_FEE_BPS] = MODE_ROUTER
    conversion = conversion_fee_bps()
    if conversion > 0:
        caps[conversion] = MODE_PERIMETER
    return caps


def client_fee_policy() -> tuple[int, str] | None:
    """The fee a current app build should quote and sign, or None if none."""
    conversion = conversion_fee_bps()
    if conversion > 0:
        return conversion, MODE_PERIMETER
    if legacy_fee_enabled():
        return LEGACY_STOCK_FEE_BPS, MODE_ROUTER
    return None


def legacy_display_fee_bps() -> int:
    """Value for the pre-v2 `gmTradeFeeBps` field.

    Pre-v2 builds refuse to trade unless this is exactly 30. Once legacy is
    switched off it reports the real fee, so those builds stop at their
    config check before quoting or signing anything.
    """
    if legacy_fee_enabled():
        return LEGACY_STOCK_FEE_BPS
    conversion = conversion_fee_bps()
    # Never report exactly 30 once legacy is off, or pre-v2 builds would pass
    # their config check and sign an intent the relay will refuse.
    return conversion if conversion != LEGACY_STOCK_FEE_BPS else 0


def perimeter_fee(gross_wei: int, fee_bps: int) -> int:
    """Mirror of CusdVault.feeFor: ceil(gross * feeBps / 10_000)."""
    if gross_wei <= 0 or fee_bps <= 0:
        return 0
    return (gross_wei * fee_bps + BPS - 1) // BPS


def perimeter_gross_for_net(net_wei: int, fee_bps: int) -> int:
    """Smallest gross whose post-fee net covers `net_wei`."""
    gross = (net_wei * BPS + (BPS - fee_bps) - 1) // (BPS - fee_bps)
    while gross - perimeter_fee(gross, fee_bps) < net_wei:
        gross += 1
    return gross
