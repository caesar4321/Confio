from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('presale', '0010_presalepurchase_funding_source')]

    operations = [
        migrations.AlterField(
            model_name='presalepurchase',
            name='funding_source',
            field=models.CharField(
                choices=[
                    ('algorand_cusd', 'Legacy cUSD (Algorand)'),
                    ('cusd_redeem', 'cUSD redeemed with the universal fee'),
                    ('cusd_plus_via_cusd', 'cUSD+ normalized through cUSD, then redeemed'),
                ],
                default='algorand_cusd',
                help_text='Which balance funded this purchase',
                max_length=20,
            ),
        ),
    ]
