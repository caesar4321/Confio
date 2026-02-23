from django.db import migrations, models


def forwards(apps, schema_editor):
    Conversion = apps.get_model('conversion', 'Conversion')
    Conversion.objects.filter(conversion_type='algo_to_usdc').update(conversion_type='algo_to_cusd')


def backwards(apps, schema_editor):
    Conversion = apps.get_model('conversion', 'Conversion')
    Conversion.objects.filter(conversion_type='algo_to_cusd').update(conversion_type='algo_to_usdc')


class Migration(migrations.Migration):

    dependencies = [
        ('conversion', '0003_remove_conversion_conversions_convers_21da52_idx_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='conversion',
            name='conversion_type',
            field=models.CharField(
                choices=[
                    ('usdc_to_cusd', 'USDC to cUSD'),
                    ('cusd_to_usdc', 'cUSD to USDC'),
                    ('algo_to_cusd', 'ALGO to cUSD (Atomic path)'),
                ],
                max_length=20,
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
