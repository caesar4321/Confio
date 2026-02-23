from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('send', '0004_alter_sendtransaction_internal_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sendtransaction',
            name='token_type',
            field=models.CharField(
                choices=[
                    ('CUSD', 'Confío Dollar'),
                    ('CONFIO', 'Confío Token'),
                    ('USDC', 'USD Coin'),
                    ('ALGO', 'ALGO'),
                ],
                max_length=10,
            ),
        ),
    ]
