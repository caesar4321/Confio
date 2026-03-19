from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
        ('ramps', '0006_koywe_bank_info'),
    ]

    operations = [
        migrations.CreateModel(
            name='RampUserAddress',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('address_street', models.TextField()),
                ('address_city', models.CharField(max_length=100)),
                ('address_state', models.CharField(max_length=100)),
                ('address_zip_code', models.CharField(max_length=30)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=models.deletion.CASCADE, related_name='ramp_user_address', to='users.user')),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
    ]
