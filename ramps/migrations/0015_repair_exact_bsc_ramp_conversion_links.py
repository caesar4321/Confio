from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import migrations


GRAIN = Decimal('0.000001')
WINDOW = timedelta(hours=24)


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def repair_exact_links(apps, schema_editor):
    RampTransaction = apps.get_model('ramps', 'RampTransaction')
    Conversion = apps.get_model('conversion', 'Conversion')

    # Build the complete plan before changing any row. A conversion is only
    # repaired when exactly one ramp row matches both its gross and net value.
    # This preserves legitimate many-to-one sweeps: their per-ramp allocation
    # is smaller than the conversion total and therefore cannot match here.
    proposed = defaultdict(list)
    ramps = RampTransaction.objects.filter(
        destination='cusd_plus',
        direction='on_ramp',
    )
    for ramp in ramps.iterator():
        metadata = dict(ramp.metadata or {})
        arrival = _decimal(metadata.get('bsc_arrival_amount'))
        allocation = dict(metadata.get('conversion_allocation') or {})
        allocated_net = _decimal(allocation.get('net_amount'))
        address = (ramp.actor_address or '').lower()
        if arrival is None or allocated_net is None or not address:
            continue

        exact = []
        candidates = Conversion.objects.filter(
            conversion_type__in=('to_savings', 'usdt_to_cusd'),
            source='ramp',
            status='COMPLETED',
            actor_address__iexact=address,
            created_at__gte=ramp.created_at - WINDOW,
            created_at__lte=ramp.created_at + WINDOW,
        )
        for conversion in candidates.iterator():
            gross = _decimal(
                conversion.gross_amount_exact
                if conversion.gross_amount_exact is not None
                else conversion.from_amount
            )
            net = _decimal(
                conversion.net_amount_exact
                if conversion.net_amount_exact is not None
                else conversion.to_amount
            )
            if gross is None or net is None:
                continue
            if abs(gross - arrival) <= GRAIN and abs(net - allocated_net) <= GRAIN:
                exact.append(conversion)
                if len(exact) > 1:
                    break
        if len(exact) == 1:
            proposed[exact[0].pk].append((ramp, metadata, allocation))

    for conversion_id, matches in proposed.items():
        # Duplicate equal-sized deposits are intentionally left for manual
        # reconciliation rather than assigning one conversion arbitrarily.
        if len(matches) != 1:
            continue
        ramp, metadata, allocation = matches[0]
        replacement = Conversion.objects.get(pk=conversion_id)
        if ramp.conversion_id == replacement.pk:
            continue

        final_currency = (
            'CUSD+' if replacement.conversion_type == 'to_savings'
            else 'CUSD_BSC'
        )
        allocation.update({
            'gross_amount': format(
                _decimal(metadata.get('bsc_arrival_amount')), 'f'
            ),
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

        # Because this one ramp exactly consumes the conversion's entire
        # gross and net amounts, any other ramp linked to the same conversion
        # is necessarily a stale partial-prefix attribution. Restore those
        # rows to their truthful pre-conversion state instead of leaving one
        # conversion displayed against several unrelated deposits.
        stale_links = RampTransaction.objects.filter(
            conversion_id=replacement.pk,
            destination='cusd_plus',
            direction='on_ramp',
        ).exclude(pk=ramp.pk)
        for stale in stale_links.iterator():
            stale_metadata = dict(stale.metadata or {})
            stale_arrival = _decimal(stale_metadata.get('bsc_arrival_amount'))
            stale_metadata.pop('conversion_allocation', None)
            RampTransaction.objects.filter(pk=stale.pk).update(
                conversion_id=None,
                final_amount=(
                    stale.crypto_amount_actual
                    if stale.crypto_amount_actual is not None
                    else stale_arrival
                ),
                final_currency='USDT BSC',
                metadata=stale_metadata,
            )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('ramps', '0014_repair_bsc_ramp_conversion_links'),
    ]

    operations = [
        migrations.RunPython(repair_exact_links, noop_reverse),
    ]
