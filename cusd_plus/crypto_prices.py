"""On-chain quotes and prices for the crypto & metals catalog.

Every number comes from PancakeSwap itself, along the exact catalog route
the router will execute: V3 routes through QuoterV2.quoteExactInput, V2
routes through the V2 router's getAmountsOut. No third-party price API, so a
displayed price is always one the user could actually trade at.

Display prices are a $100 buy quote (fee and impact included, which is the
honest "what you get" number at Confío's ticket sizes), snapshotted every
15 minutes into CryptoPricePoint for the 24h change and the sparkline.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak

from .crypto_catalog import ROUTE_V3, CryptoToken, tokens

logger = logging.getLogger(__name__)

WAD = 10 ** 18
USDT_DECIMALS = 18
PRICE_PROBE_USDT_WEI = 100 * WAD

_SEL_QUOTE_V3 = keccak(text='quoteExactInput(bytes,uint256)')[:4]
_SEL_AMOUNTS_OUT = keccak(text='getAmountsOut(uint256,address[])')[:4]


def _eth_call(to: str, data: bytes) -> bytes:
    from .tasks import _rpc

    result = _rpc('eth_call', [{'to': to, 'data': '0x' + data.hex()}, 'latest'], timeout=8)
    return bytes.fromhex((result or '0x')[2:])


def quote_exact_in(token: CryptoToken, side: str, amount_in_wei: int) -> int:
    """Output of swapping `amount_in_wei` along the catalog route.

    buy: USDT wei in -> token units out; sell: token units in -> USDT wei out.
    Raises on any RPC/revert so callers can fail closed.
    """
    if amount_in_wei <= 0:
        return 0
    kind, data = abi_decode(['uint8', 'bytes'], token.route_bytes(side))
    if kind == ROUTE_V3:
        quoter = getattr(settings, 'CRYPTO_PANCAKE_QUOTER_V2', '')
        raw = _eth_call(quoter, _SEL_QUOTE_V3 + abi_encode(['bytes', 'uint256'], [data, amount_in_wei]))
        amount_out = abi_decode(['uint256', 'uint160[]', 'uint32[]', 'uint256'], raw)[0]
    else:
        (path,) = abi_decode(['address[]'], data)
        router = getattr(settings, 'CUSD_PLUS_PANCAKE_ROUTER', '')
        raw = _eth_call(router, _SEL_AMOUNTS_OUT + abi_encode(['uint256', 'address[]'], [amount_in_wei, list(path)]))
        amount_out = abi_decode(['uint256[]'], raw)[0][-1]
    return int(amount_out)


def price_usd(token: CryptoToken) -> Decimal | None:
    """USD per whole token from a $100 buy quote; None when unavailable."""
    try:
        out = quote_exact_in(token, 'buy', PRICE_PROBE_USDT_WEI)
    except Exception as exc:  # noqa: BLE001 — unknown is not zero
        logger.warning('crypto price quote failed for %s: %s', token.symbol, exc)
        return None
    if out <= 0:
        return None
    return (Decimal(PRICE_PROBE_USDT_WEI) / Decimal(10 ** USDT_DECIMALS)) / (
        Decimal(out) / Decimal(10 ** token.decimals))


def snapshot_prices() -> int:
    """Store one CryptoPricePoint per listed token; returns how many."""
    from django.utils import timezone

    from blockchain.models import CryptoPricePoint

    now = timezone.now()
    stored = 0
    for token in tokens():
        price = price_usd(token)
        if price is None:
            continue
        CryptoPricePoint.objects.create(symbol=token.symbol, price_usd=price, at=now)
        stored += 1
    # 8 days is enough for the 24h change and a week of sparkline.
    CryptoPricePoint.objects.filter(at__lt=now - timedelta(days=8)).delete()
    return stored


def market_rows() -> list[dict]:
    """Latest price, 24h change and a 24h sparkline per listed token.

    A token with no snapshot yet has price None (the app shows "—").
    """
    from django.utils import timezone

    from blockchain.models import CryptoPricePoint

    since = timezone.now() - timedelta(hours=26)
    points: dict[str, list] = {}
    for point in CryptoPricePoint.objects.filter(at__gte=since).order_by('at'):
        points.setdefault(point.symbol, []).append(point)
    rows = []
    day_ago = timezone.now() - timedelta(hours=24)
    for token in tokens():
        series = points.get(token.symbol, [])
        latest = series[-1] if series else None
        base = next((p for p in series if p.at >= day_ago), None)
        change = None
        if latest and base and base.price_usd > 0 and base.pk != latest.pk:
            change = float((latest.price_usd - base.price_usd) / base.price_usd * 100)
        rows.append({
            'token': token,
            'price_usd': latest.price_usd if latest else None,
            'day_change_pct': change,
            'sparkline': [float(p.price_usd) for p in series if p.at >= day_ago],
            'priced_at': latest.at if latest else None,
        })
    return rows


def latest_prices() -> dict[str, Decimal]:
    """{symbol: latest snapshot price} for holdings valuation."""
    return {row['token'].symbol: row['price_usd'] for row in market_rows() if row['price_usd'] is not None}
