from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Sum, Count
from decimal import Decimal

from .models import PresalePhase, PresalePurchase, PresaleStats, UserPresaleLimit, PresaleSettings


@admin.register(PresalePhase)
class PresalePhaseAdmin(admin.ModelAdmin):
    list_display = [
        'phase_number', 
        'name', 
        'status_colored', 
        'price_per_token',
        'formatted_goal',
        'formatted_raised',
        'progress_bar',
        'participant_count',
        'start_date',
        'end_date'
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = [
        'created_at', 
        'updated_at', 
        'total_raised_display',
        'total_participants_display',
        'tokens_sold_display',
        'progress_display'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('phase_number', 'name', 'description', 'status')
        }),
        ('UI Display Fields', {
            'fields': ('target_audience', 'location_emoji', 'vision_points'),
            'description': 'These fields control how the phase appears in the mobile app UI'
        }),
        ('Pricing & Limits', {
            'fields': (
                'price_per_token', 
                'goal_amount',
                'min_purchase',
                'max_purchase',
                'max_per_user'
            )
        }),
        ('Schedule', {
            'fields': ('start_date', 'end_date')
        }),
        ('Statistics', {
            'fields': (
                'total_raised_display',
                'total_participants_display', 
                'tokens_sold_display',
                'progress_display'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def status_colored(self, obj):
        colors = {
            'coming_soon': '#8b5cf6',
            'upcoming': '#FFA500',
            'active': '#28a745',
            'completed': '#17a2b8',
            'paused': '#dc3545'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    def formatted_goal(self, obj):
        return f"${obj.goal_amount:,.2f}"
    formatted_goal.short_description = 'Goal'
    
    def formatted_raised(self, obj):
        raised = obj.total_raised
        if raised >= obj.goal_amount:
            return format_html(
                '<span style="color: #28a745; font-weight: bold;">${:,.2f}</span>',
                raised
            )
        return f"${raised:,.2f}"
    formatted_raised.short_description = 'Raised'
    
    def progress_bar(self, obj):
        percentage = float(obj.progress_percentage)
        color = '#28a745' if percentage >= 100 else '#17a2b8'
        width = min(percentage, 100)
        return format_html(
            '''
            <div style="width: 100px; height: 20px; background-color: #f0f0f0; 
                        border-radius: 10px; overflow: hidden; position: relative;">
                <div style="width: {}%; height: 100%; background-color: {}; 
                            transition: width 0.5s ease;"></div>
                <span style="position: absolute; top: 50%; left: 50%; 
                             transform: translate(-50%, -50%); font-size: 11px; 
                             font-weight: bold;">{:.1f}%</span>
            </div>
            '''.format(width, color, percentage)
        )
    progress_bar.short_description = 'Progress'
    
    def participant_count(self, obj):
        return obj.total_participants
    participant_count.short_description = 'Participants'
    
    def total_raised_display(self, obj):
        return f"${obj.total_raised:,.2f} cUSD"
    total_raised_display.short_description = 'Total Raised'
    
    def total_participants_display(self, obj):
        return f"{obj.total_participants:,} users"
    total_participants_display.short_description = 'Total Participants'
    
    def tokens_sold_display(self, obj):
        return f"{obj.tokens_sold:,.2f} CONFIO"
    tokens_sold_display.short_description = 'Tokens Sold'
    
    def progress_display(self, obj):
        return f"{obj.progress_percentage:.2f}%"
    progress_display.short_description = 'Progress %'
    
    actions = ['activate_phase', 'pause_phase', 'complete_phase']
    
    def activate_phase(self, request, queryset):
        updated = queryset.update(status='active')
        self.message_user(request, f"{updated} phase(s) activated.")
    activate_phase.short_description = "Activate selected phases"
    
    def pause_phase(self, request, queryset):
        updated = queryset.update(status='paused')
        self.message_user(request, f"{updated} phase(s) paused.")
    pause_phase.short_description = "Pause selected phases"
    
    def complete_phase(self, request, queryset):
        updated = queryset.update(status='completed')
        self.message_user(request, f"{updated} phase(s) marked as completed.")
    complete_phase.short_description = "Complete selected phases"


@admin.register(PresalePurchase)
class PresalePurchaseAdmin(admin.ModelAdmin):
    list_display = [
        'purchase_id',
        'user_link',
        'phase',
        'formatted_cusd',
        'formatted_confio',
        'price_display',
        'status_colored',
        'txid_short',
        'created_at',
        'completed_at'
    ]
    list_filter = ['status', 'phase', 'created_at']
    search_fields = ['user__username', 'user__email', 'transaction_hash']
    readonly_fields = [
        'user', 
        'phase',
        'cusd_amount',
        'confio_amount',
        'price_per_token',
        'transaction_hash',
        'from_address',
        'created_at',
        'completed_at'
    ]
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Purchase Details', {
            'fields': (
                'user',
                'phase',
                'cusd_amount',
                'confio_amount',
                'price_per_token'
            )
        }),
        ('Transaction Info', {
            'fields': (
                'status',
                'transaction_hash',
                'from_address',
                'notes'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'completed_at')
        })
    )
    
    def purchase_id(self, obj):
        return f"#{obj.id}"
    purchase_id.short_description = 'ID'
    
    def user_link(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'
    
    def formatted_cusd(self, obj):
        return f"${obj.cusd_amount:,.2f}"
    formatted_cusd.short_description = 'cUSD Amount'
    
    def formatted_confio(self, obj):
        return f"{obj.confio_amount:,.2f}"
    formatted_confio.short_description = 'CONFIO Amount'
    
    def price_display(self, obj):
        return f"${obj.price_per_token}"
    price_display.short_description = 'Price/Token'

    def txid_short(self, obj):
        if not obj.transaction_hash:
            return '-'
        txid = obj.transaction_hash
        return format_html('<span style="font-family:monospace;">{}…{}</span>', txid[:8], txid[-6:])
    txid_short.short_description = 'TxID'
    
    def status_colored(self, obj):
        colors = {
            'pending': '#FFA500',
            'processing': '#17a2b8',
            'completed': '#28a745',
            'failed': '#dc3545',
            'refunded': '#6c757d'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    def has_add_permission(self, request):
        # Prevent manual creation of purchases
        return False
    
    actions = ['mark_as_completed', 'mark_as_failed']
    
    def mark_as_completed(self, request, queryset):
        updated = 0
        for purchase in queryset.filter(status__in=['pending', 'processing']):
            purchase.complete_purchase(f"manual_completion_{purchase.id}")
            updated += 1
        self.message_user(request, f"{updated} purchase(s) marked as completed.")
    mark_as_completed.short_description = "Mark as completed"
    
    def mark_as_failed(self, request, queryset):
        updated = queryset.filter(status__in=['pending', 'processing']).update(
            status='failed'
        )
        self.message_user(request, f"{updated} purchase(s) marked as failed.")
    mark_as_failed.short_description = "Mark as failed"


@admin.register(PresaleStats)
class PresaleStatsAdmin(admin.ModelAdmin):
    list_display = [
        'phase',
        'formatted_raised',
        'formatted_participants',
        'formatted_tokens',
        'formatted_average',
        'last_updated'
    ]
    readonly_fields = [
        'phase',
        'total_raised',
        'total_participants',
        'total_tokens_sold',
        'average_purchase',
        'last_updated'
    ]
    
    def formatted_raised(self, obj):
        return f"${obj.total_raised:,.2f}"
    formatted_raised.short_description = 'Total Raised'
    
    def formatted_participants(self, obj):
        return f"{obj.total_participants:,}"
    formatted_participants.short_description = 'Participants'
    
    def formatted_tokens(self, obj):
        return f"{obj.total_tokens_sold:,.2f}"
    formatted_tokens.short_description = 'Tokens Sold'
    
    def formatted_average(self, obj):
        return f"${obj.average_purchase:,.2f}"
    formatted_average.short_description = 'Avg Purchase'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    actions = ['update_stats']
    
    def update_stats(self, request, queryset):
        updated = 0
        for stat in queryset:
            stat.update_stats()
            updated += 1
        self.message_user(request, f"Updated stats for {updated} phase(s).")
    update_stats.short_description = "Update statistics"


@admin.register(UserPresaleLimit)
class UserPresaleLimitAdmin(admin.ModelAdmin):
    list_display = [
        'user_link',
        'phase',
        'formatted_purchased',
        'formatted_remaining',
        'last_purchase_at'
    ]
    list_filter = ['phase', 'last_purchase_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['user', 'phase', 'total_purchased', 'last_purchase_at']
    
    def user_link(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'
    
    def formatted_purchased(self, obj):
        return f"${obj.total_purchased:,.2f}"
    formatted_purchased.short_description = 'Total Purchased'
    
    def formatted_remaining(self, obj):
        if obj.phase.max_per_user:
            remaining = obj.phase.max_per_user - obj.total_purchased
            if remaining <= 0:
                return format_html(
                    '<span style="color: #dc3545;">Limit Reached</span>'
                )
            return f"${remaining:,.2f}"
        return "No Limit"
    formatted_remaining.short_description = 'Remaining'
    
    def has_add_permission(self, request):
        return False


@admin.register(PresaleSettings)
class PresaleSettingsAdmin(admin.ModelAdmin):
    list_display = ['is_presale_active', 'updated_at']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Global Presale Control', {
            'fields': ('is_presale_active',),
            'description': 'Master switch to enable/disable all presale features across the entire app'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def has_add_permission(self, request):
        # Only allow one instance
        return PresaleSettings.objects.count() == 0
    
    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion
        return False
