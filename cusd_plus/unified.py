"""UnifiedTransactionTable mirror for the savings (BSC) conversion rows.

The unified table is the cross-feature ledger behind the app's main
activity feed and the ops one-stop admin. This module mirrors the savings
saga rows of `conversion.Conversion`: one unified row each, linked OneToOne
on the single `conversion` FK, status evolving with the saga.

Sibling of users.signals.create_unified_transaction_from_conversion, which
mirrors the same model's Algorand one-shot rows.
"""
import json
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# Conversion saga -> unified status. Everything in-flight reads PENDING:
# the unified feed is user-facing and "which leg exactly" belongs to the
# savings surfaces, not the main activity list.
_STATUS_MAP = {
    'COMPLETED': 'CONFIRMED',
    'DELIVERED_USDT': 'CONFIRMED',
    'FAILED': 'FAILED',
}


def sync_unified_from_cusd_plus_conversion(conv) -> None:
    """Create/update the unified row for a savings Conversion. Never raises
    — the mirror must not break the pipeline that feeds it."""
    try:
        from users.models_unified import UnifiedTransactionTable

        conversion_type = conv.conversion_type
        to_savings = conversion_type == 'to_savings'
        delivered_as_usdt = to_savings and conv.status == 'DELIVERED_USDT'
        if delivered_as_usdt:
            token_type = 'USDT'
            amount = conv.to_amount
            description = f"Entrega: {conv.to_amount} USDT"
        elif to_savings:
            # USDT in -> cUSD+ out; the position the user ends up with.
            token_type = 'CUSD_PLUS'
            amount = conv.to_amount
            description = (
                f"Conversión: {conv.from_amount} USDT → {conv.to_amount} cUSD+"
            )
        elif conversion_type == 'from_savings':
            token_type = 'USDT'
            # The activity row is rendered as an outgoing cUSD+ debit. Show
            # the exact gross position burned, not the post-fee USDT output.
            amount = conv.from_amount
            description = (
                f"Conversión: {conv.from_amount} cUSD+ → {conv.to_amount} USDT"
            )
        elif conversion_type == 'usdt_to_cusd':
            token_type = 'CUSD_BSC'
            amount = conv.to_amount
            description = (
                f"Conversión: {conv.from_amount} USDT → {conv.to_amount} cUSD"
            )
        elif conversion_type == 'cusd_to_usdt':
            token_type = 'USDT'
            # Same convention as from_savings: outgoing history represents
            # the Confío-dollar debit. The fee/net remain available on the
            # conversion for the detail view.
            amount = conv.from_amount
            description = (
                f"Conversión: {conv.from_amount} cUSD → {conv.to_amount} USDT"
            )
        else:
            logger.error('unsupported BSC conversion type %r', conversion_type)
            return

        UnifiedTransactionTable.objects.update_or_create(
            conversion=conv,
            defaults={
                'transaction_type': 'conversion',
                'amount': str(amount),
                'fee_amount': str(conv.fee_amount or ''),
                'token_type': token_type,
                'status': _STATUS_MAP.get(conv.status, 'PENDING'),
                'transaction_hash': conv.to_transaction_hash or conv.bridge_arrival_tx or '',
                'error_message': conv.error_message or '',
                # The converter converts with themselves — sender == counterparty,
                # same convention as the Algorand conversion mirror.
                'sender_user': conv.actor_user,
                'sender_business': conv.actor_business,
                'sender_type': conv.actor_type,
                'sender_display_name': conv.actor_display_name or '',
                'sender_phone': (getattr(conv.actor_user, 'phone_number', '') or '') if conv.actor_user else '',
                'sender_address': conv.user_bsc_address or '',
                'counterparty_user': conv.actor_user,
                'counterparty_business': conv.actor_business,
                'counterparty_type': conv.actor_type,
                'counterparty_display_name': conv.actor_display_name or '',
                'counterparty_phone': None,
                'counterparty_address': conv.user_bsc_address or '',
                'description': description,
                'from_address': conv.user_bsc_address or '',
                'to_address': conv.user_bsc_address or '',
                'transaction_date': conv.created_at,
                'deleted_at': conv.deleted_at,
            },
        )
    except Exception:  # noqa: BLE001 — mirror failure must not fail the rail
        logger.exception('unified mirror failed for conversion %s', conv.internal_id)


def _stock_symbol(asset: str) -> str:
    """Best-effort ticker from the shipped, offline-safe GM registry."""
    from .gm_holdings import _fallback_registry

    target = (asset or '').lower()
    for symbol, meta in _fallback_registry().items():
        if str(meta.get('address') or '').lower() == target:
            return symbol[:-2] if symbol.lower().endswith('on') else symbol
    return 'acción'


def _stock_event_amount(
        receipt, kind: str, user_addr: str, router_addr: str, asset_addr: str):
    """Exact user-facing USD value from StockBought/StockSold, when present."""
    if not receipt:
        return None
    from eth_abi import decode
    from eth_utils import keccak

    signature = (
        'StockBought(address,address,uint256,uint256,uint256,uint256,uint256)'
        if kind == 'stock_buy'
        else 'StockSold(address,address,uint256,uint256,uint256,uint256,uint256)'
    )
    topic = '0x' + keccak(text=signature).hex()
    user_topic = (user_addr or '').lower().replace('0x', '').rjust(64, '0')
    asset_topic = (asset_addr or '').lower().replace('0x', '').rjust(64, '0')
    for log in receipt.get('logs') or []:
        topics = log.get('topics') or []
        if ((log.get('address') or '').lower() != (router_addr or '').lower()
                or len(topics) < 3 or topics[0].lower() != topic
                or topics[1].lower().replace('0x', '') != user_topic
                or topics[2].lower().replace('0x', '') != asset_topic):
            continue
        try:
            raw = bytes.fromhex((log.get('data') or '0x')[2:])
            if len(raw) != 32 * 5:
                continue
            values = decode(['uint256'] * 5, raw)
        except (TypeError, ValueError):
            continue
        # Both events encode (..., USDT principal/proceeds, fee, ...).
        principal, fee = int(values[2]), int(values[3])
        if kind == 'stock_sell' and fee > principal:
            continue
        return principal + fee if kind == 'stock_buy' else principal - fee
    return None


