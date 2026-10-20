"""A Comunidad member's asset profile, under their Comunidad name.

Every Didit-verified member has one unless they hid it from their own
profile (CommunityProfileSettings.portfolio_hidden). It shows the member's
Comunidad name (a chosen username, or a pseudonym, never a legal name) and
is reached only from where the member already appears (see
community.followable_member), so ids can't be walked to list everyone.

What it states, all display-grade (the same stored reads Home and Tu mes
use, never a money path):

- dollars: Confío Dollar (cUSD on BSC) + Confío Dollar+ (vault shares x
  share price) + landed USDT not yet minted.
- stocks: units from the stored scan x Ondo's live price.
- Bitcoin & gold (2026-10-19): units from the crypto holdings scan x the
  latest PancakeSwap snapshot; their own ledger (CryptoTrade), walked apart
  from stocks so an unreadable swap can't poison a stock's P&L.
- $CONFIO presale: tokens bought in the presale (completed purchases).
- positions: cost basis by average cost over the member's own Confío
  trades, so P&L, invested and average entry are exact for anything bought
  in Confío. A position the ledger can't explain (units from outside) shows
  its value without P&L: unknown is never stated as a number.
- stats: trades, average time a position was held, member since.

Anything that can't be read is None, and the app hides it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

logger = logging.getLogger(__name__)

UNITS_TOLERANCE = Decimal('0.000001')
DUST_USD = Decimal('0.01')


def _dec(value) -> Decimal | None:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d.is_finite() else None


@dataclass
class OpenPosition:
    symbol: str
    ticker: str
    name: str
    units: Decimal
    value_usd: Decimal | None
    invested_usd: Decimal | None = None
    avg_entry_usd: Decimal | None = None
    pnl_usd: Decimal | None = None
    pnl_pct: Decimal | None = None
    day_change_pct: Decimal | None = None


@dataclass
class ClosedPosition:
    symbol: str
    ticker: str
    name: str
    invested_usd: Decimal
    proceeds_usd: Decimal
    pnl_usd: Decimal
    pnl_pct: Decimal | None
    closed_on: str


@dataclass
class Portfolio:
    dollars_usd: Decimal | None
    stocks_usd: Decimal | None
    total_usd: Decimal | None
    # Investments' 24h change (stocks, and Bitcoin & gold when held): the
    # "hoy" beside the total. The name predates crypto.
    stocks_change_24h_usd: Decimal | None
    presale_confio: Decimal | None
    presale_invested_usd: Decimal | None
    trade_count: int | None
    avg_hold_seconds: int | None
    member_since: str | None
    open_positions: list | None = field(default_factory=list)
    closed_positions: list | None = field(default_factory=list)
    crypto_usd: Decimal | None = Decimal('0')


def personal_wallet(user) -> str | None:
    from users.models import Account

    account = (
        Account.objects.filter(user=user, account_type='personal', deleted_at__isnull=True)
        .exclude(bsc_address__isnull=True).exclude(bsc_address='')
        .order_by('account_index').first()
    )
    return account.bsc_address.lower() if account else None


def dollars_usd(wallet: str) -> Decimal | None:
    """Confío Dollar + Confío Dollar+ + landed USDT. None when any part is
    unknown: a partial sum would read as a confident, wrong balance."""
    from blockchain.bsc_balance_service import BscBalanceService, to_amount
    from cusd_plus import vault

    try:
        raw = BscBalanceService.balances_raw(wallet)
    except Exception:  # noqa: BLE001
        logger.warning('portfolio: balance read failed', exc_info=True)
        return None
    needed = ['CUSD_BSC', 'USDT_BSC']
    if vault.vault_address():
        needed.append('CUSD_PLUS')
    if any(token not in raw for token in needed):
        return None
    total = to_amount(raw['CUSD_BSC']) + to_amount(raw['USDT_BSC'])
    if 'CUSD_PLUS' in needed and raw['CUSD_PLUS']:
        plus = _dec(vault.position_usd(wallet))
        if plus is None or plus <= 0:
            # Shares held but no price ever read: unknown, not $0.
            return None
        total += plus
    return total


def presale_totals(user) -> tuple[Decimal | None, Decimal | None]:
    """(CONFIO bought, dollars paid) over the member's completed presale
    purchases. Refunded or failed purchases never count."""
    from django.db.models import Sum

    from presale.models import PresalePurchase

    try:
        totals = PresalePurchase.objects.filter(user=user, status='completed').aggregate(
            confio=Sum('confio_amount'), usd=Sum('cusd_amount'))
    except Exception:  # noqa: BLE001
        logger.warning('portfolio: presale totals unreadable', exc_info=True)
        return None, None
    return _dec(totals['confio'] or 0), _dec(totals['usd'] or 0)


def _market() -> dict:
    from cusd_plus import gm_api

    out = {}
    for item in gm_api.all_market():
        pm = item.get('primaryMarket') or {}
        um = item.get('underlyingMarket') or {}
        symbol = pm.get('symbol')
        if not symbol:
            continue
        ticker = um.get('ticker') or symbol.removesuffix('on')
        out[symbol] = {
            'price': _dec(pm.get('price')),
            'day_pct': _dec(pm.get('priceChangePct24h')),
            'ticker': ticker,
            'name': um.get('name') or ticker,
        }
    return out


@dataclass
class _Book:
    units: Decimal = Decimal('0')
    cost: Decimal = Decimal('0')
    bought: Decimal = Decimal('0')
    sold: Decimal = Decimal('0')
    explained: bool = True
    opened_at: datetime | None = None


def walk_trades(trades, now):
    """Average-cost books per symbol from the member's own trades, every
    closed episode (opened → sold out) with its realized result, and how
    long each position was (or has been) held."""
    books: dict[str, _Book] = {}
    closed = []
    holds = []
    poisoned = False
    for t in trades:
        if t.symbol.startswith('?') or t.units <= 0:
            # Which symbol an unreadable trade moved is unknown: no book can
            # be trusted after it, including books it may have opened.
            poisoned = True
            for book in books.values():
                book.explained = False
            continue
        book = books.setdefault(t.symbol, _Book(explained=not poisoned))
        if t.usd is None:
            book.explained = False
        if t.kind.endswith('_buy'):
            if book.units <= 0:
                book.opened_at = t.when
                book.bought = Decimal('0')
                book.sold = Decimal('0')
            book.units += t.units
            book.cost += t.usd or Decimal('0')
            book.bought += t.usd or Decimal('0')
            continue
        if book.units <= 0 or book.units < t.units * (1 - UNITS_TOLERANCE):
            # Sold more than Confío's ledger holds: units came from outside.
            book.explained = False
            book.units = max(book.units - t.units, Decimal('0'))
            continue
        share = min(t.units / book.units, Decimal('1'))
        book.cost -= book.cost * share
        book.units -= t.units
        book.sold += t.usd or Decimal('0')
        if book.units <= t.units * UNITS_TOLERANCE:
            book.units = Decimal('0')
            if book.opened_at and book.explained:
                holds.append((t.when - book.opened_at).total_seconds())
            if book.explained and book.bought > 0:
                closed.append((t.symbol, book.bought, book.sold, book.sold - book.bought, t.when))
            book.cost = Decimal('0')
            book.explained = not poisoned
            book.opened_at = None
    return books, closed, holds


def open_hold_seconds(books, held, now) -> list:
    """How long each still-held position has been open, counting only
    positions the ledger explains and the holdings scan confirms."""
    out = []
    for symbol, book in books.items():
        units = _dec((held or {}).get(symbol))
        if (book.explained and book.units > 0 and book.opened_at and units
                and abs(book.units - units) <= max(book.units, units) * UNITS_TOLERANCE):
            out.append((now - book.opened_at).total_seconds())
    return out


@dataclass
class _CryptoPart:
    total: Decimal | None
    change_24h: Decimal | None
    open_positions: list | None
    closed: list            # walk_trades episodes
    holds: list
    open_holds: list
    trades: list | None


def crypto_part(wallet: str, now) -> _CryptoPart:
    """Bitcoin & gold for one wallet. Never scans a wallet that has never
    swapped in Confío (nothing to show, and no RPC per profile view)."""
    from blockchain.models import CryptoHoldings
    from cusd_plus.crypto_catalog import by_symbol
    from cusd_plus.crypto_holdings import holdings_units
    from cusd_plus.crypto_month import _live_prices, confirmed_trades, display_name
    from cusd_plus.crypto_prices import market_rows

    try:
        trades = confirmed_trades(wallet)
    except Exception:  # noqa: BLE001
        logger.warning('portfolio: crypto ledger unreadable', exc_info=True)
        trades = None
    if trades == [] and not CryptoHoldings.objects.filter(bsc_address=wallet).exists():
        return _CryptoPart(Decimal('0'), Decimal('0'), [], [], [], [], [])
    try:
        raw = holdings_units(wallet)
    except Exception:  # noqa: BLE001
        logger.warning('portfolio: crypto holdings unreadable', exc_info=True)
        raw = None
    try:
        prices = _live_prices(now)
        day = {r['token'].symbol: r['day_change_pct'] for r in market_rows()}
    except Exception:  # noqa: BLE001
        logger.warning('portfolio: crypto prices unavailable', exc_info=True)
        prices, day = None, {}
    books, closed, holds = walk_trades(trades or [], now)

    held_units = {}
    total: Decimal | None = Decimal('0') if raw is not None and prices is not None else None
    change: Decimal | None = total
    positions = []
    for symbol, base in sorted((raw or {}).items()):
        token = by_symbol(symbol, include_unlisted=True)
        if token is None or not base:
            if base:
                total = change = None  # off-catalog: unknown, never dropped
            continue
        units = Decimal(int(base)) / (Decimal(10) ** token.decimals)
        held_units[symbol] = units
        price = (prices or {}).get(symbol)
        value = units * price if price is not None else None
        pct = day.get(symbol)
        if value is None:
            total = change = None
        else:
            if total is not None:
                total += value
            if change is not None:
                change = None if pct is None or pct <= -100 else change + value - value / (1 + Decimal(str(pct)) / 100)
        position = OpenPosition(symbol=symbol, ticker=token.ticker, name=display_name(token), units=units,
                                value_usd=value,
                                day_change_pct=Decimal(str(pct)) if pct is not None else None)
        book = books.get(symbol)
        if (trades is not None and book is not None and book.explained and book.units > 0
                and abs(book.units - units) <= max(book.units, units) * UNITS_TOLERANCE):
            position.invested_usd = book.cost
            position.avg_entry_usd = book.cost / book.units
            if value is not None and book.cost > 0:
                position.pnl_usd = value - book.cost
                position.pnl_pct = (value - book.cost) / book.cost * 100
        if value is None or value >= DUST_USD:
            positions.append(position)
    return _CryptoPart(
        total=total, change_24h=change, open_positions=positions if raw is not None else None,
        closed=closed, holds=holds,
        open_holds=open_hold_seconds(books, held_units, now) if raw is not None else [],
        trades=trades,
    )


def build_portfolio(user) -> Portfolio | None:
    from cusd_plus.gm_holdings import STALE_AFTER, complete_holdings
    from cusd_plus.stock_month import confirmed_trades

    wallet = personal_wallet(user)
    if not wallet:
        return None
    now = timezone.now()
    try:
        trades = confirmed_trades(wallet)
    except Exception:  # noqa: BLE001
        logger.warning('portfolio: trade ledger unreadable', exc_info=True)
        trades = None
    # A complete scan only: a list scan may skip a failing token, and a
    # skipped holding would publish as a confident, too-low total.
    try:
        # Same freshness as the stocks screen: an old scan would keep
        # publishing positions moved out since.
        scan = complete_holdings(wallet, max_age=STALE_AFTER)
        held = scan[0] if scan is not None else None
    except Exception:  # noqa: BLE001
        logger.warning('portfolio: holdings unreadable', exc_info=True)
        held = None
    try:
        market = _market()
    except Exception:  # noqa: BLE001
        logger.warning('portfolio: market unavailable', exc_info=True)
        market = None

    books, closed, holds = walk_trades(trades or [], now)

    open_positions = []
    known = held is not None and market is not None
    stocks_total: Decimal | None = Decimal('0') if known else None
    change_24h: Decimal | None = Decimal('0') if known else None
    for symbol, units in sorted((held or {}).items()):
        units = _dec(units)
        if units is None or units <= 0:
            continue
        info = (market or {}).get(symbol) or {}
        price = info.get('price')
        value = units * price if price is not None else None
        if value is None:
            stocks_total = None
            change_24h = None
        else:
            if stocks_total is not None:
                stocks_total += value
            pct = info.get('day_pct')
            if change_24h is not None:
                if pct is None or pct <= -100:
                    change_24h = None
                else:
                    change_24h += value - value / (1 + pct / 100)
        position = OpenPosition(
            symbol=symbol, ticker=info.get('ticker') or symbol.removesuffix('on'),
            name=info.get('name') or symbol.removesuffix('on'), units=units, value_usd=value,
            day_change_pct=info.get('day_pct'),
        )
        book = books.get(symbol)
        if (trades is not None and book is not None and book.explained and book.units > 0
                and abs(book.units - units) <= max(book.units, units) * UNITS_TOLERANCE):
            position.invested_usd = book.cost
            position.avg_entry_usd = book.cost / book.units
            if value is not None and book.cost > 0:
                position.pnl_usd = value - book.cost
                position.pnl_pct = (value - book.cost) / book.cost * 100
        if value is None or value >= DUST_USD:
            open_positions.append(position)
    crypto = crypto_part(wallet, now)
    if crypto.open_positions is not None:
        open_positions.extend(crypto.open_positions)
    open_positions.sort(key=lambda p: p.value_usd or Decimal('0'), reverse=True)

    from cusd_plus.crypto_catalog import by_symbol as crypto_token
    from cusd_plus.crypto_month import display_name as crypto_name

    closed_positions = []
    for symbol, bought, sold, pnl, when in sorted(closed + crypto.closed, key=lambda e: e[4], reverse=True):
        info = (market or {}).get(symbol) or {}
        token = crypto_token(symbol, include_unlisted=True)
        if token is not None:
            info = {'ticker': token.ticker, 'name': crypto_name(token)}
        closed_positions.append(ClosedPosition(
            symbol=symbol, ticker=info.get('ticker') or symbol.removesuffix('on'),
            name=info.get('name') or symbol.removesuffix('on'), invested_usd=bought, proceeds_usd=sold,
            pnl_usd=pnl, pnl_pct=(pnl / bought * 100) if bought > 0 else None,
            closed_on=timezone.localdate(when).isoformat(),
        ))

    dollars = dollars_usd(wallet)
    presale_confio, presale_usd = presale_totals(user)
    parts = (dollars, stocks_total, crypto.total)
    total = sum(parts, Decimal('0')) if all(p is not None for p in parts) else None
    if change_24h is not None:
        change_24h = change_24h + crypto.change_24h if crypto.change_24h is not None else None
    ledgers_known = trades is not None and crypto.trades is not None
    joined = getattr(user, 'date_joined', None)
    return Portfolio(
        dollars_usd=dollars,
        stocks_usd=stocks_total,
        total_usd=total,
        stocks_change_24h_usd=change_24h,
        presale_confio=presale_confio,
        presale_invested_usd=presale_usd,
        trade_count=len(trades) + len(crypto.trades) if ledgers_known else None,
        avg_hold_seconds=(
            _coarse_hold(holds + open_hold_seconds(books, held, now) + crypto.holds + crypto.open_holds)
            if ledgers_known and held is not None and crypto.open_positions is not None else None
        ),
        member_since=joined.strftime('%Y-%m') if joined else None,
        open_positions=open_positions if held is not None and crypto.open_positions is not None else None,
        closed_positions=closed_positions[:50] if ledgers_known else None,
        crypto_usd=crypto.total,
    )


def _coarse_hold(holds) -> int | None:
    """Average holding time rounded to the hour (0 = under an hour): an
    exact figure for a single open position is now minus its purchase
    time, which would date the trade to the second."""
    if not holds:
        return None
    return int(round(sum(holds) / len(holds) / 3600)) * 3600
