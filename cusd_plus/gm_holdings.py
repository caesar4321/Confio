"""
Ondo GM (tokenized stock) holdings — universe scan, no per-user bookkeeping.

Design (locked with Julian 2026-07-10, replacing a per-account holdings
model): the ONLY durable state is a system-wide token registry
(gm_tokens.json: symbol -> {address, decimals}, one entry per GM asset).
A user's portfolio is discovered by scanning the whole registry against
their address with Multicall3 — balanceOf calls packed into 250-call
chunks — so the chain stays the single source of truth and nothing can go
invisible because a row wasn't created. No DB model, no sync jobs.

Storage mirrors the BSC balances (blockchain/bsc_balance_service.py): the
last COMPLETE scan is a StockHoldings row in Postgres. The stocks screen
re-reads the chain when the row is stale or older than STALE_AFTER; Tu mes
reads the row at any age (it moves no stocks) and scans only when there is
no row yet or it was marked stale. The wallet's own trades mark it stale at
broadcast and at confirmation; a transfer in from outside shows up at the
next re-read. A partial (list) scan keeps a 30s Redis entry and a 7-day
last-known fallback, so a dead node degrades to a stale portfolio, never a
vanished one. USD values are never stored — the resolver computes them
from the globally cached GM market payload (display only, chain-first).

The live registry comes from Ondo's `/assets/all/addresses` metadata endpoint
and is cached server-side for one day. `gm_tokens.json` is only the deploy-time
fallback snapshot, so an upstream outage never makes held positions vanish.
"""
import json
from datetime import timedelta
import logging
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
import re

from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from eth_abi import decode, encode
from eth_utils import keccak

from . import vault

logger = logging.getLogger(__name__)

# Canonical Multicall3 (same address on BSC as everywhere).
MULTICALL3 = '0xcA11bde05977b3631167028862bE2a173976CA11'
SEL_TRY_AGGREGATE = keccak(text='tryAggregate(bool,(address,bytes)[])')[:4]
SEL_GET_BLOCK_NUMBER = keccak(text='getBlockNumber()')[:4]
SEL_BALANCE_OF = keccak(text='balanceOf(address)')[:4]

# Subcalls per eth_call — keeps calldata well under public-node limits.
CHUNK = 250

SCAN_TTL = 30
SCAN_LAST_TTL = 7 * 24 * 3600
# The stocks screen re-reads the chain past this (cUSD-a's threshold).
STALE_AFTER = timedelta(minutes=5)
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
    blocks: dict | None = None,
) -> dict:
    """One Multicall3 pass over the whole registry; returns nonzero
    balances as {symbol: units_float}. Raises on RPC failure. `failures`,
    when given, collects the symbols whose balanceOf didn't answer (the
    default mode skips them), so a caller can decide which ones matter.
    `blocks`, when given, gets {symbol: block number the balance was read
    at}: Multicall3.getBlockNumber() rides in each chunk's own call, so it is
    exact even when the RPC pool serves chunks from different nodes."""
    entries = list(token_registry.items())
    holder_arg = encode(['address'], [user_bsc_address])
    held = {}
    for i in range(0, len(entries), CHUNK):
        chunk = entries[i:i + CHUNK]
        calls = [
            (item['address'], SEL_BALANCE_OF + holder_arg)
            for _, item in chunk
        ]
        if blocks is not None:
            calls.insert(0, (MULTICALL3, SEL_GET_BLOCK_NUMBER))
        # requireSuccess=False: one misbehaving token must not hide the rest.
        data = SEL_TRY_AGGREGATE + encode(['bool', '(address,bytes)[]'], [False, calls])
        res = vault._rpc('eth_call', [{'to': MULTICALL3, 'data': '0x' + data.hex()}, block_tag])
        results = decode(['(bool,bytes)[]'], bytes.fromhex(res[2:]))[0]
        if blocks is not None:
            head, results = (results[0] if results else (False, b'')), results[1:]
            at = int.from_bytes(head[1][:32], 'big') if head[0] and len(head[1]) >= 32 else None
            blocks.update({symbol: at for symbol, _ in chunk})
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


