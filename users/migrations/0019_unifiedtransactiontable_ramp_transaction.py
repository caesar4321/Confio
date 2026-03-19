from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ramps', '0002_ramptransaction'),
        ('users', '0018_bankinfo_ramp_payment_method'),
    ]

    operations = [
        migrations.AlterField(
            model_name='unifiedtransactiontable',
            name='transaction_type',
            field=models.CharField(choices=[('send', 'Send/Receive'), ('payment', 'Payment'), ('payroll', 'Payroll'), ('conversion', 'Conversion'), ('exchange', 'P2P Exchange'), ('reward', 'Reward'), ('presale', 'Presale Purchase'), ('ramp', 'Ramp')], db_index=True, max_length=10),
        ),
        migrations.AddField(
            model_name='unifiedtransactiontable',
            name='ramp_transaction',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='unified_transaction', to='ramps.ramptransaction'),
        ),
    ]
