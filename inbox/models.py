from django.conf import settings
from django.db import models
from django.db.models import Q

from users.models import Account, Business


class OwnerType(models.TextChoices):
    SYSTEM = 'SYSTEM', 'System'
    USER = 'USER', 'User'
    BUSINESS = 'BUSINESS', 'Business'


class ChannelKind(models.TextChoices):
    FOUNDER = 'FOUNDER', 'Founder'
    NEWS = 'NEWS', 'News'
    BUSINESS = 'BUSINESS', 'Business'
    SYSTEM = 'SYSTEM', 'System'


class AvatarType(models.TextChoices):
    EMOJI = 'EMOJI', 'Emoji'
    IMAGE_URL = 'IMAGE_URL', 'Image URL'
    USER = 'USER', 'User'


class SubscriptionMode(models.TextChoices):
    REQUIRED = 'REQUIRED', 'Required'
    DEFAULT_ON = 'DEFAULT_ON', 'Default On'
    OPTIONAL = 'OPTIONAL', 'Optional'


class ChannelScope(models.TextChoices):
    GLOBAL = 'GLOBAL', 'Global'
    BUSINESS = 'BUSINESS', 'Business'
    ACCOUNT = 'ACCOUNT', 'Account'


class NotificationLevel(models.TextChoices):
    DEFAULT = 'DEFAULT', 'Default'
    ALL = 'ALL', 'All'
    IMPORTANT_ONLY = 'IMPORTANT_ONLY', 'Important Only'
    NONE = 'NONE', 'None'


class ContentItemType(models.TextChoices):
    TEXT = 'TEXT', 'Text'
    NEWS = 'NEWS', 'News'
    VIDEO = 'VIDEO', 'Video'


class ContentStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    SCHEDULED = 'SCHEDULED', 'Scheduled'
    PUBLISHED = 'PUBLISHED', 'Published'
    ARCHIVED = 'ARCHIVED', 'Archived'


class VisibilityPolicy(models.TextChoices):
    FROM_PUBLISH_TIME = 'FROM_PUBLISH_TIME', 'From Publish Time'
    BACKLOG = 'BACKLOG', 'Backlog'
    PINNED = 'PINNED', 'Pinned'


class ContentSurfaceType(models.TextChoices):
    CHANNEL = 'CHANNEL', 'Channel'
    DISCOVER = 'DISCOVER', 'Discover'
    HOME_HIGHLIGHT = 'HOME_HIGHLIGHT', 'Home Highlight'


class ContentPlatformType(models.TextChoices):
    TIKTOK = 'TIKTOK', 'TikTok'
    INSTAGRAM = 'INSTAGRAM', 'Instagram'
    YOUTUBE = 'YOUTUBE', 'YouTube'


class ContentNotificationPriority(models.TextChoices):
    SILENT = 'SILENT', 'Silent'
    NORMAL = 'NORMAL', 'Normal'
    IMPORTANT = 'IMPORTANT', 'Important'


class SupportConversationStatus(models.TextChoices):
    OPEN = 'OPEN', 'Open'
    CLOSED = 'CLOSED', 'Closed'


class SupportSenderType(models.TextChoices):
    USER = 'USER', 'User'
    AGENT = 'AGENT', 'Agent'
    SYSTEM = 'SYSTEM', 'System'


class SupportMessageType(models.TextChoices):
    TEXT = 'TEXT', 'Text'
    SYSTEM = 'SYSTEM', 'System'


class Channel(models.Model):
    slug = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=32, choices=ChannelKind.choices)
    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=200, null=True, blank=True)
    avatar_type = models.CharField(max_length=16, choices=AvatarType.choices, default=AvatarType.EMOJI)
    avatar_value = models.CharField(max_length=255, null=True, blank=True)
    subscription_mode = models.CharField(
        max_length=16,
        choices=SubscriptionMode.choices,
        default=SubscriptionMode.REQUIRED,
    )
    channel_scope = models.CharField(max_length=16, choices=ChannelScope.choices, default=ChannelScope.GLOBAL)
    owner_type = models.CharField(max_length=16, choices=OwnerType.choices, default=OwnerType.SYSTEM)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='owned_inbox_channels',
    )
    owner_business = models.ForeignKey(
        Business,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='owned_inbox_channels',
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'title']
        indexes = [
            models.Index(fields=['is_active', 'sort_order'], name='inbox_channel_active_idx'),
            models.Index(fields=['kind', 'is_active'], name='inbox_channel_kind_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(owner_type=OwnerType.SYSTEM, owner_user__isnull=True, owner_business__isnull=True)
                    | Q(owner_type=OwnerType.USER, owner_user__isnull=False, owner_business__isnull=True)
                    | Q(owner_type=OwnerType.BUSINESS, owner_user__isnull=True, owner_business__isnull=False)
                ),
                name='inbox_channel_owner_valid',
            ),
        ]

    def __str__(self):
        return self.title


