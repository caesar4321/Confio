"""
Ondo GM (tokenized stock) holdings — universe scan, no per-user bookkeeping.

Design (locked with Julian 2026-07-10, replacing a per-account holdings
model): the ONLY durable state is a system-wide token registry
(gm_tokens.json: symbol -> {address, decimals}, one entry per GM asset).
A user's portfolio is discovered by scanning the whole registry against
their address with Multicall3 — balanceOf calls packed into 250-call
chunks — so the chain stays the single source of truth and nothing can go
invisible because a row wasn't created. No DB model, no sync jobs.

Freshness mirrors vault.position_usd: 30s fresh cache per address, 7-day
last-known fallback so a dead node degrades to a stale portfolio, never a
vanished one. USD values are never stored — the resolver computes them
from the globally cached GM market payload (display only, chain-first).

The live registry comes from Ondo's `/assets/all/addresses` metadata endpoint
and is cached server-side for one day. `gm_tokens.json` is only the deploy-time
fallback snapshot, so an upstream outage never makes held positions vanish.
"""
import json
import logging
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
import re

from django.core.cache import cache
from django.conf import settings
from eth_abi import decode, encode
from eth_utils import keccak

from . import vault

logger = logging.getLogger(__name__)

# Canonical Multicall3 (same address on BSC as everywhere).
MULTICALL3 = '0xcA11bde05977b3631167028862bE2a173976CA11'
SEL_TRY_AGGREGATE = keccak(text='tryAggregate(bool,(address,bytes)[])')[:4]
SEL_BALANCE_OF = keccak(text='balanceOf(address)')[:4]

# Subcalls per eth_call — keeps calldata well under public-node limits.
CHUNK = 250

SCAN_TTL = 30
SCAN_LAST_TTL = 7 * 24 * 3600
REGISTRY_TTL = 24 * 3600
REGISTRY_FALLBACK_TTL = 5 * 60
# {'tokens': registry, 'live': bool} in ONE entry: whether the registry is
# Ondo's live answer (not the snapshot) can never outlive, or be evicted apart
# from, the registry it describes. v2: v1 entries carry no liveness.
REGISTRY_CACHE_KEY = 'gm_bsc_registry_v2'


def _parse_bsc_registry(rows, *, strict: bool = False) -> dict:
    if not isinstance(rows, list):
        raise RuntimeError('Ondo GM address registry is not a list')
    registry = {}
    addresses = set()
    for row in rows:
        if not isinstance(row, dict):
            if strict:
                raise RuntimeError('Ondo GM address registry contains a malformed row')
            continue
        symbol = str(row.get('symbol') or '').strip()
        items = row.get('addresses') or []
        if not isinstance(items, list):
            if strict:
                raise RuntimeError('Ondo GM address registry contains malformed addresses')
            continue
        for item in items:
            if not isinstance(item, dict):
                if strict:
                    raise RuntimeError('Ondo GM address registry contains malformed addresses')
                continue
            if item.get('networkChainId') != 'bsc-56':
                continue
            address = str(item.get('address') or '')
            if not symbol or not re.fullmatch(r'0x[0-9a-fA-F]{40}', address):
                if strict:
                    raise RuntimeError('Ondo GM address registry contains invalid BSC metadata')
                continue
            address_key = address.lower()
            if strict and (symbol in registry or address_key in addresses):
                raise RuntimeError('Ondo GM address registry contains duplicate BSC metadata')
            try:
                decimals = int(item.get('decimals') or 18)
            except (TypeError, ValueError) as exc:
                raise RuntimeError('Ondo GM address registry contains invalid decimals') from exc
            if not 0 <= decimals <= 36:
                if strict:
                    raise RuntimeError('Ondo GM address registry contains invalid decimals')
                continue
            registry[symbol] = {'address': address, 'decimals': decimals}
            addresses.add(address_key)
            break
    return registry


@lru_cache(maxsize=1)
def _fallback_registry() -> dict:
    path = Path(__file__).parent / 'gm_tokens.json'
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        logger.exception('GM fallback registry is missing or malformed')
        return {}


def registry() -> dict | None:
    """BSC symbol -> address metadata from Ondo, with local outage fallback."""
    return registry_entry()[0]


