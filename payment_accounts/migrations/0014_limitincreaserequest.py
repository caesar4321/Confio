import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('payment_accounts', '0013_infiniajourney_minimum_wallet_output'),
        ('users', '0043_bankinfo_breb_key_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='LimitIncreaseRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('internal_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('provider', models.CharField(choices=[('cobre', 'Cobre'), ('infinia', 'Infinia')], default='infinia', max_length=20)),
                ('status', models.CharField(choices=[('started', 'Verification started'), ('submitted', 'Submitted'), ('in_review', 'In review'), ('forwarded', 'Forwarded to provider'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('needs_more_info', 'Needs more information')], default='started', max_length=20)),
                ('income_type', models.CharField(choices=[('employed', 'Employed'), ('self_employed', 'Self-employed'), ('not_employed', 'Not employed'), ('business', 'Business')], max_length=20)),
                ('occupation', models.CharField(blank=True, default='', max_length=120)),
                ('expected_monthly_usd', models.DecimalField(decimal_places=2, max_digits=20)),
                ('source_of_funds', models.CharField(choices=[('salary', 'Salary'), ('business_income', 'Business income'), ('savings', 'Savings'), ('investments', 'Investments'), ('family_support', 'Family support'), ('other', 'Other')], max_length=20)),
                ('didit_session_id', models.CharField(blank=True, max_length=80, null=True, unique=True)),
                ('didit_status', models.CharField(blank=True, default='', max_length=30)),
                ('evidence', models.JSONField(blank=True, default=dict, help_text='Didit decision facts; never presigned media URLs.')),
                ('provider_documents', models.JSONField(blank=True, default=dict, help_text='Provider document IDs after forwarding.')),
                ('forwarded_at', models.DateTimeField(blank=True, null=True)),
                ('reviewer_note', models.TextField(blank=True, default='', help_text='Internal only.')),
                ('user_message', models.CharField(blank=True, default='', help_text='Shown to the user in the app.', max_length=255)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('confio_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='limit_increase_requests', to='users.account')),
            ],
            options={
                'indexes': [models.Index(fields=['status', 'created_at'], name='limit_increase_status_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('status__in', ['started', 'submitted', 'in_review', 'forwarded'])), fields=('confio_account',), name='limit_increase_one_open_uniq')],
            },
        ),
    ]
