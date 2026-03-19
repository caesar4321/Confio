from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('p2p_exchange', '0003_p2ptrade_internal_id'),
        ('users', '0017_bankinfo_provider_metadata'),
    ]

    operations = [
        migrations.CreateModel(
            name='RampPaymentMethod',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, help_text='Soft delete timestamp', null=True)),
                ('code', models.CharField(help_text='Provider code, e.g. WIREPE or QRI-PE', max_length=50)),
                ('country_code', models.CharField(help_text='ISO country code', max_length=2)),
                ('display_name', models.CharField(max_length=100)),
                ('provider_type', models.CharField(choices=[('bank', 'Traditional Bank'), ('fintech', 'Fintech/Digital Wallet'), ('cash', 'Cash/Physical'), ('other', 'Other')], default='other', max_length=10)),
                ('description', models.TextField(blank=True)),
                ('icon', models.CharField(blank=True, max_length=50)),
                ('is_active', models.BooleanField(default=True)),
                ('display_order', models.IntegerField(default=0)),
                ('requires_phone', models.BooleanField(default=False)),
                ('requires_email', models.BooleanField(default=False)),
                ('requires_account_number', models.BooleanField(default=True)),
                ('requires_identification', models.BooleanField(default=False)),
                ('supports_on_ramp', models.BooleanField(default=False)),
                ('supports_off_ramp', models.BooleanField(default=False)),
                ('field_schema', models.JSONField(blank=True, default=dict, help_text='Server-owned field schema for AddBankInfo and payout destination capture.')),
                ('bank', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='ramp_payment_methods', to='users.bank')),
                ('country', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='ramp_payment_methods', to='users.country')),
                ('legacy_payment_method', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ramp_payment_methods', to='p2p_exchange.p2ppaymentmethod')),
            ],
            options={
                'ordering': ['country_code', 'display_order', 'display_name'],
                'unique_together': {('code', 'country_code')},
            },
        ),
    ]