# After a trade at block N, no scan read before N may be cached (list or
# complete): a node behind it (the RPC pool rotates) shows the pre-trade
# portfolio. Nodes catch up within seconds; the floor outlives that easily.
FLOOR_TTL = 10 * 60
# From broadcast to confirmation the trade's block isn't known (the app shows
# success on the receipt, seconds before finality sets the floor): no scan is
# cached while the wallet has a stock trade on the wire, asked of the
# database at store time (indexed; once per uncached scan, so every read
# while a trade is on the wire, and at most once per SCAN_TTL otherwise), so
# nothing has to be set at broadcast or lifted at each terminal status. The
# receipt checker's own horizon: an older 'signed'/'sent' row is stuck.
IN_FLIGHT_MAX_AGE = timedelta(minutes=15)


def invalidate_holdings(user_bsc_address: str, min_block: int | None = None) -> None:
    """Drop the fresh scans (both modes) after a trade; last-known stays.
    Also moves the holdings generation: a scan already running read the
    pre-trade chain, and must neither be cached nor (complete mode) used.
    `min_block` (the trade's block, when known) becomes the floor below
    which no later read is cached either."""
    from uuid import uuid4
    key = (user_bsc_address or '').lower()
    # The floor BEFORE the generation: a scan that reads the new generation
    # always sees it.
    try:
        if min_block is not None:
            _raise_floor(key, int(min_block))
        cache.set(f'gm_hold_gen:{key}', uuid4().hex, SCAN_LAST_TTL)
    finally:
        drop_fresh_holdings(key)          # the durable mark lands even when Redis is down


def drop_fresh_holdings(user_bsc_address: str) -> None:
    """Drop the fresh list scan and mark the stored complete scan stale,
    without moving the generation: at a broadcast, scans stored before it
    are pre-trade, while ones running now can't be stored anyway (the
    trade's row is on the wire)."""
    from blockchain.models import StockHoldings
    key = (user_bsc_address or '').lower()
    try:
        StockHoldings.objects.filter(bsc_address=key).update(is_stale=True)
    finally:
        cache.delete(f'gm_hold:{key}')


def _stored(key: str):
    from blockchain.models import StockHoldings
    return StockHoldings.objects.filter(bsc_address=key).first()


def _listed(held: dict) -> dict:
    """The positions on Ondo's live list (a delisted one stays out of the
    list readers, whichever scan ran last)."""
    token_registry = registry()
    if not token_registry:
        return dict(held)
    return {s: u for s, u in held.items() if s in token_registry}


def stock_batches_in_flight(user_bsc_address: str, max_age=IN_FLIGHT_MAX_AGE):
    """The wallet's stock batches on the wire (signed or sent), created
    within `max_age`: older ones are stuck, not settling. A 'signed' row
    whose broadcast raised counts: the reconciler may still land it."""
    from django.utils import timezone
    from blockchain.models import SponsoredBatch
    return SponsoredBatch.objects.filter(
        user_bsc_address__iexact=user_bsc_address, kind__in=('stock_buy', 'stock_sell'),
        status__in=('signed', 'sent'), created_at__gte=timezone.now() - max_age)


def _wallet_in_flight(key: str) -> bool:
    try:
        return stock_batches_in_flight(key).exists()
    except Exception:  # noqa: BLE001 — unknown: don't cache (the read is still served)
        logger.warning('in-flight check failed for %s', key, exc_info=True)
        return True


def _raise_floor(key: str, block: int) -> None:
    """floor = max(floor, block), atomic on Redis: two confirmations of one
    wallet at once must leave the higher block, or a node between the two
    could get its read STORED (Tu mes reads the row at any age)."""
    from blockchain.bsc_balance_service import raise_floor
    raise_floor(f'gm_hold_floor:{key}', block, FLOOR_TTL)


