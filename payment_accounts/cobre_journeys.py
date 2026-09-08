"""Durable Cobre USD_STABLE ↔ COPCO ↔ COP journeys.

Each downstream leg spends only a posted, operation-bound credit. Provider
submissions retain one immutable operation and idempotency key across retries.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .allbridge_next import address
from .clients import CobreClient
from .eligibility import context_from_identity, enforce_and_record
from .infinia_journeys import positive, _state
from .models import CobreJourney, FinancialAccount, LedgerEntry, MoneyFlow, MoneyOperation, PayoutDestination
from .services import PaymentAccountError, _require_provider_enabled, _require_capability, submit_money_operation

TERMINAL = {'completed', 'failed', 'needs_review'}
FAILED = {'failed', 'reversed', 'needs_review'}
DEPOSITS = {'breb_credit', 'r2p_breb_credit', 'col_credit', 'col_top_up_credit', 'col_cb_credit', 'transfer_credit', 'r2p_credit', 'dd_credit'}


def enabled():
    if not getattr(settings, 'COBRE_JOURNEYS_ENABLED', False):
        raise PaymentAccountError('Cobre payment journeys are not enabled')
    _require_provider_enabled('cobre')


def minor(value):
    value = positive(value) * 100
    if value != value.to_integral_value():
        raise PaymentAccountError('Cobre amounts require at most two decimal places')
    return int(value)


def content(entry):
    return entry.provider_data.get('content') or entry.provider_data


def validate_accounts(owner, local, crypto, copco, destination_country):
    if owner.deleted_at or owner.account_type != 'personal':
        raise PaymentAccountError('An active personal account is required')
    if (local.country, local.asset, crypto.asset, copco.asset) != ('COL', 'COP', 'USD_STABLE', 'COPCO'):
        raise PaymentAccountError('Cobre journeys require COP, COPCO and USD_STABLE balances')
    if len({a.pk for a in (local, crypto, copco)}) != 3:
        raise PaymentAccountError('Three distinct balances are required')
    for a in (local, crypto, copco):
        p = a.provider_profile
        if (p.confio_account_id != owner.pk or p.provider != 'cobre' or p.pk != local.provider_profile_id
                or p.status != 'active' or a.status != 'active' or not a.provider_account_id):
            raise PaymentAccountError('Active owned Cobre balances under the same profile are required')
    identity = local.provider_profile.identity_verification
    if not identity or identity.status != 'verified':
        raise PaymentAccountError('Verified identity required')
    for scope in ('conversion', 'payout'):
        enforce_and_record(confio_account=owner, provider='cobre', scope=scope,
            context=context_from_identity(identity, account_country='COL', destination_country=destination_country))


@transaction.atomic
def create_journey(*, owner, local_account, crypto_account, copco_account, request_id,
                   minimum_fx_output, direction, bridge=None, credit=None, destination=None):
    enabled()
    request_id, minimum = uuid.UUID(str(request_id)), positive(minimum_fx_output)
    minor(minimum)
    owner = type(owner).objects.select_for_update().get(pk=owner.pk)
    accounts = [local_account, crypto_account, copco_account]
    list(FinancialAccount.objects.select_for_update().filter(pk__in=[a.pk for a in accounts]).order_by('pk'))
    wallet = address(owner.bsc_address)
    if direction not in {'to_bank', 'to_wallet'}:
        raise PaymentAccountError('Invalid journey direction')
    if direction == 'to_bank':
        if (not destination or destination.confio_account_id != owner.pk or destination.provider != 'cobre'
                or destination.kind != 'breb_key' or destination.asset != 'COP' or destination.country != 'COL'
                or destination.status != 'active' or not destination.provider_destination_id):
            raise PaymentAccountError('An owned active Bre-B destination is required')
        if (credit or not bridge or bridge.quote.confio_account_id != owner.pk
                or bridge.quote.source_token_id != 'BSC:USDT'
                or bridge.quote.funding_instruction.financial_account_id != crypto_account.pk):
            raise PaymentAccountError('An owned bridge to the USD_STABLE balance is required')
    else:
        if (bridge or not credit or credit.provider != 'cobre' or credit.financial_account_id != local_account.pk
                or credit.asset != 'COP' or credit.direction != 'credit' or positive(credit.amount) <= 0
                or content(credit).get('type') not in DEPOSITS):
            raise PaymentAccountError('An unused COP deposit credit is required')
        # Select a previously provisioned, owned beneficiary. Revalidate with
        # Cobre immediately before payout; the client never supplies a wallet.
        destination = PayoutDestination.objects.filter(confio_account=owner, provider='cobre',
            kind='crypto_wallet', status='active', asset='USDC_POL', details__address=wallet).first()
        if not destination or not destination.provider_destination_id:
            raise PaymentAccountError('A verified Cobre beneficiary for this wallet is required')
    snapshot = {'provider_counterparty_id': destination.provider_destination_id,
        'destination_internal_id': str(destination.internal_id), 'display_label': f'{destination.label} · {destination.holder_name}', 'country': 'COL' if direction == 'to_bank' else 'XXX'}
    if direction == 'to_wallet':
        snapshot.update(wallet_address=wallet, chain='polygon', token='usdc')
    validate_accounts(owner, local_account, crypto_account, copco_account, snapshot['country'])
    for a in (crypto_account, copco_account) if direction == 'to_bank' else (local_account, copco_account):
        _require_capability(a, 'convert')
    _require_capability(local_account if direction == 'to_bank' else crypto_account,
                        'send_third_party' if direction == 'to_bank' else 'crypto_payout')
    existing = CobreJourney.objects.filter(confio_account=owner, request_id=request_id).first()
    expected = (direction, local_account.pk, crypto_account.pk, copco_account.pk, minimum, snapshot, wallet)
    if existing:
        actual = (existing.direction, existing.local_account_id, existing.crypto_account_id,
                  existing.copco_account_id, existing.minimum_fx_output, existing.destination_snapshot, existing.wallet_address)
        if expected != actual or (direction == 'to_bank' and existing.bridge_id != bridge.pk) or (
                direction == 'to_wallet' and existing.funding_credit_id != credit.pk):
            raise PaymentAccountError('Request id already used for different journey details')
        return existing
    if CobreJourney.objects.filter(confio_account=owner).exclude(stage__in=['completed', 'failed']).exists():
        raise PaymentAccountError('An existing Cobre payment is still pending')
    if MoneyOperation.objects.filter(provider='cobre', source_account__in=accounts,
            status__in=['created', 'submitted', 'processing', 'settling', 'unknown']).exists():
        raise PaymentAccountError('An existing provider operation is still pending')
    if credit and CobreJourney.objects.filter(funding_credit=credit).exists():
        raise PaymentAccountError('Deposit already used by a journey')
    flow = MoneyFlow.objects.create(confio_account=owner, kind='withdraw' if direction == 'to_bank' else 'fund',
        source_asset='USDT_BSC' if bridge else 'COP', source_amount=bridge.quote.money_flow.source_amount if bridge else credit.amount,
        target_asset='COP' if direction == 'to_bank' else 'USDT_BSC',
        metadata={'orchestrator': 'cobre', 'minimum_fx_output': str(minimum), 'settlement_type': 'standard'})
    return CobreJourney.objects.create(money_flow=flow, confio_account=owner, request_id=request_id,
        direction=direction, local_account=local_account, crypto_account=crypto_account, copco_account=copco_account,
        bridge=bridge, funding_credit=credit, minimum_fx_output=minimum,
        destination_snapshot=snapshot, wallet_address=wallet)


def credit_for(operation, account, kind):
    if not operation.provider_operation_id:
        return Decimal(0)
    rows = LedgerEntry.objects.filter(provider='cobre', financial_account=account, asset=account.asset,
        direction='credit', amount__gt=0).filter(
        Q(provider_data__content__metadata__money_movement_id=operation.provider_operation_id) |
        Q(provider_data__metadata__money_movement_id=operation.provider_operation_id))
    return sum((e.amount for e in rows if content(e).get('type') == kind
                and content(e).get('credit_debit_type') == 'credit'), Decimal(0))


def has_source_credit(operation):
    if not operation.provider_operation_id:
        return False
    return LedgerEntry.objects.filter(provider='cobre', financial_account=operation.source_account,
        direction='credit', amount__gt=0).filter(
        Q(provider_data__content__metadata__money_movement_id=operation.provider_operation_id) |
        Q(provider_data__metadata__money_movement_id=operation.provider_operation_id)).exists()


def new_leg(j, leg, source, target, amount):
    minor(amount)
    op = MoneyOperation.objects.create(money_flow=j.money_flow, provider='cobre',
        operation_type={'fx': 'conversion', 'ramp': 'internal_transfer', 'payout': 'payout'}[leg],
        source_account=source, destination_account=target, source_asset=source.asset, source_amount=amount,
        target_asset=target.asset if target else source.asset,
        idempotency_key=str(uuid.uuid5(j.internal_id, leg)),
        external_destination=j.destination_snapshot if leg == 'payout' else {},
        provider_data={'quote_id': j.fx_quote['id']} if leg == 'fx' else {})
    setattr(j, leg + '_operation', op)
    j.save(update_fields=[leg + '_operation', 'fx_quote', 'updated_at'])
    _state(j, {'fx': 'converting', 'ramp': 'converting_cop', 'payout': 'paying_out'}[leg])
    return op


def quoted_leg(j, source, target, amount, client):
    quote = client.create_fx_quote({'type': 'static_quote',
        'currency_pair': f'{source.asset.lower()}/{target.asset.lower()}', 'source_amount': minor(amount)})
    try:
        expiry = parse_datetime(str(quote.get('valid_until', '')))
        valid = (quote.get('id') and quote.get('type') == 'static_quote'
            and quote.get('currency_pair') == f'{source.asset.lower()}/{target.asset.lower()}'
            and positive(quote.get('source_amount')) == minor(amount)
            and positive(quote.get('destination_amount')) / 100 >= j.minimum_fx_output
            and expiry and not timezone.is_naive(expiry) and expiry > timezone.now())
        minor(positive(quote.get('destination_amount')) / 100)
    except (AttributeError, ValueError, TypeError, ArithmeticError, PaymentAccountError):
        valid = False
    if not valid:
        _state(j, 'needs_review', failure='fx_quote_outside_authorization')
        return None
    j.fx_quote = quote
    return new_leg(j, 'fx', source, target, amount)


def _proceeds(j, operation, target, kind, expected):
    amount = credit_for(operation, target, kind)
    if amount and amount != expected:
        _state(j, 'needs_review', failure='conversion_credit_mismatch')
        return None
    return amount


def advance_journey(journey_id, *, client=None):
    operation = None
    with transaction.atomic():
        j = CobreJourney.objects.select_for_update(of=('self',)).select_related(
            'money_flow', 'confio_account', 'local_account__provider_profile', 'crypto_account__provider_profile',
            'copco_account__provider_profile', 'funding_credit', 'bridge__quote',
            'fx_operation', 'ramp_operation', 'payout_operation').get(pk=journey_id)
        if j.stage in TERMINAL:
            return j
        enabled()
        validate_accounts(j.confio_account, j.local_account, j.crypto_account, j.copco_account, j.destination_snapshot['country'])
        if address(j.confio_account.bsc_address) != j.wallet_address:
            _state(j, 'needs_review', failure='wallet_changed'); return j
        for op in (j.ramp_operation, j.fx_operation, j.payout_operation):
            if op and has_source_credit(op):
                _state(j, 'needs_review', failure='provider_source_credit_posted'); return j
            if op and op.status in FAILED:
                _state(j, 'needs_review', failure='provider_leg_' + op.status); return j
        if not j.funding_credit_id:
            if j.bridge.status in {'failed', 'expired', 'refunded', 'needs_review'}:
                _state(j, 'needs_review', failure='bridge_not_delivered'); return j
            if j.bridge.status != 'delivered' or not j.bridge.provider_credit_id:
                return j
            e = j.bridge.provider_credit
            if e.financial_account_id != j.crypto_account_id or e.asset != 'USD_STABLE' or e.direction != 'credit':
                _state(j, 'needs_review', failure='funding_credit_mismatch'); return j
            j.funding_credit = e
            j.save(update_fields=['funding_credit', 'updated_at'])
        if j.direction == 'to_wallet' and not j.ramp_operation_id:
            operation = new_leg(j, 'ramp', j.local_account, j.copco_account, j.funding_credit.amount)
        elif not j.fx_operation_id:
            amount = j.funding_credit.amount if j.direction == 'to_bank' else _proceeds(
                j, j.ramp_operation, j.copco_account, 'onramp_credit', j.ramp_operation.source_amount)
            if amount:
                source, target = (j.crypto_account, j.copco_account) if j.direction == 'to_bank' else (j.copco_account, j.crypto_account)
                operation = quoted_leg(j, source, target, amount, client or CobreClient())
            elif amount is not None and j.ramp_operation.status == 'created':
                operation = j.ramp_operation
        elif j.direction == 'to_bank' and not j.ramp_operation_id:
            amount = _proceeds(j, j.fx_operation, j.copco_account, 'cbmm_credit', positive(j.fx_quote['destination_amount']) / 100)
            if amount:
                operation = new_leg(j, 'ramp', j.copco_account, j.local_account, amount)
            elif amount is not None and j.fx_operation.status == 'created':
                operation = j.fx_operation
        elif not j.payout_operation_id:
            upstream = j.ramp_operation if j.direction == 'to_bank' else j.fx_operation
            target = j.local_account if j.direction == 'to_bank' else j.crypto_account
            amount = _proceeds(j, upstream, target, 'offramp_credit' if j.direction == 'to_bank' else 'cbmm_credit',
                              upstream.source_amount if j.direction == 'to_bank' else positive(j.fx_quote['destination_amount']) / 100)
            if amount:
                operation = new_leg(j, 'payout', target, None, amount)
            elif amount is not None and upstream.status == 'created':
                operation = upstream
        elif j.payout_operation.status == 'succeeded':
            if j.direction == 'to_bank':
                j.money_flow.target_amount = j.payout_operation.target_amount
                j.money_flow.save(update_fields=['target_amount', 'updated_at'])
                _state(j, 'completed')
            elif j.bridge_id:
                if j.bridge.status == 'delivered':
                    j.money_flow.target_amount = Decimal(j.bridge.actual_out_units) / 10**18
                    j.money_flow.save(update_fields=['target_amount', 'updated_at'])
                    _state(j, 'completed')
                elif j.bridge.status in {'failed', 'expired', 'refunded', 'needs_review'}:
                    _state(j, 'needs_review', failure='return_bridge_' + j.bridge.status)
            else:
                arrived = prove_wallet_arrival(j)
                if j.stage != 'needs_review':
                    _state(j, 'awaiting_wallet_authorization' if arrived else 'awaiting_wallet_delivery')
        elif j.payout_operation.status == 'created':
            operation = j.payout_operation
    if operation:
        submit_money_operation(operation)
    return j


def prove_wallet_arrival(j):
    if j.wallet_arrival_units:
        return True
    from . import bridge_chain as chain
    op = j.payout_operation
    if not op.provider_operation_id:
        return False
    entries = LedgerEntry.objects.filter(provider='cobre', financial_account=j.crypto_account,
        direction='debit', asset='USD_STABLE').filter(
        Q(provider_data__content__metadata__money_movement_id=op.provider_operation_id) |
        Q(provider_data__metadata__money_movement_id=op.provider_operation_id))
    hashes = set()
    for e in entries:
        c, m = content(e), content(e).get('metadata') or {}
        if (c.get('type') == 'stable_payout_debit' and c.get('credit_debit_type') == 'debit'
                and str(m.get('beneficiary_chain', '')).lower() == 'polygon'
                and str(m.get('beneficiary_token', '')).lower() == 'usdc'
                and str(m.get('beneficiary_account_number', '')).lower() == j.wallet_address):
            hashes.add(str(m.get('tracking_key', '')).lower())
    if len(hashes) != 1 or not next(iter(hashes)):
        return False
    tx_hash = next(iter(hashes))
    receipt = chain.final_receipt('POL', tx_hash)
    if not receipt:
        return False
    received = chain.received_units(receipt, 'POL:USDC', j.wallet_address)
    if received <= 0 or Decimal(received) / 10**6 > op.source_amount:
        _state(j, 'needs_review', failure='wallet_receipt_mismatch')
        return False
    j.wallet_arrival_units, j.wallet_arrival_tx_hash = str(received), tx_hash
    j.save(update_fields=['wallet_arrival_units', 'wallet_arrival_tx_hash', 'updated_at'])
    return True


@transaction.atomic
def attach_return_bridge(*, owner, journey_id, bridge):
    j = CobreJourney.objects.select_for_update().get(internal_id=journey_id, confio_account=owner)
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


def observe_refund(entry):
    """A credit back to the original source is never new spendable proceeds."""
    c = content(entry)
    movement_id = (c.get('metadata') or {}).get('money_movement_id')
    if entry.direction != 'credit' or not movement_id:
        return
    for op in MoneyOperation.objects.filter(provider='cobre', provider_operation_id=movement_id,
            source_account=entry.financial_account, money_flow__metadata__orchestrator='cobre'):
        j = CobreJourney.objects.select_related('money_flow').get(money_flow=op.money_flow)
        _state(j, 'needs_review', failure='provider_source_credit_posted')
