# Generated by Django 4.2.20 on 2025-07-01 23:34

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('prover', '0003_remove_zkloginproof_profile'),
        ('users', '0004_user_auth_token_version'),
    ]

    operations = [
        migrations.CreateModel(
            name='Account',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('account_type', models.CharField(choices=[('personal', 'Personal'), ('business', 'Business')], default='personal', help_text='Type of account (personal or business)', max_length=10)),
                ('account_index', models.PositiveIntegerField(default=0, help_text='Index of the account within its type (0, 1, 2, etc.)')),
                ('sui_address', models.CharField(blank=True, help_text='Last‑computed Sui address for this account', max_length=66, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_login_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'ordering': ['user', 'account_type', 'account_index'],
            },
        ),
        migrations.CreateModel(
            name='Business',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Business name', max_length=255)),
                ('description', models.TextField(blank=True, help_text='Business description', null=True)),
                ('category', models.CharField(choices=[('food', 'Comida y Bebidas'), ('retail', 'Comercio y Ventas'), ('services', 'Servicios Profesionales'), ('health', 'Belleza y Salud'), ('transport', 'Transporte y Delivery'), ('other', 'Otros Negocios')], help_text='Business category', max_length=20)),
                ('business_registration_number', models.CharField(blank=True, help_text='Business registration number or tax ID', max_length=20, null=True)),
                ('address', models.TextField(blank=True, help_text='Business address', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name_plural': 'Businesses',
                'ordering': ['name'],
            },
        ),
        migrations.DeleteModel(
            name='UserProfile',
        ),
        migrations.AddField(
            model_name='account',
            name='business',
            field=models.ForeignKey(blank=True, help_text='Associated business for business accounts', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='accounts', to='users.business'),
        ),
        migrations.AddField(
            model_name='account',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='accounts', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterUniqueTogether(
            name='account',
            unique_together={('user', 'account_type', 'account_index')},
        ),
    ]
