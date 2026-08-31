from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('conversion', '0011_conversion_bsc_cusd_types'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='conversion',
            constraint=models.UniqueConstraint(
                condition=(
                    models.Q(contract_event_index__isnull=False)
                    & models.Q(to_transaction_hash__isnull=False)
                    & ~models.Q(to_transaction_hash='')
                ),
                fields=('to_transaction_hash', 'contract_event_index'),
                name='uniq_conversion_contract_event',
            ),
        ),
    ]
