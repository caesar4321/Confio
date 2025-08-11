"""
CONFIO Presale Module

This module implements a flexible presale system for CONFIO tokens with:
- Multiple rounds with adjustable parameters
- Flexible CONFIO/cUSD exchange rates
- Lock mechanism with permanent unlock
- Admin controls and user claims

Key files:
- confio_presale.py: Main presale smart contract
- deploy_presale.py: Deployment script
- admin_presale.py: Admin management interface
- interact_presale.py: User interaction interface
"""

from .confio_presale import confio_presale, compile_presale

__all__ = ['confio_presale', 'compile_presale']