from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='AIContextDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(choices=[('decision-log', 'Decision log'), ('meeting-notes', 'Meeting notes'), ('videos', 'Videos'), ('weekly-reports', 'Weekly reports'), ('social-stats', 'Social stats'), ('strategy', 'Strategy'), ('legal', 'Legal'), ('user-reports', 'User reports'), ('other', 'Other')], max_length=32)),
                ('title', models.CharField(max_length=255)),
                ('slug', models.SlugField(max_length=120)),
                ('relative_path', models.CharField(blank=True, default='', max_length=500)),
                ('body', models.TextField()),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('COMMITTED', 'Committed'), ('PUSHED', 'Pushed'), ('FAILED', 'Failed')], default='DRAFT', max_length=16)),
                ('commit_sha', models.CharField(blank=True, default='', max_length=64)),
                ('committed_at', models.DateTimeField(blank=True, null=True)),
                ('pushed_at', models.DateTimeField(blank=True, null=True)),
                ('error', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='TelegramChat',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('chat_identifier', models.CharField(help_text='Telegram username, invite target, numeric chat id, or t.me URL.', max_length=255, unique=True)),
                ('topic', models.CharField(blank=True, default='', max_length=120)),
                ('is_active', models.BooleanField(default=True)),
                ('last_message_id', models.BigIntegerField(blank=True, null=True)),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['title']},
        ),
        migrations.CreateModel(
            name='MediaAsset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('platform', models.CharField(choices=[('TELEGRAM', 'Telegram'), ('TIKTOK', 'TikTok'), ('YOUTUBE', 'YouTube'), ('INSTAGRAM', 'Instagram'), ('UNKNOWN', 'Unknown')], max_length=16)),
                ('source_url', models.URLField(blank=True, default='', max_length=2048)),
                ('canonical_url', models.URLField(blank=True, default='', max_length=2048)),
                ('external_id', models.CharField(blank=True, default='', max_length=255)),
                ('title', models.CharField(blank=True, default='', max_length=500)),
                ('description', models.TextField(blank=True, default='')),
                ('author', models.CharField(blank=True, default='', max_length=255)),
                ('duration_seconds', models.FloatField(blank=True, null=True)),
                ('view_count', models.BigIntegerField(blank=True, null=True)),
                ('like_count', models.BigIntegerField(blank=True, null=True)),
                ('comment_count', models.BigIntegerField(blank=True, null=True)),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('thumbnail_url', models.URLField(blank=True, default='', max_length=2048)),
                ('local_file_path', models.CharField(blank=True, default='', max_length=1024)),
                ('file_size_bytes', models.BigIntegerField(blank=True, null=True)),
                ('telegram_message_id', models.BigIntegerField(blank=True, null=True)),
                ('telegram_file_id', models.CharField(blank=True, default='', max_length=255)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('FETCHED', 'Fetched'), ('DOWNLOADED', 'Downloaded'), ('FAILED', 'Failed')], default='PENDING', max_length=16)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('fetched_at', models.DateTimeField(blank=True, null=True)),
                ('error', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('telegram_chat', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='media_assets', to='content_ingestion.telegramchat')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='aicontextdocument',
            index=models.Index(fields=['category', '-created_at'], name='ai_ctx_category_idx'),
        ),
        migrations.AddIndex(
            model_name='aicontextdocument',
            index=models.Index(fields=['status', '-created_at'], name='ai_ctx_status_idx'),
        ),
        migrations.AddIndex(
            model_name='aicontextdocument',
            index=models.Index(fields=['relative_path'], name='ai_ctx_path_idx'),
        ),
        migrations.AddIndex(
            model_name='telegramchat',
            index=models.Index(fields=['is_active', 'title'], name='content_tg_active_idx'),
        ),
        migrations.AddIndex(
            model_name='mediaasset',
            index=models.Index(fields=['platform', 'external_id'], name='content_asset_ext_idx'),
        ),
        migrations.AddIndex(
            model_name='mediaasset',
            index=models.Index(fields=['telegram_chat', 'telegram_message_id'], name='content_asset_tg_msg_idx'),
        ),
        migrations.AddIndex(
            model_name='mediaasset',
            index=models.Index(fields=['status', '-created_at'], name='content_asset_status_idx'),
        ),
        migrations.AddConstraint(
            model_name='mediaasset',
            constraint=models.UniqueConstraint(fields=('telegram_chat', 'telegram_message_id'), name='content_asset_tg_msg_unique'),
        ),
    ]
