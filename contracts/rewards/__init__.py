"""
Rewards distribution smart contracts.

Currently exposes the CONFIO rewards vault that is funded off-chain and allows
eligible users (and optional referrers) to self-claim allocations that were
attested by the backend.
"""

from .confio_rewards import compile_confio_rewards  # noqa: F401
