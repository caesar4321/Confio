from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payment_accounts', '0023_automatic_payin')]

    operations = [migrations.AlterField(
        model_name='financialaccount',
        name='payin_document_country',
        field=models.CharField(
            max_length=2, blank=True, default='',
            help_text='Legacy sender document jurisdiction (ISO-2), retained for historical reference. Not used by name-based pay-in admission.',
        ),
    )]
