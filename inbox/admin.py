from django.contrib import admin
from django.contrib import messages
from django import forms
from django.utils import timezone

from .models import (
    Channel,
    ChannelMembership,
    ContentItem,
    ContentReadState,
    ContentReaction,
    ContentSurface,
    ReactionType,
    SupportConversation,
    SupportConversationState,
    SupportMessage,
)
from .tasks import send_content_item_push_task


DISCOVER_TAG_COLOR_CHOICES = (
    ('', 'Automatico'),
    ('#1DB587', 'Verde Producto'),
    ('#7C3AED', 'Morado KYC'),
    ('#F97316', 'Naranja Preventa'),
    ('#F59E0B', 'Amarillo Mercado'),
    ('#FF4444', 'Rojo Video'),
    ('#2563EB', 'Azul'),
)


class ContentItemAdminForm(forms.ModelForm):
    tag_color = forms.ChoiceField(
        label='Color de etiqueta',
        choices=DISCOVER_TAG_COLOR_CHOICES,
        required=False,
        help_text='Color para la etiqueta en Descubrir. Si lo dejas en Automatico, se usa el color por tag.',
    )
    tiktok_url = forms.URLField(
        label='TikTok URL',
        required=False,
        help_text='Solo para publicaciones de video.',
    )
    instagram_url = forms.URLField(
        label='Instagram URL',
        required=False,
        help_text='Solo para publicaciones de video.',
    )
    youtube_url = forms.URLField(
        label='YouTube URL',
        required=False,
        help_text='Solo para publicaciones de video.',
    )

    class Meta:
        model = ContentItem
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        metadata = getattr(self.instance, 'metadata', {}) or {}
        platform_links = metadata.get('platform_links') or {}
        self.fields['tag_color'].initial = metadata.get('tag_color', '')
        self.fields['tiktok_url'].initial = platform_links.get('TikTok', '')
        self.fields['instagram_url'].initial = platform_links.get('Instagram', '')
        self.fields['youtube_url'].initial = platform_links.get('YouTube', '')

    def clean(self):
        cleaned_data = super().clean()
        metadata = dict((self.instance.metadata or {}).copy())

        tag_color = cleaned_data.get('tag_color')
        if tag_color:
            metadata['tag_color'] = tag_color
        else:
            metadata.pop('tag_color', None)

        platform_links = {}
        if cleaned_data.get('tiktok_url'):
            platform_links['TikTok'] = cleaned_data['tiktok_url']
        if cleaned_data.get('instagram_url'):
            platform_links['Instagram'] = cleaned_data['instagram_url']
        if cleaned_data.get('youtube_url'):
            platform_links['YouTube'] = cleaned_data['youtube_url']

        if platform_links:
            metadata['platform_links'] = platform_links
            metadata['platforms'] = list(platform_links.keys())
        else:
            metadata.pop('platform_links', None)
            metadata.pop('platforms', None)

        cleaned_data['metadata'] = metadata
        return cleaned_data


class ContentSurfaceInline(admin.TabularInline):
    model = ContentSurface
    extra = 0
    autocomplete_fields = ('content_item',)
    fields = ('surface', 'rank', 'is_pinned', 'starts_at', 'ends_at')


class ContentItemInline(admin.TabularInline):
    model = ContentItem
    extra = 0
    fields = (
        'item_type',
        'status',
        'title',
        'tag',
        'published_at',
        'visibility_policy',
        'send_in_app',
        'send_push',
    )
    readonly_fields = ('created_at', 'updated_at')
    show_change_link = True
    ordering = ('-published_at', '-created_at')


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'slug',
        'kind',
        'subscription_mode',
        'channel_scope',
        'owner_type',
        'is_active',
        'sort_order',
    )
    list_filter = (
        'kind',
        'subscription_mode',
        'channel_scope',
        'owner_type',
        'is_active',
    )
    search_fields = ('title', 'slug', 'subtitle', 'avatar_value')
    autocomplete_fields = ('owner_user', 'owner_business')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('sort_order', 'title')
    inlines = [ContentItemInline]
    fieldsets = (
        (
            'Channel',
            {
                'fields': (
                    'title',
                    'slug',
                    'subtitle',
                    'kind',
                    'is_active',
                    'sort_order',
                )
            },
        ),
        (
            'Branding',
            {
                'fields': (
                    'avatar_type',
                    'avatar_value',
                )
            },
        ),
        (
            'Audience',
            {
                'fields': (
                    'subscription_mode',
                    'channel_scope',
                )
            },
        ),
        (
            'Ownership',
            {
                'fields': (
                    'owner_type',
                    'owner_user',
                    'owner_business',
                )
            },
        ),
        (
            'Timestamps',
            {
                'fields': ('created_at', 'updated_at'),
                'classes': ('collapse',),
            },
        ),
    )


