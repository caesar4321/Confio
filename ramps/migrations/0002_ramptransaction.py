from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('conversion', '0005_revert_algo_conversion_types_to_usdc_to_cusd'),
        ('ramps', '0001_initial'),
        ('usdc_transactions', '0004_remove_usdcdeposit_usdc_deposi_deposit_d05aca_idx_and_more'),
        ('users', '0018_bankinfo_ramp_payment_method'),
    ]

    operations = [
        migrations.CreateModel(
            name='RampTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('internal_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('provider', models.CharField(choices=[('guardarian', 'Guardarian'), ('koywe', 'Koywe')], max_length=20)),
                ('direction', models.CharField(choices=[('on_ramp', 'On Ramp'), ('off_ramp', 'Off Ramp')], max_length=10)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('PROCESSING', 'Processing'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed'), ('AML_REVIEW', 'AML Review')], default='PENDING', max_length=20)),
                ('provider_order_id', models.CharField(blank=True, max_length=100)),
                ('external_id', models.CharField(blank=True, max_length=100)),
                ('country_code', models.CharField(blank=True, max_length=2)),
                ('actor_type', models.CharField(choices=[('user', 'Personal'), ('business', 'Business')], default='user', max_length=10)),
                ('actor_display_name', models.CharField(blank=True, max_length=255)),
                ('actor_address', models.CharField(blank=True, default='', max_length=66)),
                ('fiat_currency', models.CharField(blank=True, max_length=20)),
                ('fiat_amount', models.DecimalField(blank=True, decimal_places=6, max_digits=19, null=True)),
                ('crypto_currency', models.CharField(blank=True, max_length=20)),
                ('crypto_amount_estimated', models.DecimalField(blank=True, decimal_places=6, max_digits=19, null=True)),
                ('crypto_amount_actual', models.DecimalField(blank=True, decimal_places=6, max_digits=19, null=True)),
                ('final_currency', models.CharField(default='CUSD', max_length=20)),
                ('final_amount', models.DecimalField(blank=True, decimal_places=6, max_digits=19, null=True)),
                ('status_detail', models.TextField(blank=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('actor_business', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='ramp_transactions', to='users.business')),
                ('actor_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='ramp_transactions', to='users.user')),
                ('conversion', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ramp_transaction', to='conversion.conversion')),
                ('guardarian_transaction', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ramp_transaction', to='usdc_transactions.guardariantransaction')),
                ('usdc_deposit', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ramp_transaction', to='usdc_transactions.usdcdeposit')),
                ('usdc_withdrawal', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ramp_transaction', to='usdc_transactions.usdcwithdrawal')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='ramptransaction',
            index=models.Index(fields=['provider', 'direction', '-created_at'], name='ramps_rampt_provide_e3d64c_idx'),
        ),
        migrations.AddIndex(
            model_name='ramptransaction',
            index=models.Index(fields=['actor_user', '-created_at'], name='ramps_rampt_actor_u_f8d7c1_idx'),
        ),
        migrations.AddIndex(
            model_name='ramptransaction',
            index=models.Index(fields=['actor_business', '-created_at'], name='ramps_rampt_actor_b_3e8f58_idx'),
        ),
        migrations.AddIndex(
            model_name='ramptransaction',
            index=models.Index(fields=['status', '-created_at'], name='ramps_rampt_status_d1bcca_idx'),
        ),
        migrations.AddIndex(
            model_name='ramptransaction',
            index=models.Index(fields=['provider_order_id'], name='ramps_rampt_provide_4f3dad_idx'),
        ),
        migrations.AddIndex(
            model_name='ramptransaction',
            index=models.Index(fields=['external_id'], name='ramps_rampt_externa_98e5bc_idx'),
        ),
    ]
