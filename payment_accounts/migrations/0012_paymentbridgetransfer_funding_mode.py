from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payment_accounts', '0011_financialaccount_payin_document_country_and_more')]
    operations = [migrations.AddField(
        model_name='paymentbridgetransfer', name='funding_mode',
        field=models.CharField(max_length=24, default='wallet', choices=[
            ('wallet', 'Wallet signature'), ('infinia', 'Infinia payout'),
        ]),
    )]
