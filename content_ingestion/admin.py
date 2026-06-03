from django.contrib import admin

from .models import AIContextDocument, MediaAsset, TelegramChat


@admin.register(TelegramChat)
class TelegramChatAdmin(admin.ModelAdmin):
    list_display = ('title', 'chat_identifier', 'topic', 'is_active', 'last_message_id', 'last_synced_at')
    list_filter = ('is_active', 'topic')
    search_fields = ('title', 'chat_identifier', 'topic')
    readonly_fields = ('last_synced_at', 'created_at', 'updated_at')


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ('id', 'platform', 'title', 'status', 'author', 'duration_seconds', 'created_at')
    list_filter = ('platform', 'status', 'created_at')
    search_fields = ('title', 'description', 'author', 'source_url', 'canonical_url', 'external_id')
    readonly_fields = ('created_at', 'updated_at', 'fetched_at')
    autocomplete_fields = ('telegram_chat',)
    date_hierarchy = 'created_at'


@admin.register(AIContextDocument)
class AIContextDocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'category', 'title', 'status', 'relative_path', 'committed_at', 'pushed_at')
    list_filter = ('category', 'status', 'created_at')
    search_fields = ('title', 'slug', 'relative_path', 'body', 'commit_sha')
    readonly_fields = ('relative_path', 'commit_sha', 'committed_at', 'pushed_at', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
