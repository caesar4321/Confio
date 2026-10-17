"""Comunidad posts made from a member's own money movements.

After a stock trade, a top-up, a withdrawal, a send between Confío users
or a Pay payment,
the app offers a ready-made post. Nothing is ever published without the
member tapping "Compartir": the snapshot below is only the template.

What a post shows is frozen at share time in ``ContentItem.metadata['activity']``:
the exact amount (unless the member hid it) and, for a stock sale, the
realized profit or loss. A stock purchase also shows how the position is
doing *now*, computed at read time from Ondo's live price, until the member
sells out of it; then it freezes at the sale price.

Time is the one thing never shown precisely: only the activity's date, read
as "Hoy" / "Ayer" / "Esta semana". An exact amount plus an exact minute
would point at one transaction on BscScan.

Never shareable: $CONFIO (presale, rewards, CONFIO sends or payments), raw
USDT deposits and withdrawals to outside wallets, payroll, conversions. A Pay
post names a business merchant, never a personal one.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

STOCK_BUY = 'stock_buy'
STOCK_SELL = 'stock_sell'
TOP_UP = 'top_up'
WITHDRAW = 'withdraw'
SEND = 'send'
RECEIVE = 'receive'
PAY = 'pay'
KINDS = (STOCK_BUY, STOCK_SELL, TOP_UP, WITHDRAW, SEND, RECEIVE, PAY)
# What a success screen asks for: the newest unshared activity of its group.
GROUPS = {
    'stock': (STOCK_BUY, STOCK_SELL),
    'ramp': (TOP_UP, WITHDRAW),
    'send': (SEND,),
    'receive': (RECEIVE,),
    'pay': (PAY,),
}
# How far back a success screen's "latest" lookup reaches.
RECENT_WINDOW = timedelta(hours=2)
# Older activity can still be shared from its receipt, within reason.
SHAREABLE_FOR = timedelta(days=30)
# Dates are the member's day, not UTC's; La Paz (UTC-4) sits in the middle
# of Confío's countries.
DISPLAY_TZ = ZoneInfo('America/La_Paz')
SEND_TOKENS = {'CUSD', 'CUSD_PLUS', 'USDC', 'USDT'}
UNITS_TOLERANCE = Decimal('0.000001')
NOTE_MAX_CHARS = 500


class ActivityShareError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


NOT_SHAREABLE = 'Esta actividad no se puede compartir.'
ALREADY_SHARED = 'Ya compartiste esta actividad.'


def _dec(value) -> Decimal | None:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d.is_finite() else None


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format(value.quantize(Decimal('0.01')), 'f')


def _date(dt) -> str | None:
    return dt.astimezone(DISPLAY_TZ).date().isoformat() if dt else None


def _minutes(start, end) -> int | None:
    if not start or not end or end < start:
        return None
    return max(int((end - start).total_seconds() // 60), 1)


# ── Snapshots ────────────────────────────────────────────────────────────────

@dataclass
class Snapshot:
    kind: str
    data: dict


def snapshot_for(row, user) -> Snapshot | None:
    """The shareable view of one of this member's own unified rows, or None
    when it is not theirs, not final, or not a shareable kind."""
    if row is None or row.deleted_at is not None or row.status != 'CONFIRMED':
        return None
    try:
        if row.sponsored_batch_id:
            return _stock_snapshot(row, user)
        if row.ramp_transaction_id:
            return _ramp_snapshot(row, user)
        if row.local_money_flow_id:
            return _local_transfer_snapshot(row, user)
        if row.send_transaction_id:
            return _send_snapshot(row, user)
        if row.payment_transaction_id:
            return _pay_snapshot(row.payment_transaction, row.amount, user)
    except Exception:  # noqa: BLE001 — an unreadable row is simply not shareable
        logger.exception('activity share: could not read unified row %s', row.id)
    return None


def _personal_account(user, bsc_address):
    from users.models import Account

    account = Account.objects.filter(bsc_address__iexact=bsc_address, deleted_at__isnull=True).first()
    if account is None or account.user_id != user.id or account.business_id is not None:
        return None
    return account


def _ticker_and_name(symbol: str) -> tuple[str, str]:
    try:
        from cusd_plus import gm_api

        for item in gm_api.all_market():
            if (item.get('primaryMarket') or {}).get('symbol') == symbol:
                um = item.get('underlyingMarket') or {}
                ticker = um.get('ticker') or symbol.removesuffix('on')
                return ticker, um.get('name') or ticker
    except Exception:  # noqa: BLE001 — a name is cosmetic
        logger.warning('activity share: no market metadata for %s', symbol)
    ticker = symbol.removesuffix('on')
    return ticker, ticker


def _wallet_trades(bsc_address):
    """[(batch_id, Trade)] for every confirmed Confío stock trade of the
    wallet, oldest first."""
    from blockchain.models import SponsoredBatch
    from cusd_plus.stock_month import _decode_trades

    batches = list(
        SponsoredBatch.objects.filter(
            user_bsc_address__iexact=bsc_address, kind__in=(STOCK_BUY, STOCK_SELL), status='confirmed')
        .select_related('unified_transaction').order_by('created_at', 'id')
    )
    return list(zip([b.id for b in batches], _decode_trades(batches)))


def _realized(trades, batch_id) -> tuple[Decimal, Decimal] | None:
    """(average cost of the units sold, proceeds) for the sale `batch_id`,
    by average cost over the wallet's own Confío trades. None when the
    ledger can't explain the position: an unreadable trade, a missing
    settlement, or units that arrived from outside Confío."""
    target = next((t for bid, t in trades if bid == batch_id), None)
    if target is None or target.usd is None or target.units <= 0:
        return None
    units = Decimal('0')
    cost = Decimal('0')
    for bid, t in trades:
        if t.symbol.startswith('?'):
            return None
        if t.symbol != target.symbol:
            continue
        if bid == batch_id:
            if units <= 0 or units < t.units * (1 - UNITS_TOLERANCE):
                return None
            return cost * min(t.units / units, Decimal('1')), t.usd
        if t.usd is None:
            return None
        if t.kind == STOCK_BUY:
            units += t.units
            cost += t.usd
        else:
            # Selling more than the ledger holds means units came from
            # outside Confío: every later cost basis would be invented.
            if units <= 0 or units < t.units * (1 - UNITS_TOLERANCE):
                return None
            sold = min(t.units / units, Decimal('1'))
            cost -= cost * sold
            units = max(units - t.units, Decimal('0'))
    return None


def _stock_snapshot(row, user) -> Snapshot | None:
    batch = row.sponsored_batch
    if batch.kind not in (STOCK_BUY, STOCK_SELL) or batch.status != 'confirmed':
        return None
    if _personal_account(user, batch.user_bsc_address) is None:
        return None
    trades = _wallet_trades(batch.user_bsc_address)
    trade = next((t for bid, t in trades if bid == batch.id), None)
    if trade is None or trade.symbol.startswith('?') or trade.units <= 0:
        return None
    usd = _dec(row.amount)
    if usd is None or usd <= 0:
        return None
    ticker, name = _ticker_and_name(trade.symbol)
    data = {
        'kind': batch.kind,
        'symbol': trade.symbol,
        'ticker': ticker,
        'name': name,
        'units': format(trade.units.normalize(), 'f'),
        'amount_usd': _money(usd),
        'price_usd': format((usd / trade.units).quantize(Decimal('0.0001')), 'f'),
        'date': _date(batch.created_at),
        # Server-side only, for live P&L; never serialized.
        'wallet': batch.user_bsc_address.lower(),
        'batch_id': batch.id,
    }
    if batch.kind == STOCK_SELL:
        realized = _realized(trades, batch.id)
        if realized is not None:
            basis, proceeds = realized
            pnl = proceeds - basis
            data['pnl_usd'] = _money(pnl)
            data['pnl_pct'] = format((pnl / basis * 100).quantize(Decimal('0.01')), 'f') if basis > 0 else None
    return Snapshot(batch.kind, data)


def _ramp_rail(code: str) -> str:
    return 'QR' if 'QR' in (code or '').upper() else 'transferencia'


def _ramp_snapshot(row, user) -> Snapshot | None:
    ramp = row.ramp_transaction
    if ramp.status != 'COMPLETED' or ramp.actor_user_id != user.id or ramp.actor_business_id:
        return None
    kind = TOP_UP if ramp.direction == 'on_ramp' else WITHDRAW
    usd = _dec(row.amount)
    return Snapshot(kind, {
        'kind': kind,
        'amount_usd': _money(usd),
        'rail': _ramp_rail((ramp.metadata or {}).get('payment_method_code', '')),
        'country': (ramp.country_code or '').upper()[:2] or None,
        'minutes': _minutes(ramp.created_at, ramp.completed_at),
        'date': _date(ramp.completed_at or ramp.created_at),
    })


LOCAL_RAILS = {
    'qr': 'QR',
    'breb_key': 'Bre-B',
    'pix_key': 'Pix',
    'bank_account': 'transferencia',
    'bank_details': 'transferencia',
}


def _country2(value) -> str | None:
    try:
        from payment_accounts.infinia_fees import iso_alpha2

        return iso_alpha2(value)
    except Exception:  # noqa: BLE001
        return None


def _local_transfer_snapshot(row, user) -> Snapshot | None:
    from payment_accounts.models import PayoutDestination

    flow = row.local_money_flow
    journey = getattr(flow, 'infinia_journey', None)
    if journey is None or journey.stage != 'completed':
        return None
    owner = journey.confio_account
    if owner.user_id != user.id or owner.account_type == 'business':
        return None
    if journey.direction == 'to_bank':
        kind = WITHDRAW
        internal_id = (journey.destination_snapshot or {}).get('destination_internal_id')
        destination = PayoutDestination.objects.filter(internal_id=internal_id).first() if internal_id else None
        rail = LOCAL_RAILS.get(destination.kind if destination else '', 'transferencia')
    else:
        kind = TOP_UP
        payin = (journey.local_account.payin_rail or '').strip()
        rail = 'QR' if 'QR' in payin.upper() else (payin or 'transferencia')
    return Snapshot(kind, {
        'kind': kind,
        'amount_usd': _money(_dec(row.amount)),
        'rail': rail,
        'country': _country2(journey.local_account.country),
        'minutes': _minutes(flow.created_at, flow.completed_at),
        'date': _date(flow.completed_at or flow.created_at),
    })


def _send_snapshot(row, user) -> Snapshot | None:
    send = row.send_transaction
    if send.status != 'CONFIRMED' or (send.token_type or '').upper() not in SEND_TOKENS:
        return None
    # Between two Confío people only: no businesses, no outside wallets.
    if not send.sender_user_id or not send.recipient_user_id:
        return None
    if send.sender_business_id or send.recipient_business_id:
        return None
    if send.sender_user_id == send.recipient_user_id:
        return None
    if send.sender_user_id == user.id:
        kind = SEND
    elif send.recipient_user_id == user.id:
        kind = RECEIVE
    else:
        return None
    # The counterparty is never named: it is a third person's activity.
    return Snapshot(kind, {
        'kind': kind,
        'amount_usd': _money(_dec(row.amount)),
        'date': _date(send.created_at),
    })


def _pay_snapshot(payment, amount, user, *, final=True) -> Snapshot | None:
    """A Pay payment the member made. A business merchant is named (that
    is promotion for them); a personal merchant never is: it is a private
    person. $CONFIO payments and payments made as a business are not
    shareable."""
    if payment is None or payment.payer_user_id != user.id or payment.payer_business_id:
        return None
    if final and payment.status != 'CONFIRMED':
        return None
    if not final and payment.status == 'FAILED':
        return None
    if (payment.token_type or '').upper() == 'CONFIO':
        return None
    merchant = None
    if payment.merchant_type == 'business' and payment.merchant_business_id:
        merchant = (payment.merchant_business.name or '').strip()[:60] or None
    return Snapshot(PAY, {
        'kind': PAY,
        'amount_usd': _money(_dec(amount)),
        'merchant': merchant,
        'date': _date(payment.created_at),
    })


# ── Finding and sharing ──────────────────────────────────────────────────────

def _member_rows(user):
    from django.db.models import Q

    from users.models_unified import UnifiedTransactionTable

    return UnifiedTransactionTable.objects.filter(
        Q(sender_user=user) | Q(counterparty_user=user),
        deleted_at__isnull=True,
        status='CONFIRMED',
    ).select_related(
        'sponsored_batch', 'ramp_transaction', 'send_transaction', 'payment_transaction__merchant_business',
        'local_money_flow__infinia_journey__local_account',
        'local_money_flow__infinia_journey__confio_account',
    )


def is_shared(row_id, user) -> bool:
    """Shared by this member already, with the post still pending or live.
    The other side of a send shares its own view independently."""
    from .models import CommunityActivityShare, CommunityReviewStatus

    return CommunityActivityShare.objects.filter(
        unified_transaction_id=row_id,
        user=user,
        content_item__community_review__status__in=[
            CommunityReviewStatus.PENDING, CommunityReviewStatus.APPROVED],
    ).exists()


def _reference_filter(reference: str):
    """The rows a status screen's own id points at: a ramp order id, a
    local-transfer journey reference, a send's id, or a transaction hash."""
    import uuid

    from django.db.models import Q

    reference = (reference or '').strip()[:128]
    if not reference:
        return None
    match = (
        Q(ramp_transaction__provider_order_id=reference)
        | Q(ramp_transaction__external_id=reference)
        | Q(send_transaction__internal_id=reference)
        | Q(payment_transaction__internal_id=reference)
    )
    if reference.lower().startswith('0x'):
        match |= (Q(sponsored_batch__tx_hash__iexact=reference)
                  | Q(send_transaction__transaction_hash__iexact=reference)
                  | Q(payment_transaction__transaction_hash__iexact=reference))
    try:
        match |= Q(local_money_flow__infinia_journey__internal_id=uuid.UUID(reference))
    except ValueError:
        pass
    return match


