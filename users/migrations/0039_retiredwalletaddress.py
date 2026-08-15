from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0038_unified_stock_sponsored_batch'),
    ]

    operations = [
        migrations.CreateModel(
            name='RetiredWalletAddress',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chain', models.CharField(choices=[('algorand', 'Algorand'), ('bsc', 'BSC')], max_length=16)),
                ('address', models.CharField(max_length=66)),
                ('retired_at', models.DateTimeField(auto_now_add=True)),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='retired_wallet_addresses', to='users.account')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='retired_wallet_addresses', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name='retiredwalletaddress',
            constraint=models.UniqueConstraint(fields=('chain', 'address'), name='uniq_retired_wallet_chain_address'),
        ),
        migrations.AddIndex(
            model_name='retiredwalletaddress',
            index=models.Index(fields=['account', 'chain'], name='ret_wallet_account_chain_idx'),
        ),
        migrations.AddIndex(
            model_name='retiredwalletaddress',
            index=models.Index(fields=['user', 'chain'], name='ret_wallet_user_chain_idx'),
        ),
    ]