class ContentItem(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='content_items')
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inbox_authored_content',
    )
    owner_type = models.CharField(max_length=16, choices=OwnerType.choices, default=OwnerType.SYSTEM)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inbox_owned_content',
    )
    owner_business = models.ForeignKey(
        Business,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inbox_owned_content',
    )
    item_type = models.CharField(max_length=16, choices=ContentItemType.choices)
    status = models.CharField(max_length=16, choices=ContentStatus.choices, default=ContentStatus.DRAFT)
    title = models.CharField(max_length=255, null=True, blank=True)
    body = models.TextField(null=True, blank=True)
    tag = models.CharField(max_length=64, null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    visibility_policy = models.CharField(
        max_length=24,
        choices=VisibilityPolicy.choices,
        default=VisibilityPolicy.FROM_PUBLISH_TIME,
    )
    notification_priority = models.CharField(
        max_length=16,
        choices=ContentNotificationPriority.choices,
        default=ContentNotificationPriority.NORMAL,
    )
    send_push = models.BooleanField(default=False)
    send_in_app = models.BooleanField(default=True)
    push_sent_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-created_at']
        indexes = [
            models.Index(fields=['channel', 'status', '-published_at'], name='inbox_content_channel_idx'),
            models.Index(fields=['status', '-published_at'], name='inbox_content_status_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(owner_type=OwnerType.SYSTEM, owner_user__isnull=True, owner_business__isnull=True)
                    | Q(owner_type=OwnerType.USER, owner_user__isnull=False, owner_business__isnull=True)
                    | Q(owner_type=OwnerType.BUSINESS, owner_user__isnull=True, owner_business__isnull=False)
                ),
                name='inbox_content_owner_valid',
            ),
        ]

    def __str__(self):
        return self.title or f'{self.channel.title} ({self.item_type})'


class ChannelMembership(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='channel_memberships')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True, related_name='channel_memberships')
    business = models.ForeignKey(Business, on_delete=models.CASCADE, null=True, blank=True, related_name='channel_memberships')
    is_subscribed = models.BooleanField(default=True)
    is_muted = models.BooleanField(default=False)
    push_level = models.CharField(max_length=16, choices=NotificationLevel.choices, default=NotificationLevel.DEFAULT)
    in_app_level = models.CharField(max_length=16, choices=NotificationLevel.choices, default=NotificationLevel.DEFAULT)
    joined_at = models.DateTimeField(auto_now_add=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_content_item = models.ForeignKey(
        'ContentItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='last_seen_by_memberships',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'account', 'business'], name='inbox_membership_ctx_idx'),
            models.Index(fields=['channel', 'is_subscribed'], name='inbox_membership_sub_idx'),
            models.Index(fields=['user', 'channel'], name='inbox_membership_user_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(account__isnull=False, business__isnull=True)
                    | Q(account__isnull=True, business__isnull=False)
                ),
                name='inbox_membership_context_valid',
            ),
            models.UniqueConstraint(
                fields=['channel', 'user', 'account'],
                condition=Q(account__isnull=False, business__isnull=True),
                name='inbox_membership_channel_user_account_uniq',
            ),
            models.UniqueConstraint(
                fields=['channel', 'user', 'business'],
                condition=Q(account__isnull=True, business__isnull=False),
                name='inbox_membership_channel_user_business_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.user} -> {self.channel}'


class ContentSurface(models.Model):
    content_item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name='surfaces')
    surface = models.CharField(max_length=24, choices=ContentSurfaceType.choices)
    rank = models.IntegerField(null=True, blank=True)
    is_pinned = models.BooleanField(default=False)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['content_item', 'surface'], name='inbox_surface_unique'),
        ]
        indexes = [
            models.Index(fields=['surface', 'is_pinned', 'rank'], name='inbox_surface_rank_idx'),
        ]

    def __str__(self):
        return f'{self.content_item_id} on {self.surface}'


class ContentReadState(models.Model):
    content_item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name='read_states')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='content_read_states')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True, related_name='content_read_states')
    business = models.ForeignKey(Business, on_delete=models.CASCADE, null=True, blank=True, related_name='content_read_states')
    opened_from_surface = models.CharField(max_length=24, choices=ContentSurfaceType.choices, null=True, blank=True)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'account', 'business', '-read_at'], name='inbox_read_ctx_idx'),
            models.Index(fields=['content_item', '-read_at'], name='inbox_read_item_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(account__isnull=False, business__isnull=True)
                    | Q(account__isnull=True, business__isnull=False)
                ),
                name='inbox_read_context_valid',
            ),
            models.UniqueConstraint(
                fields=['content_item', 'user', 'account'],
                condition=Q(account__isnull=False, business__isnull=True),
                name='inbox_read_item_user_account_uniq',
            ),
            models.UniqueConstraint(
                fields=['content_item', 'user', 'business'],
                condition=Q(account__isnull=True, business__isnull=False),
                name='inbox_read_item_user_business_uniq',
            ),
        ]