def has_other_share(item, *, include_pending=False) -> bool:
    """Another post of the same member already carries this activity: live,
    or (include_pending) still in review. Guards every path that can put an
    activity post up: a late AI approval, staff re-review, staff restore."""
    from .models import CommunityActivityShare, CommunityReviewStatus

    share = CommunityActivityShare.objects.filter(content_item_id=item.id).first()
    if share is None:
        return False
    statuses = [CommunityReviewStatus.APPROVED]
    if include_pending:
        statuses.append(CommunityReviewStatus.PENDING)
    return CommunityActivityShare.objects.filter(
        unified_transaction_id=share.unified_transaction_id,
        user_id=share.user_id,
        content_item__community_review__status__in=statuses,
    ).exclude(content_item_id=item.id).exists()


def find_activity(user, *, unified_id=None, group=None, reference=None):
    """(row, snapshot) for one of this member's own activities that can be
    shared now: a specific one from its receipt or status screen, or the
    newest unshared one of a group for a success screen. None otherwise."""
    rows = _member_rows(user).filter(created_at__gte=timezone.now() - SHAREABLE_FOR)
    if reference:
        match = _reference_filter(reference)
        row = rows.filter(match).order_by('-id').first() if match is not None else None
        snap = snapshot_for(row, user)
        kinds = GROUPS.get(group or '')
        ok = snap and (not kinds or snap.kind in kinds) and not is_shared(row.id, user)
        return (row, snap) if ok else None
    if unified_id is not None:
        try:
            unified_id = int(unified_id)
        except (TypeError, ValueError):
            return None
        row = rows.filter(id=unified_id).first()
        snap = snapshot_for(row, user)
        return (row, snap) if snap and not is_shared(row.id, user) else None
    kinds = GROUPS.get(group or '')
    if not kinds:
        return None
    since = timezone.now() - RECENT_WINDOW
    for row in rows.filter(updated_at__gte=since).order_by('-updated_at', '-id')[:20]:
        snap = snapshot_for(row, user)
        if snap and snap.kind in kinds and not is_shared(row.id, user):
            return row, snap
    return None


