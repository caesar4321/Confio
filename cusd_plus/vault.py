"""
Read-only view of the cUSD+ vault on BSC (chain-first: the chain is the
truth). Thin eth_call helpers over the deployed CusdPlusVault — the same
pattern as gm_api.py, no web3 dependency.

Nothing here signs or moves funds; it reads the user's position and the
vault's public health so the Ahorros surfaces show real numbers.
"""
import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Selectors computed from signatures once (no hand-copy errors).
from eth_utils import keccak  # noqa: E402


def _sel(sig: str) -> str:
    return '0x' + keccak(text=sig)[:4].hex()


SEL_BALANCE_OF = _sel('balanceOf(address)')
SEL_PPLUS = _sel('pPlus()')
SEL_TOTAL_SUPPLY = _sel('totalSupply()')
SEL_BACKING = _sel('backingRatioBps()')
SEL_TOTAL_OWED = _sel('totalOwedUsd()')


def vault_address() -> str | None:
    return getattr(settings, 'CUSD_PLUS_VAULT_ADDRESS', None)


def _rpc(method: str, params: list, timeout: int = 12):
    url = getattr(settings, 'BSC_RPC_URL', 'https://bsc-dataseed.bnbchain.org')
    resp = requests.post(
        url, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params},
        timeout=timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    if 'error' in body:
        raise RuntimeError(f"bsc rpc {method}: {body['error']}")
    return body['result']


def _call(to: str, data: str) -> int:
    res = _rpc('eth_call', [{'to': to, 'data': data}, 'latest'])
    return int(res, 16) if res and res != '0x' else 0


def p_plus_wad() -> int:
    """Share price in USD, 1e18. Cached briefly — moves only on accrual."""
    addr = vault_address()
    if not addr:
        return 10 ** 18
    cached = cache.get('cusd_plus_pplus')
    if cached is None:
        cached = _call(addr, SEL_PPLUS) or 10 ** 18
        cache.set('cusd_plus_pplus', cached, 30)
    return cached


def position_usd(user_bsc_address: str) -> float:
    """USD value of an address's cUSD+ position = shares × pPlus.
    Returns 0.0 if the vault isn't wired or the address holds nothing."""
    addr = vault_address()
    if not addr or not user_bsc_address:
        return 0.0
    try:
        shares = _call(addr, SEL_BALANCE_OF + user_bsc_address.lower().replace('0x', '').rjust(64, '0'))
        if shares == 0:
            return 0.0
        return (shares * p_plus_wad()) / (10 ** 36)
    except Exception:  # noqa: BLE001 — read failure must not break the screen
        logger.warning('cUSD+ position read failed for %s', user_bsc_address, exc_info=True)
        return 0.0


def health() -> dict:
    """Public vault health for admin / verify surfaces."""
    addr = vault_address()
    if not addr:
        return {'wired': False}
    try:
        return {
            'wired': True,
            'address': addr,
            'p_plus': p_plus_wad() / 1e18,
            'total_owed_usd': _call(addr, SEL_TOTAL_OWED) / 1e18,
            'backing_ratio_bps': _call(addr, SEL_BACKING),
        }
    except Exception as exc:  # noqa: BLE001
        return {'wired': True, 'address': addr, 'error': str(exc)}
