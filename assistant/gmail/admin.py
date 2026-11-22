"""Staff see that a connection exists, never an address, a token or anything from mail."""
from django.contrib import admin

from .models import GmailConnection


class GmailConnectionAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'can_send', 'connected_at', 'last_sync_at', 'failures')
    list_filter = ('status', 'can_send')
    fields = list_display
    readonly_fields = list_display

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Deleting the row would skip the revoke at Google.
        return False


def register(site):
    site.register(GmailConnection, GmailConnectionAdmin)
