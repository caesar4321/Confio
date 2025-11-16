from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_last_activity_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='unifiedtransactiontable',
            name='transaction_type',
            field=models.CharField(
                choices=[
                    ('send', 'Send/Receive'),
                    ('payment', 'Payment'),
                    ('conversion', 'Conversion'),
                    ('exchange', 'P2P Exchange'),
                    ('reward', 'Reward'),
                    ('presale', 'Presale Purchase'),
                ],
                db_index=True,
                max_length=10,
            ),
        ),
    ]

