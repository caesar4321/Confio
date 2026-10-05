"""
BSC wallet balances, stored the cUSD-a way (blockchain/balance_service.py):
a Balance row per (account, token) in Postgres with a Redis copy in front,
re-read from the chain when a row is missing, marked stale, or older than
STALE_THRESHOLD.

Display reads only (summaries, Tu mes, payroll "can fund"). Every path that
moves money (send, pay, withdraw, sweep, mint, payroll fund) keeps reading
balanceOf live: money never moves on a stored number.

Rows are marked stale by vault.invalidate_position, called where the wallet's
own transactions are broadcast, where they confirm (every party a token
Transfer in the receipt touched), and by the inbound deposit scanners. A
transfer in from outside Confío with no scanner (cUSD, CONFIO) shows up at
the next re-read, within STALE_THRESHOLD, as cUSD-a's did.
"""
import logging
from datetime import timedelta
from decimal import Decimal, localcontext
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

# Balance.token -> where it lives on BSC. CUSD_PLUS is the vault's share token.
TOKENS = ('CUSD_BSC', 'CONFIO_BSC', 'USDT_BSC', 'CUSD_PLUS')
DECIMALS = 18                         # every token above
GEN_TTL = 7 * 24 * 3600
# After a confirmed transaction at block N, no read taken before N is stored
# (the RPC pool rotates; a lagging node shows the pre-transaction balance).
# Nodes catch up within seconds; the floor outlives that easily.
FLOOR_TTL = 10 * 60
ACCOUNT_TTL = 3600
NO_ACCOUNT_TTL = 60
NO_ACCOUNT = 0                        # cached "no account owns this address"


def token_addresses() -> dict:
    """{token: contract address} for the tokens wired in this environment."""
    from cusd_plus import vault
    out = {
        'CUSD_BSC': getattr(settings, 'CUSD_VAULT_ADDRESS', None),
        'CONFIO_BSC': getattr(settings, 'BSC_CONFIO_TOKEN_ADDRESS', None),
        'USDT_BSC': vault.usdt_address(),
        'CUSD_PLUS': vault.vault_address(),
    }
    return {t: a.lower() for t, a in out.items() if a}


