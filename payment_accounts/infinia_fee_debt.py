"""Carry unpaid invoice amounts between signed settlements without duplicate claims."""
from decimal import Decimal
from django.db import transaction
from .models import InfiniaFeeDebt, MoneyFlow
from .infinia_fees import FeePricingError


@transaction.atomic
def finalize_incoming(journey):
    if journey.direction != 'to_wallet':
        return None
    flow = MoneyFlow.objects.select_for_update().get(pk=journey.money_flow_id)
    fee = flow.metadata.get('infinia_fee')
    repricable = bool(fee and (not fee.get('arrival_finalized') or int(fee.get('deferred_units', '0'))))
    if repricable and fee.get('arrival_finalized'):
        from blockchain.models import SponsoredBatch
        repricable = not SponsoredBatch.objects.filter(user=journey.confio_account.user,
            client_request_id__startswith='local-mint-' + str(journey.internal_id)).exclude(
            status__in=['reverted', 'noop_failed']).exists()
    if fee and fee.get('cap_on_arrival') and repricable and journey.bridge_id and journey.bridge.status == 'delivered':
        from cusd_plus.cusd_vault import preview_mint_wei
        preview = preview_mint_wei(int(journey.bridge.actual_out_units))
        if not 0 <= preview.fee_bps <= 90 or preview.net_wei <= 0:
            raise FeePricingError('Invalid mint preview')
        invoice = int(fee.get('invoice_units', fee['units']))
        collected = min(invoice, preview.net_wei)
        fee = dict(fee, invoice_units=str(invoice), units=str(collected),
                   deferred_units=str(invoice-collected), arrival_finalized=True,
                   minimum_net_units=str(max(0, int(fee['minimum_net_units']))))
        flow.metadata = dict(flow.metadata, infinia_fee=fee)
        flow.save(update_fields=['metadata'])
    journey.money_flow.metadata = flow.metadata
    return fee


@transaction.atomic
def quoted(owner):
    type(owner).objects.select_for_update().get(pk=owner.pk)
    from .infinia_maintenance import _release_expired
    _release_expired(owner)
    rows = list(InfiniaFeeDebt.objects.filter(source_flow__confio_account=owner,
        reserved_flow__isnull=True, settled_tx_hash='').order_by('pk'))
    return [r.pk for r in rows], sum((r.amount_usd for r in rows), Decimal(0))


@transaction.atomic
def reserve(snapshot, flow):
    ids = (snapshot or {}).get('debt_ids', [])
    if ids and InfiniaFeeDebt.objects.filter(pk__in=ids, source_flow__confio_account=flow.confio_account,
            reserved_flow__isnull=True, settled_tx_hash='').update(reserved_flow=flow) != len(ids):
        raise FeePricingError('Unpaid fees changed; request a new quote')


def require_reservation(snapshot, flow):
    ids = snapshot.get('debt_ids', [])
    if ids and InfiniaFeeDebt.objects.filter(pk__in=ids, reserved_flow=flow).count() != len(ids):
        raise FeePricingError('Unpaid fees changed; request a new quote')


@transaction.atomic
def reconcile(journey, evidence):
    fee = journey.money_flow.metadata.get('infinia_fee', {})
    flow = journey.bridge.quote.money_flow if journey.direction == 'to_bank' else journey.money_flow
    if evidence:
        require_reservation(fee, flow)
        # The old invoice is discharged by cash plus the new residual invoice.
        # Its cash receipt always reports only the actual collector transfer.
        InfiniaFeeDebt.objects.filter(pk__in=fee.get('debt_ids', []), reserved_flow=flow).update(
            settled_tx_hash=evidence['transaction_hash'])
        residual = int(fee.get('deferred_units', '0'))
        if residual:
            row, _ = InfiniaFeeDebt.objects.get_or_create(source_flow=flow,
                defaults={'amount_usd': Decimal(residual)/Decimal(10**18)})
            if row.amount_usd != Decimal(residual)/Decimal(10**18):
                raise FeePricingError('Inconsistent unpaid fee invoice')
    else:
        InfiniaFeeDebt.objects.filter(pk__in=fee.get('debt_ids', []), reserved_flow=flow).update(settled_tx_hash='')
