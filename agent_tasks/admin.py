"""Read-only admin, registered on confio_admin_site (config/admin_dashboard.py).
The connect URL, the goal and what a page said are never shown."""
from django.contrib import admin


class _ReadOnly(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(f.name for f in self.model._meta.fields if f.name not in (self.exclude or ()))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AgentTaskAdmin(_ReadOnly):
    exclude = ('connect_url', 'session_id', 'lease', 'history', 'goal', 'shown_target', 'visited_pages')
    list_display = ('internal_id', 'user', 'site', 'state', 'reason', 'steps', 'cost_usd', 'created_at')
    list_filter = ('state', 'reason')
    search_fields = ('internal_id', 'site', 'user__username', 'user__email')
    ordering = ('-created_at',)


class AgentProfileAdmin(_ReadOnly):
    exclude = ('external_id',)
    list_display = ('user', 'site', 'provider', 'created_at', 'last_used_at')
    search_fields = ('site', 'user__username')
