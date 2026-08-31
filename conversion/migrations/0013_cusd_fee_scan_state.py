from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('conversion', '0012_unique_contract_fee_event'),
    ]

    operations = [
        migrations.CreateModel(
            name='CusdFeeScanState',
            fields=[
                ('chain_id', models.PositiveBigIntegerField(primary_key=True, serialize=False)),
                ('last_finalized_block', models.PositiveBigIntegerField(default=0)),
                ('last_finalized_hash', models.CharField(blank=True, default='', max_length=66)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'cusd_fee_scan_state'},
        ),
    ]
