from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('security', '0022_integrityverdict_fingerprint_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='DiditFaceBlocklistEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('session_id', models.CharField(max_length=64)),
                ('list_uuid', models.CharField(max_length=64)),
                ('entry_uuid', models.CharField(max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('removed_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='didit_face_blocklist_entries',
                                           to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [models.UniqueConstraint(
                    condition=models.Q(('removed_at__isnull', True)), fields=('session_id',),
                    name='one_active_face_block_per_session')],
            },
        ),
    ]
