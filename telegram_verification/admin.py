from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from config.admin_mixins import EnhancedAdminMixin, ExportCsvMixin, ExportJsonMixin
from .models import TelegramVerification


@admin.register(TelegramVerification)
class TelegramVerificationAdmin(EnhancedAdminMixin, ExportCsvMixin, ExportJsonMixin, admin.ModelAdmin):
    list_display = ['id', 'user', 'phone_number', 'request_id', 'status_badge', 'created_at', 'expires_at']
    list_filter = ['is_verified', 'created_at', 'expires_at']
    search_fields = ['phone_number', 'request_id', 'user__username', 'user__email']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']

    actions = ['mark_as_verified', 'export_as_csv', 'export_as_json', 'purge_expired_pending']

    def status_badge(self, obj: TelegramVerification):
        now = timezone.now()
        if obj.is_verified:
            color = '#10B981'; label = 'VERIFIED'
        elif obj.expires_at and obj.expires_at < now:
            color = '#EF4444'; label = 'EXPIRED'
        else:
            color = '#F59E0B'; label = 'PENDING'
        return format_html('<span style="background-color:{};color:#fff;padding:3px 8px;border-radius:10px;font-size:11px;font-weight:600;">{}</span>', color, label)
    status_badge.short_description = 'Status'

    @admin.action(description='✅ Marcar como verificado')
    def mark_as_verified(self, request, queryset):
        updated = queryset.update(is_verified=True)
        self.message_user(request, f'{updated} registro(s) marcados como verificados.', messages.SUCCESS)

    @admin.action(description='🧹 Purgar pendientes expirados')
    def purge_expired_pending(self, request, queryset):
        now = timezone.now()
        qs = TelegramVerification.objects.filter(is_verified=False, expires_at__lt=now)
        deleted = 0
        for obj in qs:
            obj.hard_delete() if hasattr(obj, 'hard_delete') else obj.delete()
            deleted += 1
        self.message_user(request, f'{deleted} registro(s) expirados eliminados.', messages.INFO)
