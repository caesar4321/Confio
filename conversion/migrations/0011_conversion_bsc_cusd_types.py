from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('conversion', '0010_conversion_exact_fee_ledger'),
    ]

    operations = [
        migrations.AlterField(
            model_name='conversion',
            name='conversion_type',
            field=models.CharField(
                choices=[
                    ('usdc_to_cusd', 'USDC to cUSD'),
                    ('cusd_to_usdc', 'cUSD to USDC'),
                    ('usdc_to_algo', 'USDC to ALGO'),
                    ('to_savings', 'USDT -> cUSD+ (Ahorrar)'),
                    ('from_savings', 'cUSD+ -> USDT (Retirar)'),
                    ('usdt_to_cusd', 'USDT -> cUSD (BSC)'),
                    ('cusd_to_usdt', 'cUSD -> USDT (BSC)'),
                ],
                max_length=20,
            ),
        ),
    ]
