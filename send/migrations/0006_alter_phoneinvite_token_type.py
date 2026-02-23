from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('send', '0005_add_algo_token_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='phoneinvite',
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
