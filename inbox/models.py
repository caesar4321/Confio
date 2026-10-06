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
    INSTITUTION = 'INSTITUTION', 'Institution'
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
    # The "Oficial" badge in Descubrir. A staff grant is necessary but not
    # sufficient: see inbox.official for the live rule (owner KYB included).
    # Granted in the admin only — never requested or set by the owner.
    official_granted_at = models.DateTimeField(null=True, blank=True)
    official_granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    official_note = models.CharField(
        max_length=255,
        blank=True,
        help_text='How staff confirmed who controls this channel (required to grant Oficial).',
    )
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
    push_claimed_at = models.DateTimeField(null=True, blank=True)
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


class ContentPollVote(models.Model):
    """A person's answer is shared across accounts and publication surfaces."""
    content_item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name='poll_votes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='content_poll_votes')
    option_id = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['content_item', 'user'], name='inbox_poll_item_user_uniq'),
        ]


class CommunityReviewStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    # The AI could not decide (outage, unparseable output) after every retry.
    # Never published: the author is told to try again.
    FAILED = 'FAILED', 'Failed'
    # Taken down after publishing: by reports, a re-review, staff, or the author.
    REMOVED = 'REMOVED', 'Removed'


class CommunityPostReview(models.Model):
    """The AI gate in front of a member's Comunidad post.

    A post is a ContentItem owned by its author; it stays unpublished until a
    review approves it. Only APPROVED posts are ever PUBLISHED.
    """
    content_item = models.OneToOneField(ContentItem, on_delete=models.CASCADE, related_name='community_review')
    status = models.CharField(max_length=16, choices=CommunityReviewStatus.choices, default=CommunityReviewStatus.PENDING)
    # Private upload awaiting review; copied to the public bucket only on approval.
    pending_image_key = models.CharField(max_length=512, null=True, blank=True, unique=True)
    # Which model made the final call ('' while pending).
    decided_by_model = models.CharField(max_length=64, blank=True, default='')
    escalated = models.BooleanField(default=False)
    category = models.CharField(max_length=32, blank=True, default='')
    # Shown to the author, in Spanish.
    reason = models.CharField(max_length=280, blank=True, default='')
    # Every model verdict, in order, for audit.
    verdicts = models.JSONField(default=list, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    # Set per attempt; only the worker holding the latest one may decide.
    claim_token = models.CharField(max_length=32, blank=True, default='')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='removed_community_posts',
    )
    rereviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', '-created_at'], name='inbox_cpr_status_idx'),
        ]

    def __str__(self):
        return f'Review {self.content_item_id}: {self.status}'


class CommunityReportReason(models.TextChoices):
    SCAM = 'SCAM', 'Estafa o fraude'
    SPAM = 'SPAM', 'Spam o publicidad'
    OFFENSIVE = 'OFFENSIVE', 'Ofensivo o acoso'
    PERSONAL_DATA = 'PERSONAL_DATA', 'Datos personales'
    OTHER = 'OTHER', 'Otro'


class CommunityPostReport(models.Model):
    content_item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name='community_reports')
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='community_reports')
    reason = models.CharField(max_length=16, choices=CommunityReportReason.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['content_item', 'reporter'], name='inbox_community_report_uniq'),
        ]

    def __str__(self):
        return f'{self.reporter_id} reported {self.content_item_id}: {self.reason}'


class CommunityComment(models.Model):
    """A comment on a Comunidad post, one level deep.

    Top-level comments have no parent; replies point at a top-level comment
    (a reply to a reply is filed under the same top-level comment). Gated by
    the same AI review as posts: only APPROVED comments are shown to others.
    """
    content_item = models.ForeignKey(ContentItem, on_delete=models.CASCADE, related_name='community_comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='community_comments')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
    body = models.TextField()
    # Post participants tagged in this comment, validated at creation.
    mentions = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='community_mentions')
    status = models.CharField(max_length=16, choices=CommunityReviewStatus.choices, default=CommunityReviewStatus.PENDING)
    decided_by_model = models.CharField(max_length=64, blank=True, default='')
    escalated = models.BooleanField(default=False)
    category = models.CharField(max_length=32, blank=True, default='')
    reason = models.CharField(max_length=280, blank=True, default='')
    verdicts = models.JSONField(default=list, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    # Set per attempt; only the worker holding the latest one may decide.
    claim_token = models.CharField(max_length=32, blank=True, default='')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='removed_community_comments',
    )
    rereviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['content_item', 'parent', 'status', 'created_at'], name='inbox_cc_thread_idx'),
            models.Index(fields=['author', '-created_at'], name='inbox_cc_author_idx'),
            models.Index(fields=['status', '-updated_at'], name='inbox_cc_status_idx'),
        ]

    def __str__(self):
        return f'Comment {self.id} on {self.content_item_id}: {self.status}'