@admin.register(ContentItem)
class ContentItemAdmin(admin.ModelAdmin):
    form = ContentItemAdminForm
    list_display = (
        'id',
        'title_or_body',
        'channel',
        'item_type',
        'status',
        'discover_status',
        'published_at',
        'push_sent_at',
        'send_in_app',
        'send_push',
    )
    list_filter = (
        'channel',
        'item_type',
        'status',
        'visibility_policy',
        'notification_priority',
        'send_push',
        'send_in_app',
        'surfaces__surface',
        'surfaces__is_pinned',
    )
    search_fields = ('title', 'body', 'tag', 'channel__title', 'channel__slug')
    autocomplete_fields = ('channel', 'author_user', 'owner_user', 'owner_business')
    readonly_fields = ('created_at', 'updated_at', 'push_sent_at')
    list_select_related = ('channel', 'author_user', 'owner_user', 'owner_business')
    date_hierarchy = 'published_at'
    ordering = ('-published_at', '-created_at')
    inlines = [ContentSurfaceInline]
    actions = ('publish_selected_now', 'send_push_for_selected_content')
    fieldsets = (
        (
            'Content',
            {
                'fields': (
                    'channel',
                    'item_type',
                    'status',
                    'title',
                    'body',
                    'tag',
                )
            },
        ),
        (
            'Publishing',
            {
                'fields': (
                    'published_at',
                    'visibility_policy',
                    'notification_priority',
                    'send_in_app',
                    'send_push',
                    'push_sent_at',
                )
            },
        ),
        (
            'Descubrir y video',
            {
                'fields': (
                    'tag_color',
                    'tiktok_url',
                    'instagram_url',
                    'youtube_url',
                )
            },
        ),
        (
            'Ownership',
            {
                'fields': (
                    'author_user',
                    'owner_type',
                    'owner_user',
                    'owner_business',
                )
            },
        ),
        (
            'Metadata',
            {
                'fields': ('metadata',),
                'classes': ('collapse',),
            },
        ),
        (
            'Timestamps',
            {
                'fields': ('created_at', 'updated_at'),
                'classes': ('collapse',),
            },
        ),
    )

    def title_or_body(self, obj):
        return obj.title or (obj.body[:80] if obj.body else '')

    title_or_body.short_description = 'Content'

    def discover_status(self, obj):
        discover_surface = obj.surfaces.filter(surface='DISCOVER').first()
        if not discover_surface:
            return '-'
        if discover_surface.is_pinned:
            return 'Pinned'
        return 'Live'

    discover_status.short_description = 'Discover'

    @admin.action(description='Publicar seleccionado ahora')
    def publish_selected_now(self, request, queryset):
        updated = 0
        for item in queryset:
            dirty_fields = []
            if item.status != 'PUBLISHED':
                item.status = 'PUBLISHED'
                dirty_fields.append('status')
            if item.published_at is None:
                item.published_at = timezone.now()
                dirty_fields.append('published_at')
            if not dirty_fields:
                continue
            item.save(update_fields=[*dirty_fields, 'updated_at'])
            updated += 1

        self.message_user(request, f'{updated} contenido(s) publicados.', level=messages.SUCCESS)

    @admin.action(description='Enviar push para el contenido seleccionado')
    def send_push_for_selected_content(self, request, queryset):
        queued = 0
        skipped = 0
        for item in queryset:
            if item.status != 'PUBLISHED' or not item.send_push or item.push_sent_at is not None:
                skipped += 1
                continue
            send_content_item_push_task.delay(item.id)
            queued += 1

        if queued:
            self.message_user(request, f'Push encolado para {queued} contenido(s).', level=messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f'{skipped} contenido(s) omitidos: deben estar publicados, con push activado y no enviados aún.',
                level=messages.WARNING,
            )


