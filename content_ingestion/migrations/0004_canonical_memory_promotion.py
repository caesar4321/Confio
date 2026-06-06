from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('content_ingestion', '0003_create_memory_vector_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='CanonicalMemoryTurn',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('telegram_chat_id', models.BigIntegerField()),
                ('telegram_message_id', models.BigIntegerField()),
                ('sender_id', models.BigIntegerField(blank=True, null=True)),
                ('sender_name', models.CharField(blank=True, default='', max_length=255)),
                ('authority', models.CharField(max_length=16)),
                ('user_text', models.TextField()),
                ('assistant_text', models.TextField(blank=True, default='')),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['created_at', 'pk']},
        ),
        migrations.CreateModel(
            name='CanonicalMemoryPromotion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(choices=[
                    ('preferences', 'Preferences'),
                    ('facts', 'Facts'),
                    ('decisions', 'Decisions'),
                    ('content-rules', 'Content rules'),
                    ('decision-log', 'Decision log'),
                    ('meeting-notes', 'Meeting notes'),
                    ('videos', 'Videos'),
                    ('weekly-reports', 'Weekly reports'),
                    ('social-stats', 'Social stats'),
                    ('strategy', 'Strategy'),
                    ('legal', 'Legal'),
                    ('user-reports', 'User reports'),
                    ('other', 'Other'),
                ], max_length=32)),
                ('statement', models.TextField()),
                ('evidence_quote', models.TextField()),
                ('confidence', models.FloatField(default=0)),
                ('fingerprint', models.CharField(max_length=64, unique=True)),
                ('source_turn_ids', models.JSONField(blank=True, default=list)),
                ('source_authority', models.CharField(blank=True, default='', max_length=16)),
                ('status', models.CharField(choices=[
                    ('AUTO_PENDING', 'Pending automatic promotion'),
                    ('PROMOTED', 'Promoted'),
                    ('REVIEW', 'Needs review'),
                    ('REJECTED', 'Rejected'),
                ], default='REVIEW', max_length=16)),
                ('reason', models.TextField(blank=True, default='')),
                ('target_path', models.CharField(blank=True, default='', max_length=500)),
                ('commit_sha', models.CharField(blank=True, default='', max_length=64)),
                ('promoted_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(
            model_name='canonicalmemoryturn',
            constraint=models.UniqueConstraint(
                fields=('telegram_chat_id', 'telegram_message_id'),
                name='canonical_turn_tg_message_unique',
            ),
        ),
        migrations.AddIndex(
            model_name='canonicalmemoryturn',
            index=models.Index(fields=['processed_at', 'created_at'], name='canonical_turn_pending_idx'),
        ),
        migrations.AddIndex(
            model_name='canonicalmemorypromotion',
            index=models.Index(fields=['status', '-created_at'], name='canonical_promo_status_idx'),
        ),
        migrations.AddIndex(
            model_name='canonicalmemorypromotion',
            index=models.Index(fields=['category', '-created_at'], name='canonical_promo_category_idx'),
        ),
    ]
