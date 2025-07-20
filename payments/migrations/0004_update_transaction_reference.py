# Generated manually to update foreign key reference

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('send', '0005_rename_transaction_to_sendtransaction'),
        ('payments', '0003_add_payment_transaction'),
    ]

    operations = [
        migrations.AlterField(
            model_name='invoice',
            name='transaction',
            field=models.ForeignKey(
                blank=True,
                help_text='DEPRECATED: Use payment_transactions instead',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='invoice',
                to='send.sendtransaction'
            ),
        ),
    ] 