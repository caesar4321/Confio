"""Durable Infinia conversion/payout orchestration using authenticated ledger facts."""
import uuid
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .allbridge_next import address
from .clients import InfiniaClient
from .eligibility import context_from_identity, enforce_and_record
from .models import InfiniaJourney, MoneyFlow, MoneyOperation, LedgerEntry
from .services import PaymentAccountError, _require_provider_enabled, _require_capability, submit_money_operation


def enabled():
    if not getattr(settings, 'INFINIA_JOURNEYS_ENABLED', False):
        raise PaymentAccountError('Infinia payment journeys are not enabled')
    _require_provider_enabled('infinia')


def positive(value):
    value = Decimal(str(value))
    if not value.is_finite() or value <= 0 or value >= Decimal('1e9') or value != value.quantize(Decimal('1e-18')):
        raise PaymentAccountError('Invalid journey amount')
    return value


def provider_number(value):
    value = positive(value)
    result = float(value)
    if Decimal(str(result)) != value:
        raise PaymentAccountError('Amount exceeds provider numeric precision')
    return result


def validate_accounts(owner, local, crypto, destination_country):
    if owner.deleted_at:
        raise PaymentAccountError('Account is unavailable')
    for account in (local, crypto):
        profile = account.provider_profile
        if (profile.confio_account_id != owner.pk or profile.provider != 'infinia'
                or profile.status != 'active' or account.status != 'active'):
            raise PaymentAccountError('An active owned Infinia account is required')
    if local.pk == crypto.pk or crypto.asset != 'USDC_POL' or local.country == 'XXX':
        raise PaymentAccountError('A local fiat account and native Polygon USDC account are required')
    identity = crypto.provider_profile.identity_verification
    if not identity or identity.status != 'verified':
        raise PaymentAccountError('Verified identity required')
    for scope in ('conversion', 'payout'):
        enforce_and_record(confio_account=owner, provider='infinia', scope=scope,
            context=context_from_identity(identity, account_country=local.country, destination_country=destination_country))


@transaction.atomic
def create_journey(*, owner, local_account, crypto_account, request_id, minimum_fx_output,
                   direction, bridge=None, credit=None, destination=None):
    enabled()
    request_id = uuid.UUID(str(request_id))
    minimum = positive(minimum_fx_output)
    owner = type(owner).objects.select_for_update().get(pk=owner.pk)
    from .models import FinancialAccount
    list(FinancialAccount.objects.select_for_update().filter(pk__in=[local_account.pk, crypto_account.pk]).order_by('pk'))
    if direction not in {'to_bank', 'to_wallet'}:
        raise PaymentAccountError('Invalid journey direction')
    wallet = address(owner.bsc_address)
    snapshot = {'destination_account': {'type': 'POLYGON', 'address': wallet}, 'country': 'XXX'}
    if direction == 'to_bank':
        if (not destination or destination.confio_account_id != owner.pk or destination.provider != 'infinia'
                or destination.asset != local_account.asset or destination.country != local_account.country
                or destination.kind == 'crypto_wallet' or destination.status not in {'pending', 'active'}):
            raise PaymentAccountError('An owned matching local payout destination is required')
        snapshot = {'destination_account': destination.details, 'country': destination.country,
                    'destination_internal_id': str(destination.internal_id),
                    'display_label': f'{destination.label} · {destination.holder_name}'}
        if (not bridge or bridge.quote.confio_account_id != owner.pk
                or bridge.quote.source_token_id != 'BSC:USDT'
                or bridge.quote.funding_instruction.financial_account_id != crypto_account.pk):
            raise PaymentAccountError('An owned bridge to this crypto account is required')
        if credit:
            raise PaymentAccountError('Outbound credit is resolved from bridge evidence')
    else:
        if (bridge or not credit or credit.financial_account_id != local_account.pk or credit.provider != 'infinia'
                or credit.direction != 'credit' or credit.asset != local_account.asset or positive(credit.amount) <= 0
                or (credit.provider_data.get('operation') or {}).get('type') not in {None, 'PAYIN', 'CREDIT'}):
            raise PaymentAccountError('An unspent local deposit credit is required')
    validate_accounts(owner, local_account, crypto_account, snapshot['country'])
    source, target = (crypto_account, local_account) if direction == 'to_bank' else (local_account, crypto_account)
    _require_capability(source, 'convert')
    _require_capability(target, 'send_third_party')
    existing = InfiniaJourney.objects.filter(confio_account=owner, request_id=request_id).first()
    expected = (direction, local_account.pk, crypto_account.pk, minimum, snapshot, wallet)
    if existing:
        actual = (existing.direction, existing.local_account_id, existing.crypto_account_id,
                  existing.minimum_fx_output, existing.destination_snapshot, existing.wallet_address)
        if actual != expected or (direction == 'to_bank' and existing.bridge_id != bridge.pk) or (
                direction == 'to_wallet' and existing.funding_credit_id != credit.pk):
            raise PaymentAccountError('Request id already used for different journey details')
        return existing
    if MoneyOperation.objects.filter(provider='infinia', source_account__in=[local_account, crypto_account],
            status__in=['created', 'submitted', 'processing', 'settling', 'unknown']).exists():
        raise PaymentAccountError('An existing provider operation is still pending')
    # One provider journey per owner while unsettled; reserve the credit for
    # exactly one journey and avoid concurrent conversion/payout balance races.
    if InfiniaJourney.objects.filter(confio_account=owner).exclude(stage__in=['completed', 'failed']).exists():
        raise PaymentAccountError('An existing local payment is still pending')
    if credit and InfiniaJourney.objects.filter(funding_credit=credit).exists():
        raise PaymentAccountError('Deposit already used by a journey')
    flow = MoneyFlow.objects.create(confio_account=owner, kind='withdraw' if direction == 'to_bank' else 'fund',
        source_asset='USDT_BSC' if direction == 'to_bank' else local_account.asset,
        source_amount=bridge.quote.money_flow.source_amount if bridge else credit.amount,
        target_asset=local_account.asset if direction == 'to_bank' else 'USDT_BSC',
        metadata={'orchestrator': 'infinia', 'minimum_fx_output': str(minimum)})
    return InfiniaJourney.objects.create(money_flow=flow, confio_account=owner, request_id=request_id,
        direction=direction, local_account=local_account, crypto_account=crypto_account,
        bridge=bridge, funding_credit=credit, minimum_fx_output=minimum,
        destination_snapshot=snapshot, wallet_address=wallet)