def sync_unified_from_stock_batch(
        batch, receipt=None, *, require_event: bool = False, strict: bool = False) -> None:
    """Mirror one final Ondo trade into the activity ledger."""
    try:
        from django.conf import settings
        from django.utils import timezone
        from users.models import Account
        from send.models import SendTransaction
        from users.models_unified import UnifiedTransactionTable
        from .sponsor_7702 import _decode_stock_call

        if batch.kind not in ('stock_buy', 'stock_sell') or not batch.tx_hash:
            return
        calls = json.loads(batch.calls_json or '[]')
        actions = [
            action for call in calls
            if (action := _decode_stock_call(call, historical=True)) is not None
        ]
        if len(actions) != 1 or actions[0]['kind'] != batch.kind:
            raise ValueError('stock batch has no unique matching router call')
        action = actions[0]
        account = Account.objects.filter(
            bsc_address__iexact=batch.user_bsc_address,
            deleted_at__isnull=True,
        ).select_related('user', 'business').first()
        if account is None:
            raise ValueError('stock batch account not found')

        router = (getattr(settings, 'CUSD_PLUS_STOCK_ROUTER_ADDRESS', '') or '').lower()
        amount_wei = _stock_event_amount(
            receipt, batch.kind, batch.user_bsc_address, router, action['asset'])
        if amount_wei is None and require_event:
            raise ValueError('stock receipt has no matching exact settlement event')
        if amount_wei is None:
            amount_wei = int(action['history_amount_wei'])
        amount = format((Decimal(amount_wei) / Decimal(10 ** 18)).normalize(), 'f')
        ticker = _stock_symbol(action['asset'])
        is_buy = batch.kind == 'stock_buy'
        display = 'Compra' if is_buy else 'Venta'
        user_name = (
            account.business.name if account.business_id
            else (account.user.get_full_name() or account.user.username or '')
        )
        relation = {
            'sender_user': account.user if is_buy else None,
            'sender_business': account.business if is_buy else None,
            # Ondo is an identified institutional counterparty, not an
            # unknown external wallet. "business" also keeps older clients
            # from mislabelling a stock settlement as a stranger's deposit.
            'sender_type': 'business' if not is_buy or account.business_id else 'user',
            'sender_display_name': user_name if is_buy else 'Ondo Stocks',
            'sender_phone': (getattr(account.user, 'phone_number', '') or '') if is_buy else '',
            'sender_address': batch.user_bsc_address if is_buy else router,
            'counterparty_user': None if is_buy else account.user,
            'counterparty_business': None if is_buy else account.business,
            'counterparty_type': 'business' if (is_buy or account.business_id) else 'user',
            'counterparty_display_name': 'Ondo Stocks' if is_buy else user_name,
            'counterparty_phone': None,
            # to_address retains the auditable router address. Keep the
            # display-counterparty address blank on buys for older clients,
            # whose heuristic labels any raw recipient as "Wallet externa".
            'counterparty_address': '' if is_buy else batch.user_bsc_address,
            'from_address': batch.user_bsc_address if is_buy else router,
            'to_address': router if is_buy else batch.user_bsc_address,
        }
        row, _ = UnifiedTransactionTable.objects.update_or_create(
            sponsored_batch=batch,
            defaults={
                'transaction_type': 'send',
                'amount': amount,
                'token_type': 'CUSD_PLUS',
                'amount_denomination': 'USD_VALUE',
                'status': 'CONFIRMED',
                'error_message': '',
                'transaction_hash': batch.tx_hash,
                'description': f'Ondo Stocks: {display} de {ticker}',
                'transaction_date': batch.created_at,
                'deleted_at': None,
                **relation,
            },
        )
        # A scanner may have observed a router refund/mint before finality.
        # Hide that false "external wallet" row; this stock receipt owns it.
        UnifiedTransactionTable.objects.filter(
            transaction_hash__iexact=batch.tx_hash,
            transaction_type='send',
            sender_type='external',
            to_address__iexact=batch.user_bsc_address,
            token_type__in=('USDT', 'CUSD_PLUS'),
            deleted_at__isnull=True,
        ).exclude(pk=row.pk).update(deleted_at=timezone.now())
        # The false unified row is a mirror of a scanner-created SendTransaction.
        # Soft-delete the source too, otherwise any later save signal can revive
        # the false "external deposit" after we hid its mirror.
        SendTransaction.all_objects.filter(
            transaction_hash__iexact=batch.tx_hash,
            sender_type='external',
            recipient_address__iexact=batch.user_bsc_address,
            token_type__in=('USDT', 'CUSD_PLUS'),
            deleted_at__isnull=True,
        ).update(deleted_at=timezone.now())
    except Exception:  # noqa: BLE001 — history must never reverse settlement
        if strict:
            raise
        logger.exception('unified stock mirror failed for batch %s', getattr(batch, 'id', None))
