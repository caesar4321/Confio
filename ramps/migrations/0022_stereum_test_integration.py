import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('ramps', '0021_remove_direct_transfer_proof'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='StereumTestOperation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('request_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('consumption_key', models.CharField(max_length=64, null=True, blank=True, unique=True)),
                ('credential_scope', models.CharField(max_length=64)),
                ('action', models.CharField(max_length=32)),
                ('request_data', models.JSONField(default=dict)),
                ('response_data', models.JSONField(default=dict)),
                ('provider_id', models.CharField(blank=True, max_length=160)),
                ('status', models.CharField(default='prepared', max_length=24)),
                ('provider_status', models.CharField(blank=True, max_length=80)),
                ('error', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='StereumTestWebhook',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('digest', models.CharField(max_length=64, unique=True)),
                ('credential_scope', models.CharField(max_length=64)),
                ('payload', models.JSONField()),
                ('received_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
