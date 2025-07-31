# Generated manually
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usdc_transactions', '0008_create_unified_usdc_transaction_table'),
    ]

    operations = [
        migrations.AlterField(
            model_name='unifiedusdctransactiontable',
            name='created_at',
            field=models.DateTimeField(help_text='When the transaction was created'),
        ),
    ]