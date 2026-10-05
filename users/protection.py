"""'Tu dólar te protegió' — the protection value on Tu mes.

Design: docs/designs/cashflow-home-tu-mes.md Decision 3, R13 and
docs/designs/tu-mes-insights.md §4, R21, R22; founder decision 2026-10-04:
"today" is the Binance P2P rate everywhere (replaces the Koywe buy quote).

Two bases, by country:

  purchase (BO, AR: Confío on-ramp live)
    protected = on-ramp lots still held after a chronological replay of every
                balance-changing USD event (R13), capped at the wallet balance;
    paid      = what the user paid in Confío for those dollars (Koywe, fees in);
    today     = the same dollars at today's Binance P2P rate.
    Conservative: purchase prices include fees, the P2P rate doesn't.

  month_start (VE: no on-ramp; and BO/AR users who never bought in Confío)
    protected = dollars held since the 1st (balance now minus this month's
                net inflow, capped at the balance);
    paid      = those dollars at the Binance P2P rate kept for the 1st;
    today     = those dollars at today's Binance P2P rate.

A gain worth at least US$1 at today's rate is state 'gained'. Anything
less (including a reversal when the local currency strengthens) is state
'stable': the card says the dollars kept their dollar value and never shows
a loss (founder decision 2026-10-04). Every unknown hides the card (fail
closed): no lots, no fresh rate, no month-start rate, a failed balance
read, any error.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CURRENCY_BY_COUNTRY = {'BO': 'BOB', 'AR': 'ARS', 'VE': 'VES'}
MONTH_START_CURRENCIES = {'VES'}         # no Confío on-ramp: compare with the 1st
RATE_SOURCE = 'binance_p2p'
RATE_MAX_AGE = timedelta(hours=2)        # older than this = unknown (the fetch runs every 30 min)
MIN_GAIN_USD = Decimal('1')              # hide gains worth less than US$1 today
RESULT_TTL = 10 * 60

OUTFLOW_KINDS = {'merchant', 'p2p_send', 'payroll_out', 'donation', 'withdrawal', 'investment_in'}
INFLOW_KINDS = {'income_person', 'sale', 'payroll_in', 'bonus', 'top_up', 'investment_out'}


def protection_countries() -> set:
    """Country kill switch (settings.TU_MES_PROTECTION_COUNTRIES, env CSV)."""
    return {c.strip().upper() for c in getattr(settings, 'TU_MES_PROTECTION_COUNTRIES', []) if c.strip()}


# ── Rates (Binance P2P, fetched every 30 min by exchange_rates) ──────────────
def current_rate(currency: str):
    """(rate, fetched_at) of the freshest Binance P2P row, or None if stale."""
    from django.utils import timezone
    from exchange_rates.models import ExchangeRate
    row = (ExchangeRate.objects.filter(source_currency=currency, target_currency='USD', source=RATE_SOURCE,
                                       is_active=True).order_by('-fetched_at').first())
    if row is None or row.rate <= 0 or timezone.now() - row.fetched_at > RATE_MAX_AGE:
        return None
    return Decimal(row.rate), row.fetched_at


def month_start_rate(currency: str, year: int, month: int):
    """The rate kept for the 1st of the month (DailyRateSnapshot), or None."""
    from datetime import date
    from exchange_rates.models import DailyRateSnapshot
    row = DailyRateSnapshot.objects.filter(date=date(year, month, 1), currency=currency, source=RATE_SOURCE).first()
    return Decimal(row.rate) if row and row.rate > 0 else None


# ── R13: chronological lot replay ───────────────────────────────────────────
@dataclass
class Lot:
    usd: Decimal
    local: Decimal          # what was paid for these dollars, in local currency


def _lot_for(row, movement, currency: str) -> Lot | None:
    """A completed Koywe on-ramp in the account's currency is a lot; any other
    top-up (crypto deposit, other currency) is plain dollars."""
    rt = getattr(row, 'ramp_transaction', None)
    if rt is None or rt.direction != 'on_ramp' or rt.status != 'COMPLETED' or rt.provider != 'koywe':
        return None
    if (rt.fiat_currency or '').upper() != currency or not rt.fiat_amount or rt.fiat_amount <= 0:
        return None
    return Lot(usd=movement.amount, local=Decimal(rt.fiat_amount))


def _conversion_fee(row) -> Decimal:
    conv = getattr(row, 'conversion', None)
    if conv is not None and getattr(conv, 'source', '') == 'ramp':
        return Decimal('0')
    try:
        fee = Decimal(str(getattr(row, 'fee_amount', '') or '0'))
    except Exception:  # noqa: BLE001
        return Decimal('0')
    return fee if fee > 0 else Decimal('0')


def _signed(row, m) -> Decimal:
    """+ dollars in, − dollars out, 0 neutral (savings/conversion principal)."""
    if m.kind == 'own_transfer':
        return m.amount if m.direction == 'received' else -m.amount
    if m.kind in INFLOW_KINDS:
        return m.amount
    if m.kind in OUTFLOW_KINDS:
        return -m.amount
    if m.kind in ('conversion', 'savings_in', 'savings_out'):
        # The principal stays (same dollars, other wrapper) but a recorded fee
        # leaves the wallet; a ramp's own conversion fee is already in its net.
        return -_conversion_fee(row)
    return Decimal('0')


def _spend_oldest(lots: list[Lot], amount: Decimal) -> list[Lot]:
    out = [Lot(l.usd, l.local) for l in lots]
    while amount > 0 and out:
        first = out[0]
        if first.usd <= amount:
            amount -= first.usd
            out.pop(0)
        else:
            first.local -= first.local * (amount / first.usd)
            first.usd -= amount
            amount = Decimal('0')
    return out


def replay(movements_with_rows, currency: str) -> list[Lot]:
    """Apply events oldest first: on-ramp lots and other inflows add dollars;
    every outflow spends plain dollars first, then the oldest lot first."""
    lots: list[Lot] = []
    plain = Decimal('0')
    for row, m in movements_with_rows:
        delta = _signed(row, m)
        if delta > 0:
            lot = _lot_for(row, m, currency) if m.kind == 'top_up' else None
            if lot:
                lots.append(lot)
            else:
                plain += delta
            continue
        outflow = -delta
        if outflow <= 0:
            continue
        take = min(plain, outflow)
        plain -= take
        lots = _spend_oldest(lots, outflow - take)
    return lots


def _cap(lots: list[Lot], balance_usd: Decimal) -> list[Lot]:
    """Keep at most balance_usd of lots. Dollars the ledger can't explain
    leave by the same rule as spending: oldest lot first (FIFO, R13)."""
    total = sum((l.usd for l in lots), Decimal('0'))
    return _spend_oldest(lots, total - balance_usd) if total > balance_usd else lots


def held_since(balance: Decimal, events_since_start) -> Decimal:
    """Dollars held the WHOLE time since the start: the lowest running
    balance, rebuilt backwards from today's balance through this month's
    events (oldest first in, walked newest to oldest). Spending everything
    and getting paid again later counts as zero held, never as the net."""
    running = balance
    lowest = balance
    for row, m in reversed(list(events_since_start)):
        running -= _signed(row, m)
        lowest = min(lowest, running)
    return max(Decimal('0'), lowest)


@dataclass
class Protection:
    currency: str
    basis: str                  # 'purchase' | 'month_start'
    protected_usd: Decimal
    paid_local: Decimal         # purchase: what was paid; month_start: value on the 1st
    today_local: Decimal
    avg_rate: Decimal           # purchase: average paid per USD; month_start: rate on the 1st
    today_rate: Decimal
    quoted_at: str
    state: str = 'gained'       # 'gained' | 'stable' (gain under US$1, or a reversal)

    @property
    def gain_local(self) -> Decimal:
        return self.today_local - self.paid_local


def _ledger(user, account, account_type, business_id):
    """(cache-key version, loader of rows+movements oldest first)."""
    from django.db.models import Count, Max
    from users.cashflow import ROW_RELATIONS, _stamp_viewer, classify, prepare_context
    from users.graphql_views import account_unified_queryset

    scope = account_unified_queryset(user, account, account_type, business_id)
    # Any new or changed ledger row changes the version, so cached results
    # never outlive a spend (status flips bump updated_at).
    v = scope.aggregate(n=Count('id'), last=Max('id'), touched=Max('updated_at'))
    touched = v['touched'].timestamp() if v['touched'] else 0      # microseconds kept
    version = f"{v['n']}-{v['last']}-{touched}"

    def load(since=None):
        rows_qs = scope if since is None else scope.filter(transaction_date__gte=since)
        rows = list(rows_qs.order_by('transaction_date', 'id').select_related(*ROW_RELATIONS))
        ctx = prepare_context(user, account, account_type, business_id, scope, rows)
        events = []
        for row in rows:
            _stamp_viewer(row, account, account_type, business_id)
            movement = classify(row, ctx)
            if movement is not None:
                events.append((row, movement))
        return events
    return version, load


def _balance_usd(account, version: str) -> Decimal:
    """The cap's chain read, cached under the ledger version: the RPCs run
    once after a money movement, not on every Tu mes open."""
    from cusd_plus import vault
    key = f'tumes_protection:{account.id}:{version}:balance'
    balance = cache.get(key)
    if balance is None:
        balance = Decimal(vault.withdrawable_usdt_wei(account.bsc_address)) / Decimal(10 ** 18)
        cache.set(key, balance, RESULT_TTL)
    return balance


def protection_value(user, account, account_type, business_id, year: int, month: int) -> Protection | None:
    """The protection figures for the user's current month, or None whenever
    anything is unknown."""
    if account_type != 'personal' or not account.bsc_address:
        return None
    country = (getattr(user, 'phone_country', None) or '').upper()
    if country not in protection_countries() or country not in CURRENCY_BY_COUNTRY:
        return None
    currency = CURRENCY_BY_COUNTRY[country]
    now = current_rate(currency)
    if now is None:
        return None
    today_rate, fetched_at = now

    version, load = _ledger(user, account, account_type, business_id)
    lots = []
    if currency not in MONTH_START_CURRENCIES:
        key = f'tumes_protection:{account.id}:{version}:lots:{currency}'
        lots = cache.get(key)
        if lots is None:
            lots = replay(load(), currency)
            cache.set(key, lots, RESULT_TTL)
    if not lots:
        # No dollars bought in Confío (VE always; BO/AR users who got their
        # dollars another way): compare with the 1st of the month instead.
        start_rate = month_start_rate(currency, year, month)
        if start_rate is None:
            return None
        balance = _balance_usd(account, version)
        key = f'tumes_protection:{account.id}:{version}:held:{year}-{month}'
        protected = cache.get(key)
        if protected is None:
            from users.cashflow import month_window
            from zoneinfo import ZoneInfo
            start, _ = month_window(year, month, ZoneInfo('UTC'))   # the 1st's rate is a UTC-day snapshot
            protected = held_since(balance, load(since=start))
            cache.set(key, protected, RESULT_TTL)
        if protected <= 0:
            return None
        result = Protection(currency=currency, basis='month_start', protected_usd=protected,
                            paid_local=protected * start_rate, today_local=protected * today_rate,
                            avg_rate=start_rate, today_rate=today_rate, quoted_at=fetched_at.isoformat())
    else:
        lots = _cap(lots, _balance_usd(account, version))
        protected = sum((l.usd for l in lots), Decimal('0'))
        if protected <= 0:
            return None
        paid = sum((l.local for l in lots), Decimal('0'))
        result = Protection(currency=currency, basis='purchase', protected_usd=protected, paid_local=paid,
                            today_local=protected * today_rate, avg_rate=paid / protected,
                            today_rate=today_rate, quoted_at=fetched_at.isoformat())
    if result.gain_local < MIN_GAIN_USD * today_rate:
        result.state = 'stable'     # never a loss: "tus dólares siguen valiendo lo mismo"
    return result