def registry_entry() -> tuple[dict | None, bool]:
    """(registry, live) from ONE read: live is False when it is the shipped
    snapshot, which lacks tokens listed after it (a scan over it can miss a
    position). Read together so liveness can never disagree with the tokens."""
    cached = cache.get(REGISTRY_CACHE_KEY)
    if isinstance(cached, dict) and 'tokens' in cached:
        return cached['tokens'], cached.get('live') is True
    fallback = _fallback_registry()
    try:
        from . import gm_api
        rows = gm_api.all_addresses()
        live = _parse_bsc_registry(rows)
        result = live or fallback
        if result:
            cache.set(REGISTRY_CACHE_KEY, {'tokens': result, 'live': bool(live)},
                      REGISTRY_TTL if live else REGISTRY_FALLBACK_TTL)
        return (result or None), bool(live)
    except Exception:  # noqa: BLE001 — portfolio degrades to shipped snapshot
        logger.warning('GM address registry unavailable; using local fallback', exc_info=True)
        if fallback:
            # Retry Ondo soon after an outage, but avoid a request stampede.
            cache.set(REGISTRY_CACHE_KEY, {'tokens': fallback, 'live': False}, REGISTRY_FALLBACK_TTL)
        return (fallback or None), False


def audit_registry() -> dict:
    """Fresh, fail-closed GM universe for irreversible wallet retirement.

    Unlike ``registry()``, this never reads the day cache and never substitutes
    the shipped snapshot for a failed live fetch. The returned universe is the
    union of live and shipped addresses: a delisted legacy token can still hold
    value, while the fresh response covers tokens added after the snapshot.
    """
    from . import gm_api

    fallback = _fallback_registry()
    live = _parse_bsc_registry(gm_api.all_addresses_fresh(), strict=True)
    if not live:
        raise RuntimeError('Ondo GM address registry is empty')
    # A fixed, reviewed authoritative floor catches truncated-but-valid JSON.
    # Percentage tolerances are unsafe here: with hundreds of assets they can
    # silently omit dozens of contracts during an irreversible retirement.
    minimum_live = int(getattr(
        settings,
        'CUSD_PLUS_GM_AUDIT_MIN_LIVE_ASSETS',
        438,
    ))
    if minimum_live <= 0:
        raise RuntimeError('Ondo GM audit minimum is not configured')
    if len(live) < minimum_live:
        raise RuntimeError(
            f'Ondo GM address registry is incomplete ({len(live)} < {minimum_live})'
        )

    combined = {}
    seen_addresses = set()
    for source_name, source in (('snapshot', fallback), ('live', live)):
        for symbol, item in source.items():
            address_key = str(item['address']).lower()
            if address_key in seen_addresses:
                continue
            key = symbol
            if key in combined:
                key = f'{symbol}@{source_name}:{address_key}'
            combined[key] = item
            seen_addresses.add(address_key)
    return combined


def _scan(
    user_bsc_address: str,
    token_registry: dict,
    *,
    block_tag: str = 'latest',
    require_complete: bool = False,
    failures: set | None = None,
) -> dict:
    """One Multicall3 pass over the whole registry; returns nonzero
    balances as {symbol: units_float}. Raises on RPC failure. `failures`,
    when given, collects the symbols whose balanceOf didn't answer (the
    default mode skips them), so a caller can decide which ones matter."""
    entries = list(token_registry.items())
    holder_arg = encode(['address'], [user_bsc_address])
    held = {}
    for i in range(0, len(entries), CHUNK):
        chunk = entries[i:i + CHUNK]
        calls = [
            (item['address'], SEL_BALANCE_OF + holder_arg)
            for _, item in chunk
        ]
        # requireSuccess=False: one misbehaving token must not hide the rest.
        data = SEL_TRY_AGGREGATE + encode(['bool', '(address,bytes)[]'], [False, calls])
        res = vault._rpc('eth_call', [{'to': MULTICALL3, 'data': '0x' + data.hex()}, block_tag])
        results = decode(['(bool,bytes)[]'], bytes.fromhex(res[2:]))[0]
        if require_complete and len(results) != len(chunk):
            raise RuntimeError('GM Multicall returned an incomplete result set')
        if failures is not None:
            failures.update(symbol for symbol, _ in chunk[len(results):])
        for (ok, ret), (symbol, item) in zip(results, chunk):
            if not ok or len(ret) < 32:
                if require_complete:
                    raise RuntimeError(f'GM balanceOf failed for {symbol}')
                if failures is not None:
                    failures.add(symbol)
                continue
            raw = int.from_bytes(ret[:32], 'big')
            if raw:
                held[symbol] = float(Decimal(raw) / Decimal(10) ** item.get('decimals', 18))
    return held


