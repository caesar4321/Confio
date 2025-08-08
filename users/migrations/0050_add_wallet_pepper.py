# Generated migration for WalletPepper model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0049_add_aml_review_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='WalletPepper',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('firebase_uid', models.CharField(db_index=True, help_text='Firebase UID for wallet generation', max_length=128, unique=True)),
                ('pepper', models.CharField(help_text="Unique server pepper for this user's wallet", max_length=64, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(blank=True, help_text='User account (if authenticated)', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='wallet_pepper', to='users.user')),
            ],
            options={
                'verbose_name': 'Wallet Pepper',
                'verbose_name_plural': 'Wallet Peppers',
                'db_table': 'wallet_pepper',
            },
        ),
    ]