class CommunityCommentReport(models.Model):
    comment = models.ForeignKey(CommunityComment, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='community_comment_reports')
    reason = models.CharField(max_length=16, choices=CommunityReportReason.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['comment', 'reporter'], name='inbox_comment_report_uniq'),
        ]


class CommunityCommentReaction(models.Model):
    """One reaction per person per comment, from the same set as posts."""
    comment = models.ForeignKey(CommunityComment, on_delete=models.CASCADE, related_name='reactions')
    reaction_type = models.ForeignKey(ReactionType, on_delete=models.PROTECT, related_name='community_comment_reactions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='community_comment_reactions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['comment', 'user'], name='inbox_comment_reaction_uniq'),
        ]


class ProfilePictureStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    # The picture people see. At most one per person.
    ACTIVE = 'ACTIVE', 'Active'
    REJECTED = 'REJECTED', 'Rejected'
    FAILED = 'FAILED', 'Failed'
    # An approved picture the person later swapped out.
    REPLACED = 'REPLACED', 'Replaced'
    # Taken down by the person or staff.
    REMOVED = 'REMOVED', 'Removed'


class ProfilePictureSubmission(models.Model):
    """A member's profile picture, AI-screened before anyone else sees it.

    Uploads wait in the private ``pending/`` prefix of the profile-pictures
    bucket; only an approved, re-encoded copy is written to ``public/``.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile_pictures')
    status = models.CharField(max_length=16, choices=ProfilePictureStatus.choices, default=ProfilePictureStatus.PENDING)
    pending_key = models.CharField(max_length=512, unique=True)
    public_url = models.CharField(max_length=512, blank=True, default='')
    # Set once the public copy of a removed/replaced picture is confirmed
    # deleted. REMOVED/REPLACED with a public_url and no stamp = cleanup owed;
    # the sweeper keeps retrying until it lands.
    public_deleted_at = models.DateTimeField(null=True, blank=True)
    decided_by_model = models.CharField(max_length=64, blank=True, default='')
    escalated = models.BooleanField(default=False)
    category = models.CharField(max_length=32, blank=True, default='')
    reason = models.CharField(max_length=280, blank=True, default='')
    verdicts = models.JSONField(default=list, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    # Set per attempt; only the worker holding the latest one may decide.
    claim_token = models.CharField(max_length=32, blank=True, default='')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='removed_profile_pictures',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status'], name='inbox_pp_user_status_idx'),
            models.Index(fields=['status', '-updated_at'], name='inbox_pp_status_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(status='ACTIVE'),
                name='inbox_pp_one_active_per_user',
            ),
        ]

    def __str__(self):
        return f'Profile picture {self.id} of {self.user_id}: {self.status}'


class PublicObjectState(models.TextChoices):
    # Key chosen and committed BEFORE the upload; becomes LIVE in the same
    # transaction that references it. Still RESERVED after a grace period =
    # the publish never completed, so whatever was uploaded is deleted.
    RESERVED = 'RESERVED', 'Reserved'
    LIVE = 'LIVE', 'Live'
    # No longer referenced; deleted by the sweeper until S3 confirms.
    DOOMED = 'DOOMED', 'Doomed'
    DELETED = 'DELETED', 'Deleted'


class PublicObject(models.Model):
    """Ledger of every public object Comunidad writes (post images, profile
    pictures), so no crash, rollback or failed delete can leave public bytes
    nothing points at."""
    bucket = models.CharField(max_length=128)
    key = models.CharField(max_length=512)
    state = models.CharField(max_length=16, choices=PublicObjectState.choices, default=PublicObjectState.RESERVED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['bucket', 'key'], name='inbox_public_object_uniq'),
        ]
        indexes = [
            models.Index(fields=['state', 'updated_at'], name='inbox_public_object_state_idx'),
        ]

    def __str__(self):
        return f'{self.bucket}/{self.key}: {self.state}'


class CommunityBlock(models.Model):
    """A member blocking another. Mutual invisibility in Comunidad: neither
    sees the other's posts or comments, and they cannot mention or notify
    each other. Only the blocker can undo it."""
    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='community_blocks_made')
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='community_blocks_received')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['blocker', 'blocked'], name='inbox_community_block_uniq'),
            models.CheckConstraint(condition=~Q(blocker=models.F('blocked')), name='inbox_community_block_not_self'),
        ]

    def __str__(self):
        return f'{self.blocker_id} blocked {self.blocked_id}'


class CommunityRulesAcceptance(models.Model):
    """A member accepting a version of the Comunidad rules (Terms §11), required
    before their first post, comment or profile picture under that version."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='community_rules_acceptances')
    version = models.CharField(max_length=32)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'version'], name='inbox_community_rules_uniq'),
        ]

    def __str__(self):
        return f'{self.user_id} accepted rules {self.version}'