def _state(j, stage, *, failure=''):
    j.stage, j.failure_code = stage, failure
    j.save(update_fields=['stage', 'failure_code', 'updated_at'])
    flow = j.money_flow
    flow.status = {'completed': 'succeeded', 'failed': 'failed', 'needs_review': 'needs_review'}.get(stage, 'processing')
    flow.metadata = dict(flow.metadata, stage=stage)
    if stage in {'completed', 'failed'}:
        flow.completed_at = timezone.now()
    flow.save(update_fields=['status', 'metadata', 'completed_at', 'updated_at'])


def _credit_for_operation(operation, account):
    # COMPLETED means sent. Require actual destination movement(s), related by
    # the provider operation ID, not by amount. Refunds/fees are not proceeds.
    if not operation.provider_operation_id:
        return Decimal(0)
    entries = LedgerEntry.objects.filter(financial_account=account, provider='infinia',
        direction='credit', asset=account.asset, amount__gt=0,
        provider_data__operation__operation_id=operation.provider_operation_id)
    accepted = [e for e in entries if (e.provider_data.get('operation') or {}).get('type') in {'INTERNAL_TRANSFER', 'CREDIT'}]
    return sum((e.amount for e in accepted), Decimal(0))


def has_refund(operation):
    if not operation.provider_operation_id:
        return False
    kind = 'PAYOUT_REFUND' if operation.operation_type == 'payout' else 'INTERNAL_TRANSFER_REFUND'
    return LedgerEntry.objects.filter(provider='infinia', financial_account=operation.source_account,
        direction='credit', amount__gt=0, provider_data__operation__type=kind,
        provider_data__operation__operation_id=operation.provider_operation_id).exists()


def _new_operation(j, leg, source, target, amount):
    return MoneyOperation.objects.create(money_flow=j.money_flow, provider='infinia',
        operation_type='conversion' if leg == 'fx' else 'payout', source_account=source,
        destination_account=target, source_asset=source.asset, source_amount=amount,
        target_asset=target.asset if target else source.asset,
        idempotency_key=str(uuid.uuid5(j.internal_id, leg)),
        external_destination={} if leg == 'fx' else j.destination_snapshot,
        provider_data={'quote_id': j.fx_quote['id']} if leg == 'fx' else {})


