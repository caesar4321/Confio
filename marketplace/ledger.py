"""UnifiedTransactionTable mirror for Comprar orders: history and "Tu mes".

One order writes at most two rows, keyed by payment_reference_id
('comprar:<order pk>:<leg>'):

  buy     buyer → escrow, once the deposit is mirrored (funded or later)
  sale    escrow → store owner, the merchant's net (amount − fee) on release
  refund  escrow → buyer, the full amount on refund

Each row names only the party it belongs to (buy: sender_user = buyer; sale:
counterparty_user = store owner; refund: counterparty_user = buyer), so a
row never lands in the other party's history: money held in escrow is
nobody's income yet. Written from sync_order, the only writer of money
states; failures are logged and never undo the sync.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

REF_PREFIX = 'comprar:'
# Sender name on escrow payouts: "Recibido de Comprar".
ESCROW_NAME = 'Comprar'
# The app keys on this prefix (utils/marketplaceMovement.ts): no resend, no
# send-row lookup, since neither party is a person to pay back.
DESCRIPTION_PREFIX = 'Comprar: '
HEAL_WINDOW_DAYS = 14


def reference(order_pk: int, leg: str) -> str:
    return f'{REF_PREFIX}{order_pk}:{leg}'


def parse_reference(value) -> tuple[int, str] | None:
    """(order pk, leg) for a Comprar ledger reference, else None."""
    value = str(value or '')
    if not value.startswith(REF_PREFIX):
        return None
    pk, _, leg = value[len(REF_PREFIX):].partition(':')
    if not pk.isdigit() or leg not in ('buy', 'sale', 'refund'):
        return None
    return int(pk), leg


def _name(account) -> str:
    try:
        return account.display_name or ''
    except Exception:  # noqa: BLE001 — a name must never block the ledger
        return ''


def _business(account):
    """The Business behind a business account (its history scope), else None."""
    return account.business if account.account_type == 'business' and account.business_id else None


def _amount(value: Decimal) -> str:
    # Exact token units (a $1.01 order pays the merchant 0.9292): display
    # and Tu mes round to cents on their own.
    return format(Decimal(value).normalize(), 'f')


def sync_order_ledger(order) -> None:
    """Create/update this order's ledger rows from its mirrored status.
    Never raises (savepoint-wrapped: safe inside sync_order's transaction)."""
    if order.status not in ('funded', 'shipped', 'disputed', 'released', 'refunded'):
        return
    try:
        with transaction.atomic():
            _write(order)
    except Exception:  # noqa: BLE001 — history must never reverse settlement
        logger.exception('[COMPRAR] ledger mirror failed for order %s', order.pk)


def sync_locked(order_pk: int) -> None:
    """sync_order_ledger under the order's row lock, the lock sync_order
    holds: writers outside sync_order (backfill, heal) never race it into
    writing the same leg twice."""
    from .models import Order
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(pk=order_pk).first()
        if order is not None:
            sync_order_ledger(order)


def heal_missing(limit: int = 100) -> int:
    """Re-mirror recently settled orders whose rows are missing or stale: a
    mirror that failed as the order settled, or failed again when the exact
    settlement time arrived (the keeper stops syncing settled orders, so
    nothing else would retry). Returns how many were re-mirrored."""
    from users.models_unified import UnifiedTransactionTable as U
    from .models import Order

    # Recent settlements only: a gap is fresh; older orders are the backfill
    # command's job. Keeps this per-keeper-run scan small.
    since = timezone.now() - timedelta(days=HEAL_WINDOW_DAYS)
    orders = list(Order.objects.filter(
        Q(settled_at__gte=since) | Q(settled_at__isnull=True, updated_at__gte=since),
        status__in=('released', 'refunded')).values_list('pk', 'status', 'settled_at'))
    if not orders:
        return 0
    refs = [reference(pk, leg) for pk, _, _ in orders for leg in ('buy', 'sale', 'refund')]
    dates = dict(U.objects.filter(transaction_type='send', payment_reference_id__in=refs)
                 .values_list('payment_reference_id', 'transaction_date'))
    healed = 0
    for pk, status, settled_at in orders:
        leg = reference(pk, 'sale' if status == 'released' else 'refund')
        stale = (reference(pk, 'buy') not in dates or leg not in dates
                 or (settled_at is not None and dates[leg] != settled_at))
        if stale and healed < limit:
            sync_locked(pk)
            healed += 1
    return healed


def _upsert(ref: str, defaults: dict) -> None:
    from users.models_unified import UnifiedTransactionTable as U
    row, _ = U.objects.update_or_create(
        transaction_type='send', payment_reference_id=ref, defaults=defaults)
    # History orders by created_at: a row written late (backfill, a retried
    # mirror, a settlement time found after the fact) must sit at the moment
    # the money moved, so it follows transaction_date on every write.
    if row.created_at != defaults['transaction_date']:
        U.objects.filter(pk=row.pk).update(created_at=defaults['transaction_date'])


def _write(order) -> None:
    from .escrow import escrow_address

    escrow = escrow_address()
    store = order.store
    buyer_account = order.buyer_account
    seller_account = store.owner_account
    title = order.product_title
    funded_at = order.funded_at or order.created_at

    _upsert(
        reference(order.pk, 'buy'),
        {
            'amount': _amount(order.amount_usd),
            'fee_amount': '',
            'token_type': 'CUSD_BSC',
            'amount_denomination': 'TOKEN_UNITS',
            'status': 'CONFIRMED',
            'transaction_hash': order.deposit_tx_hash or '',
            'error_message': '',
            'sender_user': order.buyer,
            'sender_business': _business(buyer_account),
            'sender_type': 'business' if _business(buyer_account) else 'user',
            'sender_display_name': _name(buyer_account),
            'sender_phone': '',
            'sender_address': order.buyer_address,
            # The store is named, never linked: its owner must not see the
            # buyer's deposit as money received (it sits in escrow).
            'counterparty_user': None,
            'counterparty_business': None,
            # 'business', with a blank display address, keeps clients from
            # labelling the escrow contract an unknown external wallet.
            'counterparty_type': 'business',
            'counterparty_display_name': store.name,
            'counterparty_phone': None,
            'counterparty_address': '',
            'description': f'{DESCRIPTION_PREFIX}{title}',
            'from_address': order.buyer_address,
            'to_address': escrow,
            'transaction_date': funded_at,
            'deleted_at': None,
        },
    )

    if order.status not in ('released', 'refunded'):
        return
    settled_at = order.settled_at or timezone.now()
    released = order.status == 'released'
    if released:
        leg, owner, account, to = 'sale', store.owner, seller_account, order.merchant_address
        amount = Decimal(order.amount_usd) - order.fee_usd
        description = f'{DESCRIPTION_PREFIX}venta de {title}'
    else:
        leg, owner, account, to = 'refund', order.buyer, buyer_account, order.buyer_address
        amount = Decimal(order.amount_usd)
        description = f'{DESCRIPTION_PREFIX}reembolso de {title}'
    _upsert(
        reference(order.pk, leg),
        {
            'amount': _amount(amount),
            'fee_amount': '',
            'token_type': 'CUSD_BSC',
            'amount_denomination': 'TOKEN_UNITS',
            'status': 'CONFIRMED',
            # Unknown: anyone may settle on chain, so last_tx_hash (our own
            # last broadcast) can name a ship/dispute tx instead.
            'transaction_hash': '',
            'error_message': '',
            'sender_user': None,
            'sender_business': None,
            'sender_type': 'business',
            'sender_display_name': ESCROW_NAME,
            'sender_phone': '',
            'sender_address': '',
            'counterparty_user': owner,
            'counterparty_business': _business(account),
            'counterparty_type': 'business' if _business(account) else 'user',
            'counterparty_display_name': _name(account),
            'counterparty_phone': None,
            'counterparty_address': to,
            'description': description,
            'from_address': escrow,
            'to_address': to,
            'transaction_date': settled_at,
            'deleted_at': None,
        },
    )
