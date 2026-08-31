from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0040_account_wallet_reenrollment_assessment'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='unifiedtransactiontable',
            name='unified_token_type_canonical',
        ),
        migrations.AlterField(
            model_name='unifiedtransactiontable',
            name='token_type',
            field=models.CharField(
                choices=[
                    ('CUSD', 'Confío Dollar'),
                    ('CUSD_BSC', 'Confío Dollar (BSC)'),
                    ('CONFIO', 'Confío Token'),
                    ('USDC', 'USD Coin'),
                    ('ALGO', 'ALGO'),
                    ('CUSD_PLUS', 'Confío Dollar Plus'),
                    ('USDT', 'Tether USD'),
                ],
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name='unifiedtransactiontable',
            constraint=models.CheckConstraint(
                condition=models.Q(token_type__in=[
                    'ALGO', 'CONFIO', 'CUSD', 'CUSD_BSC', 'CUSD_PLUS',
                    'USDC', 'USDT',
                ]),
                name='unified_token_type_canonical',
            ),
        ),
    ]