class ReactionType(models.Model):
    emoji = models.CharField(max_length=16, unique=True)
    label = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    is_selectable = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.emoji} {self.label}'


class ContentReaction(models.Model):
    content_item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name='reactions')
    reaction_type = models.ForeignKey(ReactionType, on_delete=models.PROTECT, related_name='content_reactions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='content_reactions')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True, related_name='content_reactions')
    business = models.ForeignKey(Business, on_delete=models.CASCADE, null=True, blank=True, related_name='content_reactions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['content_item', 'reaction_type'], name='inbox_reaction_item_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(account__isnull=False, business__isnull=True)
                    | Q(account__isnull=True, business__isnull=False)
                ),
                name='inbox_reaction_context_valid',
            ),
            models.UniqueConstraint(
                fields=['content_item', 'user', 'account'],
                condition=Q(account__isnull=False, business__isnull=True),
                name='inbox_reaction_item_user_account_uniq',
            ),
            models.UniqueConstraint(
                fields=['content_item', 'user', 'business'],
                condition=Q(account__isnull=True, business__isnull=False),
                name='inbox_reaction_item_user_business_uniq',
            ),
        ]


class ContentPlatformClick(models.Model):
    content_item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name='platform_clicks')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='content_platform_clicks')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True, related_name='content_platform_clicks')
    business = models.ForeignKey(Business, on_delete=models.CASCADE, null=True, blank=True, related_name='content_platform_clicks')
    surface = models.CharField(max_length=24, choices=ContentSurfaceType.choices)
    platform = models.CharField(max_length=16, choices=ContentPlatformType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['content_item', 'platform', '-created_at'], name='inbox_click_item_platform_idx'),
            models.Index(fields=['user', '-created_at'], name='inbox_click_user_idx'),
            models.Index(fields=['surface', 'platform', '-created_at'], name='inbox_click_surface_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(account__isnull=False, business__isnull=True)
                    | Q(account__isnull=True, business__isnull=False)
                ),
                name='inbox_platform_click_context_valid',
            ),
        ]


class ContentPlatformClickDailyStat(models.Model):
    date = models.DateField()
    content_item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name='platform_click_daily_stats')
    surface = models.CharField(max_length=24, choices=ContentSurfaceType.choices)
    platform = models.CharField(max_length=16, choices=ContentPlatformType.choices)
    click_count = models.PositiveIntegerField(default=0)
    unique_user_count = models.PositiveIntegerField(default=0)
    aggregated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['content_item', 'platform', '-date'], name='ibox_clk_day_item_idx'),
            models.Index(fields=['surface', 'platform', '-date'], name='ibox_clk_day_surf_idx'),
            models.Index(fields=['-date', '-click_count'], name='ibox_clk_day_date_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['date', 'content_item', 'surface', 'platform'],
                name='ibox_clk_day_unique',
            ),
        ]


class SupportConversation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='support_conversations')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True, related_name='support_conversations')
    business = models.ForeignKey(Business, on_delete=models.CASCADE, null=True, blank=True, related_name='support_conversations')
    status = models.CharField(max_length=16, choices=SupportConversationStatus.choices, default=SupportConversationStatus.OPEN)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_support_conversations',
    )
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'status'], name='support_conv_user_idx'),
            models.Index(fields=['assigned_to', 'status'], name='support_conv_agent_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(account__isnull=False, business__isnull=True)
                    | Q(account__isnull=True, business__isnull=False)
                ),
                name='support_conversation_context_valid',
            ),
            models.UniqueConstraint(
                fields=['user', 'account'],
                condition=Q(account__isnull=False, business__isnull=True, status=SupportConversationStatus.OPEN),
                name='support_open_user_account_uniq',
            ),
            models.UniqueConstraint(
                fields=['user', 'business'],
                condition=Q(account__isnull=True, business__isnull=False, status=SupportConversationStatus.OPEN),
                name='support_open_user_business_uniq',
            ),
        ]


class SupportMessage(models.Model):
    conversation = models.ForeignKey(SupportConversation, on_delete=models.CASCADE, related_name='messages')
    sender_type = models.CharField(max_length=16, choices=SupportSenderType.choices)
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_messages',
    )
    message_type = models.CharField(max_length=16, choices=SupportMessageType.choices, default=SupportMessageType.TEXT)
    body = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at'], name='support_message_conv_idx'),
        ]


class SupportConversationState(models.Model):
    conversation = models.ForeignKey(SupportConversation, on_delete=models.CASCADE, related_name='states')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='support_conversation_states')
    last_seen_message = models.ForeignKey(
        SupportMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='last_seen_in_states',
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['conversation', 'user'], name='support_state_conversation_user_uniq'),
        ]
