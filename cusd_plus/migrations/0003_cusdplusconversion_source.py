# Hand-written (makemigrations needs live AWS settings); mirrors models.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cusd_plus', '0002_cusdplusconversion_bridge_arrival_tx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='cusdplusconversion',
            name='source',
            field=models.CharField(
                choices=[
                    ('convert', 'In-app conversion (user-quoted)'),
                    ('external_deposit', 'External USDT-BSC deposit'),
                    ('ramp', 'Ramp (Koywe) delivery'),
                ],
                default='convert',
                max_length=20,
            ),
        ),
    ]