def to_amount(raw: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 80
        return Decimal(int(raw)).scaleb(-DECIMALS)


def to_raw(amount) -> int:
    with localcontext() as ctx:
        ctx.prec = 80
        return int(Decimal(amount).scaleb(DECIMALS))


def account_id_for(bsc_address: str) -> int | None:
    """The account whose BSC anchor this is (unique, case-insensitive), or None."""
    key = (bsc_address or '').lower()
    if not key:
        return None
    try:
        cached = cache.get(f'bsc_acct:{key}')
    except Exception:  # noqa: BLE001 — Redis down: ask the database
        cached = None
    if cached is not None:
        return cached or None
    from django.db.models.functions import Lower
    from users.models import Account
    # Same predicate as uniq_account_bsc_address_ci, so the lookup rides it.
    found = (Account.objects.annotate(_bsc=Lower('bsc_address'))
             .filter(_bsc=key, bsc_address__isnull=False).exclude(bsc_address='')
             .values_list('id', flat=True).first())
    try:
        cache.set(f'bsc_acct:{key}', found or NO_ACCOUNT, ACCOUNT_TTL if found else NO_ACCOUNT_TTL)
    except Exception:  # noqa: BLE001
        pass
    return found


def _cache_key(account_id: int, key: str) -> str:
    return f'bsc_bal:{account_id}:{key}'


def _gen_key(key: str) -> str:
    return f'bsc_bal_gen:{key}'


def _floor_key(key: str) -> str:
    return f'bsc_bal_floor:{key}'


_RAISE_LUA = ("local cur = tonumber(redis.call('GET', KEYS[1])) "
              "if (not cur) or cur < tonumber(ARGV[1]) then "
              "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]) end")


def raise_floor(cache_key: str, block: int, ttl: int) -> None:
    """floor = max(floor, block), atomically on Redis: two confirmations of
    one wallet at once must leave the HIGHER block (a stored read is used
    for minutes, Tu mes's stock row at any age). django_redis keeps ints
    raw, so cache.get reads the script's value back. Other backends (tests)
    get a plain read-then-write."""
    block = int(block)
    try:
        from django_redis import get_redis_connection
        get_redis_connection('default').eval(_RAISE_LUA, 1, cache.make_key(cache_key), block, int(ttl))
        return
    except Exception:  # noqa: BLE001 — not a Redis cache: best effort below
        pass
    current = cache.get(cache_key)
    if not current or int(current) < block:
        cache.set(cache_key, block, ttl)


def read_chain(bsc_address: str, tokens: dict) -> tuple[dict, int | None]:
    """({token: base units}, block read at) in ONE Multicall3 round trip.
    A token whose balanceOf didn't answer is left out; the block is None
    when the node didn't say. Raises when the call itself fails."""
    from eth_abi import decode, encode
    from cusd_plus import vault
    from cusd_plus.gm_holdings import MULTICALL3, SEL_BALANCE_OF, SEL_GET_BLOCK_NUMBER, SEL_TRY_AGGREGATE
    holder = encode(['address'], [bsc_address])
    names = list(tokens)
    calls = [(MULTICALL3, SEL_GET_BLOCK_NUMBER)] + [(tokens[t], SEL_BALANCE_OF + holder) for t in names]
    data = SEL_TRY_AGGREGATE + encode(['bool', '(address,bytes)[]'], [False, calls])
    res = vault._rpc('eth_call', [{'to': MULTICALL3, 'data': '0x' + data.hex()}, 'latest'])
    results = decode(['(bool,bytes)[]'], bytes.fromhex(res[2:]))[0]
    head, results = (results[0] if results else (False, b'')), results[1:]
    block = int.from_bytes(head[1][:32], 'big') if head[0] and len(head[1]) >= 32 else None
    out = {}
    for token, (ok, ret) in zip(names, results):
        if ok and len(ret) >= 32:
            out[token] = int.from_bytes(ret[:32], 'big')
    return out, block


class BscBalanceService:
    """Stored BSC balances with chain truth behind them (see module doc)."""

    CACHE_TTL = 300  # 5 minutes
    STALE_THRESHOLD = timedelta(minutes=5)

    @classmethod
    def balances_raw(cls, bsc_address: str) -> dict:
        """{token: base units} for the wallet. A token missing from the
        result is UNKNOWN (the chain didn't answer and no row exists):
        callers must not show it as a confident zero."""
        key = (bsc_address or '').lower()
        tokens = token_addresses()
        if not key or not tokens:
            return {}
        account_id = account_id_for(key)
        if account_id is None:
            # No account owns it (a merchant contract, a stranger): nothing
            # to store under, so a plain read.
            try:
                return read_chain(key, tokens)[0]
            except Exception:  # noqa: BLE001 — display read
                logger.warning('BSC balance read failed for %s', key, exc_info=True)
                return {}
        cached = cache.get(_cache_key(account_id, key))
        if isinstance(cached, dict) and set(cached) >= set(tokens):
            return {t: cached[t] for t in tokens}
        from .models import Balance
        # Read BEFORE the rows: a transaction marking them stale after this
        # point moves it, and no copy of rows read before that is cached.
        generation = cache.get(_gen_key(key))
        rows = {r.token: r for r in Balance.objects.filter(
            account_id=account_id, token__in=list(tokens), address=key)}
        now = timezone.now()
        if len(rows) == len(tokens) and all(
                not r.is_stale and now - r.last_synced <= cls.STALE_THRESHOLD for r in rows.values()):
            raw = {t: to_raw(r.amount) for t, r in rows.items()}
            oldest = min(r.last_synced for r in rows.values())
            ttl = int((cls.STALE_THRESHOLD - (now - oldest)).total_seconds())
            if ttl > 0:
                cache.set(_cache_key(account_id, key), raw, min(ttl, cls.CACHE_TTL))
                # mark_stale UPDATEs the rows, then deletes the copy: if its
                # UPDATE landed after our SELECT, either we see it here or its
                # delete comes after our write. Never a stale copy left.
                if (cache.get(_gen_key(key)) != generation or Balance.objects.filter(
                        account_id=account_id, token__in=list(tokens), address=key, is_stale=True).exists()):
                    cache.delete(_cache_key(account_id, key))
            return raw
        try:
            chain, block = read_chain(key, tokens)
        except Exception:  # noqa: BLE001 — degrade to the stored rows, never to a false 0
            logger.warning('BSC balance read failed for %s', key, exc_info=True)
            chain, block = {}, None
        floor = cache.get(_floor_key(key))
        if chain and floor and (block is None or block < int(floor)):
            # A node behind the wallet's last confirmed transaction: shown to
            # this caller, never stored (the next read asks again).
            pass
        elif chain:
            cls._store(account_id, key, chain, generation, complete=len(chain) == len(tokens))
        out = {t: to_raw(r.amount) for t, r in rows.items()}
        out.update(chain)
        return out

    @classmethod
    def _store(cls, account_id: int, key: str, chain: dict, generation, complete: bool) -> None:
        """Write a chain read. A transaction marked stale while it was read
        (the generation moved) leaves the rows stale: the read may predate it."""
        from .models import Balance
        now = timezone.now()
        for token, raw in chain.items():
            Balance.objects.update_or_create(
                account_id=account_id, token=token,
                defaults={'address': key, 'amount': to_amount(raw), 'is_stale': False,
                          'last_blockchain_check': now, 'sync_attempts': 0})
        if complete:
            cache.set(_cache_key(account_id, key), dict(chain), cls.CACHE_TTL)
        if cache.get(_gen_key(key)) != generation:
            # Rows first, then the copy (the order readers rely on, above).
            Balance.objects.filter(account_id=account_id, token__in=list(chain)).update(is_stale=True)
            cache.delete(_cache_key(account_id, key))

    @classmethod
    def mark_stale(cls, bsc_address: str, min_block: int | None = None) -> None:
        """The wallet's balances changed (or are about to): the next read
        goes to the chain. The floor (`min_block`, the confirmed
        transaction's block) and then the generation move FIRST, so neither a
        read already running nor one served by a lagging node can store its
        pre-change answer as fresh."""
        key = (bsc_address or '').lower()
        if not key:
            return
        try:
            if min_block:
                raise_floor(_floor_key(key), min_block, FLOOR_TTL)
            cache.set(_gen_key(key), uuid4().hex, GEN_TTL)
        finally:
            # The durable mark lands even when Redis is down (the caller may
            # swallow the error and never retry); readers can't store then
            # either, their own cache reads raise.
            account_id = account_id_for(key)
            if account_id is not None:
                from .models import Balance
                Balance.objects.filter(account_id=account_id, token__in=TOKENS).update(is_stale=True)
                # After the rows: a reader that cached rows read before the
                # update loses that copy here (and checks the generation).
                cache.delete(_cache_key(account_id, key))


TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
ZERO_ADDRESS = '0x' + '0' * 40


def parties_from_receipt(receipt: dict, watched: set | None = None) -> set:
    """Every wallet a token Transfer in this receipt moved one of TOKENS
    (or of `watched` token addresses) from or to (recipients included: a
    send, payment, payout or claim)."""
    if watched is None:
        watched = set(token_addresses().values())
    out = set()
    for log in (receipt or {}).get('logs') or []:
        topics = log.get('topics') or []
        if (len(topics) >= 3 and str(topics[0]).lower() == TRANSFER_TOPIC
                and str(log.get('address') or '').lower() in watched):
            for topic in topics[1:3]:
                addr = '0x' + str(topic)[-40:].lower()
                if addr != ZERO_ADDRESS:
                    out.add(addr)
    return out
