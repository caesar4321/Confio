from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('send', '0020_fix_empty_transaction_hashes'),
    ]

    operations = [
        migrations.CreateModel(
            name='PhoneInvite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, help_text='Soft delete timestamp', null=True)),
                ('invitation_id', models.CharField(max_length=64, unique=True)),
                ('phone_key', models.CharField(db_index=True, max_length=32)),
                ('phone_country', models.CharField(blank=True, max_length=2)),
                ('phone_number', models.CharField(max_length=20)),
                ('amount', models.DecimalField(decimal_places=6, max_digits=19)),
                ('token_type', models.CharField(choices=[('cUSD', 'Confío Dollar'), ('CONFIO', 'Confío Token'), ('USDC', 'USD Coin')], max_length=10)),
                ('message', models.CharField(blank=True, max_length=256)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('claimed', 'Claimed'), ('reclaimed', 'Reclaimed')], default='pending', max_length=16)),
                ('claimed_at', models.DateTimeField(blank=True, null=True)),
                ('claimed_txid', models.CharField(blank=True, max_length=66)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('claimed_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='phone_invites_claimed', to=settings.AUTH_USER_MODEL)),
                ('inviter_user', models.ForeignKey(null=True, on_delete=models.deletion.SET_NULL, related_name='phone_invites_sent', to=settings.AUTH_USER_MODEL)),
                ('send_transaction', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name='phone_invite', to='send.sendtransaction')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='phoneinvite',
            index=models.Index(fields=['phone_key', 'status'], name='idx_phoneinvite_phonekey_status'),
        ),
        migrations.AddIndex(
            model_name='phoneinvite',
            index=models.Index(fields=['invitation_id'], name='idx_phoneinvite_invitation'),
        ),
    ]