def share_activity(user, business, unified_id, note: str = '', show_amount: bool = True):
    """Publish the member's own activity as a Comunidad post, on their tap.
    Without a note the post is only Confío's template and goes up at once;
    a note is reviewed like any other post."""
    from users.models import User

    from . import community
    from .models import (
        CommunityActivityShare,
        CommunityPostReview,
        ContentItem,
        ContentItemType,
        ContentStatus,
        OwnerType,
    )

    note = (note or '').strip()
    if len(note) > NOTE_MAX_CHARS:
        raise ActivityShareError('too_long', f'Tu comentario supera los {NOTE_MAX_CHARS} caracteres.')
    if community.URL_RE.search(note):
        raise ActivityShareError('links', community.LINK_REASON)

    with transaction.atomic():
        # One author at a time, so the same activity can't go up twice.
        User.objects.select_for_update().filter(pk=user.pk).first()
        block = community.posting_block(user, business, activity=True)
        if block:
            raise ActivityShareError(block, community.BLOCK_MESSAGES[block])
        found = find_activity(user, unified_id=unified_id)
        if found is None:
            if _member_rows(user).filter(id=unified_id).exists() and is_shared(unified_id, user):
                raise ActivityShareError('already_shared', ALREADY_SHARED)
            raise ActivityShareError('not_shareable', NOT_SHAREABLE)
        row, snap = found
        activity = {**snap.data, 'show_amount': bool(show_amount)}
        item = ContentItem.objects.create(
            channel=community.community_channel(),
            author_user=user,
            owner_type=OwnerType.USER,
            owner_user=user,
            item_type=ContentItemType.TEXT,
            status=ContentStatus.DRAFT,
            body=note,
            tag=community.COMMUNITY_TAG,
            send_push=False,
            send_in_app=False,
            metadata={'community': True, 'activity': activity},
        )
        CommunityActivityShare.objects.create(
            content_item=item, unified_transaction=row, user=user, kind=snap.kind)
        review = CommunityPostReview.objects.create(content_item=item)
        review_id = review.id
        consume_intents_for(row, user, item)
        if note:
            transaction.on_commit(lambda: community.enqueue_review(review_id))
        else:
            transaction.on_commit(lambda: approve_template(review_id))
    return item


