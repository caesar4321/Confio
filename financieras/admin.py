from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm

from .models import Financiera, FinancieraReport, FinancieraReview


class LocationMergeActionForm(ActionForm):
    """Extra input for the merge actions: the canonical value to apply."""

    location_value = forms.CharField(
        required=False,
        label='Location value',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Bella Vista'}),
    )


class FinancieraReviewInline(admin.TabularInline):
    model = FinancieraReview
    extra = 0
    fields = ('rating', 'sent_usdc', 'received_usd', 'comment', 'reviewer', 'created_at')
    readonly_fields = ('created_at',)
    raw_id_fields = ('reviewer',)


class FinancieraAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'country_code', 'state', 'city', 'neighborhood', 'whatsapp',
        'owner', 'supports_usdc_algorand', 'is_active', 'review_count_display',
        'avg_rating_display', 'created_at',
    )
    list_filter = ('country_code', 'is_active', 'supports_usdc_algorand', 'helps_with_confio')
    search_fields = ('name', 'city', 'neighborhood', 'state', 'whatsapp', 'owner__username')
    raw_id_fields = ('owner',)
    inlines = [FinancieraReviewInline]
    action_form = LocationMergeActionForm
    actions = ['unlist_financieras', 'relist_financieras', 'merge_city', 'merge_neighborhood']

    @admin.display(description='Reviews')
    def review_count_display(self, obj):
        return obj.review_count

    @admin.display(description='Avg rating')
    def avg_rating_display(self, obj):
        avg = obj.avg_rating
        return f'{avg:.1f}' if avg is not None else '—'

    @admin.action(description='Unlist selected financieras (hide from directory)')
    def unlist_financieras(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description='Relist selected financieras')
    def relist_financieras(self, request, queryset):
        queryset.update(is_active=True)

    def _merge_location(self, request, queryset, field):
        value = ' '.join((request.POST.get('location_value') or '').split())
        if not value:
            self.message_user(
                request,
                'Type the canonical value in the "Location value" box next to the action selector.',
                messages.ERROR,
            )
            return
        updated = queryset.update(**{field: value})
        self.message_user(request, f'Set {field} to "{value}" on {updated} financieras.')

    @admin.action(description='Merge: set CITY of selected to "Location value"')
    def merge_city(self, request, queryset):
        self._merge_location(request, queryset, 'city')

    @admin.action(description='Merge: set BARRIO of selected to "Location value"')
    def merge_neighborhood(self, request, queryset):
        self._merge_location(request, queryset, 'neighborhood')


class FinancieraReviewAdmin(admin.ModelAdmin):
    list_display = (
        'financiera', 'rating', 'sent_usdc', 'received_usd', 'reviewer',
        'send_transaction', 'usdc_withdrawal', 'created_at',
    )
    list_filter = ('rating',)
    search_fields = ('financiera__name', 'reviewer__username', 'comment')
    raw_id_fields = ('financiera', 'reviewer', 'send_transaction', 'usdc_withdrawal')


class FinancieraReportAdmin(admin.ModelAdmin):
    list_display = ('financiera', 'reporter', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('financiera__name', 'reporter__username', 'reason')
    raw_id_fields = ('financiera', 'reporter')
    actions = ['mark_reviewed', 'mark_dismissed']

    @admin.action(description='Mark selected reports as reviewed')
    def mark_reviewed(self, request, queryset):
        queryset.update(status='reviewed')

    @admin.action(description='Dismiss selected reports')
    def mark_dismissed(self, request, queryset):
        queryset.update(status='dismissed')
