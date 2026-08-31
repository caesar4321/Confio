from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('presale', '0012_exact_bsc_amount_and_legacy_funding')]

    operations = [
        migrations.AlterField(
            model_name='presalepurchase',
            name='funding_source',
            field=models.CharField(
                choices=[
                    ('algorand_cusd', 'Legacy cUSD (Algorand)'),
                    ('cusd_redeem', 'Legacy cUSD redeemed with the universal fee'),
                    ('cusd_direct', 'cUSD paid directly'),
                    ('cusd_plus_via_cusd', 'cUSD+ normalized to cUSD internally'),
                ],
                default='algorand_cusd',
                help_text='Which balance funded this purchase',
                max_length=20,
            ),
        ),
    ]
