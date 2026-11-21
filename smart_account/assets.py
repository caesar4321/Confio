"""What an address holds, priced. Used for the account, for inherited
accounts and for the personal wallet's "move everything" preview.

Balances shown and moved are exact on-chain base units, read fresh; the
stored holdings pipelines only tell us WHICH tokens to read.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from . import chain

logger = logging.getLogger(__name__)

# Catalog tokens the account implementation can force-sell (price-feed
# constants in ConfioSmartAccount: BTCB and XAUt). Also the only tokens the
# account may trade through the swap router.
FEED_SYMBOLS = frozenset({'BTCB', 'XAUT'})


@dataclass
class Asset:
    key: str
    kind: str          # dollar | stock | crypto | confio | other
    symbol: str
    name: str
    address: str
    units: int
    decimals: int
    value_usd: Decimal | None
    can_pay_fee: bool


class AssetsUnknown(RuntimeError):
    """Holdings could not be enumerated. Never rendered as 'empty'."""


def _stock_market() -> dict:
    from cusd_plus import gm_api
    return {(item.get('primaryMarket') or {}).get('symbol'): item for item in gm_api.all_market()}


def stock_registry() -> dict:
    from cusd_plus import gm_holdings
    return gm_holdings.registry() or {}


def stock_by_address(address: str):
    address = (address or '').lower()
    for symbol, meta in stock_registry().items():
        if (meta.get('address') or '').lower() == address:
            return symbol, meta
    return None


def is_feed_token(token) -> bool:
    return token is not None and token.symbol.upper() in FEED_SYMBOLS


def resolve_asset_key(key: str):
    """(kind, symbol, address, decimals) for an asset key, or None."""
    from cusd_plus import crypto_catalog
    key = (key or '').strip()
    if key == 'cusd_plus':
        return 'dollar', 'cUSD+', chain.cusd_plus_address(), 18
    if key == 'cusd':
        return 'dollar', 'cUSD', chain.cusd_address(), 18
    if key == 'usdt':
        return 'other', 'USDT', chain.usdt_address(), 18
    if key == 'confio':
        return 'confio', 'CONFIO', chain.confio_address(), 18
    if key.startswith('stock:'):
        meta = stock_registry().get(key[6:])
        if meta:
            return 'stock', key[6:], meta['address'].lower(), int(meta.get('decimals') or 18)
        return None
    if key.startswith('crypto:'):
        token = crypto_catalog.by_symbol(key[7:], include_unlisted=True)
        if token:
            return 'crypto', token.symbol, token.address, token.decimals
        return None
    return None


def assets_of(address: str, *, include_zero_dollars: bool = False,
              confio_sale: tuple[str, str] | None = None) -> list[Asset]:
    """Everything Confío handles that `address` holds. Raises AssetsUnknown
    when the stock or crypto scan is unknown, and ChainError on a failed
    balance read. `confio_sale` is the (venue, price reference) an account
    latched (chain.confio_sale_of): CONFIO is then a fee source, priced by
    that reference (spec 5.5)."""
    from cusd_plus import crypto_catalog, crypto_holdings, crypto_prices, gm_holdings

    address = address.lower()
    out: list[Asset] = []
    p_plus = None

    plus, cusd = chain.cusd_plus_address(), chain.cusd_address()
    if plus:
        units = chain.balance_of(plus, address)
        if units or include_zero_dollars:
            p_plus = chain.p_plus_wad()
            out.append(Asset('cusd_plus', 'dollar', 'cUSD+', 'Confío Dollar+', plus, units, 18,
                             Decimal(units) * Decimal(p_plus) / Decimal(10 ** 36), True))
    if cusd:
        units = chain.balance_of(cusd, address)
        if units or include_zero_dollars:
            out.append(Asset('cusd', 'dollar', 'cUSD', 'Confío Dollar', cusd, units, 18,
                             Decimal(units) / Decimal(10 ** 18), True))
    usdt = chain.usdt_address()
    if usdt:
        units = chain.balance_of(usdt, address)
        if units:
            out.append(Asset('usdt', 'other', 'USDT', 'USDT', usdt, units, 18,
                             Decimal(units) / Decimal(10 ** 18), True))

    held_stocks = gm_holdings.holdings_units(address)
    if held_stocks is None:
        raise AssetsUnknown('stock holdings unknown')
    if held_stocks:
        registry = stock_registry()
        try:
            market = _stock_market()
        except Exception:  # noqa: BLE001 — unpriced, never a made-up value
            logger.warning('smart account: stock market data unavailable', exc_info=True)
            market = {}
        for symbol in held_stocks:
            meta = registry.get(symbol)
            if not meta:
                continue
            token_address = meta['address'].lower()
            decimals = int(meta.get('decimals') or 18)
            units = chain.balance_of(token_address, address)
            if not units:
                continue
            item = market.get(symbol) or {}
            price = (item.get('primaryMarket') or {}).get('price')
            under = item.get('underlyingMarket') or {}
            value = (Decimal(units) / Decimal(10 ** decimals) * Decimal(str(price))) if price is not None else None
            out.append(Asset(f'stock:{symbol}', 'stock', under.get('ticker') or symbol.removesuffix('on'),
                             under.get('name') or symbol, token_address, units, decimals, value, True))

    held_crypto = crypto_holdings.holdings_units(address)
    if held_crypto is None:
        raise AssetsUnknown('crypto holdings unknown')
    if held_crypto:
        prices = crypto_prices.latest_prices()
        for symbol in held_crypto:
            token = crypto_catalog.by_symbol(symbol, include_unlisted=True)
            if token is None:
                continue
            units = chain.balance_of(token.address, address)
            if not units:
                continue
            price = prices.get(symbol)
            value = (Decimal(units) / Decimal(10 ** token.decimals) * price) if price is not None else None
            out.append(Asset(f'crypto:{symbol}', 'crypto', token.ticker, token.name, token.address,
                             units, token.decimals, value, is_feed_token(token)))

    confio = chain.confio_address()
    if confio:
        units = chain.balance_of(confio, address)
        if units:
            # No market and no price reference in v1 (spec 5.5): unpriced,
            # and not a fee source until the account has latched the
            # factory's CONFIO slot. Once latched it is priced by the latched
            # reference (a stale one leaves it unpriced: the contract would
            # refuse the sale) and joins the sale order like any holding.
            value, can_pay = None, False
            if confio_sale is not None:
                can_pay = True
                price = chain.feed_price_usd(confio_sale[1], chain.CONFIO_FEED_MAX_AGE)
                if price is not None:
                    value = Decimal(units) / Decimal(10 ** 18) * price
            out.append(Asset('confio', 'confio', 'CONFIO', 'Confío', confio, units, 18, value, can_pay))
    return out


def total_usd(assets: list[Asset]) -> Decimal:
    return sum((a.value_usd for a in assets if a.value_usd is not None), Decimal(0))


def dollars_usd(assets: list[Asset]) -> Decimal:
    return sum((a.value_usd for a in assets if a.kind == 'dollar' and a.value_usd is not None), Decimal(0))


def money(value) -> str | None:
    if value is None:
        return None
    return format(Decimal(value).quantize(Decimal('0.01')), 'f')
