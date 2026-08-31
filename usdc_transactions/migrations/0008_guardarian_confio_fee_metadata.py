from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('usdc_transactions', '0007_guardariantransaction_account')]

    operations = [
        migrations.AddField(
            model_name='guardariantransaction',
            name='confio_fee_metadata',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Immutable Confío gross/fee/net preview attached to the provider order',
            ),
        ),
    ]
