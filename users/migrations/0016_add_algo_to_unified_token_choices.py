from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0015_add_presale_fk'),
    ]

    operations = [
        migrations.AlterField(
            model_name='unifiedtransactiontable',
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
