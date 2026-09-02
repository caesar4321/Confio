from decimal import Decimal, InvalidOperation

from django.db import migrations


GRAIN = Decimal('0.000001')


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def detach_stale_siblings(apps, schema_editor):
    RampTransaction = apps.get_model('ramps', 'RampTransaction')
    Conversion = apps.get_model('conversion', 'Conversion')

    conversions = Conversion.objects.filter(
        source='ramp',
        status='COMPLETED',
        conversion_type__in=('to_savings', 'usdt_to_cusd'),
        ramp_transactions__isnull=False,
    ).distinct()
    for conversion in conversions.iterator():
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

        exact = []
        linked = list(RampTransaction.objects.filter(
            conversion_id=conversion.pk,
            destination='cusd_plus',
            direction='on_ramp',
        ))
        for ramp in linked:
            metadata = dict(ramp.metadata or {})
            arrival = _decimal(metadata.get('bsc_arrival_amount'))
            allocation = dict(metadata.get('conversion_allocation') or {})
            allocated_net = _decimal(allocation.get('net_amount'))
            if arrival is None or allocated_net is None:
                continue
            if abs(arrival - gross) <= GRAIN and abs(allocated_net - net) <= GRAIN:
                exact.append(ramp.pk)

        # One exact row consumes the entire conversion. Any siblings are
        # impossible remnants of the former partial-prefix matcher.
        if len(exact) != 1:
            continue
        owner_pk = exact[0]
        for stale in linked:
            if stale.pk == owner_pk:
                continue
            stale_metadata = dict(stale.metadata or {})
            arrival = _decimal(stale_metadata.get('bsc_arrival_amount'))
            stale_metadata.pop('conversion_allocation', None)
            RampTransaction.objects.filter(pk=stale.pk).update(
                conversion_id=None,
                final_amount=(
                    stale.crypto_amount_actual
                    if stale.crypto_amount_actual is not None
                    else arrival
                ),
                final_currency='USDT BSC',
                metadata=stale_metadata,
            )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('ramps', '0015_repair_exact_bsc_ramp_conversion_links'),
    ]

    operations = [
        migrations.RunPython(detach_stale_siblings, noop_reverse),
    ]
