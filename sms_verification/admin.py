from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.db import transaction

from config.admin_mixins import EnhancedAdminMixin, ExportCsvMixin, ExportJsonMixin
from .models import SMSVerification

# Reuse helpers from schema for consistent behavior
from .schema import _hmac_code
from .twilio_verify import send_verification_sms, TwilioVerifyError
from django.conf import settings


@admin.register(SMSVerification)
class SMSVerificationAdmin(EnhancedAdminMixin, ExportCsvMixin, ExportJsonMixin, admin.ModelAdmin):
    list_display = [
        'id', 'user', 'phone_number', 'status_badge', 'attempts', 'created_at', 'expires_at'
    ]
    list_filter = ['is_verified', 'created_at', 'expires_at']
    search_fields = ['phone_number', 'user__username', 'user__email']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    readonly_fields = ['created_at']

    actions = ['resend_code', 'mark_as_verified', 'export_as_csv', 'export_as_json']

    def status_badge(self, obj: SMSVerification):
        now = timezone.now()
        if obj.is_verified:
            color = '#10B981'
            label = 'VERIFIED'
        elif obj.expires_at and obj.expires_at < now:
            color = '#EF4444'
            label = 'EXPIRED'
        else:
            color = '#F59E0B'
            label = 'PENDING'
        return format_html(
            '<span style="background-color:{};color:#fff;padding:3px 8px;border-radius:10px;font-size:11px;font-weight:600;">{}</span>',
            color,
            label
        )
    status_badge.short_description = 'Status'

    @admin.action(description='📲 Reenviar código (genera OTP nuevo)')
    def resend_code(self, request, queryset):
        max_batch = 25
        count = queryset.count()
        if count > max_batch:
            self.message_user(request, f'Por seguridad, límite de {max_batch} por lote. Seleccionados: {count}.', messages.WARNING)
            queryset = queryset[:max_batch]

        ttl = getattr(settings, 'SMS_CODE_TTL_SECONDS', 600)

        sent = 0
        skipped = 0
        with transaction.atomic():
            for ver in queryset.select_for_update():
                if ver.is_verified:
                    skipped += 1
                    continue
                # Trigger a fresh Twilio Verify SMS (Twilio handles code generation)
                try:
                    verification_sid, status = send_verification_sms(ver.phone_number)
                    # Refresh local TTL/attempt tracking; store HMAC(phone+sid) as placeholder
                    ver.code_hash = _hmac_code(ver.phone_number, verification_sid or 'sid')
                    ver.expires_at = timezone.now() + timezone.timedelta(seconds=ttl)
                    ver.attempts = 0
                    ver.save(update_fields=['code_hash', 'expires_at', 'attempts'])
                    sent += 1
                except TwilioVerifyError as e:
                    self.message_user(request, f'Fallo al reenviar a {ver.phone_number}: {e}', messages.ERROR)

        self.message_user(request, f'OTP reenviado a {sent} registro(s); omitidos {skipped}.', messages.SUCCESS)

    @admin.action(description='✅ Marcar como verificado')
    def mark_as_verified(self, request, queryset):
        updated = queryset.update(is_verified=True)
        self.message_user(request, f'{updated} registro(s) marcados como verificados.', messages.SUCCESS)
