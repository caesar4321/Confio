from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('security', '0008_identityverification_verified_address_neighborhood')]
    operations = [
        migrations.CreateModel(
            name='RegistrationRestriction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('ip', 'IP'), ('device', 'Device fingerprint')], max_length=16)),
                ('value', models.CharField(max_length=255)),
                ('reason', models.TextField()),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('kind', 'value'), name='unique_registration_source')]},
        ),
    ]
