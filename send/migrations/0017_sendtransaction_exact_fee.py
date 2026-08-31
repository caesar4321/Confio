from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('send', '0016_reclassify_legacy_bsc_invite_status')]

    operations = [
        migrations.AddField(
            model_name='sendtransaction',
            name='fee_amount',
            field=models.DecimalField(
                decimal_places=18,
                default=0,
                help_text='Exact finalized Confío conversion fee; zero for internal sends.',
                max_digits=38,
            ),
        ),
        migrations.AddField(
            model_name='sendtransaction',
            name='net_amount',
            field=models.DecimalField(
                blank=True,
                decimal_places=18,
                help_text='Exact finalized recipient amount; defaults to amount for legacy/internal sends.',
                max_digits=38,
                null=True,
            ),
        ),
    ]
