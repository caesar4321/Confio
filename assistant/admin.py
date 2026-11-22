from django.contrib import admin

from .models import AssistantMemory, AssistantMemoryFact, AssistantProfile, AssistantThreadState, AssistantTurn


class AssistantTurnAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'modality', 'screen', 'cost_usd', 'latency_ms', 'error', 'created_at')
    list_filter = ('modality', 'created_at')
    search_fields = ('user__username', 'user__email', 'screen')
    raw_id_fields = ('user', 'conversation', 'user_message', 'reply_message')
    readonly_fields = [f.name for f in AssistantTurn._meta.fields]


class AssistantThreadStateAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'handoff_at', 'handoff_reason', 'returned_to_ai_at', 'updated_at')
    raw_id_fields = ('conversation',)


class AssistantProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'mascot', 'mascot_name', 'bubble_hidden', 'updated_at')
    raw_id_fields = ('user',)


class _MemoryAdmin(admin.ModelAdmin):
    """When and how much, never what: a person's memory is theirs."""
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Deleting a row here would undo a forget. Deleting the person still cascades.
        match = getattr(request, 'resolver_match', None)
        if 'assistantmemory' in (getattr(match, 'url_name', None) or ''):
            return False
        return super().has_delete_permission(request, obj)

    def lookup_allowed(self, lookup, value, request=None):
        # A filter in the URL would answer "does it hold X?" without showing X.
        return lookup in ('id', 'id__exact', 'user__id__exact')


class AssistantMemoryAdmin(_MemoryAdmin):
    fields = ('user', 'account', 'business', 'facts_enabled', 'recall_enabled', 'summary_runs',
              'summary_input_tokens', 'summary_output_tokens', 'summary_cost_usd', 'created_at', 'updated_at')
    list_display = ('id', 'user', 'facts_enabled', 'recall_enabled', 'summary_runs', 'summary_cost_usd',
                    'updated_at')
    raw_id_fields = ('user', 'account', 'business')


class AssistantMemoryFactAdmin(_MemoryAdmin):
    fields = ('memory', 'created_at', 'deleted_at')
    list_display = ('id', 'created_at', 'deleted_at')


class AssistantGuideStepAdmin(admin.ModelAdmin):
    """What the first-steps guide offered each person (read-only evidence)."""
    list_display = ('user', 'step', 'shown_count', 'shown_at', 'accepted_at', 'dismissed_at')
    list_filter = ('step',)
    raw_id_fields = ('user',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class AssistantGuideEventAdmin(admin.ModelAdmin):
    """The guide's funnel, event by event (read-only evidence)."""
    list_display = ('created_at', 'user', 'step', 'event', 'detail', 'country')
    list_filter = ('step', 'event', 'country')
    raw_id_fields = ('user',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ProbeAnswerAdmin(admin.ModelAdmin):
    """Answers to the bubble's one-time question (read-only evidence)."""
    list_display = ('probe_id', 'answer', 'phone_country', 'funded', 'created_at')
    list_filter = ('probe_id', 'answer', 'phone_country', 'funded')
    readonly_fields = ('user', 'probe_id', 'answer', 'phone_country', 'funded', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class AssistantNeedAdmin(admin.ModelAdmin):
    """Nightly-tagged needs (read-only evidence; paraphrases are redacted)."""
    list_display = ('category', 'met_by_confio', 'phone_country', 'funded', 'paraphrase', 'message_at')
    list_filter = ('category', 'met_by_confio', 'phone_country', 'funded')
    readonly_fields = ('message', 'user', 'category', 'met_by_confio', 'paraphrase', 'phone_country', 'funded',
                       'message_at', 'created_at')
    raw_id_fields = ('message', 'user')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
