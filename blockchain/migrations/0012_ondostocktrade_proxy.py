from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('blockchain', '0011_payment_unique_by_source'),
    ]

    operations = [
        migrations.CreateModel(
            name='OndoStockTrade',
            fields=[],
            options={
                'verbose_name': 'Ondo stock trade',
                'verbose_name_plural': 'Ondo stock trades',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('blockchain.sponsoredbatch',),
        ),
    ]
