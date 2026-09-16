"""Provider-funded bridge deposits. No user signature or sponsor transaction."""
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


# Bridge outcomes that are finished and understood: nothing moved, or the funds
# verifiably returned to the user's own wallet. The journey failed; no human has
# anything to decide. Only an unresolved bridge propagates as review.
SETTLED_BRIDGE_FAILURES = frozenset({'failed', 'expired', 'refunded'})


def live_journeys(queryset, *, recoverable=RECOVERABLE_DELAYS):
    """Journeys the worker may advance, including proven re-quote candidates.

    Every gate that asks "is another journey using these funds?" must use this
    predicate, and so must the worker that advances them, or the two disagree
    and a journey nothing will ever touch blocks one that is trying to run.
    This is not sufficient funds-release evidence: unresolved provider
    operations reserve their source accounts even on parked journeys.
    Cobre's reconciler never retries needs_review, so it passes recoverable=().
    """
    from django.db.models import Q
    live = ~Q(stage__in=['completed', 'failed', 'needs_review'])
    if recoverable:
        live |= Q(stage='needs_review', failure_code__in=sorted(recoverable))
        # A conversion the provider refused without creating anything is going
        # to be re-quoted, so it is live in both senses: the worker must pick it
        # up, and it still contends for the funds. Do not select every failed
        # operation: permanent rejections would otherwise reserve forever.
        from django.db.models import F, Value, TextField
        from django.db.models.functions import Concat
        from django.db.models.fields.json import KeyTextTransform
        queryset = queryset.alias(
            _fx_rejection_text=KeyTextTransform('message', 'fx_operation__provider_data'),
            _expired_quote_message=Concat(Value('Quote: '),
                KeyTextTransform('id', 'fx_quote'), Value(' is expired'), output_field=TextField()))
        live |= (Q(stage='needs_review', failure_code='provider_leg_requires_review',
                   payout_operation__isnull=True, fx_operation__status='failed',
                   fx_operation__failure_code='400', fx_operation__provider_data__status='fail',
                   _fx_rejection_text=F('_expired_quote_message'))
                 & (Q(fx_operation__provider_operation_id__isnull=True)
                    | Q(fx_operation__provider_operation_id='')))
    return queryset.filter(live)


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
    route_index = next((i for i, r in enumerate(quote.routes) if r['messenger'] in {'near-intents', 'relay'}), None)
    if route_index is None:
        raise InfiniaBridgeReview('No deposit-based bridge route is available')
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
