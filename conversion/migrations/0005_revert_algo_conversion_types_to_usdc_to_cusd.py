from django.db import migrations, models


def forwards(apps, schema_editor):
    Conversion = apps.get_model('conversion', 'Conversion')
    Conversion.objects.filter(conversion_type='algo_to_cusd').update(conversion_type='usdc_to_cusd')
    Conversion.objects.filter(conversion_type='algo_to_usdc').update(conversion_type='usdc_to_cusd')


def backwards(apps, schema_editor):
    # Irreversible data normalization: keep current values on rollback.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('conversion', '0004_alter_conversion_type_algo_to_cusd'),
    ]

    operations = [
        migrations.AlterField(
            model_name='conversion',
            name='conversion_type',
            field=models.CharField(
                choices=[
                    ('usdc_to_cusd', 'USDC to cUSD'),
                    ('cusd_to_usdc', 'cUSD to USDC'),
                ],
                max_length=20,
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