def advance_journey(journey_id, *, client=None):
    """Persist each leg under a row lock, submit only after COMMIT.

    Provider retry/reconciliation owns unknown submissions under the original
    idempotency key. A worker never creates a replacement economic leg.
    """
    operation = None
    with transaction.atomic():
        j = InfiniaJourney.objects.select_for_update(of=('self',)).select_related(
            'money_flow', 'confio_account', 'local_account__provider_profile',
            'crypto_account__provider_profile', 'funding_credit', 'bridge__quote',
            'fx_operation', 'payout_operation').get(pk=journey_id)
        if j.stage in {'completed', 'failed', 'needs_review'}:
            return j
        for op in (j.fx_operation, j.payout_operation):
            if op and has_refund(op):
                _state(j, 'needs_review', failure='provider_refund_posted'); return j
        enabled()
        validate_accounts(j.confio_account, j.local_account, j.crypto_account, j.destination_snapshot['country'])
        if address(j.confio_account.bsc_address) != j.wallet_address:
            _state(j, 'needs_review', failure='wallet_changed'); return j
        source, target = (j.crypto_account, j.local_account) if j.direction == 'to_bank' else (j.local_account, j.crypto_account)
        if not j.funding_credit_id:
            if j.bridge.status in {'failed', 'expired', 'refunded', 'needs_review'}:
                _state(j, 'needs_review', failure='bridge_not_delivered'); return j
            if not j.bridge.provider_credit_id:
                return j
            credit = j.bridge.provider_credit
            if credit.financial_account_id != source.pk or credit.asset != source.asset or credit.direction != 'credit':
                _state(j, 'needs_review', failure='funding_credit_mismatch'); return j
            j.funding_credit = credit
            j.save(update_fields=['funding_credit', 'updated_at'])
        if not j.fx_operation_id:
            _require_capability(source, 'convert')
            amount = j.funding_credit.amount
            # Always request a fresh locked quote. Quotes don't move money; a
            # crash before saving may obtain another quote without a second debit.
            quote = (client or InfiniaClient()).create_transfer_quote({
                'external_id': str(j.internal_id), 'source_account_id': source.provider_account_id,
                'target_account_id': target.provider_account_id, 'source_amount': provider_number(amount),
                'requested_lock_time': 60})
            try:
                expires = parse_datetime(str(quote.get('expire_at', '')))
                if expires and timezone.is_naive(expires):
                    expires = expires.replace(tzinfo=dt_timezone.utc)
                valid = (quote.get('id') and quote.get('status') == 'ACTIVE' and expires
                    and expires > timezone.now() and str(quote.get('source_account_id')) == source.provider_account_id
                    and str(quote.get('target_account_id')) == target.provider_account_id
                    and positive(quote.get('source_amount')) == amount
                    and positive(quote.get('target_amount')) >= j.minimum_fx_output)
            except (AttributeError, TypeError, ValueError, ArithmeticError, PaymentAccountError):
                valid = False
            if not valid:
                _state(j, 'needs_review', failure='fx_quote_outside_authorization'); return j
            j.fx_quote = quote
            j.fx_operation = _new_operation(j, 'fx', source, target, amount)
            j.save(update_fields=['fx_quote', 'fx_operation', 'updated_at'])
            _state(j, 'converting')
            operation = j.fx_operation
        elif j.fx_operation.status in {'failed', 'reversed', 'needs_review'}:
            _state(j, 'needs_review', failure='conversion_' + j.fx_operation.status)
        elif not j.payout_operation_id:
            proceeds = _credit_for_operation(j.fx_operation, target)
            if not proceeds:
                operation = j.fx_operation if j.fx_operation.status == 'created' else None
            elif proceeds < j.minimum_fx_output or proceeds != positive(j.fx_quote['target_amount']):
                _state(j, 'needs_review', failure='conversion_credit_mismatch')
            else:
                _require_capability(target, 'send_third_party')
                quantum = Decimal('0.01') if j.direction == 'to_bank' else Decimal('0.000001')
                from decimal import ROUND_DOWN
                payout_amount = proceeds.quantize(quantum, rounding=ROUND_DOWN)
                positive(payout_amount)
                j.payout_operation = _new_operation(j, 'payout', target, None, payout_amount)
                j.save(update_fields=['payout_operation', 'updated_at'])
                _state(j, 'paying_out')
                operation = j.payout_operation
        elif j.payout_operation.status in {'failed', 'reversed', 'needs_review'}:
            _state(j, 'needs_review', failure='payout_' + j.payout_operation.status)
        elif j.payout_operation.status == 'succeeded':
            if j.direction == 'to_wallet' and j.bridge_id and j.bridge.status in {'failed', 'expired', 'needs_review', 'refunded'}:
                _state(j, 'needs_review', failure='return_bridge_' + j.bridge.status)
                return j
            if j.direction == 'to_bank':
                # A payout face amount is not proof of net bank proceeds.
                j.money_flow.target_amount = j.payout_operation.target_amount
                j.money_flow.metadata = dict(j.money_flow.metadata,
                    payout_face_amount=str(j.payout_operation.source_amount), payout_asset=j.local_account.asset)
                j.money_flow.save(update_fields=['target_amount', 'updated_at'])
                _state(j, 'completed')
            elif j.bridge_id and j.bridge.status == 'delivered':
                j.money_flow.target_amount = Decimal(j.bridge.actual_out_units) / Decimal(10**18)
                j.money_flow.save(update_fields=['target_amount', 'updated_at'])
                _state(j, 'completed')
            elif j.bridge_id:
                _state(j, 'bridging')
            else:
                arrived = _prove_wallet_arrival(j)
                if j.stage != 'needs_review':
                    _state(j, 'awaiting_wallet_authorization' if arrived else 'awaiting_wallet_delivery')
        elif j.payout_operation.status == 'created':
            operation = j.payout_operation
    if operation:
        # Never hold the journey transaction over a money-moving HTTP request.
        submit_money_operation(operation)
    return j