TEMPLATE_VERDICT = {'decision': 'approve', 'category': 'ok', 'confidence': 1.0, 'reason': '',
                    'model': 'activity-template'}


def approve_template(review_id: int) -> str:
    """A post that is only Confío's own template has nothing for the AI to
    read. It still goes through _finalize, so a ban or a revoked KYC since
    the tap keeps it from going up."""
    from . import community
    from .models import CommunityPostReview, CommunityReviewStatus

    with transaction.atomic():
        review = CommunityPostReview.objects.select_for_update().filter(id=review_id).first()
        if review is None or review.status != CommunityReviewStatus.PENDING:
            return review.status if review else 'missing'
        claim = community.new_claim()
        review.claim_token = claim
        review.attempts += 1
        review.save(update_fields=['attempts', 'claim_token', 'updated_at'])
    return community._finalize(review_id, claim, dict(TEMPLATE_VERDICT), escalated=False,
                               verdicts=[dict(TEMPLATE_VERDICT)])


# ── Reading ──────────────────────────────────────────────────────────────────

def _price_map() -> dict:
    try:
        from cusd_plus import gm_api

        return {
            (item.get('primaryMarket') or {}).get('symbol'): _dec((item.get('primaryMarket') or {}).get('price'))
            for item in gm_api.all_market()
        }
    except Exception:  # noqa: BLE001 — no live price: the post shows no live P&L
        logger.warning('activity share: live prices unavailable')
        return {}


def _position_state(activity, trades_by_wallet) -> tuple[str, Decimal | None]:
    """How the purchase behind a post stands now:
    ('closed', sale price) once a later sale emptied the position, even if
    the member bought the stock again afterwards; ('open', None) while it is
    still held; ('unknown', None) when the history can't be read, which
    shows no P&L rather than a live number that may not apply."""
    wallet = activity.get('wallet')
    if not wallet:
        return 'unknown', None
    if wallet not in trades_by_wallet:
        try:
            trades_by_wallet[wallet] = _wallet_trades(wallet)
        except Exception:  # noqa: BLE001
            logger.warning('activity share: could not read trades of a wallet')
            trades_by_wallet[wallet] = None
    trades = trades_by_wallet[wallet]
    if not trades:
        return 'unknown', None
    symbol = activity['symbol']
    found = False
    units = Decimal('0')
    for bid, t in trades:
        if t.symbol.startswith('?'):
            return 'unknown', None
        if t.symbol != symbol:
            continue
        units += t.units if t.kind == STOCK_BUY else -t.units
        if units < 0 and -units > t.units * UNITS_TOLERANCE:
            # Sold more than Confío's ledger holds: units came from outside.
            return 'unknown', None
        if bid == activity.get('batch_id'):
            found = True
            peak = units
            continue
        if found and t.kind == STOCK_SELL and units <= peak * UNITS_TOLERANCE:
            if not t.usd or t.units <= 0:
                return 'unknown', None
            return 'closed', t.usd / t.units
    if not found:
        return 'unknown', None
    return ('open', None) if units > 0 else ('unknown', None)


