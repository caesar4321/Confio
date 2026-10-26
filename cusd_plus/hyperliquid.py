"""Hyperliquid read boundary (POST /info). No signing, no /exchange.

Responses are untrusted upstream data: callers validate shapes before use,
and errors never carry upstream bodies to the user.
"""
from __future__ import annotations

import contextlib
import contextvars
import time

import requests
from django.conf import settings

TIMEOUT = (5, 15)
# A sweep's time.monotonic() deadline: past it, no new read starts (a
# history paging many pages stops there), so the sweep ends inside its lock.
_READ_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar('hl_read_deadline', default=None)


@contextlib.contextmanager
def reads_until(deadline: float):
    token = _READ_DEADLINE.set(deadline)
    try:
        yield
    finally:
        _READ_DEADLINE.reset(token)


class HyperliquidError(Exception):
    pass


class SweepDeadline(Exception):
    """A sweep's time is up. Deliberately NOT a HyperliquidError: no handler
    that maps a failed read to "not credited yet" or a fallback may ever see
    it; it unwinds the whole row, which the next sweep reads again."""


def _base_url() -> str:
    return (getattr(settings, 'HYPERLIQUID_API_URL', '') or 'https://api.hyperliquid.xyz').rstrip('/')


def info(body: dict, *, session=None):
    """One /info request. Raises HyperliquidError on transport, status or JSON failure."""
    deadline = _READ_DEADLINE.get()
    if deadline is not None and time.monotonic() > deadline:
        raise SweepDeadline()
    http = session or requests
    try:
        response = http.post(_base_url() + '/info', json=body, timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException as exc:
        raise HyperliquidError('hyperliquid_unavailable') from exc
    if response.status_code != 200:
        raise HyperliquidError(f'hyperliquid_status_{response.status_code}')
    try:
        return response.json()
    except ValueError as exc:
        raise HyperliquidError('hyperliquid_bad_json') from exc


def meta(dex: str = '', *, session=None) -> dict:
    body = {'type': 'meta'}
    if dex:
        body['dex'] = dex
    result = info(body, session=session)
    if not isinstance(result, dict) or not isinstance(result.get('universe'), list):
        raise HyperliquidError('hyperliquid_bad_meta')
    return result


def spot_token_names(*, session=None) -> dict[int, str]:
    """Spot token index -> name (USDC is 0); collateral tokens are spot tokens.
    Any malformed entry fails the whole read: a junk name must never pass
    as a real (non-USDC) collateral."""
    result = info({'type': 'spotMeta'}, session=session)
    tokens = result.get('tokens') if isinstance(result, dict) else None
    if not isinstance(tokens, list) or not tokens:
        raise HyperliquidError('hyperliquid_bad_spot_meta')
    names: dict[int, str] = {}
    for token in tokens:
        index = token.get('index') if isinstance(token, dict) else None
        name = token.get('name') if isinstance(token, dict) else None
        if (not isinstance(index, int) or isinstance(index, bool) or index < 0
                or not isinstance(name, str) or not name or index in names):
            raise HyperliquidError('hyperliquid_bad_spot_meta')
        names[index] = name
    if names.get(0) != 'USDC':
        raise HyperliquidError('hyperliquid_bad_spot_meta')
    return names


def exchange(payload: dict, *, session=None) -> dict:
    """POST /exchange with an action the MEMBER signed (the server never
    signs). Returns the parsed body; raises on transport/status failures."""
    http = session or requests
    try:
        response = http.post(_base_url() + '/exchange', json=payload, timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException as exc:
        raise HyperliquidError('hyperliquid_unavailable') from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise HyperliquidError(f'hyperliquid_status_{response.status_code}') from exc
    if response.status_code != 200:
        raise HyperliquidError(f'hyperliquid_status_{response.status_code}')
    if not isinstance(body, dict):
        raise HyperliquidError('hyperliquid_bad_json')
    return body


def user_role(user: str, *, session=None) -> str:
    """'missing' for an address HyperCore has never seen (its first deposit
    pays the new-account charge)."""
    result = info({'type': 'userRole', 'user': user}, session=session)
    role = result.get('role') if isinstance(result, dict) else None
    if not isinstance(role, str):
        raise HyperliquidError('hyperliquid_bad_user_role')
    return role


def user_abstraction(user: str, *, session=None) -> str:
    result = info({'type': 'userAbstraction', 'user': user}, session=session)
    if result is None:
        return 'default'
    if not isinstance(result, str):
        raise HyperliquidError('hyperliquid_bad_abstraction')
    return result


def clearinghouse_state(user: str, dex: str = '', *, session=None) -> dict:
    body = {'type': 'clearinghouseState', 'user': user}
    if dex:
        body['dex'] = dex
    result = info(body, session=session)
    if (not isinstance(result, dict) or not isinstance(result.get('assetPositions'), list)
            or not isinstance(result.get('withdrawable'), str)):
        raise HyperliquidError('hyperliquid_bad_clearinghouse')
    return result


PAGE_LIMIT = 500  # the smallest of Hyperliquid's time-range page sizes


def _paged(body: dict, start_ms: int, *, session=None, max_pages: int = 40) -> list:
    """Every row of a time-range /info query: Hyperliquid caps each answer,
    so ask again from the last row's time until a short page arrives.
    Raises rather than return a truncated history."""
    rows, cursor, seen = [], int(start_ms), set()
    for _ in range(max_pages):
        page = info(dict(body, startTime=cursor), session=session)
        if not isinstance(page, list):
            raise HyperliquidError('hyperliquid_bad_history')
        fresh = []
        for row in page:
            key = json_key(row)
            if key not in seen:
                seen.add(key)
                fresh.append(row)
        rows.extend(fresh)
        if len(page) < PAGE_LIMIT or not fresh:
            return rows
        cursor = max(int(r.get('time') or 0) for r in page)
    raise HyperliquidError('hyperliquid_history_too_long')


def json_key(row) -> str:
    import json

    return json.dumps(row, sort_keys=True, default=str)


def user_fills_by_time(user: str, start_ms: int, *, session=None) -> list:
    return _paged({'type': 'userFillsByTime', 'user': user, 'aggregateByTime': False}, start_ms, session=session)


def user_funding(user: str, start_ms: int, *, session=None) -> list:
    return _paged({'type': 'userFunding', 'user': user}, start_ms, session=session)


def ledger_updates(user: str, start_ms: int, *, session=None) -> list:
    return _paged({'type': 'userNonFundingLedgerUpdates', 'user': user}, start_ms, session=session)


def frontend_open_orders(user: str, dex: str = '', *, session=None) -> list:
    body = {'type': 'frontendOpenOrders', 'user': user}
    if dex:
        body['dex'] = dex
    result = info(body, session=session)
    if not isinstance(result, list):
        raise HyperliquidError('hyperliquid_bad_open_orders')
    return result


def l2_book(coin: str, *, session=None) -> dict:
    result = info({'type': 'l2Book', 'coin': coin}, session=session)
    levels = result.get('levels') if isinstance(result, dict) else None
    if not isinstance(levels, list) or len(levels) != 2:
        raise HyperliquidError('hyperliquid_bad_book')
    return result


def meta_and_asset_ctxs(dex: str = '', *, session=None) -> tuple[dict, list]:
    body = {'type': 'metaAndAssetCtxs'}
    if dex:
        body['dex'] = dex
    result = info(body, session=session)
    if (not isinstance(result, list) or len(result) != 2 or not isinstance(result[0], dict)
            or not isinstance(result[1], list)):
        raise HyperliquidError('hyperliquid_bad_ctxs')
    return result[0], result[1]


def candles(coin: str, interval: str, start_ms: int, end_ms: int, *, session=None) -> list:
    result = info({'type': 'candleSnapshot', 'req': {'coin': coin, 'interval': interval,
                                                     'startTime': int(start_ms), 'endTime': int(end_ms)}},
                  session=session)
    if not isinstance(result, list):
        raise HyperliquidError('hyperliquid_bad_candles')
    return result
