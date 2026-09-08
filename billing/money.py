"""Exact integer-unit equations shared by quotes, finalization, and tests."""

FEE_NUMERATOR = 90
FEE_DENOMINATOR = 10_000
RECEIVER_NUMERATOR = FEE_DENOMINATOR - FEE_NUMERATOR


def fee_units(gross_units: int) -> int:
    """The Pay contract's 0.9% receiver-side fee, rounded up."""
    if gross_units < 0:
        raise ValueError('gross_units must be non-negative')
    if gross_units == 0:
        return 0
    return (gross_units * FEE_NUMERATOR + FEE_DENOMINATOR - 1) // FEE_DENOMINATOR


def receiver_net_units(gross_units: int) -> int:
    return gross_units - fee_units(gross_units)


def minimal_gross_for_receiver_net(target_net_units: int) -> int:
    """Smallest gross whose post-contract-fee net reaches the target."""
    if target_net_units < 0:
        raise ValueError('target_net_units must be non-negative')
    if target_net_units == 0:
        return 0
    gross = (
        target_net_units * FEE_DENOMINATOR + RECEIVER_NUMERATOR - 1
    ) // RECEIVER_NUMERATOR
    while receiver_net_units(gross) < target_net_units:
        gross += 1
    while gross > 0 and receiver_net_units(gross - 1) >= target_net_units:
        gross -= 1
    return gross