def reads_before(blocks: dict, block: int | None) -> bool:
    """Some balance in `blocks` was read before `block` (or at an unknown block)."""
    return bool(block) and any(at is None or at < block for at in blocks.values())


def _behind_floor(key: str, blocks: dict, wallet_in_flight: bool | None = None) -> bool:
    """A read older than the last trade's block (or of unknown block while a
    floor stands), or taken while a trade is on the wire: fine to use as-is
    by a caller that knows, never cached. A caller that saw a trade on the
    wire (before its scan) skips the query; "none" seen before the scan is
    asked again here, at store time: a trade broadcast while the scan ran
    (drop_fresh_holdings relies on this) must not get its pre-trade read
    cached."""
    if reads_before(blocks, cache.get(f'gm_hold_floor:{key}')):
        return True
    return True if wallet_in_flight else _wallet_in_flight(key)


def _generation(key: str):
    return cache.get(f'gm_hold_gen:{key}')


def holdings_units(user_bsc_address: str) -> dict | None:
    """{symbol: units} for everything the address holds; {} when it holds
    nothing (or the registry is empty). None means UNKNOWN — the scan
    failed and no last-known value exists; callers must not render that
    as an empty portfolio.

    A list's scan: it skips a failing token so one bad contract can't hide a
    portfolio, and degrades to the last-known. A total stated as "today"
    (Tu mes) uses complete_holdings instead: every live token must answer,
    stored as a StockHoldings row (a partial scan cached here never passes
    as complete)."""
    if not user_bsc_address:
        return {}
    key = user_bsc_address.lower()
    row = _stored(key)
    if row is not None and not row.is_stale and timezone.now() - row.scanned_at <= STALE_AFTER:
        return _listed(row.held)
    cached = cache.get(f'gm_hold:{key}')
    if cached is not None:
        return cached
    # Re-read with a COMPLETE scan, which also refreshes the stored row Tu
    # mes reads (a transfer in reaches it from here). A partial scan below
    # only when a complete one can't be had; after a failed one, not tried
    # again for SCAN_TTL (a token that keeps failing, an RPC outage), so
    # each read doesn't pay two scans.
    fail_key = f'gm_hold_full_fail:{key}'
    complete = None
    if not cache.get(fail_key):
        try:
            complete = _complete_holdings(key, max_age=STALE_AFTER)
        except Exception:  # noqa: BLE001 — fall through to the list scan
            logger.warning('GM complete holdings refresh failed for %s', key, exc_info=True)
        if complete is None:
            cache.set(fail_key, 1, SCAN_TTL)
    if complete is not None:
        return _listed(complete[0])
    token_registry = registry()
    if token_registry is None:
        return _last_known(key, row)
    if not token_registry:
        return {}
    generation = _generation(key)
    blocks: dict = {}
    try:
        held = _scan(key, token_registry, blocks=blocks)
    except Exception:  # noqa: BLE001 — degrade to stale, never to vanished
        logger.warning('GM holdings scan failed for %s', user_bsc_address, exc_info=True)
        return _last_known(key, row)
    # Not cached if a trade landed mid-scan, or a node behind the last trade served it.
    if _generation(key) == generation and not _behind_floor(key, blocks):
        _store(key, generation, {f'gm_hold:{key}': held}, held)
    return held


def known_holdings_units(user_bsc_address: str) -> dict | None:
    """holdings_units without a chain scan: the fresh cache, the stored row
    or the last-known (possibly a few minutes old). For latency-bound
    readers (a chat turn); None = never scanned, UNKNOWN."""
    if not user_bsc_address:
        return {}
    key = user_bsc_address.lower()
    cached = cache.get(f'gm_hold:{key}')
    if cached is not None:
        return cached
    return _last_known(key, _stored(key))


