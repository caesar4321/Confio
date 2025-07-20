# Generated manually to rename Transaction to SendTransaction

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('send', '0004_alter_transaction_token_type'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='Transaction',
            new_name='SendTransaction',
        ),
    ] 