@admin.register(ChannelMembership)
class ChannelMembershipAdmin(admin.ModelAdmin):
    list_display = (
        'channel',
        'user',
        'account',
        'business',
        'is_subscribed',
        'is_muted',
        'push_level',
        'in_app_level',
        'last_seen_at',
    )
    list_filter = ('channel', 'is_subscribed', 'is_muted', 'push_level', 'in_app_level')
    search_fields = (
        'channel__title',
        'channel__slug',
        'user__username',
        'user__email',
    )
    autocomplete_fields = ('channel', 'user', 'account', 'business', 'last_seen_content_item')
    readonly_fields = ('joined_at', 'created_at', 'updated_at')
    list_select_related = ('channel', 'user', 'account', 'business', 'last_seen_content_item')


@admin.register(ContentSurface)
class ContentSurfaceAdmin(admin.ModelAdmin):
    list_display = ('content_item', 'channel_title', 'surface', 'rank', 'is_pinned', 'starts_at', 'ends_at')
    list_filter = ('surface', 'is_pinned', 'content_item__channel')
    search_fields = ('content_item__title', 'content_item__body', 'content_item__channel__title')
    autocomplete_fields = ('content_item',)
    list_select_related = ('content_item__channel',)

    def channel_title(self, obj):
        return obj.content_item.channel.title

    channel_title.short_description = 'Channel'


@admin.register(ContentReadState)
class ContentReadStateAdmin(admin.ModelAdmin):
    list_display = ('content_item', 'user', 'account', 'business', 'opened_from_surface', 'read_at')
    list_filter = ('opened_from_surface', 'content_item__channel')
    search_fields = (
        'content_item__title',
        'content_item__channel__title',
        'user__username',
        'user__email',
    )
    autocomplete_fields = ('content_item', 'user', 'account', 'business')
    list_select_related = ('content_item', 'user', 'account', 'business')


@admin.register(ReactionType)
class ReactionTypeAdmin(admin.ModelAdmin):
    list_display = ('emoji', 'label', 'is_active', 'is_selectable', 'sort_order')
    list_filter = ('is_active', 'is_selectable')
    search_fields = ('emoji', 'label')
    ordering = ('sort_order', 'emoji')


@admin.register(ContentReaction)
class ContentReactionAdmin(admin.ModelAdmin):
    list_display = ('content_item', 'reaction_type', 'user', 'account', 'business', 'created_at')
    list_filter = ('reaction_type', 'content_item__channel')
    search_fields = (
        'content_item__title',
        'content_item__channel__title',
        'user__username',
        'user__email',
    )
    autocomplete_fields = ('content_item', 'reaction_type', 'user', 'account', 'business')
    list_select_related = ('content_item', 'reaction_type', 'user', 'account', 'business')


class SupportMessageInline(admin.TabularInline):
    model = SupportMessage
    extra = 0
    autocomplete_fields = ('sender_user',)
    fields = ('sender_type', 'sender_user', 'message_type', 'body', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(SupportConversation)
class SupportConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'account', 'business', 'status', 'assigned_to', 'last_message_at')
    list_filter = ('status',)
    search_fields = ('user__username', 'user__email', 'assigned_to__username', 'assigned_to__email')
    autocomplete_fields = ('user', 'account', 'business', 'assigned_to')
    readonly_fields = ('created_at', 'updated_at')
    list_select_related = ('user', 'account', 'business', 'assigned_to')
    inlines = [SupportMessageInline]


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'sender_type', 'sender_user', 'message_type', 'created_at')
    list_filter = ('sender_type', 'message_type')
    search_fields = ('body', 'sender_user__username', 'sender_user__email')
    autocomplete_fields = ('conversation', 'sender_user')
    list_select_related = ('conversation', 'sender_user')


@admin.register(SupportConversationState)
class SupportConversationStateAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'user', 'last_seen_message', 'last_seen_at')
    search_fields = ('conversation__user__username', 'user__username', 'user__email')
    autocomplete_fields = ('conversation', 'user', 'last_seen_message')
    list_select_related = ('conversation', 'user', 'last_seen_message')
