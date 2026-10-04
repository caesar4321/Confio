import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('ramps', '0022_stereum_test_integration'), ('security', '0023_didit_face_blocklist')]
    operations = [migrations.CreateModel(
        name='StereumCustomer',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('credential_scope', models.CharField(max_length=64)),
            ('external_user_id', models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
            ('identity_fingerprint', models.CharField(max_length=64)),
            ('request_snapshot', models.JSONField()),
            ('status', models.CharField(max_length=24, default='validating')),
            ('validation_id', models.CharField(max_length=160, blank=True)),
            ('provider_customer_id', models.CharField(max_length=160, blank=True)),
            ('error', models.CharField(max_length=300, blank=True)),
            ('consent_at', models.DateTimeField()),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='users.user')),
            ('source_verification', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='security.identityverification')),
        ],
        options={'constraints': [
            models.UniqueConstraint(fields=('user', 'credential_scope'), name='stereum_customer_user_scope'),
            models.UniqueConstraint(fields=('credential_scope', 'provider_customer_id'),
                condition=~models.Q(provider_customer_id=''), name='stereum_customer_provider_scope'),
        ]},
    )]
