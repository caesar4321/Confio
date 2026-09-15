from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('users', '0043_bankinfo_breb_key_length'),
                    ('payment_accounts', '0021_journey_wallet_conversion')]
    operations = [
        migrations.AddField(model_name='unifiedtransactiontable', name='local_money_flow',
            field=models.OneToOneField(null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='unified_transaction', to='payment_accounts.moneyflow')),
        migrations.AlterField(model_name='unifiedtransactiontable', name='transaction_type',
            field=models.CharField(max_length=20, db_index=True, choices=[
                ('send', 'Send/Receive'), ('payment', 'Payment'), ('payroll', 'Payroll'),
                ('conversion', 'Conversion'), ('exchange', 'P2P Exchange'), ('reward', 'Reward'),
                ('presale', 'Presale Purchase'), ('ramp', 'Ramp'),
                ('local_transfer', 'Local transfer'), ('humanitarian', 'Humanitarian Aid')]))]
