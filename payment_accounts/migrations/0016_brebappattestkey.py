from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('payment_accounts', '0015_accountactivation'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name='BrebAppAttestKey', fields=[
        ('key_id', models.CharField(max_length=44, primary_key=True, serialize=False)),
        ('public_key', models.TextField()), ('receipt', models.BinaryField()),
        ('counter', models.PositiveBigIntegerField(default=0)),
        ('revoked', models.BooleanField(default=False)), ('created_at', models.DateTimeField(auto_now_add=True)),
        ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
    ])]
