from django.db import migrations


def restore_unconverted_gross(apps, schema_editor):
    RampTransaction = apps.get_model('ramps', 'RampTransaction')

    rows = RampTransaction.objects.filter(
        destination='cusd_plus',
        direction='on_ramp',
        status='COMPLETED',
        conversion__isnull=True,
        final_currency='USDT BSC',
    )
    for ramp in rows.iterator():
        gross = ramp.crypto_amount_actual or ramp.crypto_amount_estimated
        if gross is None or ramp.final_amount == gross:
            continue
        RampTransaction.objects.filter(pk=ramp.pk).update(final_amount=gross)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('ramps', '0016_detach_stale_exact_conversion_siblings'),
    ]

    operations = [
        migrations.RunPython(restore_unconverted_gross, noop_reverse),
    ]
