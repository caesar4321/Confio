"""A Cuenta inteligente's asset trades, for the person's portfolio ledger.

The personal wallet's trades are its confirmed sponsored batches
(cusd_plus/stock_month.py, cusd_plus/crypto_month.py). An account's trades
happen inside the contract, so they come from its events, already stored by
smart_account/reconcile.py (SmartAccountEvent):

- Traded(venue, tokenIn, tokenOut, amountIn, amountOut): an owner trade.
- RelayTraded(id, venue, tokenIn, tokenOut, spent, got, usdCounted): a
  hands-off trade (v2); a buy's usdCounted is its dollars, exact.
- RuleExecuted(id, tokenIn, tokenOut, amountIn, amountOut): a rule's run.
- ForcedSale(tokenIn, amountIn, dollarsOut, forPeriod): a sale for the fee.

Each is decoded once into a SmartAccountTrade row (index_event): the hook
the reconciler calls with the events it just stored; a read indexes any it
missed. A leg paid in Confío Dollar+ is priced at the vault's share price IN
THAT BLOCK, an RPC read: a request never makes it (allow_rpc=False) and an
event that needs it is pending (AccountTradesPending), never guessed.

Fail-closed like the wallet's ledger: an event that moves a token Confío
can't name becomes an unreadable trade ('?'), which makes the ledger
untrusted rather than silently smaller. Dollars-only events (a payout rule
swapping cUSD to USDT, a CONFIO sale) are indexed as no trade (kind '').
"""
from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

TRADE_EVENTS = ('Traded', 'RelayTraded', 'RuleExecuted', 'ForcedSale')
WAD = Decimal(10) ** 18


class AccountTradesPending(Exception):
    """An account trade isn't priced yet (its share price needs the chain)."""


class _NeedsRpc(Exception):
    pass


def _dollar(token: str) -> str | None:
    """'cusd' | 'cusd_plus' | 'usdt' for Confío's dollars, else None."""
    from smart_account import chain

    token = (token or '').lower()
    if not token:
        return None
    for key, address in (('cusd', chain.cusd_address()), ('cusd_plus', chain.cusd_plus_address()),
                         ('usdt', chain.usdt_address())):
        if address and token == address.lower():
            return key
    return None


def _not_sleeve(token: str) -> bool:
    """A known token that is no investment of the sleeve (CONFIO)."""
    from smart_account import chain

    confio = chain.confio_address()
    return bool(confio) and (token or '').lower() == confio.lower()


def _asset(token: str):
    """('stock' | 'crypto', symbol, decimals) for a sleeve asset, or None."""
    from cusd_plus.crypto_catalog import by_address
    from cusd_plus.gm_holdings import _fallback_registry, registry

    token = (token or '').lower()
    if not token:
        return None
    for source in (registry() or {}, _fallback_registry() or {}):
        for symbol, meta in source.items():
            if str(meta.get('address') or '').lower() == token:
                return 'stock', symbol, int(meta.get('decimals') or 18)
    crypto = by_address(token, include_unlisted=True)
    if crypto is not None:
        return 'crypto', crypto.symbol, crypto.decimals
    return None


def p_plus_at(block: int) -> int:
    """The Confío Dollar+ share price (1e18 = US$1) in `block`."""
    from cusd_plus import vault

    address = vault.vault_address()
    if not address:
        return 10 ** 18
    result = vault._rpc('eth_call', [{'to': address, 'data': '0x' + vault.SEL_PPLUS}, hex(int(block))])
    value = int(result, 16) if result and result != '0x' else 0
    if value <= 0:
        raise RuntimeError(f'no share price in block {block}')
    return value


def _usd(dollar: str, amount: int, block: int, allow_rpc: bool) -> Decimal:
    if dollar != 'cusd_plus':
        return Decimal(int(amount)) / WAD
    if not allow_rpc:
        raise _NeedsRpc()
    return Decimal(int(amount)) * Decimal(p_plus_at(block)) / WAD / WAD


