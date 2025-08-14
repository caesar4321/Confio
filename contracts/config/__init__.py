"""
Compatibility package that re-exports LocalNet config used by deploy scripts.

This module bridges imports like `contracts.config.algorand_localnet_config`
to the canonical files under `contracts/payment/config/`.
"""

from .algorand_localnet_config import *  # noqa: F401,F403
try:
    from .localnet_accounts import *  # noqa: F401,F403
except Exception:
    pass
try:
    from .localnet_assets import *  # noqa: F401,F403
except Exception:
    pass

