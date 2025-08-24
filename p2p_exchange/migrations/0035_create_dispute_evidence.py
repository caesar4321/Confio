from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('p2p_exchange', '0034_add_dispute_code_fields'),
        ('users', '0061_update_invitation_trigger_phone_key'),
    ]

    operations = [
        migrations.CreateModel(
            name='P2PDisputeEvidence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(default=False)),
                ('s3_bucket', models.CharField(blank=True, max_length=100)),
                ('s3_key', models.CharField(max_length=512)),
                ('url', models.URLField()),
                ('content_type', models.CharField(blank=True, max_length=100)),
                ('size_bytes', models.BigIntegerField(blank=True, null=True)),
                ('sha256', models.CharField(blank=True, max_length=80)),
                ('etag', models.CharField(blank=True, max_length=80)),
                ('confio_code', models.CharField(blank=True, max_length=16)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('source', models.CharField(choices=[('mobile', 'Mobile App'), ('web', 'Web Upload'), ('email', 'Email Ingest')], default='mobile', max_length=16)),
                ('status', models.CharField(choices=[('uploaded', 'Uploaded'), ('validated', 'Validated'), ('rejected', 'Rejected')], default='uploaded', max_length=16)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('dispute', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='evidences', to='p2p_exchange.p2pdispute')),
                ('trade', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='evidences', to='p2p_exchange.p2ptrade')),
                ('uploader_business', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='uploaded_dispute_evidences', to='users.business')),
                ('uploader_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='uploaded_dispute_evidences', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-uploaded_at'],
            },
        ),
        migrations.AddIndex(
            model_name='p2pdisputeevidence',
            index=models.Index(fields=['dispute', 'uploaded_at'], name='p2p_exchan_dispute_9d0e2e_idx'),
        ),
        migrations.AddIndex(
            model_name='p2pdisputeevidence',
            index=models.Index(fields=['trade', 'uploaded_at'], name='p2p_exchan_trade_up_fc1a2d_idx'),
        ),
    ]

