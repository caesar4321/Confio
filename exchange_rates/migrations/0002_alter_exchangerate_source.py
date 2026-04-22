from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exchange_rates', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='exchangerate',
            name='source',
            field=models.CharField(
                choices=[
                    ('yadio', 'Yadio.io'),
                    ('exchangerate_api', 'ExchangeRate-API'),
                    ('currencylayer', 'CurrencyLayer'),
                    ('binance_p2p', 'Binance P2P'),
                    ('bluelytics', 'Bluelytics (Argentina)'),
                    ('dolarapi', 'DolarAPI (Argentina)'),
                    ('bcv', 'Banco Central de Venezuela'),
                    ('manual', 'Manual Entry'),
                ],
                max_length=50,
            ),
        ),
    ]
