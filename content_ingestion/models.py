from django.db import models
from django.utils import timezone


class MediaPlatform(models.TextChoices):
    TELEGRAM = 'TELEGRAM', 'Telegram'
    TIKTOK = 'TIKTOK', 'TikTok'
    YOUTUBE = 'YOUTUBE', 'YouTube'
    INSTAGRAM = 'INSTAGRAM', 'Instagram'
    UNKNOWN = 'UNKNOWN', 'Unknown'


class IngestionStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    FETCHED = 'FETCHED', 'Fetched'
    DOWNLOADED = 'DOWNLOADED', 'Downloaded'
    FAILED = 'FAILED', 'Failed'


class AIContextCategory(models.TextChoices):
    DECISION_LOG = 'decision-log', 'Decision log'
    MEETING_NOTES = 'meeting-notes', 'Meeting notes'
    VIDEOS = 'videos', 'Videos'
    WEEKLY_REPORTS = 'weekly-reports', 'Weekly reports'
    SOCIAL_STATS = 'social-stats', 'Social stats'
    STRATEGY = 'strategy', 'Strategy'
    LEGAL = 'legal', 'Legal'
    USER_REPORTS = 'user-reports', 'User reports'
    OTHER = 'other', 'Other'


class AIContextCommitStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    COMMITTED = 'COMMITTED', 'Committed'
    PUSHED = 'PUSHED', 'Pushed'
    FAILED = 'FAILED', 'Failed'


class TelegramChat(models.Model):
    title = models.CharField(max_length=255)
    chat_identifier = models.CharField(
        max_length=255,
        unique=True,
        help_text='Telegram username, invite target, numeric chat id, or t.me URL.',
    )
    topic = models.CharField(max_length=120, blank=True, default='')
    is_active = models.BooleanField(default=True)
    last_message_id = models.BigIntegerField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title']
        indexes = [
            models.Index(fields=['is_active', 'title'], name='content_tg_active_idx'),
        ]

    def __str__(self):
        return self.title


class MediaAsset(models.Model):
    platform = models.CharField(max_length=16, choices=MediaPlatform.choices)
    source_url = models.URLField(max_length=2048, blank=True, default='')
    canonical_url = models.URLField(max_length=2048, blank=True, default='')
    external_id = models.CharField(max_length=255, blank=True, default='')
    title = models.CharField(max_length=500, blank=True, default='')
    description = models.TextField(blank=True, default='')
    author = models.CharField(max_length=255, blank=True, default='')
    duration_seconds = models.FloatField(null=True, blank=True)
    view_count = models.BigIntegerField(null=True, blank=True)
    like_count = models.BigIntegerField(null=True, blank=True)
    comment_count = models.BigIntegerField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    thumbnail_url = models.URLField(max_length=2048, blank=True, default='')
    local_file_path = models.CharField(max_length=1024, blank=True, default='')
    file_size_bytes = models.BigIntegerField(null=True, blank=True)
    telegram_chat = models.ForeignKey(
        TelegramChat,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='media_assets',
    )
    telegram_message_id = models.BigIntegerField(null=True, blank=True)
    telegram_file_id = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=16, choices=IngestionStatus.choices, default=IngestionStatus.PENDING)
    metadata = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['platform', 'external_id'], name='content_asset_ext_idx'),
            models.Index(fields=['telegram_chat', 'telegram_message_id'], name='content_asset_tg_msg_idx'),
            models.Index(fields=['status', '-created_at'], name='content_asset_status_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['telegram_chat', 'telegram_message_id'],
                name='content_asset_tg_msg_unique',
            ),
        ]

    def mark_failed(self, error: str):
        self.status = IngestionStatus.FAILED
        self.error = error[:4000]
        self.fetched_at = timezone.now()
        self.save(update_fields=['status', 'error', 'fetched_at', 'updated_at'])

    def __str__(self):
        return self.title or self.canonical_url or self.source_url or f'{self.platform} asset {self.pk}'


class AIContextDocument(models.Model):
    category = models.CharField(max_length=32, choices=AIContextCategory.choices)
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=120)
    relative_path = models.CharField(max_length=500, blank=True, default='')
    body = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=AIContextCommitStatus.choices,
        default=AIContextCommitStatus.DRAFT,
    )
    commit_sha = models.CharField(max_length=64, blank=True, default='')
    committed_at = models.DateTimeField(null=True, blank=True)
    pushed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['category', '-created_at'], name='ai_ctx_category_idx'),
            models.Index(fields=['status', '-created_at'], name='ai_ctx_status_idx'),
            models.Index(fields=['relative_path'], name='ai_ctx_path_idx'),
        ]

    def mark_failed(self, error: str):
        self.status = AIContextCommitStatus.FAILED
        self.error = error[:4000]
        self.save(update_fields=['status', 'error', 'updated_at'])

    def __str__(self):
        return f'{self.category}: {self.title}'