@transaction.atomic
def attach_return_bridge(*, owner, journey_id, bridge):
    j = InfiniaJourney.objects.select_for_update().get(internal_id=journey_id, confio_account=owner)
    if j.bridge_id:
        if j.bridge_id != bridge.pk:
            raise PaymentAccountError('Journey already has a return bridge')
        return j
    if (j.direction != 'to_wallet' or j.stage != 'awaiting_wallet_authorization'
            or bridge.quote.confio_account_id != owner.pk or bridge.quote.source_token_id != 'POL:USDC'
            or bridge.quote.destination_address != j.wallet_address
            or bridge.quote.funding_instruction.financial_account_id != j.crypto_account_id
            or bridge.quote.amount_units != j.wallet_arrival_units):
        raise PaymentAccountError('Return bridge does not match this journey')
    j.bridge = bridge
    j.save(update_fields=['bridge', 'updated_at'])
    _state(j, 'bridging')
    return j


def _prove_wallet_arrival(j):
    if j.wallet_arrival_units:
        return True
    from . import bridge_chain as chain
    operation = j.payout_operation
    if not operation.provider_operation_id:
        return False
    entries = LedgerEntry.objects.filter(provider='infinia', financial_account=j.crypto_account,
        direction='debit', asset='USDC_POL', provider_data__operation__operation_id=operation.provider_operation_id,
        provider_data__operation__type='PAYOUT')
    hashes = {str((e.provider_data.get('third_party') or {}).get('transaction_hash', '')).lower()
              for e in entries if (e.provider_data.get('third_party') or {}).get('type') == 'CRYPTO'
              and str((e.provider_data.get('third_party') or {}).get('crypto_network', '')).upper() == 'POLYGON'}
    if len(hashes) != 1 or not next(iter(hashes)):
        return False
    tx_hash = next(iter(hashes))
    receipt = chain.final_receipt('POL', tx_hash)
    if not receipt:
        return False
    received = chain.received_units(receipt, 'POL:USDC', j.wallet_address)
    if received <= 0 or Decimal(received) / Decimal(10**6) > operation.source_amount:
        _state(j, 'needs_review', failure='wallet_receipt_mismatch')
        return False
    j.wallet_arrival_units, j.wallet_arrival_tx_hash = str(received), tx_hash
    j.save(update_fields=['wallet_arrival_units', 'wallet_arrival_tx_hash', 'updated_at'])
    return True


def observe_refund(entry):
    """React only to a posted refund for a known operation and source account."""
    if entry.direction != 'credit' or Decimal(str(entry.amount)) <= 0:
        return
    operation = entry.provider_data.get('operation') or {}
    field = {'INTERNAL_TRANSFER_REFUND': 'fx_operation', 'PAYOUT_REFUND': 'payout_operation'}.get(operation.get('type'))
    if not field or not operation.get('operation_id'):
        return
    for j in InfiniaJourney.objects.filter(**{
        field + '__provider_operation_id': str(operation['operation_id']),
        field + '__source_account_id': entry.financial_account_id,
    }).select_related('money_flow'):
        _state(j, 'needs_review', failure='provider_refund_posted')
