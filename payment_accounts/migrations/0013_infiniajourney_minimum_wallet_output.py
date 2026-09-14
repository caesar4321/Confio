from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payment_accounts', '0012_paymentbridgetransfer_funding_mode')]
    operations = [migrations.AddField(
        model_name='infiniajourney', name='minimum_wallet_output',
        field=models.DecimalField(max_digits=38, decimal_places=18, null=True, blank=True),
    )]
