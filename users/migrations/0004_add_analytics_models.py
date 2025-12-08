# Generated manually for DAU/WAU/MAU analytics models

from django.db import migrations, models
import django.core.validators
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_add_presale_transaction_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyMetrics',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(db_index=True, help_text='Date of this metrics snapshot (typically yesterday)', unique=True)),
                ('dau', models.IntegerField(help_text='Daily Active Users - users active in last 24 hours', validators=[django.core.validators.MinValueValidator(0)])),
                ('wau', models.IntegerField(help_text='Weekly Active Users - users active in last 7 days', validators=[django.core.validators.MinValueValidator(0)])),
                ('mau', models.IntegerField(help_text='Monthly Active Users - users active in last 30 days', validators=[django.core.validators.MinValueValidator(0)])),
                ('total_users', models.IntegerField(help_text='Total registered users as of this date', validators=[django.core.validators.MinValueValidator(0)])),
                ('new_users_today', models.IntegerField(default=0, help_text='New user signups on this date', validators=[django.core.validators.MinValueValidator(0)])),
                ('dau_mau_ratio', models.DecimalField(decimal_places=4, help_text='DAU/MAU ratio - engagement indicator (0.0 to 1.0)', max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal('0'))])),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='When this snapshot was created')),
            ],
            options={
                'verbose_name': 'Daily Metrics',
                'verbose_name_plural': 'Daily Metrics',
                'ordering': ['-date'],
            },
        ),
        migrations.CreateModel(
            name='CountryMetrics',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(db_index=True, help_text='Date of this metrics snapshot')),
                ('country_code', models.CharField(db_index=True, help_text='ISO 3166-1 alpha-2 country code (e.g., VE, AR, CO)', max_length=2)),
                ('dau', models.IntegerField(help_text='Daily Active Users from this country', validators=[django.core.validators.MinValueValidator(0)])),
                ('wau', models.IntegerField(help_text='Weekly Active Users from this country', validators=[django.core.validators.MinValueValidator(0)])),
                ('mau', models.IntegerField(help_text='Monthly Active Users from this country', validators=[django.core.validators.MinValueValidator(0)])),
                ('total_users', models.IntegerField(help_text='Total registered users from this country', validators=[django.core.validators.MinValueValidator(0)])),
                ('new_users_today', models.IntegerField(default=0, help_text='New signups from this country on this date', validators=[django.core.validators.MinValueValidator(0)])),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='When this snapshot was created')),
            ],
            options={
                'verbose_name': 'Country Metrics',
                'verbose_name_plural': 'Country Metrics',
                'ordering': ['-date', 'country_code'],
                'unique_together': {('date', 'country_code')},
            },
        ),
        migrations.AddIndex(
            model_name='dailymetrics',
            index=models.Index(fields=['-date'], name='users_daily_date_idx'),
        ),
        migrations.AddIndex(
            model_name='dailymetrics',
            index=models.Index(fields=['created_at'], name='users_daily_created_idx'),
        ),
        migrations.AddIndex(
            model_name='countrymetrics',
            index=models.Index(fields=['-date', 'country_code'], name='users_country_date_country_idx'),
        ),
        migrations.AddIndex(
            model_name='countrymetrics',
            index=models.Index(fields=['country_code', '-date'], name='users_country_country_date_idx'),
        ),
        migrations.AddIndex(
            model_name='countrymetrics',
            index=models.Index(fields=['created_at'], name='users_country_created_idx'),
        ),
    ]
