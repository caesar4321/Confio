from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import migrations


GRAIN = Decimal('0.000001')
WINDOW = timedelta(hours=24)


def repair_mismatched_links(apps, schema_editor):
    RampTransaction = apps.get_model('ramps', 'RampTransaction')
    Conversion = apps.get_model('conversion', 'Conversion')

    ramps = RampTransaction.objects.filter(
        destination='cusd_plus',
        direction='on_ramp',
        conversion__isnull=False,
    ).select_related('conversion')

    for ramp in ramps.iterator():
        raw_arrival = (ramp.metadata or {}).get('bsc_arrival_amount')
        if raw_arrival in (None, ''):
            continue
        try:
            arrival = Decimal(str(raw_arrival))
            linked_gross = Decimal(
                ramp.conversion.gross_amount_exact
                if ramp.conversion.gross_amount_exact is not None
                else ramp.conversion.from_amount
            )
        except (InvalidOperation, TypeError, ValueError):
            continue
        if abs(arrival - linked_gross) <= GRAIN:
            continue

        # A many-to-one conversion is legitimate when one sweep consumed
        # several ramp arrivals. Repair only an impossible over-allocation:
        # the sum currently attached to this conversion exceeds its gross.
        sibling_gross = Decimal('0')
        sibling_rows = RampTransaction.objects.filter(
            conversion_id=ramp.conversion_id,
            destination='cusd_plus',
            direction='on_ramp',
        ).values_list('metadata', flat=True)
        for sibling_metadata in sibling_rows:
            raw_sibling = (sibling_metadata or {}).get('bsc_arrival_amount')
            try:
                sibling_gross += Decimal(str(raw_sibling))
            except (InvalidOperation, TypeError, ValueError):
                sibling_gross = Decimal('0')
                break
        if sibling_gross <= linked_gross + GRAIN:
            continue

        # Repair only an unambiguous exact replacement belonging to the same
        # wallet, product type and time window. Anything else stays untouched
        # for manual reconciliation.
        address = (ramp.actor_address or '').lower()
        if not address:
            continue
        metadata = dict(ramp.metadata or {})
        allocation = dict(metadata.get('conversion_allocation') or {})
        try:
            allocated_net = Decimal(str(allocation['net_amount']))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            continue
        candidates = list(Conversion.objects.filter(
            conversion_type__in=('to_savings', 'usdt_to_cusd'),
            status='COMPLETED',
            actor_address__iexact=address,
            ramp_transactions__isnull=True,
            created_at__gte=ramp.created_at - WINDOW,
            created_at__lte=ramp.created_at + WINDOW,
            from_amount__gte=arrival - GRAIN,
            from_amount__lte=arrival + GRAIN,
            to_amount__gte=allocated_net - GRAIN,
            to_amount__lte=allocated_net + GRAIN,
        )[:2])
        if len(candidates) != 1:
            continue

        replacement = candidates[0]
        final_currency = (
            'CUSD+' if replacement.conversion_type == 'to_savings'
            else 'CUSD_BSC'
        )
        allocation.update({
            'gross_amount': format(arrival, 'f'),
            'net_amount': format(replacement.to_amount, 'f'),
            'conversion_id': str(replacement.internal_id),
        })
        metadata['conversion_allocation'] = allocation
        RampTransaction.objects.filter(pk=ramp.pk).update(
            conversion_id=replacement.pk,
            final_amount=replacement.to_amount,
            final_currency=final_currency,
            metadata=metadata,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('ramps', '0013_normalize_bsc_cusd_final_currency'),
    ]

    operations = [
        migrations.RunPython(repair_mismatched_links, noop_reverse),
    ]
