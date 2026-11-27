"""A member's own trade history as CSV: Futuros, stocks (Ondo), Bitcoin & gold.

One top-level query, `tradeHistoryCsv(product: futuros|stocks|crypto)`,
queried alone by the app (GraphQL validation is all-or-nothing). It is the
member's own data: no Cuenta inteligente requirement, no country, iOS or
feature-switch gate, so a member now in a blocked country still gets their
past trades. Account context comes from the JWT only:

- personal account: its own wallet (and, for stocks/crypto, the trades of
  the person's own Cuenta inteligente, from the same indexed ledger the
  portfolio reads: inbox.SmartAccountTrade);
- business account: stocks/crypto for the business OWNER (as the stock and
  crypto holdings resolvers serve business wallets); employees never;
  Futuros is personal-only, as every perps resolver;
- a Cuenta inteligente JWT context is refused (deny by default).

Only final trades: confirmed sponsored batches; for Futuros, positions whose
order actually filled (opened_at set) and whose margin left dollars in a
confirmed batch, with their close when closed. The currently open one is
included with status 'open'. Quotes, failed and refunded-before-open rows
never appear. Newest first, at most MAX_ROWS rows (`capped` says so).

Numbers are exact stored values, plain decimal strings; blank = not recorded.
Times are UTC ISO 8601 (seconds).
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import timezone as dt_timezone
from decimal import Decimal, localcontext

import graphene
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_ROWS = 5000
WAD = Decimal(10) ** 18
PRODUCTS = ('futuros', 'stocks', 'crypto')

FUTUROS_COLUMNS = [
    'position_id',        # Confío position id
    'market',             # Hyperliquid coin: 'BTC' or 'xyz:GOLD'
    'ticker',
    'asset_class',        # crypto | stock | index | commodity | fx
    'side',               # long | short
    'leverage',
    'status',             # open | closed | liquidated
    'margin_usd',         # margin chosen at the open
    'margin_added_usd',   # sum of top-ups that left dollars (refunded ones included here, see put_in_usd)
    'margin_adds',        # how many top-ups make margin_added_usd
    'put_in_usd',         # margin + top-ups - refunded top-ups (net of entry fee): what the app shows as put in
    'entry_price',        # average fill price of the opening order
    'size',               # position size at the open, in coin units (unsigned)
    'opened_at',          # when the opening order filled
    'close_price',        # average price of the closing fills
    'closed_at',          # venue time of the closing fill
    'realized_pnl_usd',   # closed P&L from the venue fills (before fees and funding)
    'funding_usd',        # funding settled at close (negative = paid); blank while open
    'venue_fees_usd',     # Hyperliquid trading fees
    'liquidation',        # '' | book | backstop
    'returned_usd',       # dollars that re-entered Confío dollars, fee included
    'result_usd',         # returned_usd + refunded top-ups - put_in_usd, once done (all costs included)
    'returned_at',        # when the money was back (done)
]

STOCK_COLUMNS = [
    'trade_id',           # batch-<id> (wallet) | smart-<id> (Cuenta inteligente)
    'account',            # personal | business | smart
    'executed_at',
    'side',               # buy | sell
    'ticker',             # TSLA
    'symbol',             # the token: TSLAon
    'shares',             # signed Ondo quote quantity (what the ledger counts) / indexed units (smart)
    'quote_price_usd',    # Ondo's signed price per share (wallet trades only)
    'usd',                # exact settlement, see _usd_comment
    'fee_usd',            # Confío's perimeter fee inside `usd`, when exactly known
    'tx_hash',
    'block_number',
]

CRYPTO_COLUMNS = [
    'trade_id',
    'account',
    'executed_at',
    'side',
    'symbol',             # catalog symbol: BTCB, XAUT
    'ticker',             # BTC, XAUT
    'category',           # crypto | metal
    'units',              # exact token units from the receipt
    'usd',
    'fee_usd',
    'tx_hash',
    'block_number',
]

# `usd` (stocks and crypto) is the ledger's settlement, as the activity
# history shows it: a BUY is the dollars that left Confío dollars INCLUDING
# Confío's fee; a SELL is the dollars that re-entered them AFTER the fee.
# fee_usd is that perimeter fee, from the finalized fee-event ledger
# (conversion.CusdFeeEvent), written only when exactly one event of the
# trade's direction exists in its transaction and it reconciles with `usd`
# (buy: gross == usd; sell: net == usd). Otherwise blank (legacy router-fee
# trades, a fee event not scanned yet, Cuenta inteligente trades).

MESSAGES = {
    'auth_required': 'Inicia sesión para descargar tu historial.',
    'bad_product': 'Elige Futuros, Acciones u Oro y Bitcoin.',
    'account_not_supported': 'Descarga tu historial desde tu cuenta personal.',
    'personal_only': 'El historial de Futuros se descarga desde tu cuenta personal.',
    'owner_only': 'Solo el dueño del negocio puede descargar el historial.',
    'no_wallet': 'Esta cuenta todavía no tiene una billetera.',
    'unavailable': 'No pudimos preparar tu historial. Intenta de nuevo en unos minutos.',
}


class ExportRefused(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


# ── formatting ────────────────────────────────────────────────────────────

def _num(value) -> str:
    """Plain decimal string: no exponent, separators or symbols; '' = unknown."""
    if value is None or value == '':
        return ''
    # Wide context: 30 integer + 18 fraction digits must survive normalize().
    with localcontext() as ctx:
        ctx.prec = 100
        try:
            d = Decimal(str(value))
        except ArithmeticError:
            return ''
        if not d.is_finite():
            return ''
        if d == 0:
            return '0'
        return format(d.normalize(), 'f')


# Cells a spreadsheet could read as a formula (CSV injection). Text columns
# only: numbers are written by _num and a leading '-' there is a sign.
TEXT_COLUMNS = frozenset({'symbol', 'ticker', 'market', 'asset_class', 'category', 'side', 'status',
                          'liquidation', 'trade_id', 'tx_hash', 'account'})
_FORMULA_START = ('=', '+', '-', '@', '\t', '\r')


def _safe_text(value) -> str:
    text = '' if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def _time(value) -> str:
    if value is None:
        return ''
    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    return value.astimezone(dt_timezone.utc).isoformat(timespec='seconds')


def _stock_ticker(symbol: str) -> str:
    return symbol[:-2] if symbol.lower().endswith('on') else symbol


def render_csv(columns: list, rows: list) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator='\n', extrasaction='raise')
    writer.writeheader()
    for row in rows:
        writer.writerow({k: (_safe_text(v) if k in TEXT_COLUMNS else v) for k, v in row.items()})
    return out.getvalue()


# ── account context (JWT only) ───────────────────────────────────────────

def resolve_account(info, product: str):
    """(user, account) of the JWT context allowed to export `product`."""
    from users.jwt_context import get_jwt_business_context_with_validation, is_business_employee
    from users.models import Account

    user = getattr(info.context, 'user', None)
    if user is None or not user.is_authenticated:
        raise ExportRefused('auth_required')
    # A smart context comes back None (not allow_smart): refused like every
    # flow not reviewed for it. Its trades ride along in the personal export.
    ctx = get_jwt_business_context_with_validation(info, required_permission=None)
    if not ctx:
        raise ExportRefused('account_not_supported')
    index = ctx.get('account_index') or 0
    if ctx.get('account_type') == 'business':
        if product == 'futuros':
            raise ExportRefused('personal_only')
        business_id = ctx.get('business_id')
        # Owners only, proven by the Account (the employee row is delegation).
        if (not business_id or is_business_employee(user, business_id)
                or not Account.objects.filter(user=user, business_id=business_id, account_type='business',
                                              deleted_at__isnull=True).exists()):
            raise ExportRefused('owner_only')
        account = Account.objects.filter(business_id=business_id, account_type='business',
                                         account_index=index, deleted_at__isnull=True).first()
    elif ctx.get('account_type') == 'personal':
        account = Account.objects.filter(user=user, account_type='personal', account_index=index,
                                         deleted_at__isnull=True).first()
    else:
        raise ExportRefused('account_not_supported')
    if account is None or not account.bsc_address:
        raise ExportRefused('no_wallet')
    return user, account


# ── Futuros ──────────────────────────────────────────────────────────────

def futuros_rows(user, wallet: str, limit: int = MAX_ROWS) -> tuple[list, bool]:
    from django.db.models import F

    from blockchain.models import PerpPosition

    from . import perps_catalog
    from .perps_schema import margin_put_in, position_result_usd

    wallet = (wallet or '').lower()
    positions = list(
        PerpPosition.objects.filter(user=user, wallet=wallet, open_batch__status='confirmed',
                                    opened_at__isnull=False)
        # Quotes and failed opens never traded; 'cancelled' is a dropped quote.
        .exclude(state__in=('quoted', 'failed', 'cancelled', 'bridging', 'refunded'))
        .select_related('market').prefetch_related('margin_changes')
        .order_by(F('opened_at').desc(), '-id')[:limit + 1])
    capped = len(positions) > limit
    rows = []
    views: dict = {}
    for p in positions[:limit]:
        if p.market_id not in views:
            views[p.market_id] = perps_catalog.view(p.market)
        view = views[p.market_id]
        adds = [c for c in p.margin_changes.all()
                if c.direction == 'add' and c.state not in ('quoted', 'failed', 'cancelled')]
        put_in, refunded = margin_put_in(p)
        # A malformed stored size is blank, never a failed export.
        size = _num((p.flow or {}).get('size_initial') or p.size)
        status = 'open' if p.state == 'open' else ('liquidated' if p.liquidation or p.state == 'liquidated'
                                                    else 'closed')
        rows.append({
            'position_id': p.id,
            'market': p.market.coin,
            'ticker': view.ticker,
            'asset_class': view.asset_class,
            'side': p.side,
            'leverage': p.leverage,
            'status': status,
            'margin_usd': _num(p.margin_usd),
            'margin_added_usd': _num(sum((Decimal(c.amount_usd) for c in adds), Decimal(0))),
            'margin_adds': len(adds),
            'put_in_usd': _num(put_in - refunded),
            'entry_price': _num(p.entry_avg_px),
            'size': size[1:] if size.startswith('-') else size,
            'opened_at': _time(p.opened_at),
            'close_price': _num(p.close_avg_px) if status != 'open' else '',
            'closed_at': _time(p.closed_at) if status != 'open' else '',
            'realized_pnl_usd': _num(p.realized_pnl) if status != 'open' else '',
            'funding_usd': _num(p.funding) if status != 'open' else '',
            'venue_fees_usd': _num(p.venue_fees) if status != 'open' else '',
            'liquidation': p.liquidation or '',
            'returned_usd': _num(p.returned_usd),
            'result_usd': _num(position_result_usd(p, put_in, refunded)),
            'returned_at': _time(p.done_at) if p.state == 'done' else '',
        })
    return rows, capped


# ── stocks and crypto ────────────────────────────────────────────────────

def _fees_by_tx(tx_hashes) -> dict:
    from conversion.models import CusdFeeEvent

    out: dict = {}
    hashes = {h.lower() for h in tx_hashes if h}
    if not hashes:
        return out
    for event in CusdFeeEvent.objects.filter(tx_hash__in=hashes):
        out.setdefault(event.tx_hash.lower(), []).append(event)
    return out


def _fee_usd(events, side: str, usd) -> str:
    """The perimeter fee inside `usd`, only when it reconciles exactly."""
    if usd in (None, ''):
        return ''
    direction = 'exit' if side == 'buy' else 'entry'
    matching = [e for e in events or () if e.direction == direction]
    if len(matching) != 1:
        return ''
    event = matching[0]
    usd_wei = Decimal(str(usd)) * WAD
    if usd_wei != (event.gross_wei if side == 'buy' else event.net_wei):
        return ''
    return _num(Decimal(event.fee_wei) / WAD)


def _wallet_forms(wallet: str) -> set:
    """The stored forms of an address: batches are written lowercase
    (sponsor_7702); the checksum form covers any older writer. An exact IN
    keeps the (user, created_at) and tx indexes usable."""
    from eth_utils import to_checksum_address

    wallet = (wallet or '').lower()
    forms = {wallet}
    try:
        forms.add(to_checksum_address(wallet))
    except (TypeError, ValueError):
        pass
    return forms


def _signer_ids(user, account) -> set:
    """Who can have signed this account's batches. An address alone is not
    proof of ownership (a deleted account's address can be registered again),
    so batches must also be signed by the account's own people: the user for
    a personal account; the owner and the business's employees, past ones
    included, for a business account."""
    if account.account_type != 'business':
        return {user.id}
    from users.models_employee import BusinessEmployee

    ids = {user.id}
    if account.user_id:
        ids.add(account.user_id)
    ids |= set(BusinessEmployee.all_objects.filter(business_id=account.business_id)
               .values_list('user_id', flat=True))
    return ids


def _settled_usd(batch):
    row = getattr(batch, 'unified_transaction', None)
    if row is None or row.deleted_at is not None or row.status != 'CONFIRMED':
        return None
    try:
        return Decimal(str(row.amount))
    except ArithmeticError:
        return None


def _smart_rows(user, prefix: str, limit: int) -> list:
    """The person's own Cuenta inteligente trades, as already indexed for the
    portfolio ledger (inbox/account_trades.py). Unreadable ('?') rows and
    events not indexed yet are left out (nothing exact to export)."""
    from inbox.models import SmartAccountTrade
    from inbox.person_wallets import account_addresses

    addresses = account_addresses(user)
    if not addresses:
        return []
    return list(SmartAccountTrade.objects.filter(address__in=addresses, kind__startswith=prefix)
                .exclude(symbol__startswith='?').exclude(symbol='').select_related('event')
                .order_by('-traded_at', '-id')[:limit + 1])


def _includes_smart(user, account) -> bool:
    """Only the person's anchor personal wallet carries their Cuenta
    inteligente (as Portfolio and the Liga do)."""
    from inbox.member_portfolio import personal_wallet

    return account.account_type == 'personal' and personal_wallet(user) == (account.bsc_address or '').lower()


def stock_rows(user, account, limit: int = MAX_ROWS) -> tuple[list, bool]:
    from blockchain.models import SponsoredBatch

    from .sponsor_7702 import _decode_stock_call
    from .stock_month import _symbol_by_address

    wallet = account.bsc_address.lower()
    label = 'business' if account.account_type == 'business' else 'personal'
    batches = list(SponsoredBatch.objects.filter(
        user_bsc_address__in=_wallet_forms(wallet), user_id__in=_signer_ids(user, account),
        kind__in=('stock_buy', 'stock_sell'), status='confirmed')
        .select_related('unified_transaction').order_by('-created_at', '-id')[:limit + 1])
    fees = _fees_by_tx(b.tx_hash for b in batches)
    by_address = _symbol_by_address() if batches else {}
    rows = []
    for batch in batches:
        side = 'buy' if batch.kind == 'stock_buy' else 'sell'
        try:
            actions = [a for call in json.loads(batch.calls_json or '[]')
                       if (a := _decode_stock_call(call, historical=True)) is not None]
        except Exception:  # noqa: BLE001 — an unreadable call still settled: export what is known
            actions = []
        action = actions[0] if len(actions) == 1 and actions[0]['kind'] == batch.kind else None
        symbol = by_address.get(action['asset'], '') if action else ''
        usd = _settled_usd(batch)
        rows.append({
            'trade_id': f'batch-{batch.id}', 'account': label,
            'executed_at': _time(batch.created_at), 'side': side,
            'ticker': _stock_ticker(symbol) if symbol else '', 'symbol': symbol,
            'shares': _num(Decimal(action['quantity']) / WAD) if action else '',
            'quote_price_usd': _num(Decimal(action['price']) / WAD) if action and action.get('price') else '',
            'usd': _num(usd), 'fee_usd': _fee_usd(fees.get((batch.tx_hash or '').lower()), side, usd),
            'tx_hash': batch.tx_hash, 'block_number': batch.block_number or '',
            '_at': batch.created_at,
        })
    capped = len(batches) > limit
    if _includes_smart(user, account):
        smart = _smart_rows(user, 'stock_', limit)
        capped = capped or len(smart) > limit
        for t in smart[:limit]:
            rows.append({
                'trade_id': f'smart-{t.id}', 'account': 'smart',
                'executed_at': _time(t.traded_at), 'side': 'buy' if t.kind.endswith('_buy') else 'sell',
                'ticker': _stock_ticker(t.symbol), 'symbol': t.symbol, 'shares': _num(t.units),
                'quote_price_usd': '', 'usd': _num(t.usd), 'fee_usd': '',
                'tx_hash': t.event.tx_hash, 'block_number': t.block_number, '_at': t.traded_at,
            })
    return _newest(rows, limit, capped)


def crypto_rows(user, account, limit: int = MAX_ROWS) -> tuple[list, bool]:
    from blockchain.models import CRYPTO_BATCH_KINDS, SponsoredBatch

    from .crypto_catalog import by_symbol

    wallet = account.bsc_address.lower()
    label = 'business' if account.account_type == 'business' else 'personal'
    batches = list(SponsoredBatch.objects.filter(
        user_bsc_address__in=_wallet_forms(wallet), user_id__in=_signer_ids(user, account),
        kind__in=CRYPTO_BATCH_KINDS, status='confirmed')
        .select_related('crypto_trade', 'unified_transaction').order_by('-created_at', '-id')[:limit + 1])
    fees = _fees_by_tx(b.tx_hash for b in batches)

    def token_fields(symbol):
        token = by_symbol(symbol, include_unlisted=True) if symbol else None
        return {'symbol': symbol or '', 'ticker': token.ticker if token else (symbol or ''),
                'category': token.category if token else ''}

    rows = []
    for batch in batches:
        side = 'buy' if batch.kind == 'crypto_buy' else 'sell'
        trade = getattr(batch, 'crypto_trade', None)
        # CryptoTrade is the exact receipt settlement; a legacy swap without
        # it keeps its history amount and no units (never estimated).
        usd = trade.usd if trade is not None else _settled_usd(batch)
        rows.append({
            'trade_id': f'batch-{batch.id}', 'account': label,
            'executed_at': _time(batch.created_at), 'side': side,
            **token_fields(trade.symbol if trade is not None else None),
            'units': _num(trade.units) if trade is not None else '',
            'usd': _num(usd), 'fee_usd': _fee_usd(fees.get((batch.tx_hash or '').lower()), side, usd),
            'tx_hash': batch.tx_hash, 'block_number': batch.block_number or '',
            '_at': batch.created_at,
        })
    capped = len(batches) > limit
    if _includes_smart(user, account):
        smart = _smart_rows(user, 'crypto_', limit)
        capped = capped or len(smart) > limit
        for t in smart[:limit]:
            rows.append({
                'trade_id': f'smart-{t.id}', 'account': 'smart',
                'executed_at': _time(t.traded_at), 'side': 'buy' if t.kind.endswith('_buy') else 'sell',
                **token_fields(t.symbol), 'units': _num(t.units), 'usd': _num(t.usd), 'fee_usd': '',
                'tx_hash': t.event.tx_hash, 'block_number': t.block_number, '_at': t.traded_at,
            })
    return _newest(rows, limit, capped)


def _newest(rows: list, limit: int, capped: bool) -> tuple[list, bool]:
    rows.sort(key=lambda r: (r['_at'], r['trade_id']), reverse=True)
    capped = capped or len(rows) > limit
    rows = rows[:limit]
    for r in rows:
        r.pop('_at')
    return rows, capped


def build(user, account, product: str, limit: int | None = None) -> dict:
    limit = limit or MAX_ROWS
    if product == 'futuros':
        rows, capped = futuros_rows(user, account.bsc_address, limit)
        columns = FUTUROS_COLUMNS
    elif product == 'stocks':
        rows, capped = stock_rows(user, account, limit)
        columns = STOCK_COLUMNS
    elif product == 'crypto':
        rows, capped = crypto_rows(user, account, limit)
        columns = CRYPTO_COLUMNS
    else:
        raise ExportRefused('bad_product')
    return {
        'filename': f'confio_{product}_trades_{timezone.now():%Y%m%d}.csv',
        'content_type': 'text/csv; charset=utf-8',
        'csv': render_csv(columns, rows),
        'row_count': len(rows),
        'capped': capped,
    }


# ── GraphQL ──────────────────────────────────────────────────────────────

class TradeHistoryCsvType(graphene.ObjectType):
    success = graphene.Boolean(required=True)
    error = graphene.String(description='auth_required | bad_product | account_not_supported | personal_only | '
                                        'owner_only | no_wallet | unavailable')
    message = graphene.String(description='Spanish, for the member')
    filename = graphene.String()
    content_type = graphene.String()
    csv = graphene.String(description='UTF-8 CSV text with a header row, newest first')
    row_count = graphene.Int()
    capped = graphene.Boolean(description=f'True: only the newest {MAX_ROWS} trades are in the file')


class Query(graphene.ObjectType):
    trade_history_csv = graphene.Field(
        TradeHistoryCsvType, product=graphene.String(required=True, description='futuros | stocks | crypto'),
        description="The JWT account's own confirmed trades of one product, as CSV")

    def resolve_trade_history_csv(self, info, product):
        product = (product or '').strip().lower()
        try:
            if product not in PRODUCTS:
                raise ExportRefused('bad_product')
            user, account = resolve_account(info, product)
            return TradeHistoryCsvType(success=True, **build(user, account, product))
        except ExportRefused as exc:
            return TradeHistoryCsvType(success=False, error=exc.code, message=MESSAGES[exc.code])
        except Exception:  # noqa: BLE001
            logger.exception('trade history export failed (%s)', product)
            return TradeHistoryCsvType(success=False, error='unavailable', message=MESSAGES['unavailable'])
