"""Only states and times: nothing from WhatsApp, the code or the browser's address."""
from django.contrib import admin

from .models import WhatsAppLink


class WhatsAppLinkAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'state', 'reason', 'linked_at', 'last_sync_at', 'next_sync_at', 'failures')
    list_filter = ('state', 'reason')
    search_fields = ('user__id',)
    fields = list_display[1:] + ('created_at',)
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # unlinking deletes the vendor profile too: the person does it from the app
