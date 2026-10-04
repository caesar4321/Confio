"""Daily cUSD+ snapshots and monthly savings earnings ("Tu ahorro ganó").

Design: docs/designs/tu-mes-insights.md R17/R19/R20/R23/R26/R28 and the
delta corrections. One run per UTC day, shortly after midnight:

  1. pin a block (eth_blockNumber), read pPlus() AT that block;
  2. read every registered account's share balance at the SAME block with
     Multicall3 (250 balanceOf per eth_call), each batch retried 3x;
  3. write the day's price row (complete=True, plus the account ids whose
     batch still failed) and one holding row per NONZERO balance.

Earnings for a day = shares held on that day's snapshot x the price change
until the next day's snapshot, credited to the earlier day (the day it
accrued). It's an estimate (R23): a deposit or withdrawal during a day moves
at most that day's accrual, so the app shows "~US$X".

Fail closed everywhere: no price row for a day, or the account listed as
failed on it, makes that month's earnings None (the card hides). Never the
1e18 fallback, never "latest" for the pinned reads.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from eth_abi import decode, encode

from . import vault
from .gm_holdings import CHUNK, MULTICALL3, SEL_BALANCE_OF, SEL_TRY_AGGREGATE

logger = logging.getLogger(__name__)

BATCH_RETRIES = 3
WAD = Decimal(10) ** 18


def _at(block: int) -> str:
    return hex(block)


def _pps_at(addr: str, block: int) -> int:
    res = vault._rpc('eth_call', [{'to': addr, 'data': vault.SEL_PPLUS}, _at(block)])
    value = int(res, 16) if res and res != '0x' else 0
    if value <= 0:
        raise RuntimeError('pPlus() returned no value at the pinned block')
    return value


def _balances_at(token: str, addresses: list[str], block: int) -> dict[str, int]:
    """{address: shares} for one batch at the pinned block. Raises on any
    RPC or per-call failure so the caller can retry or record the batch."""
    calls = [(token, SEL_BALANCE_OF + encode(['address'], [a])) for a in addresses]
    data = SEL_TRY_AGGREGATE + encode(['bool', '(address,bytes)[]'], [False, calls])
    res = vault._rpc('eth_call', [{'to': MULTICALL3, 'data': '0x' + data.hex()}, _at(block)])
    results = decode(['(bool,bytes)[]'], bytes.fromhex(res[2:]))[0]
    if len(results) != len(addresses):
        raise RuntimeError('Multicall returned an incomplete result set')
    out = {}
    for (ok, ret), address in zip(results, addresses):
        if not ok or len(ret) < 32:
            raise RuntimeError(f'balanceOf failed for {address}')
        out[address] = int.from_bytes(ret[:32], 'big')
    return out


def snapshot_day(day: date | None = None) -> str:
    """Write the snapshot for `day` (UTC today by default). Idempotent: a
    day that already has its price row is left alone. Returns a short
    status for the task log."""
    from django.db import transaction
    from django.utils import timezone
    from users.models import Account
    from users.models_cashflow import CusdPlusHoldingSnapshot, CusdPlusPriceSnapshot

    day = day or timezone.now().date()
    if CusdPlusPriceSnapshot.objects.filter(date=day).exists():
        return 'exists'
    token = vault.vault_address()
    if not token:
        return 'no-vault'

    block = int(vault._rpc('eth_blockNumber', []), 16)
    pps = _pps_at(token, block)          # raises: no row today → everyone's month unknown

    # Fresh, never the 10-minute scanner cache: an account registered just
    # before the run must be read, or a complete day would record it as 0.
    registered = {
        row['bsc_address'].lower(): row['id']
        for row in Account.objects.filter(deleted_at__isnull=True)
        .exclude(bsc_address__isnull=True).exclude(bsc_address='').values('id', 'bsc_address')
    }
    addresses = sorted(registered)
    held: dict[int, int] = {}
    failed: list[int] = []
    for i in range(0, len(addresses), CHUNK):
        batch = addresses[i:i + CHUNK]
        for attempt in range(1, BATCH_RETRIES + 1):
            try:
                for address, shares in _balances_at(token, batch, block).items():
                    if shares:
                        held[registered[address]] = shares
                break
            except Exception:  # noqa: BLE001 — retried, then recorded per account (R28)
                if attempt == BATCH_RETRIES:
                    logger.warning('savings snapshot batch %s failed at block %s', i // CHUNK, block, exc_info=True)
                    failed.extend(registered[a] for a in batch)

    with transaction.atomic():
        CusdPlusPriceSnapshot.objects.create(
            date=day, pps_wad=pps, block_number=block, complete=True, failed_account_ids=sorted(failed))
        CusdPlusHoldingSnapshot.objects.bulk_create([
            CusdPlusHoldingSnapshot(account_id=account_id, date=day, shares_raw=shares, block_number=block)
            for account_id, shares in held.items()])
    return f'ok holders={len(held)} failed={len(failed)}'


def savings_earned(account_id: int, year: int, month: int, today: date | None = None):
    """(earned_usd, [(day, usd), ...]) for a UTC calendar month, or None when
    any needed snapshot is missing or the account's read failed on it.

    Covers the month's days whose accrual is complete: every day of a past
    month, and up to yesterday for the current month (a day's accrual needs
    the next day's snapshot). Before the 1st's accrual is known the result
    is (0, []) and the app shows nothing (< US$0.01)."""
    import calendar
    from django.utils import timezone
    from users.models_cashflow import CusdPlusHoldingSnapshot, CusdPlusPriceSnapshot

    today = today or timezone.now().date()
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    end = min(last, today - timedelta(days=1))          # last day whose accrual is known
    if end < first:
        return Decimal('0'), []

    prices = {
        p.date: p for p in CusdPlusPriceSnapshot.objects.filter(
            date__gte=first, date__lte=end + timedelta(days=1), complete=True)
    }
    holdings = {
        h.date: Decimal(h.shares_raw) for h in CusdPlusHoldingSnapshot.objects.filter(
            account_id=account_id, date__gte=first, date__lte=end)
    }
    daily = []
    total = Decimal('0')
    day = first
    while day <= end:
        start_row, end_row = prices.get(day), prices.get(day + timedelta(days=1))
        if start_row is None or end_row is None:
            return None
        if account_id in (start_row.failed_account_ids or []):
            return None
        shares = holdings.get(day, Decimal('0'))           # complete day + no row = 0 shares (R26)
        usd = shares * (Decimal(end_row.pps_wad) - Decimal(start_row.pps_wad)) / (WAD * WAD)
        daily.append((day, usd))
        total += usd
        day += timedelta(days=1)
    return total, daily