def invalidate_holdings(user_bsc_address: str) -> None:
    """Drop the fresh scans (both modes) after a trade; last-known stays.
    Also moves the holdings generation: a scan already running read the
    pre-trade chain, and must neither be cached nor (complete mode) used."""
    from uuid import uuid4
    key = (user_bsc_address or '').lower()
    cache.set(f'gm_hold_gen:{key}', uuid4().hex, SCAN_LAST_TTL)
    cache.delete_many([f'gm_hold:{key}', f'gm_hold_full:{key}'])


def _generation(key: str):
    return cache.get(f'gm_hold_gen:{key}')


def holdings_units(user_bsc_address: str, *, require_complete: bool = False) -> dict | None:
    """{symbol: units} for everything the address holds; {} when it holds
    nothing (or the registry is empty). None means UNKNOWN — the scan
    failed and no last-known value exists; callers must not render that
    as an empty portfolio.

    require_complete=True (never stale, for numbers stated as "today" like
    Tu mes): every token's balanceOf must answer, or the result is UNKNOWN.
    The default scan skips a failing token
    so one bad contract can't hide a portfolio, which is right for a list and
    wrong for a total. Complete scans keep their own 30s entry, because a
    partial scan stored by another screen must never pass as complete."""
    if not user_bsc_address:
        return {}
    key = user_bsc_address.lower()
    if require_complete:
        return _complete_holdings(key)
    cached = cache.get(f'gm_hold:{key}')
    if cached is not None:
        return cached
    token_registry = registry()
    if token_registry is None:
        return cache.get(f'gm_hold_last:{key}')
    if not token_registry:
        return {}
    generation = _generation(key)
    try:
        held = _scan(key, token_registry)
    except Exception:  # noqa: BLE001 — degrade to stale, never to vanished
        logger.warning('GM holdings scan failed for %s', user_bsc_address, exc_info=True)
        return cache.get(f'gm_hold_last:{key}')
    if _generation(key) == generation:     # else a trade landed mid-scan: don't cache it
        cache.set(f'gm_hold:{key}', held, SCAN_TTL)
        cache.set(f'gm_hold_last:{key}', held, SCAN_LAST_TTL)
    return held


def _complete_holdings(key: str) -> dict | None:
    cached = cache.get(f'gm_hold_full:{key}')
    if cached is not None:
        return cached
    token_registry, live = registry_entry()
    if token_registry is None or not live:
        return None                        # the snapshot may lack a held token
    # Delisted tokens (shipped snapshot, gone from Ondo's live list) can still
    # hold value (see audit_registry). Scanned best-effort: a retired contract
    # that no longer answers must not hide every portfolio; a held one it
    # drops leaves the ledger unexplained (value only), never a wrong gain.
    live_addresses = {str(m.get('address') or '').lower() for m in token_registry.values()}
    delisted = {s: m for s, m in _fallback_registry().items()
                if s not in token_registry and str(m.get('address') or '').lower() not in live_addresses}
    if not token_registry and not delisted:
        return {}
    # One pass over both; only a live token that didn't answer makes it unknown.
    for _attempt in range(2):
        generation = _generation(key)
        failures: set = set()
        try:
            held = _scan(key, {**delisted, **token_registry}, failures=failures)
        except Exception:  # noqa: BLE001 — incomplete is unknown, never a smaller portfolio
            logger.warning('GM complete holdings scan failed for %s', key, exc_info=True)
            return None
        missed = failures & set(token_registry)
        if missed:
            logger.warning('GM complete holdings scan for %s missed %s', key, sorted(missed))
            return None
        if _generation(key) != generation:
            continue                           # a trade confirmed mid-scan: read the chain again
        # A complete scan is also the best answer for the list readers, over
        # the list scan's own token set (live only): a delisted position must
        # not appear or vanish there depending on which scan ran last.
        listed = {s: u for s, u in held.items() if s in token_registry}
        cache.set_many({f'gm_hold_full:{key}': held, f'gm_hold:{key}': listed}, SCAN_TTL)
        cache.set(f'gm_hold_last:{key}', listed, SCAN_LAST_TTL)
        return held
    return None                                # trades keep landing: unknown for now
