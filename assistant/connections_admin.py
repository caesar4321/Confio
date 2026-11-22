"""The queue: who asked, and the hand-given places (100 for life)."""
from django.contrib import admin, messages

from . import connections
from .connections_models import AssistantConnectionRequest
from .gmail import config as gmail


class ConnectionRequestAdmin(admin.ModelAdmin):
    list_display = ('asked_at', 'user', 'feature', 'answer', 'address', 'invited_at', 'ready_at', 'removed_at',
                    'notified_at')
    list_select_related = ('user',)
    list_filter = ('feature', 'answer', ('invited_at', admin.EmptyFieldListFilter),
                   ('ready_at', admin.EmptyFieldListFilter))
    search_fields = ('user__username', 'google_email')
    ordering = ('asked_at',)
    readonly_fields = list_display
    fields = list_display
    actions = ('reserve_place', 'give_place', 'tell_waiting', 'take_place', 'return_place')

    @admin.display(description='Gmail que se agrega en Google')
    def address(self, obj):
        # Only once frozen: before that the person can still change it.
        if obj.feature != obj.Feature.GMAIL or obj.answer != obj.Answer.YES:
            return ''
        if obj.user is None or not obj.user.is_active or obj.user.deleted_at:
            return ''
        if obj.ready_at:
            # Given before: "Devolver acceso" brings them back.
            return obj.google_email or '(ya está en Google)'
        if not obj.google_email:
            return '(todavía no lo indicó)'
        return obj.google_email if obj.invited_at and not obj.removed_at else '(primero aparta el cupo)'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # Deleting a row would "free" a place that Google still counts.
        return False

    def changelist_view(self, request, extra_context=None):
        title = f'Gmail: {connections.seats_used()} de {gmail.MAX_TESTERS} cupos dados (el total real está en Google)'
        if not connections.pilot_open():
            title += ' · piloto apagado: no se pueden dar cupos'
        elif not connections.seats_left():
            title += ' · sin cupos'
        return super().changelist_view(request, {**(extra_context or {}), 'title': title})

    @admin.action(description='1. Apartar cupo de Gmail (gasta un cupo y fija la dirección)', permissions=['change'])
    def reserve_place(self, request, queryset):
        done = connections.reserve(queryset.values_list('pk', flat=True))
        level = messages.WARNING if done['skipped'] or done['no_seat'] else messages.SUCCESS
        self.message_user(
            request,
            f"Apartados: {done['reserved']}. Omitidos: {done['skipped']}. Sin cupo: {done['no_seat']}. "
            'Ahora agrega esa dirección en Google y haz el paso 2.', level)

    @admin.action(description='2. Ya lo agregué en Google: dar acceso y avisar', permissions=['change'])
    def give_place(self, request, queryset):
        done = connections.give(queryset.values_list('pk', flat=True))
        level = messages.WARNING if done['skipped'] else messages.SUCCESS
        self.message_user(request, f"Accesos dados: {done['given']}. Omitidos: {done['skipped']}.", level)

    @admin.action(description='Avisar a quienes esperan que hay novedades', permissions=['change'])
    def tell_waiting(self, request, queryset):
        done = connections.tell_waiting(queryset.values_list('pk', flat=True))
        self.message_user(request, f'Personas avisadas: {done}.')

    @admin.action(description='Quitar acceso a Gmail (el cupo sigue gastado)', permissions=['change'])
    def take_place(self, request, queryset):
        done = connections.remove(queryset.values_list('pk', flat=True))
        self.message_user(request, f'Accesos quitados: {done}.')

    @admin.action(description='Devolver acceso a quien ya lo tuvo (no gasta otro cupo)', permissions=['change'])
    def return_place(self, request, queryset):
        done = connections.give_back(queryset.values_list('pk', flat=True))
        level = messages.WARNING if done['skipped'] else messages.SUCCESS
        self.message_user(request, f"Accesos devueltos: {done['given']}. Omitidos: {done['skipped']}.", level)


def register(site):
    site.register(AssistantConnectionRequest, ConnectionRequestAdmin)
