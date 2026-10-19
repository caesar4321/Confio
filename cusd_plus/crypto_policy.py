"""Relay policy for ConfioSwapRouter calls (crypto & metals on PancakeSwap).

The relay sponsors a swap only when the calldata is the one canonical shape
a current Confío build produces:
- the token is in the catalog (buys: listed only; sells: any catalog entry,
  so a delisted position can always be sold);
- the route is EXACTLY the catalog route for that token and direction;
- the signed fee cap equals cUSD's live fee (the router binds it on-chain);
- the floors are no weaker than a live server requote allows
  (CRYPTO_MAX_SLIPPAGE_BPS), so a buggy or stale client cannot get a user's
  dollars swapped at a bad price.
Historical decoding (history, receipts) skips the live checks.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak

from . import crypto_catalog

logger = logging.getLogger(__name__)

BPS = 10_000
DOLLAR_PLUS = 0  # cUSD+
DOLLAR = 1  # cUSD

BUY_TYPES = ['uint8', 'uint256', 'uint256', 'bytes', 'address', 'uint256', 'uint256']
SELL_TYPES = ['uint8', 'address', 'uint256', 'bytes', 'uint256', 'uint256', 'uint256']
SEL_CRYPTO_BUY = keccak(text='buy(uint8,uint256,uint256,bytes,address,uint256,uint256)')[:4].hex()
SEL_CRYPTO_SELL = keccak(text='sell(uint8,address,uint256,bytes,uint256,uint256,uint256)')[:4].hex()


class CryptoPolicyError(Exception):
    pass


def router_address() -> str:
    return (getattr(settings, 'CRYPTO_SWAP_ROUTER_ADDRESS', '') or '').lower()


def live_fee_bps() -> int:
    """cUSD.feeBps() on-chain (60 s cache). Raises when unreadable."""
    cached = cache.get('crypto_cusd_fee_bps')
    if cached is not None:
        return int(cached)
    from . import vault

    cusd = (getattr(settings, 'CUSD_VAULT_ADDRESS', '') or '').lower()
    if not cusd:
        raise CryptoPolicyError('cusd_not_configured')
    fee = int(vault._call(cusd, '0x' + keccak(text='feeBps()')[:4].hex()))
    cache.set('crypto_cusd_fee_bps', fee, 60)
    return fee


def expected_exit_usdt(source: int, amount_in: int) -> tuple[int, int]:
    """(gross, net) USDT a buy's dollar exit yields, mirroring the vaults."""
    from . import vault
    from .cusd_vault import preview_redeem_wei

    if source == DOLLAR:
        preview = preview_redeem_wei(amount_in)
        return amount_in, preview.net_wei
    pps = vault.p_plus_wad(fresh=True)
    oracle = vault.last_oracle_price_wad(fresh=True)
    return vault.redeem_gross_usdt_out(amount_in, pps, oracle), vault.redeem_usdt_out(amount_in, pps, oracle)


def _expected_plus_shares(net_usdt: int) -> int:
    """cUSD+ shares a subscribe of `net_usdt` mints (vault math, floors)."""
    from . import vault

    pps = vault.p_plus_wad(fresh=True)
    oracle = vault.current_oracle_price_wad(fresh=True)
    if pps <= 0 or oracle <= 0:
        raise CryptoPolicyError('crypto_quote_unavailable')
    usdy = net_usdt * 10 ** 18 // oracle
    return usdy * oracle // pps


def _slip_floor(amount: int) -> int:
    bps = int(getattr(settings, 'CRYPTO_MAX_SLIPPAGE_BPS', 100))
    return amount * (BPS - bps) // BPS