def activity_payloads(items) -> dict:
    """{content_item_id: public activity dict} for the activity posts among
    `items`. Only whitelisted fields leave the server; live P&L is computed
    here for purchases."""
    prices = None
    trades_by_wallet: dict = {}
    out = {}
    for item in items:
        activity = (item.metadata or {}).get('activity')
        if not activity or activity.get('kind') not in KINDS:
            continue
        show_amount = activity.get('show_amount', True)
        public = {
            'kind': activity['kind'],
            'date': activity.get('date'),
            'amount_usd': activity.get('amount_usd') if show_amount else None,
            'ticker': activity.get('ticker'),
            'name': activity.get('name'),
            'rail': activity.get('rail'),
            'country': activity.get('country'),
            'minutes': activity.get('minutes'),
            'merchant': activity.get('merchant'),
            'pnl_usd': None,
            'pnl_pct': None,
            'position': None,
        }
        if activity['kind'] == STOCK_SELL:
            public['pnl_pct'] = activity.get('pnl_pct')
            public['pnl_usd'] = activity.get('pnl_usd') if show_amount else None
        elif activity['kind'] == STOCK_BUY:
            buy_price = _dec(activity.get('price_usd'))
            state, close_price = _position_state(activity, trades_by_wallet)
            price = close_price
            if state == 'open':
                if prices is None:
                    prices = _price_map()
                price = prices.get(activity.get('symbol'))
            public['position'] = state if state != 'unknown' else None
            if state != 'unknown' and buy_price and price:
                pct = (price / buy_price - 1) * 100
                public['pnl_pct'] = format(pct.quantize(Decimal('0.01')), 'f')
                amount = _dec(activity.get('amount_usd'))
                if show_amount and amount is not None:
                    public['pnl_usd'] = _money(amount * pct / 100)
        out[item.id] = public
    return out


KIND_VERBS = {
    STOCK_BUY: 'Compró',
    STOCK_SELL: 'Vendió',
    TOP_UP: 'Recargó',
    WITHDRAW: 'Retiró',
    SEND: 'Envió dinero a otro usuario de Confío',
    RECEIVE: 'Recibió dinero de otro usuario de Confío',
    PAY: 'Pagó con QR',
}


def activity_headline(activity: dict) -> str:
    """One line in the third person, for notifications and old app versions
    that only render a post's text: "Compró NVDA · US$5.00"."""
    kind = activity.get('kind')
    verb = KIND_VERBS.get(kind, 'Compartió una actividad')
    amount = activity.get('amount_usd') if activity.get('show_amount', True) else None
    money = f'US${amount}' if amount else None
    if kind in (STOCK_BUY, STOCK_SELL):
        parts = [f"{verb} {activity.get('ticker') or ''}".strip()]
        if money:
            parts.append(money)
        if kind == STOCK_SELL and activity.get('pnl_pct') is not None:
            pct = _dec(activity['pnl_pct'])
            if pct is not None:
                parts.append(f"{'+' if pct >= 0 else ''}{pct}%")
        return ' · '.join(parts)
    if kind in (TOP_UP, WITHDRAW):
        parts = [f'{verb} {money}' if money else verb]
        if activity.get('rail'):
            parts.append(f"por {activity['rail']}")
        if activity.get('minutes'):
            parts.append(f"en {activity['minutes']} min")
        return ' · '.join(parts)
    if kind == PAY and activity.get('merchant'):
        verb = f"Pagó en {activity['merchant']}"
    return f'{verb} · {money}' if money else verb


def coarse_time_label(date_iso: str | None) -> str:
    """"Hoy", "Ayer", "Esta semana", else the date: never the minute."""
    if not date_iso:
        return ''
    from datetime import date

    try:
        day = date.fromisoformat(date_iso)
    except ValueError:
        return ''
    today = timezone.now().astimezone(DISPLAY_TZ).date()
    delta = (today - day).days
    if delta <= 0:
        return 'Hoy'
    if delta == 1:
        return 'Ayer'
    if delta < 7:
        return 'Esta semana'
    months = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
    label = f'{day.day} {months[day.month - 1]}'
    return label if day.year == today.year else f'{label} {day.year}'


def coarse_published_at(item):
    """The post's moment as readers get it: midnight of its day (in the
    display zone) for activity posts, so no exact minute leaves the server."""
    from datetime import datetime, time

    moment = item.published_at or item.created_at
    if not moment or not (item.metadata or {}).get('activity'):
        return moment
    day = moment.astimezone(DISPLAY_TZ).date()
    return datetime.combine(day, time.min, tzinfo=DISPLAY_TZ)


