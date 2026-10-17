"""All-time U.S. stock volume traded in Confío, for Home's "Acciones" tile.

The sum of every confirmed stock trade's exact settlement (its unified
history row: what a buy debited, what a sale paid), buys and sales alike.
Stock trades never pass through conversions, so the money-flow totals
(Dinero en movimiento) don't include them and this never double counts.
Read from gm_trading_stats' shared snapshot (aggregate only, privacy floor).
"""


def traded_usd() -> float | None:
    """All-time settled stock volume in USD; None when it can't be stated.
    Only from the shared snapshot behind Acciones en movimiento: the tile
    never shows a total the screen it opens can't (still building, or below
    the privacy floor). Home then keeps its other numbers."""
    from .gm_trading_stats import MIN_TRADERS, snapshot

    stats = snapshot()
    if stats is None or stats.trader_count < MIN_TRADERS:
        return None
    return stats.total_usd
