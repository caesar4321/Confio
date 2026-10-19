"""Crypto & metals catalog (BSC tokens traded through ConfioSwapRouter).

`crypto_tokens.json` is the one source of truth: the relay sponsors a swap
only for a listed token AND its exact catalog route, quotes and holdings use
the same list, and the app mirrors it. Routes are stored in the BUY
direction (USDT -> token); a sell uses the exact reverse.

The router encodes a route as abi.encode(uint8 kind, bytes data):
  kind 0 (v3): data = packed path token(20) fee(3) token(20) ...
  kind 1 (v2): data = abi.encode(address[] path)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from eth_abi import encode as abi_encode

USDT_BSC = '0x55d398326f99059ff775485246999027b3197955'
ROUTE_V3 = 0
ROUTE_V2 = 1
CATEGORIES = ('crypto', 'metal')
_CATALOG_PATH = Path(__file__).with_name('crypto_tokens.json')


@dataclass(frozen=True)
class CryptoToken:
    symbol: str
    ticker: str
    name: str
    address: str  # lower-case
    decimals: int
    category: str
    featured: bool
    custody: str
    # Thin-liquidity tokens: buys above this many USD (gross, before the
    # exit fee) are refused by the relay. None = no cap.
    max_order_usd: int | None
    route_kind: int
    # Buy-direction hops: (token, fee, token, fee, ..., token) for v3,
    # (token, token, ...) for v2. Addresses lower-case.
    route_path: tuple
    # Display-only price history source (crypto_chart, OKX instId).
    chart_instrument: str = ''

    def route_bytes(self, side: str) -> bytes:
        """The exact `route` argument the router must receive."""
        if side not in ('buy', 'sell'):
            raise ValueError('side must be buy or sell')
        path = self.route_path if side == 'buy' else tuple(reversed(self.route_path))
        if self.route_kind == ROUTE_V3:
            data = b''
            for i, hop in enumerate(path):
                if i % 2 == 0:
                    data += bytes.fromhex(hop[2:])
                else:
                    data += int(hop).to_bytes(3, 'big')
        else:
            data = abi_encode(['address[]'], [list(path)])
        return abi_encode(['uint8', 'bytes'], [self.route_kind, data])


def _parse(entry: dict) -> CryptoToken:
    address = str(entry['address']).lower()
    route = entry['route']
    kind = {'v3': ROUTE_V3, 'v2': ROUTE_V2}[route['kind']]
    raw = route['path']
    if kind == ROUTE_V3:
        if len(raw) < 3 or len(raw) % 2 == 0:
            raise ValueError(f"{entry['symbol']}: v3 path must be token,fee,token[,fee,token]")
        path = tuple(
            str(hop).lower() if i % 2 == 0 else int(hop) for i, hop in enumerate(raw)
        )
        fees = path[1::2]
        if any(fee not in (100, 500, 2500, 10000) for fee in fees):
            raise ValueError(f"{entry['symbol']}: unknown v3 fee tier")
    else:
        if len(raw) < 2:
            raise ValueError(f"{entry['symbol']}: v2 path too short")
        path = tuple(str(hop).lower() for hop in raw)
    if path[0] != USDT_BSC or path[-1] != address:
        raise ValueError(f"{entry['symbol']}: route must run USDT -> token")
    if entry['category'] not in CATEGORIES:
        raise ValueError(f"{entry['symbol']}: unknown category")
    decimals = int(entry['decimals'])
    if not 0 < decimals <= 36:
        raise ValueError(f"{entry['symbol']}: bad decimals")
    return CryptoToken(
        symbol=entry['symbol'],
        ticker=entry.get('ticker') or entry['symbol'],
        name=entry['name'],
        address=address,
        decimals=decimals,
        category=entry['category'],
        featured=bool(entry.get('featured')),
        custody=entry.get('custody') or '',
        max_order_usd=int(entry['max_order_usd']) if entry.get('max_order_usd') else None,
        route_kind=kind,
        route_path=path,
        chart_instrument=entry.get('chart_instrument') or '',
    )


@lru_cache(maxsize=1)
def _load() -> tuple[tuple[CryptoToken, ...], tuple[CryptoToken, ...]]:
    data = json.loads(_CATALOG_PATH.read_text())
    listed, unlisted = [], []
    seen = set()
    for entry in data['tokens']:
        token = _parse(entry)
        if token.address in seen or token.symbol in {t.symbol for t in listed + unlisted}:
            raise ValueError(f'duplicate catalog entry {token.symbol}')
        seen.add(token.address)
        (listed if entry.get('listed', True) else unlisted).append(token)
    return tuple(listed), tuple(unlisted)


def tokens(*, include_unlisted: bool = False) -> tuple[CryptoToken, ...]:
    listed, unlisted = _load()
    return listed + unlisted if include_unlisted else listed


def by_address(address: str, *, include_unlisted: bool = False) -> CryptoToken | None:
    address = (address or '').lower()
    return next((t for t in tokens(include_unlisted=include_unlisted) if t.address == address), None)


def by_symbol(symbol: str, *, include_unlisted: bool = False) -> CryptoToken | None:
    symbol = (symbol or '').upper()
    return next(
        (t for t in tokens(include_unlisted=include_unlisted) if t.symbol.upper() == symbol), None)