def decode_crypto_call(call: dict, *, historical: bool = False) -> dict | None:
    """Decode a router call; None when the call is not to the swap router."""
    router = router_address()
    if not router or call['to'] != router:
        return None
    if not historical and not getattr(settings, 'CRYPTO_TRADING_ENABLED', False):
        raise CryptoPolicyError('crypto_trading_disabled')
    data = call['data']
    if not data.startswith('0x') or len(data) > 4_096 or (len(data) - 2) % 2 != 0:
        raise CryptoPolicyError('bad_calldata')
    data_hex = data[2:].lower()
    selector = data_hex[:8]
    try:
        raw = bytes.fromhex(data_hex[8:])
        if selector == SEL_CRYPTO_BUY:
            types = BUY_TYPES
        elif selector == SEL_CRYPTO_SELL:
            types = SELL_TYPES
        else:
            raise CryptoPolicyError('selector_not_allowed')
        decoded = abi_decode(types, raw)
        if abi_encode(types, decoded) != raw:
            raise CryptoPolicyError('bad_calldata')
    except CryptoPolicyError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CryptoPolicyError('bad_calldata') from exc

    if selector == SEL_CRYPTO_BUY:
        dollar, amount_in, min_usdt, route, token_addr, min_token, max_fee = decoded
        kind, side = 'crypto_buy', 'buy'
        # Buys need a LISTED token; history must still decode a later delisting.
        token = crypto_catalog.by_address(token_addr, include_unlisted=historical)
    else:
        dollar, token_addr, amount_in, route, min_usdt, min_token, max_fee = decoded
        kind, side = 'crypto_sell', 'sell'
        token = crypto_catalog.by_address(token_addr, include_unlisted=True)
    if token is None:
        raise CryptoPolicyError('token_not_listed')
    if dollar not in (DOLLAR_PLUS, DOLLAR):
        raise CryptoPolicyError('bad_dollar')
    if amount_in <= 0 or min_usdt <= 0 or min_token <= 0:
        raise CryptoPolicyError('bad_crypto_floor')
    # Live: exactly today's catalog route. History must still decode what
    # executed after a catalog route change (the router enforced the
    # endpoints on-chain), so it only checks the shape.
    if not historical and route != token.route_bytes(side):
        raise CryptoPolicyError('route_not_allowed')

    action = {
        'kind': kind,
        'token': token,
        'asset': token.address,
        'dollar': dollar,
        'amount_in': amount_in,
        'min_usdt': min_usdt,
        # buy: token floor; sell: dollar floor
        'min_out': min_token,
        'max_fee': max_fee,
    }
    if historical:
        # Receipt events replace these estimates with exact values.
        action['history_amount_wei'] = amount_in if (side == 'buy' and dollar == DOLLAR) else min_usdt
        return action

    try:
        fee = live_fee_bps()
    except Exception as exc:  # noqa: BLE001 — money policy fails closed
        logger.warning('crypto fee read failed: %s', exc)
        raise CryptoPolicyError('crypto_quote_unavailable') from exc
    if max_fee != fee:
        raise CryptoPolicyError('bad_crypto_fee_cap')

    from .crypto_prices import quote_exact_in

    try:
        if side == 'buy':
            gross, net = expected_exit_usdt(dollar, amount_in)
            expected_out = quote_exact_in(token, 'buy', net)
        else:
            gross = None
            net = quote_exact_in(token, 'sell', amount_in)
            expected_out = None
    except Exception as exc:  # noqa: BLE001
        logger.warning('crypto requote failed for %s: %s', token.symbol, exc)
        raise CryptoPolicyError('crypto_quote_unavailable') from exc

    if side == 'buy':
        if token.max_order_usd is not None and gross > token.max_order_usd * 10 ** 18:
            # Thin pool: a larger order would move the price against the user.
            raise CryptoPolicyError('crypto_order_too_large')
        # The exit floor binds the NET after cUSD's fee: never above what the
        # exit yields (the trade would revert) nor weaker than the slippage cap.
        if min_usdt > net or min_usdt < _slip_floor(net):
            raise CryptoPolicyError('bad_crypto_floor')
        if expected_out <= 0 or min_token < _slip_floor(expected_out):
            raise CryptoPolicyError('bad_crypto_floor')
        action['history_amount_wei'] = gross
    else:
        if net <= 0 or min_usdt < _slip_floor(net) or min_usdt > net:
            raise CryptoPolicyError('bad_crypto_floor')
        # What re-enters Confío dollars at the swap floor, after the fee.
        entry_net = min_usdt - (min_usdt * fee + BPS - 1) // BPS
        if dollar == DOLLAR:
            # cUSD mints 1:1 minus the entry fee: the dollar floor is exact math.
            expected_dest = entry_net
        else:
            # cUSD+ entry: never mint a position below Ondo's redeem floor
            # (the generic mint guard can't see a router-routed subscribe).
            from . import vault

            if not vault.is_safe_mint_amount(entry_net):
                raise CryptoPolicyError('savings_mint_too_small')
            try:
                expected_dest = _expected_plus_shares(entry_net)
            except CryptoPolicyError:
                raise
            except Exception as exc:  # noqa: BLE001 — money policy fails closed
                raise CryptoPolicyError('crypto_quote_unavailable') from exc
        if min_token < _slip_floor(expected_dest):
            raise CryptoPolicyError('bad_crypto_floor')
        action['history_amount_wei'] = min_usdt
    return action
