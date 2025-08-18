from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0061_update_invitation_trigger_phone_key'),
    ]

    operations = [
        migrations.CreateModel(
            name='WalletDerivationPepper',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('account_key', models.CharField(db_index=True, help_text='Unique key per account: user_{id}_{type}_{index} or user_{id}_business_{businessId}_{index}', max_length=255, unique=True)),
                ('pepper', models.CharField(help_text='Non-rotating pepper for derivation; changing it changes addresses', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'user_wallet_derivation_pepper',
                'ordering': ['-created_at'],
                'verbose_name': 'Account Derivation Pepper',
                'verbose_name_plural': 'Account Derivation Peppers',
            },
        ),
    ]
