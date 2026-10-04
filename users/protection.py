"""'Tu dólar te protegió' — the protection value on Tu mes.

Design: docs/designs/cashflow-home-tu-mes.md Decision 3, R7, R13, R14 and
docs/designs/tu-mes-insights.md §4, R21, R22, R27.

  protected USD  = on-ramp lots still held after a chronological replay of
                   every balance-changing USD event (R13), capped at the
                   wallet's dollar balance;
  paid           = what the user paid, in local currency, for those dollars;
  today          = what Confío would charge today for the same dollars, at
                   the all-in buy rate of a US$100 reference quote (R14).

Shown only when today − paid ≥ 10 local units. Every unknown hides the card
(fail closed): no lots, no cached quote, a failed balance read, any error.
Never the market rates in exchange_rates (R7: Confío's own quotes only).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# The quote size changes the all-in rate (Koywe's fee is partly flat), so the
# reference is fixed and named (R14).
REFERENCE_USD = Decimal('100')
MIN_GAIN_LOCAL = Decimal('10')          # hide under Bs 10 or its equivalent (Decision 3)
CURRENCY_BY_COUNTRY = {'BO': 'BOB', 'VE': 'VES'}
QUOTE_TTL = 10 * 60                      # R7
RESULT_TTL = 10 * 60

OUTFLOW_KINDS = {'merchant', 'p2p_send', 'payroll_out', 'donation', 'withdrawal', 'investment_in'}
INFLOW_KINDS = {'income_person', 'sale', 'payroll_in', 'bonus', 'top_up', 'investment_out'}


def protection_countries() -> set:
    """Country kill switch (settings.TU_MES_PROTECTION_COUNTRIES, env CSV)."""
    return {c.strip().upper() for c in getattr(settings, 'TU_MES_PROTECTION_COUNTRIES', []) if c.strip()}


def _quote_key(currency: str) -> str:
    return f'tumes_buy_quote:{currency}'


# ── R27: the US$100 buy quote, kept warm in the shared cache ────────────────
def warm_quote(currency: str) -> dict | None:
    """Fetch Confío's on-ramp (buy) quote for about US$100 and cache the
    all-in local-per-USD rate. Two preview calls: one to learn the rate, one
    at the US$100-equivalent fiat amount."""
    from ramps.koywe_client import KoyweClient

    client = KoyweClient(crypto_symbol='USDT BSC')
    if not client.is_configured:
        return None
    sample = client.create_preview_quote(symbol_in=currency, symbol_out=client.crypto_symbol, amount=Decimal('1000'))
    rate = Decimal(str(sample.get('amountIn') or 0)) / Decimal(str(sample.get('amountOut') or 1))
    fiat_in = (rate * REFERENCE_USD).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    quote = client.create_preview_quote(symbol_in=currency, symbol_out=client.crypto_symbol, amount=fiat_in)
    amount_in = Decimal(str(quote.get('amountIn') or 0))
    amount_out = Decimal(str(quote.get('amountOut') or 0))
    if amount_in <= 0 or amount_out <= 0:
        return None
    # Lots are NET dollars (the ramp's ledger row is conversion.to_amount,
    # after Confío's conversion fee), so today's rate must be per net dollar.
    if getattr(settings, 'CUSD_CONVERSION_FEE_ENABLED', False):
        from cusd_plus.cusd_vault import current_fee_bps
        fee_bps = Decimal(current_fee_bps())          # raises → no quote → hidden
        amount_out = amount_out * (Decimal(10000) - fee_bps) / Decimal(10000)
    from django.utils import timezone
    value = {'rate': str(amount_in / amount_out), 'quoted_at': timezone.now().isoformat()}
    cache.set(_quote_key(currency), value, QUOTE_TTL)
    return value


def cached_quote(currency: str) -> dict | None:
    value = cache.get(_quote_key(currency))
    if value is None and not getattr(settings, 'USE_REDIS_CACHE', False):
        # Dev/testnet: the in-process cache never sees the beat task's
        # writes, so fetch inline (prod reads the shared Redis cache only).
        try:
            value = warm_quote(currency)
        except Exception:  # noqa: BLE001
            logger.warning('buy quote fetch failed for %s', currency, exc_info=True)
            return None
    return value


# ── R13: chronological lot replay ───────────────────────────────────────────
@dataclass
class Lot:
    usd: Decimal
    local: Decimal          # what was paid for these dollars, in local currency


def _lot_for(row, movement, currency: str) -> Lot | None:
    """A completed Koywe on-ramp in the account's ramp currency is a lot;
    any other top-up (crypto deposit, other currency) is plain dollars."""
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


def replay(movements_with_rows, currency: str) -> list[Lot]:
    """Apply events oldest first: on-ramp lots and other inflows add dollars;
    every outflow spends plain dollars first, then the oldest lot first.
    Savings moves and conversions are neutral (same dollars, other wrapper)."""
    lots: list[Lot] = []
    plain = Decimal('0')
    for row, m in movements_with_rows:
        if m.kind == 'own_transfer':
            if m.direction == 'received':
                plain += m.amount
                continue
            outflow = m.amount
        elif m.kind in INFLOW_KINDS:
            lot = _lot_for(row, m, currency) if m.kind == 'top_up' else None
            if lot:
                lots.append(lot)
            else:
                plain += m.amount
            continue
        elif m.kind in OUTFLOW_KINDS:
            outflow = m.amount
        elif m.kind in ('conversion', 'savings_in', 'savings_out'):
            # The principal stays (same dollars, other wrapper) but a recorded
            # fee leaves the wallet. A ramp's own conversion is skipped: its
            # fee is already inside the ramp's net amount.
            outflow = _conversion_fee(row)
            if outflow <= 0:
                continue
        else:
            continue
        take = min(plain, outflow)
        plain -= take
        outflow -= take
        while outflow > 0 and lots:
            first = lots[0]
            if first.usd <= outflow:
                outflow -= first.usd
                lots.pop(0)
            else:
                share = outflow / first.usd
                first.local -= first.local * share
                first.usd -= outflow
                outflow = Decimal('0')
    return lots


def _cap(lots: list[Lot], balance_usd: Decimal) -> list[Lot]:
    """Keep at most balance_usd of lots, trimming the NEWEST first (the
    oldest dollars are the ones the replay says are still held longest)."""
    total = sum((l.usd for l in lots), Decimal('0'))
    excess = total - balance_usd
    out = [Lot(l.usd, l.local) for l in lots]
    while excess > 0 and out:
        last = out[-1]
        if last.usd <= excess:
            excess -= last.usd
            out.pop()
        else:
            last.local -= last.local * (excess / last.usd)
            last.usd -= excess
            excess = Decimal('0')
    return out


@dataclass
class Protection:
    currency: str
    protected_usd: Decimal
    paid_local: Decimal
    today_local: Decimal
    avg_rate: Decimal
    today_rate: Decimal
    quoted_at: str

    @property
    def gain_local(self) -> Decimal:
        return self.today_local - self.paid_local


def protection_value(user, account, account_type, business_id) -> Protection | None:
    """The protection figures, or None whenever anything is unknown."""
    from users.cashflow import ROW_RELATIONS, _stamp_viewer, classify, prepare_context
    from users.graphql_views import account_unified_queryset

    if account_type != 'personal':
        return None
    country = (getattr(user, 'phone_country', None) or '').upper()
    if country not in protection_countries() or country not in CURRENCY_BY_COUNTRY:
        return None
    currency = CURRENCY_BY_COUNTRY[country]
    quote = cached_quote(currency)
    if not quote:
        return None

    from django.db.models import Count, Max
    scope = account_unified_queryset(user, account, account_type, business_id)
    # Any new or changed ledger row changes the version, so cached lots never
    # outlive a spend (status flips bump updated_at).
    version = scope.aggregate(n=Count('id'), last=Max('id'), touched=Max('updated_at'))
    cache_key = f"tumes_protection:{account.id}:{version['n']}:{version['last']}:{version['touched']}"
    lots = cache.get(cache_key)
    if lots is None:
        rows = list(scope.order_by('transaction_date', 'id').select_related(*ROW_RELATIONS))
        ctx = prepare_context(user, account, account_type, business_id, scope, rows)
        events = []
        for row in rows:
            _stamp_viewer(row, account, account_type, business_id)
            movement = classify(row, ctx)
            if movement is not None:
                events.append((row, movement))
        lots = replay(events, currency)
        cache.set(cache_key, lots, RESULT_TTL)
    if not lots:
        return None

    from cusd_plus import vault
    if not account.bsc_address:
        return None
    # The cap's chain read is cached under the same ledger version: the RPCs
    # run once after a money movement, not on every Tu mes open.
    balance_key = f'{cache_key}:balance'
    balance_usd = cache.get(balance_key)
    if balance_usd is None:
        balance_usd = Decimal(vault.withdrawable_usdt_wei(account.bsc_address)) / Decimal(10 ** 18)
        cache.set(balance_key, balance_usd, RESULT_TTL)
    lots = _cap(lots, balance_usd)
    protected = sum((l.usd for l in lots), Decimal('0'))
    if protected <= 0:
        return None
    paid = sum((l.local for l in lots), Decimal('0'))
    today_rate = Decimal(quote['rate'])
    today = protected * today_rate
    result = Protection(currency=currency, protected_usd=protected, paid_local=paid, today_local=today,
                        avg_rate=paid / protected, today_rate=today_rate, quoted_at=quote['quoted_at'])
    if result.gain_local < MIN_GAIN_LOCAL:
        return None
    return result