def _last_known(key: str, row) -> dict | None:
    last = cache.get(f'gm_hold_last:{key}')
    if last is not None:
        return last
    return _listed(row.held) if row is not None else None


def _store(key: str, generation, fresh: dict, last: dict) -> bool:
    """Cache a scan read under `generation`: `fresh` entries for SCAN_TTL and
    `last` as the last-known. A trade invalidating between the caller's
    check and these writes must not leave the pre-trade scan anywhere: undo
    exactly what this call wrote (a concurrent post-trade scan's other
    entries stay) and put the previous last-known back. True when it moved
    (the scan read the pre-trade chain and must not be used)."""
    last_key = f'gm_hold_last:{key}'
    previous_last = cache.get(last_key)
    cache.set_many(fresh, SCAN_TTL)
    cache.set(last_key, last, SCAN_LAST_TTL)
    if _generation(key) == generation:
        return False
    cache.delete_many(list(fresh))
    if previous_last is None:
        cache.delete(last_key)
    else:
        cache.set(last_key, previous_last, SCAN_LAST_TTL)
    return True


def complete_holdings(user_bsc_address: str, *, wallet_in_flight: bool | None = None,
                      max_age: timedelta | None = None) -> tuple[dict, dict] | None:
    """(units, blocks) from a complete scan, or None (unknown): blocks maps
    every scanned symbol to the block its balance was read at (None when
    that chunk's node didn't say), so a caller can tell which confirmed
    trades this chain has not seen yet.

    The stored scan (StockHoldings) when it isn't stale and, with
    `max_age`, isn't older than that; otherwise a fresh scan, stored."""
    if not user_bsc_address:
        return {}, {}
    return _complete_holdings(user_bsc_address.lower(), wallet_in_flight, max_age)


def _complete_holdings(key: str, wallet_in_flight: bool | None = None,
                       max_age: timedelta | None = None) -> tuple[dict, dict] | None:
    row = _stored(key)
    if row is not None and not row.is_stale and (
            max_age is None or timezone.now() - row.scanned_at <= max_age):
        return dict(row.held), dict(row.blocks)
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
        return {}, {}
    # One pass over both; only a live token that didn't answer makes it unknown.
    for _attempt in range(2):
        generation = _generation(key)
        failures: set = set()
        blocks: dict = {}
        try:
            held = _scan(key, {**delisted, **token_registry}, failures=failures, blocks=blocks)
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
        if _behind_floor(key, blocks, wallet_in_flight):
            # Read by a node behind the last trade: the caller can tell which
            # trades it hasn't seen (blocks), but nobody else gets it cached.
            return held, blocks
        _write_row(key, held, blocks)
        try:
            moved = _store(key, generation, {f'gm_hold:{key}': listed}, listed)
        except Exception:
            _mark_row_stale(key)               # unknown whether a trade moved it: never stand as fresh
            raise
        if moved:
            _mark_row_stale(key)               # moved during the write: pre-trade, never used
            continue
        if _wallet_in_flight(key):
            # A trade broadcast after the in-flight check above (broadcast
            # marks the row stale without moving the generation): this read
            # may be pre-trade. Usable by this caller, never stored as fresh.
            _mark_row_stale(key)
            cache.delete(f'gm_hold:{key}')
        return held, blocks
    return None                                # trades keep landing: unknown for now


def _write_row(key: str, held: dict, blocks: dict) -> None:
    from blockchain.bsc_balance_service import account_id_for
    from blockchain.models import StockHoldings
    StockHoldings.objects.update_or_create(
        bsc_address=key,
        defaults={'held': held, 'blocks': blocks, 'scanned_at': timezone.now(),
                  'is_stale': False, 'account_id': account_id_for(key)})


def _mark_row_stale(key: str) -> None:
    from blockchain.models import StockHoldings
    StockHoldings.objects.filter(bsc_address=key).update(is_stale=True)
