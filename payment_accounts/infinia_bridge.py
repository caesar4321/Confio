"""Provider-funded NEXT deposits. No user signature or sponsor transaction."""
import re
import time
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .allbridge_next import NextError, address, to_units
from .models import FundingInstruction, InfiniaJourney, LedgerEntry, PaymentBridgeTransfer
from .services import PaymentAccountError


class InfiniaBridgeReview(PaymentAccountError):
    """A permanent prerequisite or authorization failure, not a transport retry."""


class InfiniaDepositExpired(PaymentAccountError):
    pass


RECOVERABLE_DELAYS = frozenset({'provider_deposit_delayed', 'source_confirmation_delayed'})


def preflight(journey, amount):
    from .bridge_execution import execution_enabled
    try:
        execution_enabled('POL:USDC')
    except PaymentAccountError as exc:
        raise InfiniaBridgeReview(str(exc)) from exc
    if not getattr(settings, 'PAYMENT_BRIDGE_QUOTES_ENABLED', False):
        raise InfiniaBridgeReview('Payment bridge quotes are not enabled')
    from .bridge import exceeds_bridge_cap
    if exceeds_bridge_cap(amount):
        raise InfiniaBridgeReview('Amount exceeds the configured bridge limit')
    instructions = FundingInstruction.objects.filter(
        financial_account=journey.crypto_account, kind='crypto_address', status='active',
    ).order_by('pk')
    instruction = next((i for i in instructions if not i.expires_at or i.expires_at > timezone.now()), None)
    if instruction is None:
        raise InfiniaBridgeReview('An active Infinia crypto account instruction is required')
    return instruction


def payout_destination(deposit):
    return {'country': 'GLOBAL', 'currency': 'USDC',
            'destinationType': {'type': 'POLYGON', 'address': deposit}}


@transaction.atomic
def prepare_infinia_bridge(journey, amount, *, client=None, intents=None):
    # Called under the journey lock, before creating the immutable payout.
    from .bridge import quote_provider_funding
    from .bridge_execution import prepare_bridge
    instruction = preflight(journey, amount)
    if journey.minimum_wallet_output is None:
        raise InfiniaBridgeReview('A minimum BSC USDT receipt must be authorized')
    quote = quote_provider_funding(
        confio_account=journey.confio_account, funding_instruction_id=instruction.internal_id,
        amount=amount, request_id=uuid.uuid5(journey.internal_id, 'direct-bridge'),
        direction='to_wallet', client=client,
    )
    route_index = next((i for i, r in enumerate(quote.routes) if r['messenger'] == 'near-intents'), None)
    if route_index is None:
        raise InfiniaBridgeReview('No deposit-based NEXT route is available')
    transfer = prepare_bridge(journey.confio_account, quote.internal_id, route_index,
                              client=client, intents=intents, infinia_journey=journey)
    if int(transfer.amount_out_min) < int(to_units(journey.minimum_wallet_output, 'BSC:USDT')):
        raise InfiniaBridgeReview('Bridge minimum is below the authorized BSC USDT receipt')
    return transfer


def validate_payout(journey, operation):
    """Check persisted terms immediately before submission, including retries."""
    bridge = journey.bridge
    if not bridge or bridge.funding_mode != 'infinia':
        return
    from .infinia_journeys import enabled
    enabled()
    preflight(journey, operation.source_amount)
    if (journey.direction != 'to_wallet' or journey.payout_operation_id != operation.pk
            or journey.confio_account.deleted_at
            or address(journey.confio_account.bsc_address) != journey.wallet_address
            or operation.source_account_id != journey.crypto_account_id
            or operation.source_asset != 'USDC_POL'
            or to_units(operation.source_amount, 'POL:USDC') != bridge.quote.amount_units
            or operation.external_destination.get('destination_account') != payout_destination(bridge.deposit_address)
            or bridge.quote.destination_address != journey.wallet_address
            or journey.minimum_wallet_output is None
            or int(bridge.amount_out_min) < int(to_units(journey.minimum_wallet_output, 'BSC:USDT'))):
        raise PaymentAccountError('Provider payout does not match its bridge')
    if int(time.time()) >= bridge.deadline - 60:
        raise InfiniaDepositExpired('Provider bridge deposit deadline is too close or expired')


def bind_payout_hash(bridge):
    """Adopt only the authenticated crypto movement of this exact payout.

    An unknown/late provider response does not authorize a replacement deposit.
    Reconciliation continues after expiry to recognize an already-sent payout.
    """
    with transaction.atomic():
        journey = InfiniaJourney.objects.select_for_update().filter(bridge=bridge, direction='to_wallet').first()
        bridge = PaymentBridgeTransfer.objects.select_for_update().get(pk=bridge.pk)
        if bridge.source_tx_hash:
            return bridge
        if not journey or not journey.payout_operation_id:
            return bridge
        operation = journey.payout_operation
        if operation.provider_operation_id:
            entries = LedgerEntry.objects.filter(
                provider='infinia', financial_account=journey.crypto_account, direction='debit', asset='USDC_POL',
                provider_data__operation__type='PAYOUT',
                provider_data__operation__operation_id=operation.provider_operation_id,
            )
            hashes = set()
            for entry in entries:
                third = entry.provider_data.get('third_party') or {}
                if third.get('type') == 'CRYPTO' and str(third.get('crypto_network', '')).upper() == 'POLYGON':
                    value = str(third.get('transaction_hash', '')).lower()
                    if re.fullmatch(r'0x[0-9a-f]{64}', value):
                        hashes.add(value)
            if len(hashes) == 1:
                bridge.source_tx_hash = hashes.pop()
                bridge.status = 'submitted'
                bridge.failure_code = ''
                bridge.save(update_fields=['source_tx_hash', 'status', 'failure_code', 'updated_at'])
                return bridge
            if len(hashes) > 1:
                bridge.status, bridge.failure_code = 'needs_review', 'ambiguous_provider_payout_hash'
        if not bridge.failure_code and int(time.time()) >= bridge.deadline:
            bridge.status, bridge.failure_code = 'needs_review', 'provider_deposit_delayed'
        if bridge.failure_code:
            bridge.save(update_fields=['status', 'failure_code', 'updated_at'])
        return bridge
