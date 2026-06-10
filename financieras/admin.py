from django.contrib import admin

from .models import Financiera, FinancieraReport, FinancieraReview


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
    actions = ['unlist_financieras', 'relist_financieras']

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


class FinancieraReviewAdmin(admin.ModelAdmin):
    list_display = (
        'financiera', 'rating', 'sent_usdc', 'received_usd', 'reviewer', 'created_at',
    )
    list_filter = ('rating',)
    search_fields = ('financiera__name', 'reviewer__username', 'comment')
    raw_id_fields = ('financiera', 'reviewer')


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
