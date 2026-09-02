"""Canonical currency identifiers for ramp settlement and final products.

Provider strings are not product identifiers. In particular, Koywe calls its
settlement asset ``USDT BSC`` while the product produced by a completed
``usdt_to_cusd`` conversion is canonical ``CUSD_BSC``. Keep this mapping in
one place so webhook sync and post-save signals cannot race to different
labels for the same RampTransaction.
"""

RAW_USDT_BSC = 'USDT BSC'
CUSD_BSC = 'CUSD_BSC'
CUSD_PLUS = 'CUSD+'


def bsc_final_currency(conversion_type: str, *, fallback: str = RAW_USDT_BSC) -> str:
    """Return the user product created by a completed BSC conversion.

    ``fallback`` is deliberately explicit for unknown/legacy conversion
    types. A provider-completed on-ramp remains raw USDT until a completed
    conversion proves which jurisdiction-dependent product was minted.
    """

    return {
        'to_savings': CUSD_PLUS,
        'usdt_to_cusd': CUSD_BSC,
        'from_savings': RAW_USDT_BSC,
        'cusd_to_usdt': RAW_USDT_BSC,
    }.get((conversion_type or '').strip(), fallback)