def display_body(item) -> str:
    """The post's text for anything that renders text only (old app builds,
    the author's own list): the template headline, then the member's note."""
    activity = (item.metadata or {}).get('activity')
    if not activity:
        return item.body or ''
    headline = activity_headline(activity)
    return f'{headline}\n\n{item.body}' if item.body else headline


def public_activity(raw: dict) -> dict:
    """The public view of one snapshot that is not a post yet (the share
    sheet's preview)."""
    from types import SimpleNamespace

    return activity_payloads([SimpleNamespace(id=0, metadata={'activity': raw})])[0]


# ── Sharing at once, before the activity is final ────────────────────────────
#
# Success screens show success when the trade is mined or the order placed,
# seconds (a trade) to hours (a top-up) before the ledger row is final. The
# share sheet opens right then with a preview built from the source record;
# a tap on "Compartir" either publishes at once (already final) or leaves an
# intent that resolve_share_intents publishes the moment it settles. What is
# published always comes from the final ledger row, never from the preview.

INTENT_WINDOWS = {
    'stock': timedelta(hours=2),
    'send': timedelta(hours=2),
    'pay': timedelta(hours=2),
    'ramp': timedelta(hours=48),
}
PREVIEW_ONLY_KEYS = ('wallet', 'batch_id')


def _stock_preview(user, reference):
    from blockchain.models import SponsoredBatch
    from cusd_plus.sponsor_7702 import _decode_stock_call
    from cusd_plus.stock_month import Trade

    if not (reference or '').lower().startswith('0x'):
        return None
    batch = SponsoredBatch.objects.filter(
        tx_hash__iexact=reference, kind__in=(STOCK_BUY, STOCK_SELL),
        status__in=('signed', 'sent', 'confirmed')).first()
    if batch is None or _personal_account(user, batch.user_bsc_address) is None:
        return None
    try:
        actions = [a for c in json.loads(batch.calls_json or '[]')
                   if (a := _decode_stock_call(c, historical=True)) is not None]
    except Exception:  # noqa: BLE001
        return None
    if len(actions) != 1 or actions[0]['kind'] != batch.kind:
        return None
    action = actions[0]
    from cusd_plus.stock_month import _symbol_by_address

    symbol = _symbol_by_address().get(action['asset'])
    units = Decimal(action['quantity']) / Decimal(10 ** 18)
    usd = Decimal(int(action['history_amount_wei'])) / Decimal(10 ** 18)
    if not symbol or units <= 0 or usd <= 0:
        return None
    ticker, name = _ticker_and_name(symbol)
    data = {
        'kind': batch.kind, 'symbol': symbol, 'ticker': ticker, 'name': name,
        'units': format(units.normalize(), 'f'), 'amount_usd': _money(usd),
        'price_usd': format((usd / units).quantize(Decimal('0.0001')), 'f'),
        'date': _date(batch.created_at), 'wallet': batch.user_bsc_address.lower(), 'batch_id': batch.id,
    }
    if batch.kind == STOCK_SELL:
        trades = [(bid, t) for bid, t in _wallet_trades(batch.user_bsc_address) if bid != batch.id]
        trades.append((batch.id, Trade(symbol=symbol, kind=STOCK_SELL, units=units, usd=usd, when=batch.created_at)))
        realized = _realized(trades, batch.id)
        if realized is not None:
            basis, proceeds = realized
            data['pnl_usd'] = _money(proceeds - basis)
            data['pnl_pct'] = format(((proceeds - basis) / basis * 100).quantize(Decimal('0.01')), 'f') if basis > 0 else None
    return Snapshot(batch.kind, data)


def _send_preview(user, reference):
    from send.models import SendTransaction

    send = SendTransaction.objects.filter(internal_id=reference).first()
    if send is None or send.status in ('FAILED', 'AML_REVIEW') or send.sender_user_id != user.id:
        return None
    probe = SimpleNamespace(amount=send.amount, send_transaction=SimpleNamespace(
        status='CONFIRMED', token_type=send.token_type, sender_user_id=send.sender_user_id,
        recipient_user_id=send.recipient_user_id, sender_business_id=send.sender_business_id,
        recipient_business_id=send.recipient_business_id, created_at=send.created_at))
    return _send_snapshot(probe, user)


