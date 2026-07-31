"""UnifiedTransactionTable mirror for cUSD+ conversions.

The unified table is the cross-feature ledger behind the app's main
activity feed and the ops one-stop admin — every rail (send, payments,
ramps, presale, Algorand conversions) mirrors into it. This module is the
cusd_plus rail's mirror: one unified row per CusdPlusConversion, linked
OneToOne (idempotent update_or_create), status evolving with the saga.

The BSC sibling of users.signals.create_unified_transaction_from_conversion
(the Algorand USDC<->cUSD converter's mirror) — same field conventions.
"""
import logging

logger = logging.getLogger(__name__)

# Conversion saga -> unified status. Everything in-flight reads PENDING:
# the unified feed is user-facing and "which leg exactly" belongs to the
# savings surfaces, not the main activity list.
_STATUS_MAP = {
    'COMPLETED': 'CONFIRMED',
    'FAILED': 'FAILED',
}


def sync_unified_from_cusd_plus_conversion(conv) -> None:
    """Create/update the unified row for a CusdPlusConversion. Never raises
    — the mirror must not break the pipeline that feeds it."""
    try:
        from users.models_unified import UnifiedTransactionTable

        to_savings = conv.direction == 'to_savings'
        if to_savings:
            # USDT in -> cUSD+ out; the position the user ends up with.
            token_type = 'CUSD_PLUS'
            description = (
                f"Conversión: {conv.amount_usd} USDT → {conv.quoted_receive_usd} cUSD+"
            )
        else:
            token_type = 'USDT'
            description = (
                f"Conversión: {conv.amount_usd} cUSD+ → {conv.quoted_receive_usd} USDT"
            )

        UnifiedTransactionTable.objects.update_or_create(
            cusd_plus_conversion=conv,
            defaults={
                'transaction_type': 'conversion',
                'amount': str(conv.quoted_receive_usd),
                'token_type': token_type,
                'status': _STATUS_MAP.get(conv.status, 'PENDING'),
                'transaction_hash': conv.dest_tx_hash or conv.bridge_arrival_tx or '',
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