def decode(event, *, allow_rpc: bool = True) -> dict:
    """The SmartAccountTrade fields for one stored event. Raises _NeedsRpc
    when its dollars need the chain and that isn't allowed."""
    args = event.args or {}
    name = event.name
    if name == 'ForcedSale':
        token_in, amount_in = args.get('tokenIn'), int(args.get('amountIn') or 0)
        token_out, amount_out = None, int(args.get('dollarsOut') or 0)
        dollar_out = 'cusd'             # dollarsOut is counted in US$ (1e18)
    elif name == 'RelayTraded':
        token_in, amount_in = args.get('tokenIn'), int(args.get('spent') or 0)
        token_out, amount_out = args.get('tokenOut'), int(args.get('got') or 0)
        dollar_out = _dollar(token_out)
    else:                                # Traded, RuleExecuted
        token_in, amount_in = args.get('tokenIn'), int(args.get('amountIn') or 0)
        token_out, amount_out = args.get('tokenOut'), int(args.get('amountOut') or 0)
        dollar_out = _dollar(token_out)
    dollar_in = _dollar(token_in)
    asset_in = None if dollar_in else _asset(token_in)
    asset_out = None if (dollar_out or token_out is None) else _asset(token_out)
    unknown_in = not dollar_in and asset_in is None and not _not_sleeve(token_in)
    unknown_out = (token_out is not None and not dollar_out and asset_out is None
                   and not _not_sleeve(token_out))
    base = {'address': event.address.lower(), 'traded_at': event.block_time, 'block_number': event.block_number}

    if dollar_in and asset_out and not unknown_in:
        category, symbol, decimals = asset_out
        counted = int(args.get('usdCounted') or 0) if name == 'RelayTraded' else 0
        usd = Decimal(counted) / WAD if counted > 0 else _usd(dollar_in, amount_in, event.block_number, allow_rpc)
        return {**base, 'symbol': symbol, 'kind': f'{category}_buy',
                'units': Decimal(amount_out) / (Decimal(10) ** decimals), 'usd': usd}
    if asset_in and dollar_out:
        category, symbol, decimals = asset_in
        return {**base, 'symbol': symbol, 'kind': f'{category}_sell',
                'units': Decimal(amount_in) / (Decimal(10) ** decimals),
                'usd': _usd(dollar_out, amount_out, event.block_number, allow_rpc)}
    if not (asset_in or asset_out or unknown_in or unknown_out):
        return {**base, 'symbol': '', 'kind': '', 'units': Decimal('0'), 'usd': None}
    # An asset moved in a way the ledger can't price (asset for asset, or a
    # token nobody can name): unreadable, in the ledger it belongs to.
    category = (asset_out or asset_in or ('stock',))[0]
    logger.warning('account trades: unreadable %s %s#%s', name, event.tx_hash, event.log_index)
    return {**base, 'symbol': f'?a{event.id}', 'kind': f'{category}_buy', 'units': Decimal('0'), 'usd': None}


def index_event(event, *, allow_rpc: bool = True):
    """The hook: decode one stored account event into its SmartAccountTrade
    (idempotent). None when it isn't a trade event, or it is pending (its
    price needs the chain and allow_rpc is False, or that read failed)."""
    from .models import SmartAccountTrade

    if event.name not in TRADE_EVENTS:
        return None
    existing = SmartAccountTrade.objects.filter(event=event).first()
    if existing is not None:
        return existing
    try:
        fields = decode(event, allow_rpc=allow_rpc)
    except _NeedsRpc:
        return None
    except Exception:  # noqa: BLE001 — a failed price read: pending, retried
        logger.warning('account trades: %s %s#%s not priced yet', event.name, event.tx_hash, event.log_index,
                       exc_info=True)
        return None
    row, _ = SmartAccountTrade.objects.get_or_create(event=event, defaults=fields)
    return row


def index_events(events, *, allow_rpc: bool = True) -> int:
    """For the reconciler: index every trade event among `events` (decoded
    SmartAccountEvent rows it just stored). Returns how many are indexed."""
    done = 0
    for event in events:
        if getattr(event, 'name', None) in TRADE_EVENTS and index_event(event, allow_rpc=allow_rpc) is not None:
            done += 1
    return done


def trades_of(address: str, *, allow_rpc: bool = False) -> tuple[list, list]:
    """(stock trades, crypto trades) of one account contract, oldest first,
    as the wallet ledger's Trade rows (source = the account). Raises
    AccountTradesPending while any of its trade events isn't priced."""
    from cusd_plus.stock_month import Trade
    from smart_account.models import SmartAccountEvent

    from .models import SmartAccountTrade

    address = (address or '').lower()
    if not address:
        return [], []
    events = list(SmartAccountEvent.objects.filter(address=address, name__in=TRADE_EVENTS)
                  .order_by('block_number', 'log_index'))
    if not events:
        return [], []
    rows = {r.event_id: r for r in SmartAccountTrade.objects.filter(event__in=events)}
    stocks, crypto = [], []
    for event in events:
        row = rows.get(event.id) or index_event(event, allow_rpc=allow_rpc)
        if row is None:
            raise AccountTradesPending(f'{event.name} {event.tx_hash} not priced yet')
        if not row.kind:
            continue
        remember_block_time(row.block_number, row.traded_at)
        trade = Trade(symbol=row.symbol, kind=row.kind, units=Decimal(row.units),
                      usd=None if row.usd is None else Decimal(row.usd), when=row.traded_at,
                      block=row.block_number, source=address)
        (crypto if row.kind.startswith('crypto_') else stocks).append(trade)
    return stocks, crypto


def remember_block_time(block: int, when) -> None:
    """An event's block time is known: a near-midnight account trade never
    needs an RPC for it (portfolio_returns._settled_at)."""
    from django.core.cache import cache

    from .portfolio_returns import _block_time_key

    try:
        cache.set(_block_time_key(block), when.timestamp(), timeout=None)
    except Exception:  # noqa: BLE001
        pass


def accounts_with_trades():
    """SmartAccount owner user ids whose accounts ever had a trade event."""
    from smart_account.models import SmartAccount, SmartAccountEvent

    addresses = set(SmartAccountEvent.objects.filter(name__in=TRADE_EVENTS)
                    .values_list('address', flat=True).distinct())
    if not addresses:
        return set()
    return set(SmartAccount.all_objects.filter(contract_address__in=addresses).exclude(status='inherited')
               .values_list('owner_user_id', flat=True))