def _ramp_preview(user, reference):
    import uuid

    from payment_accounts.models import InfiniaJourney
    from ramps.models import RampTransaction

    ramp = (RampTransaction.objects.filter(provider_order_id=reference).first()
            or RampTransaction.objects.filter(external_id=reference).first())
    if ramp is not None:
        if ramp.status == 'FAILED' or ramp.actor_user_id != user.id or ramp.actor_business_id:
            return None
        kind = TOP_UP if ramp.direction == 'on_ramp' else WITHDRAW
        # Dollars in or out of the wallet: delivered/sent crypto, estimated
        # until the provider reports the actual.
        amount = ramp.crypto_amount_actual or ramp.crypto_amount_estimated
        return Snapshot(kind, {
            'kind': kind, 'amount_usd': _money(_dec(amount)),
            'rail': _ramp_rail((ramp.metadata or {}).get('payment_method_code', '')),
            'country': (ramp.country_code or '').upper()[:2] or None, 'minutes': None,
            'date': _date(timezone.now()),
        })
    try:
        journey = InfiniaJourney.objects.select_related('local_account', 'confio_account', 'money_flow').filter(
            internal_id=uuid.UUID(str(reference))).first()
    except ValueError:
        journey = None
    if journey is None or journey.stage in ('failed', 'refunded'):
        return None
    if journey.confio_account.user_id != user.id or journey.confio_account.account_type == 'business':
        return None
    kind = WITHDRAW if journey.direction == 'to_bank' else TOP_UP
    amount = journey.money_flow.source_amount if kind == WITHDRAW else None
    return Snapshot(kind, {
        'kind': kind, 'amount_usd': _money(_dec(amount)) if amount is not None else None,
        'rail': 'QR' if 'QR' in (journey.local_account.payin_rail or '').upper() else None,
        'country': _country2(journey.local_account.country), 'minutes': None, 'date': _date(timezone.now()),
    })


def _pay_preview(user, reference):
    from payments.models import PaymentTransaction

    payment = (PaymentTransaction.objects.select_related('merchant_business')
               .filter(internal_id=reference).first())
    return _pay_snapshot(payment, payment.amount if payment else None, user, final=False) if payment else None


PREVIEWERS = {'stock': _stock_preview, 'send': _send_preview, 'ramp': _ramp_preview, 'pay': _pay_preview}


def _row_for_reference(user, reference):
    match = _reference_filter(reference)
    return _member_rows(user).filter(match).order_by('-id').first() if match is not None else None


def references_for_row(row) -> set:
    """Every status-screen id that points at this ledger row."""
    refs = set()
    if row.sponsored_batch_id and row.sponsored_batch.tx_hash:
        refs.add(row.sponsored_batch.tx_hash.lower())
    if row.send_transaction_id:
        refs.add(str(row.send_transaction.internal_id))
        if row.send_transaction.transaction_hash:
            refs.add(row.send_transaction.transaction_hash.lower())
    if row.ramp_transaction_id:
        refs.update(r for r in (row.ramp_transaction.provider_order_id, row.ramp_transaction.external_id) if r)
    if row.payment_transaction_id:
        refs.add(str(row.payment_transaction.internal_id))
        if row.payment_transaction.transaction_hash:
            refs.add(row.payment_transaction.transaction_hash.lower())
    if row.local_money_flow_id:
        journey = getattr(row.local_money_flow, 'infinia_journey', None)
        if journey is not None:
            refs.add(str(journey.internal_id))
    return refs


def consume_intents_for(row, user, content_item):
    """A share of this activity exists: any intent still waiting for it is
    done, so it can never publish a second copy later (e.g. after the
    member deletes the first)."""
    from django.db.models import Q
    from django.db.models.functions import Lower

    from .models import ActivityShareIntent, ActivityShareIntentStatus

    refs = references_for_row(row)
    if not refs:
        return 0
    lowered = {r.lower() for r in refs}
    return (ActivityShareIntent.objects.annotate(ref_lower=Lower('reference'))
            .filter(Q(ref_lower__in=lowered), user=user, status=ActivityShareIntentStatus.PENDING)
            .update(status=ActivityShareIntentStatus.PUBLISHED, content_item=content_item,
                    resolved_at=timezone.now(), last_error='shared directly'))


def preview_activity(user, group, reference):
    """(row or None, snapshot, final) for the member's activity behind a
    success screen: the final ledger view when it has settled, else a
    preview from the source record. None when it isn't theirs, failed, or
    isn't shareable."""
    found = find_activity(user, group=group, reference=reference)
    if found is not None:
        row, snap = found
        return row, snap, True
    previewer = PREVIEWERS.get(group or '')
    if previewer is None or not reference:
        return None
    try:
        snap = previewer(user, reference)
    except Exception:  # noqa: BLE001 — a preview is never worth a crash
        logger.exception('activity share: preview failed for %s', group)
        return None
    if snap is None or snap.kind not in GROUPS.get(group, ()):
        return None
    return None, snap, False


def share_or_schedule(user, business, group, reference, note='', show_amount=True):
    """The member tapped "Compartir" on the sheet. Publish now when the
    activity is final; otherwise record an intent published at settlement.
    Returns ('published', item) or ('scheduled', intent)."""
    from django.db import IntegrityError

    from . import community
    from .models import ActivityShareIntent, ActivityShareIntentStatus

    note = (note or '').strip()
    if len(note) > NOTE_MAX_CHARS:
        raise ActivityShareError('too_long', f'Tu comentario supera los {NOTE_MAX_CHARS} caracteres.')
    if community.URL_RE.search(note):
        raise ActivityShareError('links', community.LINK_REASON)
    block = community.posting_block(user, business, activity=True)
    if block:
        raise ActivityShareError(block, community.BLOCK_MESSAGES[block])
    preview = preview_activity(user, group, reference)
    if preview is None:
        raise ActivityShareError('not_shareable', NOT_SHAREABLE)
    row, _snap, final = preview
    if final:
        return 'published', share_activity(user, business, row.id, note, show_amount)
    with transaction.atomic():
        # The author lock, as share_activity and the resolver take it: a
        # direct share can't publish (and consume intents) between this
        # check and the new intent, leaving one that would publish again.
        from users.models import User

        User.objects.select_for_update().filter(pk=user.pk).first()
        return _schedule_locked(user, group, reference, note, show_amount)


