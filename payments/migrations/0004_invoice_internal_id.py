
def populate_internal_id(apps, schema_editor):
    Invoice = apps.get_model('payments', 'Invoice')
    import uuid
    for invoice in Invoice.objects.all():
        if not invoice.internal_id:
            invoice.internal_id = uuid.uuid4().hex
            invoice.save()

import payments.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0003_remove_paymenttransaction_payments_pa_payment_72dff5_idx_and_more'),
    ]
    operations = [
        migrations.AddField(
            model_name='invoice',
            name='internal_id',
            field=models.CharField(default=None, editable=False, max_length=32, null=True),
        ),
        migrations.RunPython(populate_internal_id, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='invoice',
            name='internal_id',
            field=models.CharField(default=payments.models.generate_payment_transaction_id, editable=False, max_length=32, unique=True),
        ),
        migrations.AlterField(
            model_name='invoice',
            name='internal_id',
            field=models.CharField(default=payments.models.generate_payment_transaction_id, editable=False, max_length=32, unique=True),
        ),
    ]
