from django.contrib import admin

from .models import AssistantProfile, AssistantThreadState, AssistantTurn


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


class ProbeAnswerAdmin(admin.ModelAdmin):
    """Answers to the bubble's one-time question (read-only evidence)."""
    list_display = ('probe_id', 'answer', 'phone_country', 'funded', 'created_at')
    list_filter = ('probe_id', 'answer', 'phone_country', 'funded')
    readonly_fields = ('user', 'probe_id', 'answer', 'phone_country', 'funded', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
