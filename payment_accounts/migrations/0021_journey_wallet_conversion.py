from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('payment_accounts', '0020_activation_opening_retry'),
                    ('conversion', '0013_cusd_fee_scan_state')]
    operations = [migrations.AddField(
        model_name='infiniajourney', name='wallet_conversion',
        field=models.OneToOneField(null=True, blank=True,
            on_delete=django.db.models.deletion.PROTECT,
            related_name='local_transfer_journey', to='conversion.conversion'))]