def _schedule_locked(user, group, reference, note, show_amount):
    from django.db import IntegrityError

    from .models import ActivityShareIntent, ActivityShareIntentStatus

    settled = _row_for_reference(user, reference)
    if settled is not None and is_shared(settled.id, user):
        raise ActivityShareError('already_shared', ALREADY_SHARED)
    found = find_activity(user, group=group, reference=reference)
    if found is not None:
        # Settled while we looked: share it now rather than schedule.
        return 'published', share_activity(user, None, found[0].id, note, show_amount)
    try:
        intent, _ = ActivityShareIntent.objects.update_or_create(
            user=user, group=group, reference=reference[:128], status=ActivityShareIntentStatus.PENDING,
            defaults={'note': note, 'show_amount': bool(show_amount),
                      'expires_at': timezone.now() + INTENT_WINDOWS.get(group, timedelta(hours=2))},
        )
    except IntegrityError:
        intent = ActivityShareIntent.objects.get(
            user=user, group=group, reference=reference[:128], status=ActivityShareIntentStatus.PENDING)
    return 'scheduled', intent


def resolve_share_intents(limit: int = 200) -> dict:
    """Publish pending intents whose activity has settled; drop expired ones."""
    from . import community
    from .models import ActivityShareIntent, ActivityShareIntentStatus

    now = timezone.now()
    out = {'published': 0, 'expired': 0, 'failed': 0}
    expired = ActivityShareIntent.objects.filter(status=ActivityShareIntentStatus.PENDING, expires_at__lt=now)
    out['expired'] = expired.update(status=ActivityShareIntentStatus.EXPIRED, resolved_at=now,
                                    last_error='activity did not settle in time')
    # Fewest checks first: intents that keep not settling (a slow top-up)
    # sink, so they never starve newer ones that already have.
    pending = list(ActivityShareIntent.objects.filter(status=ActivityShareIntentStatus.PENDING)
                   .select_related('user').order_by('attempts', 'created_at')[:limit])
    from users.models import User

    for intent in pending:
        with transaction.atomic():
            # The author's row first, the lock share_activity takes: a direct
            # share (user, then this intent via consume_intents_for) and this
            # resolver always lock in the same order.
            User.objects.select_for_update().filter(pk=intent.user_id).first()
            locked = ActivityShareIntent.objects.select_for_update(skip_locked=True).filter(
                id=intent.id, status=ActivityShareIntentStatus.PENDING).first()
            if locked is None:
                continue
            settled = _row_for_reference(locked.user, locked.reference)
            if settled is not None and is_shared(settled.id, locked.user):
                # Shared directly meanwhile: this intent is done.
                from .models import CommunityActivityShare

                existing = CommunityActivityShare.objects.filter(
                    unified_transaction_id=settled.id, user=locked.user).order_by('-id').first()
                locked.status = ActivityShareIntentStatus.PUBLISHED
                locked.content_item_id = existing.content_item_id if existing else None
                locked.last_error = 'shared directly'
                locked.resolved_at = now
                locked.save(update_fields=['status', 'content_item', 'last_error', 'resolved_at'])
                continue
            found = find_activity(locked.user, group=locked.group, reference=locked.reference)
            if found is None:
                # Settled but no longer shareable (failed, refunded) ends it;
                # otherwise it is still settling.
                if preview_activity(locked.user, locked.group, locked.reference) is None:
                    locked.status = ActivityShareIntentStatus.FAILED
                    locked.last_error = 'activity is no longer shareable'
                    locked.resolved_at = now
                    locked.save(update_fields=['status', 'last_error', 'resolved_at'])
                    out['failed'] += 1
                else:
                    locked.attempts += 1
                    locked.save(update_fields=['attempts'])
                continue
            row, _snap = found
            try:
                item = share_activity(locked.user, None, row.id, locked.note, locked.show_amount)
            except ActivityShareError as exc:
                locked.status = ActivityShareIntentStatus.FAILED
                locked.last_error = exc.code[:200]
                locked.resolved_at = now
                locked.save(update_fields=['status', 'last_error', 'resolved_at'])
                out['failed'] += 1
                continue
            locked.status = ActivityShareIntentStatus.PUBLISHED
            locked.content_item = item
            locked.resolved_at = now
            locked.save(update_fields=['status', 'content_item', 'resolved_at'])
            out['published'] += 1
            # The sheet said "se publicará" and stopped following: always tell
            # the member how it went. A template is up now; a note is told
            # when its review finishes, however quickly.
            if locked.note:
                item.metadata = {**(item.metadata or {}), community.NOTIFY_ON_REVIEW: True}
                item.save(update_fields=['metadata', 'updated_at'])
            else:
                review_id = item.community_review.id
                transaction.on_commit(lambda rid=review_id: community.notify_post_reviewed(rid))
    return out
