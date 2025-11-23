from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings
import payroll.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PayrollRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, help_text='Soft delete timestamp', null=True)),
                ('run_id', models.CharField(default=payroll.models.generate_run_id, editable=False, max_length=32, unique=True)),
                ('token_type', models.CharField(choices=[('CUSD', 'Confío Dollar'), ('CONFIO', 'Confío Token'), ('USDC', 'USD Coin')], default='CUSD', max_length=10)),
                ('period_seconds', models.BigIntegerField(blank=True, help_text='Cap window length in seconds', null=True)),
                ('cap_amount', models.DecimalField(blank=True, decimal_places=6, help_text='Optional gross cap per window (same decimals as token)', max_digits=19, null=True)),
                ('gross_total', models.DecimalField(decimal_places=6, default=0, max_digits=19)),
                ('net_total', models.DecimalField(decimal_places=6, default=0, max_digits=19)),
                ('fee_total', models.DecimalField(decimal_places=6, default=0, max_digits=19)),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('READY', 'Ready'), ('PARTIAL', 'Partial'), ('COMPLETED', 'Completed'), ('CANCELLED', 'Cancelled')], default='DRAFT', max_length=20)),
                ('scheduled_at', models.DateTimeField(blank=True, null=True)),
                ('business', models.ForeignKey(help_text='Business owning this payroll run', on_delete=django.db.models.deletion.CASCADE, related_name='payroll_runs', to='users.business')),
                ('created_by_user', models.ForeignKey(help_text='User who created the payroll run', on_delete=django.db.models.deletion.CASCADE, related_name='payroll_runs_created', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='PayrollItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, help_text='Soft delete timestamp', null=True)),
                ('item_id', models.CharField(default=payroll.models.generate_payroll_item_id, editable=False, max_length=32, unique=True)),
                ('token_type', models.CharField(choices=[('CUSD', 'Confío Dollar'), ('CONFIO', 'Confío Token'), ('USDC', 'USD Coin')], default='CUSD', max_length=10)),
                ('net_amount', models.DecimalField(decimal_places=6, max_digits=19)),
                ('gross_amount', models.DecimalField(decimal_places=6, max_digits=19)),
                ('fee_amount', models.DecimalField(decimal_places=6, max_digits=19)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('PREPARED', 'Prepared'), ('SUBMITTED', 'Submitted'), ('CONFIRMED', 'Confirmed'), ('FAILED', 'Failed'), ('CANCELLED', 'Cancelled')], default='PENDING', max_length=20)),
                ('transaction_hash', models.CharField(blank=True, help_text='Blockchain transaction hash', max_length=66)),
                ('blockchain_data', models.JSONField(blank=True, help_text='Unsigned transactions and metadata', null=True)),
                ('error_message', models.TextField(blank=True)),
                ('executed_at', models.DateTimeField(blank=True, null=True)),
                ('executed_by_user', models.ForeignKey(blank=True, help_text='Delegate who executed the payout', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payroll_items_executed', to=settings.AUTH_USER_MODEL)),
                ('recipient_account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payroll_items_received', to='users.account')),
                ('recipient_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payroll_items_received', to=settings.AUTH_USER_MODEL)),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='payroll.payrollrun')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='payrollrun',
            index=models.Index(fields=['run_id'], name='payrollrun_run_id_8b1c37_idx'),
        ),
        migrations.AddIndex(
            model_name='payrollrun',
            index=models.Index(fields=['business', 'status'], name='payrollrun_business_42e8c2_idx'),
        ),
        migrations.AddIndex(
            model_name='payrollrun',
            index=models.Index(fields=['created_by_user'], name='payrollrun_created_fa7c14_idx'),
        ),
        migrations.AddIndex(
            model_name='payrollitem',
            index=models.Index(fields=['item_id'], name='payrollitem_item_id_e5e3f2_idx'),
        ),
        migrations.AddIndex(
            model_name='payrollitem',
            index=models.Index(fields=['run', 'status'], name='payrollitem_run_id_dac8f4_idx'),
        ),
        migrations.AddIndex(
            model_name='payrollitem',
            index=models.Index(fields=['recipient_user'], name='payrollitem_recipient_302316_idx'),
        ),
        migrations.AddIndex(
            model_name='payrollitem',
            index=models.Index(fields=['recipient_account'], name='payrollitem_recipient_1014f6_idx'),
        ),
    ]
