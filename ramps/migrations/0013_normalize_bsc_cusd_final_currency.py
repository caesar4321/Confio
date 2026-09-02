from django.db import migrations


def normalize_bsc_cusd(apps, schema_editor):
    RampTransaction = apps.get_model('ramps', 'RampTransaction')
    RampTransaction.objects.filter(
        destination='cusd_plus',
        conversion__conversion_type='usdt_to_cusd',
        final_currency='CUSD',
    ).update(final_currency='CUSD_BSC')


def reverse_normalization(apps, schema_editor):
    # This is display normalization only. Reversing it would deliberately
    # reintroduce the ambiguous label, so preserve the canonical value.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('conversion', '0013_cusd_fee_scan_state'),
        ('ramps', '0012_alter_ramptransaction_provider'),
    ]

    operations = [
        migrations.RunPython(normalize_bsc_cusd, reverse_normalization),
    ]
