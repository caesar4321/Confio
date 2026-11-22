"""The queue: who asked, and the hand-given places (100 for life)."""
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse

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
    actions = ('reserve_place', 'give_place', 'tell_waiting', 'take_place', 'return_place', 'undo_reservation')

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

    def _confirm(self, request, queryset, action, due, title, warning, button, costs_places=False, needs_pilot=True):
        """None = confirmed (go on). Otherwise the page, with exactly what would change."""
        if needs_pilot and not connections.pilot_open():
            self.message_user(request, 'El piloto está apagado: no cambió nada y no agregues nada en Google.',
                              messages.WARNING)
            return self.response_post_save_change(request, None)
        if request.POST.get('confirmed') == action:
            return None
        chosen = list(queryset.select_related('user').order_by('asked_at', 'pk'))
        rows = [row for row in chosen if row.feature == row.Feature.GMAIL and due(row)]
        if not rows:
            self.message_user(request, 'Ninguna de las seleccionadas se puede cambiar así.', messages.WARNING)
            return self.response_post_save_change(request, None)
        applicable = len(rows)
        # No action can use more than the pilot holds, and a POST carries at most 1000 fields.
        rows = rows[:gmail.MAX_TESTERS]
        spends = None
        if costs_places:
            configured = gmail.configured_tester_ids()
            spends = sum(1 for row in rows if not row.invited_at and str(row.user_id) not in configured)
        return TemplateResponse(request, 'admin/assistant/connection_confirm.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'title': title, 'warning': warning,
            'button': button, 'action': action, 'rows': rows, 'left_out': len(chosen) - applicable,
            'next_round': applicable - len(rows), 'shown': [(row, f'{row.pk}:{connections.as_shown(row)}') for row in rows],
            'spends': spends, 'left': connections.seats_left(), 'checkbox': ACTION_CHECKBOX_NAME,
        })

    @staticmethod
    def _seen(request):
        shown = {}
        for item in request.POST.getlist('seen'):
            pk, _, what = item.partition(':')
            if pk.isdecimal():
                shown[int(pk)] = what
        return shown

    def _recorder(self, request, what):
        # Who did it, in the row's History. Never the address.
        return lambda row: self.log_change(request, row, what)

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
        page = self._confirm(
            request, queryset, 'reserve_place', connections.can_reserve, 'Apartar cupos de Gmail',
            'Cada cupo es uno de 100 para siempre. La dirección queda fija. '
            'Revisa que esté bien escrita. No la agregues en Google hasta que la lista la muestre apartada.',
            'Apartar estos cupos', costs_places=True)
        if page:
            return page
        done = connections.reserve(queryset.values_list('pk', flat=True), self._seen(request),
                                   self._recorder(request, 'Apartó un cupo de Gmail.'))
        clean = done['reserved'] and not done['skipped'] and not done['no_seat']
        then = ('Agrega en Google solo las que la lista muestra apartadas y haz el paso 2.' if done['reserved']
                else 'No se apartó ninguna: no agregues nada en Google.')
        self.message_user(
            request,
            f"Apartados: {done['reserved']}. Omitidos: {done['skipped']}. Sin cupo: {done['no_seat']}. {then}",
            messages.SUCCESS if clean else messages.WARNING)

    @admin.action(description='2. Ya lo agregué en Google: dar acceso y avisar', permissions=['change'])
    def give_place(self, request, queryset):
        page = self._confirm(
            request, queryset, 'give_place', connections.can_give, 'Dar acceso a Gmail',
            'Confirma solo si YA agregaste cada una de estas direcciones en Google. '
            'Les llega un aviso y el cupo ya no se puede deshacer.',
            'Ya están en Google: dar acceso')
        if page:
            return page
        done = connections.give(queryset.values_list('pk', flat=True), self._seen(request),
                                self._recorder(request, 'Dio acceso a Gmail.'))
        level = messages.SUCCESS if done['given'] and not done['skipped'] else messages.WARNING
        self.message_user(request, f"Accesos dados: {done['given']}. Omitidos: {done['skipped']}.", level)

    @admin.action(description='Avisar a quienes esperan que hay novedades', permissions=['change'])
    def tell_waiting(self, request, queryset):
        done = connections.tell_waiting(queryset.values_list('pk', flat=True))
        self.message_user(request, f'Personas avisadas: {done}.')

    @admin.action(description='Quitar acceso a Gmail (el cupo sigue gastado)', permissions=['change'])
    def take_place(self, request, queryset):
        done = connections.remove(queryset.values_list('pk', flat=True),
                                  self._recorder(request, 'Quitó el acceso a Gmail.'))
        self.message_user(request, f'Accesos quitados: {done}.')

    @admin.action(description='Devolver acceso a quien ya lo tuvo (no gasta otro cupo)', permissions=['change'])
    def return_place(self, request, queryset):
        page = self._confirm(
            request, queryset, 'return_place', connections.can_return, 'Devolver acceso a Gmail',
            'Estas personas perdieron el acceso o salieron. Al confirmar lo recuperan y les llega un aviso.',
            'Devolver el acceso')
        if page:
            return page
        done = connections.give_back(queryset.values_list('pk', flat=True), self._seen(request),
                                     self._recorder(request, 'Devolvió el acceso a Gmail.'))
        level = messages.SUCCESS if done['given'] and not done['skipped'] else messages.WARNING
        self.message_user(request, f"Accesos devueltos: {done['given']}. Omitidos: {done['skipped']}.", level)

    @admin.action(description='Deshacer un cupo apartado que NO agregué en Google', permissions=['change'])
    def undo_reservation(self, request, queryset):
        page = self._confirm(
            request, queryset, 'undo_reservation', connections.can_undo, 'Deshacer cupos apartados',
            'Confirma solo si NUNCA agregaste en Google una dirección de estas personas, tampoco una anterior '
            'ya corregida. Google no devuelve un cupo: si la agregaste, usa "Quitar acceso".',
            'Nunca las agregué: deshacer', needs_pilot=False)
        if page:
            return page
        done = connections.undo_reserve(queryset.values_list('pk', flat=True), self._seen(request),
                                        self._recorder(request, 'Deshizo un cupo apartado de Gmail.'))
        level = messages.SUCCESS if done['undone'] and not done['skipped'] else messages.WARNING
        self.message_user(request, f"Cupos deshechos: {done['undone']}. Omitidos: {done['skipped']}.", level)


def register(site):
    site.register(AssistantConnectionRequest, ConnectionRequestAdmin)
