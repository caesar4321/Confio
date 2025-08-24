from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    initial = False

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('users', '0061_update_invitation_trigger_phone_key'),
        ('p2p_exchange', '0032_remove_available_amount_from_p2poffer'),
    ]

    operations = [
        migrations.CreateModel(
            name='PremiumUpgradeRequest',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, help_text='Soft delete timestamp', null=True)),
                ('reason', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('pending', 'Pending Review'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=16)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_notes', models.TextField(blank=True)),
                ('business', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name='premium_upgrade_requests', to='users.business')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='reviewed_premium_requests', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name='premium_upgrade_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]

