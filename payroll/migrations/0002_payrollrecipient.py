from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
        ('payroll', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PayrollRecipient',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, help_text='Soft delete timestamp', null=True)),
                ('display_name', models.CharField(blank=True, help_text='Friendly name for the recipient', max_length=255)),
                ('business', models.ForeignKey(help_text='Business that will pay this recipient', on_delete=django.db.models.deletion.CASCADE, related_name='payroll_recipients', to='users.business')),
                ('recipient_account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payroll_recipients_accounts', to='users.account')),
                ('recipient_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payroll_recipients_for_businesses', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='payrollrecipient',
            index=models.Index(fields=['business', 'recipient_user'], name='payrollrecipient_business_recipient_user_idx'),
        ),
        migrations.AddIndex(
            model_name='payrollrecipient',
            index=models.Index(fields=['business', 'recipient_account'], name='payrollrecipient_business_recipient_account_idx'),
        ),
        migrations.AddConstraint(
            model_name='payrollrecipient',
            constraint=models.UniqueConstraint(condition=models.Q(('deleted_at__isnull', True)), fields=('business', 'recipient_user', 'recipient_account'), name='unique_payroll_recipient_per_business'),
        ),
    ]
